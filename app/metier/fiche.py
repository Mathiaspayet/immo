# -*- coding: utf-8 -*-
"""
fiche.py — F4 : la fiche d'un bien, sa chronologie et ses remplacements.

Ce que la chronologie revele :
  - un DPE ancien : le bien a deja ete vendu ou loue a cette epoque ;
  - deux DPE rapproches : correction du diagnostic, ou travaux entre les deux ;
  - un champ « remplace le DPE » rempli : le diagnostic en annule un precedent.

LE PIEGE, ET IL EST CENTRAL (CDC F4) : un DPE remplace est RETIRE de la
base active de l'ADEME. Le chercher par son numero echoue donc souvent, et
la recherche plein texte ramene alors les DPE qui le CITENT — pas lui. Une
version du script d'origine renvoyait « le premier resultat venu », ce qui
presentait deux fois le meme enregistrement comme deux DPE distincts.

On ne fait donc jamais de repli silencieux : soit le numero est verifie,
soit on dit franchement que le diagnostic n'est plus accessible.

Repris de scripts_existants/dpe_historique.py et dpe_comparer.py.
"""

import collections
import json
import logging

from app.base.connexion import connexion
from app.metier import mutations, parcelles
from app.metier.valeurs import normaliser_adresse
from app.sources import ademe

logger = logging.getLogger(__name__)

COLONNES = [
    "n_dpe", "adresse", "commune", "code_postal", "code_insee", "latitude",
    "longitude", "zone", "distance_zone_m", "date_etablissement",
    "surface_habitable", "type_batiment", "etiquette_dpe", "etiquette_ges",
    "conso_ep_m2", "conso_ef_m2", "ges_m2", "cout_annuel", "annee_construction",
    "n_dpe_remplace", "jeu_de_donnees", "importe_le", "revu_le", "vu_le",
]

LIBELLES_JEUX = {
    "existant": "Logements existants — depuis juillet 2021",
    "neuf": "Logements neufs — depuis juillet 2021",
    "ancien": "Avant juillet 2021",
}

# Limite de securite : une voie entiere peut porter des centaines de DPE.
MAX_CHAINE = 12


def _lire(conn, n_dpe):
    ligne = conn.execute(
        f"SELECT {', '.join(COLONNES)} FROM dpe WHERE n_dpe = ?", (n_dpe,)
    ).fetchone()
    return dict(ligne) if ligne else None


def _dernier_import(conn):
    """Fin du dernier import reussi — pour l'affichage, pas pour comparer."""
    ligne = conn.execute(
        "SELECT fin FROM journal_import WHERE statut = 'succes' "
        "ORDER BY id DESC LIMIT 1").fetchone()
    return ligne["fin"] if ligne else None


def _moisson_par_commune(conn):
    """
    Quand chaque commune a ete moissonnee pour la derniere fois.

    C'est le repere qui dit si l'ADEME sert encore une ligne, et il doit
    etre PAR COMMUNE : moissonner Launaguet ne dit rien de Mimizan, dont
    les lignes n'ont pas ete revues a cette occasion.

    `derniere_maj_dpe` porte exactement l'horodatage que l'import a inscrit
    dans `revu_le` — les deux s'ecrivent dans la meme transaction, a partir
    de la meme valeur. La comparaison est donc juste au caractere pres.
    """
    return {ligne["code_insee"]: ligne["derniere_maj_dpe"]
            for ligne in conn.execute(
                "SELECT code_insee, derniere_maj_dpe FROM commune "
                "WHERE derniere_maj_dpe IS NOT NULL")}


def _enrichir(ligne, moissons):
    """Ajoute ce que la base seule ne dit pas."""
    ligne["jeu_libelle"] = LIBELLES_JEUX.get(ligne.get("jeu_de_donnees"), "")
    # Une ligne que la derniere moisson de SA commune n'a pas revue n'est
    # plus servie par l'ADEME : signature d'un DPE remplace ou retire.
    #
    # Le repere etait auparavant la FIN de l'import, alors que `revu_le`
    # est ecrit pendant celui-ci : la comparaison etait fausse d'une
    # seconde, et pour toutes les lignes a la fois. Toute la chronologie
    # s'affichait « retiree de la base active », et le signal
    # « plusieurs logements » ne se declenchait jamais.
    reference = moissons.get(ligne.get("code_insee"))
    ligne["encore_publie"] = bool(
        reference and ligne.get("revu_le") and ligne["revu_le"] >= reference)
    return ligne


def _logements(diagnostics):
    """
    Combien de logements distincts cette adresse couvre-t-elle ?

    Le nombre de diagnostics ne suffit pas : une maison vendue deux fois en
    porte deux, un immeuble aussi. Ce qui les separe, c'est la SIMULTANEITE.
    Deux diagnostics du meme jour ne peuvent pas viser le meme logement —
    on diagnostique un immeuble d'un coup. Deux diagnostics a deux ans
    d'ecart, si.

    On retient donc le plus grand nombre de diagnostics partageant une meme
    date d'etablissement. Mesure sur Mimizan : des 552 adresses portant
    plusieurs DPE, cette regle en requalifie 328 en maison rediagnostiquee,
    et maintient 224 adresses reellement multiples — 4 diagnostics le meme
    jour rue des Pinsons, 2 avenue de Woolsack.

    Compter les diagnostics tout court, comme on le faisait, revenait a
    traiter toute maison rediagnostiquee en immeuble.
    """
    if not diagnostics:
        return 0
    par_jour = collections.Counter(
        d.get("date_etablissement") for d in diagnostics
        if d.get("date_etablissement"))
    return max(par_jour.values()) if par_jour else 1


def historique(adresse=None, n_dpe=None):
    """
    Tous les DPE connus pour une adresse, toutes bases confondues,
    du plus ancien au plus recent.

    L'adresse peut etre donnee directement, ou deduite d'un numero de DPE.
    """
    with connexion() as conn:
        if not adresse and n_dpe:
            depart = _lire(conn, n_dpe)
            if depart is None:
                return {"adresse": None, "diagnostics": [],
                        "message": f"Le DPE {n_dpe} n'est pas dans le cache local."}
            adresse = depart.get("adresse")

        cible = normaliser_adresse(adresse)
        if not cible:
            return {"adresse": adresse, "diagnostics": [],
                    "message": "Aucune adresse exploitable pour ce bien."}

        dernier = _dernier_import(conn)
        moissons = _moisson_par_commune(conn)
        lignes = [dict(l) for l in conn.execute(
            f"SELECT {', '.join(COLONNES)} FROM dpe WHERE adresse IS NOT NULL")]

    # La comparaison se fait sur la forme normalisee : l'orthographe varie
    # d'une base a l'autre, et un LIKE SQL ne suffirait pas.
    diagnostics = [_enrichir(l, moissons) for l in lignes
                   if normaliser_adresse(l["adresse"]) == cible]

    return {
        **_resumer(adresse, diagnostics),
        "dernier_import": dernier,
        "message": None if diagnostics else (
            f"Aucun diagnostic connu pour « {adresse} ». L'orthographe de la "
            "base diffère parfois de celle de l'annonce : cherchez le bien "
            "depuis l'écran Identifier."),
    }


def _resumer(adresse, diagnostics):
    """Une adresse et sa chronologie, triee, avec ce qu'elle dit des logements."""
    diagnostics.sort(key=lambda l: (str(l.get("date_etablissement") or ""), l["n_dpe"]))
    remplaces = {d.get("n_dpe_remplace") for d in diagnostics if d.get("n_dpe_remplace")}
    en_vigueur = [d for d in diagnostics
                  if d["encore_publie"] and d["n_dpe"] not in remplaces]
    return {
        "adresse": adresse,
        "diagnostics": diagnostics,
        "en_vigueur": len(en_vigueur),
        "logements_estimes": _logements(en_vigueur),
        "plusieurs_logements": _logements(en_vigueur) > 1,
    }


# ---------------------------------------------------------------------
#  La fiche d'un lieu
# ---------------------------------------------------------------------

def lieu(n_dpe=None, parcelle_id=None, adresse=None):
    """
    Tout ce qu'on sait d'un lieu : sa parcelle, ce qui s'y est vendu, et
    chaque logement qu'elle porte avec la chronologie de ses diagnostics.

    Il y avait deux fiches, celle d'un diagnostic et celle d'une parcelle,
    qui se recouvraient aux trois quarts — meme extrait, memes ventes — et
    renvoyaient l'une a l'autre. On n'en garde qu'une. On y entre par un
    diagnostic (les listes), une parcelle (la carte) ou une adresse
    (l'ecran Identifier) ; le diagnostic d'entree designe alors le logement
    mis EN TETE, dont la fiche montre les mesures.

    Un logement, c'est une adresse et toute sa chronologie — y compris les
    diagnostics de cette adresse que l'ADEME a geocodes ailleurs : la
    fiche d'un diagnostic les montrait, la fusion ne doit rien perdre.
    Chacun dit ou il est pose (`lieu_du_diagnostic`).

    Rend None si rien ne designe un lieu connu.
    """
    if adresse and not n_dpe:
        depuis_adresse = historique(adresse=adresse)
        if not depuis_adresse["diagnostics"]:
            return {"trouve": False, "adresse": adresse,
                    "message": depuis_adresse["message"]}
        n_dpe = depuis_adresse["diagnostics"][-1]["n_dpe"]

    depart = None
    with connexion() as conn:
        if n_dpe:
            depart = conn.execute(
                "SELECT n_dpe, adresse, code_insee, parcelle_carte FROM dpe WHERE n_dpe = ?",
                (str(n_dpe),)).fetchone()
            if depart is None:
                return {"trouve": False, "adresse": None,
                        "message": f"Le DPE {n_dpe} n'est pas dans le cache local."}
            depart = dict(depart)
            parcelle_id = depart["parcelle_carte"]

    parcelle = parcelles.parcelle(parcelle_id) if parcelle_id else None
    if parcelle is None and depart is None:
        return None

    if depart:
        extrait = parcelles.extrait(depart["n_dpe"])
        ventes = mutations.pour_dpe(depart["n_dpe"])
    else:
        extrait = parcelles.extrait_parcelle(parcelle["id"])
        ventes = mutations.pour_parcelle(parcelle["id"])
    pose = parcelles.diagnostics_de(parcelle["id"]) if parcelle else []
    if parcelle:
        ventes = _avec_les_ventes_d_origine(ventes, parcelle["id"])
        if parcelle.get("retiree_le"):
            parcelle["heritieres"] = parcelles.heritieres(parcelle["id"])

    logements = _logements_du_lieu([depart] if depart else [], pose,
                                   parcelle["id"] if parcelle else None)
    tete = None
    if depart:
        tete = next(i for i, l in enumerate(logements)
                    if any(d["n_dpe"] == depart["n_dpe"] for d in l["diagnostics"]))
    elif len(logements) == 1:
        tete = 0
    if tete is not None:
        logements.insert(0, logements.pop(tete))

    code_insee = (parcelle or {}).get("code_insee") or (depart or {}).get("code_insee")
    with connexion() as conn:
        cadastre_charge = extrait is not None or bool(code_insee and conn.execute(
            "SELECT 1 FROM parcelle WHERE code_insee = ? LIMIT 1", (code_insee,)).fetchone())
        dernier = _dernier_import(conn)

    return {
        "trouve": True,
        "parcelle": parcelle,
        "extrait": extrait,
        "cadastre_charge": cadastre_charge,
        "ventes": ventes,
        "logements": logements,
        # Le logement mis en tete, s'il y en a un : celui du diagnostic
        # d'entree, ou le seul que porte la parcelle.
        "en_tete": tete is not None,
        "dernier_import": dernier,
    }


def _avec_les_ventes_d_origine(ventes, parcelle_id):
    """
    Ajoute les ventes de la parcelle d'origine, quand celle-ci a ete
    divisee ou fusionnee.

    DVF cite les parcelles telles qu'elles etaient au jour de la vente : la
    maison vendue en 2022 sur AB0180 n'apparaissait plus nulle part une
    fois AB0180 divisee en AB0450 et AB0451. Chaque vente ainsi reprise
    dit sur quelle parcelle elle portait — tout le terrain d'alors, pas le
    seul lot d'aujourd'hui.
    """
    connues = {vente["id"] for vente in ventes}
    for ancienne in parcelles.ascendance(parcelle_id):
        origine = parcelles.parcelle(ancienne) or {}
        reference = f"{origine.get('section') or ''}{origine.get('numero') or ''}" or ancienne
        for vente in mutations.pour_parcelle(ancienne):
            if vente["id"] in connues:
                continue
            connues.add(vente["id"])
            vente["parcelle_d_origine"] = ancienne
            vente["reference_d_origine"] = reference
            ventes.append(vente)
    return sorted(ventes, key=lambda v: str(v.get("date_mutation") or ""), reverse=True)


def _logements_du_lieu(depart, pose, parcelle_id):
    """
    Les logements d'un lieu — une adresse, sa chronologie — en un passage.

    Rechercher l'historique adresse par adresse relirait toute la table a
    chaque fois : une residence en porte des dizaines. Un diagnostic sans
    adresse exploitable reste seul : on ne saurait a quoi le rapprocher,
    et l'ecarter le ferait disparaitre de la fiche.
    """
    adresses, seuls = {}, []
    for diagnostic in depart + pose:
        cle = normaliser_adresse(diagnostic.get("adresse"))
        if cle:
            adresses.setdefault(cle, diagnostic["adresse"])
        elif diagnostic["n_dpe"] not in seuls:
            seuls.append(diagnostic["n_dpe"])

    colonnes = ", ".join(COLONNES) + ", parcelle_id, parcelle_carte"
    with connexion() as conn:
        moissons = _moisson_par_commune(conn)
        lignes = [dict(l) for l in conn.execute(
            f"SELECT {colonnes} FROM dpe WHERE adresse IS NOT NULL")] if adresses else []
        lignes += [dict(l) for l in conn.execute(
            f"SELECT {colonnes} FROM dpe WHERE n_dpe IN ({', '.join('?' * len(seuls))})",
            seuls)] if seuls else []

    groupes, vus = collections.defaultdict(list), set()
    for ligne in lignes:
        cle = normaliser_adresse(ligne["adresse"]) or ligne["n_dpe"]
        if (cle in adresses or cle in seuls) and ligne["n_dpe"] not in vus:
            vus.add(ligne["n_dpe"])
            ligne["lieu_du_diagnostic"] = _pose(ligne, parcelle_id)
            del ligne["parcelle_id"], ligne["parcelle_carte"]
            groupes[cle].append(_enrichir(ligne, moissons))

    logements = [_resumer(adresses.get(cle), diagnostics)
                 for cle, diagnostics in groupes.items()]
    # Le plus recemment diagnostique d'abord : c'est le plus probablement
    # celui qui vient d'etre mis en vente.
    logements.sort(key=lambda l: str(l["diagnostics"][-1].get("date_etablissement") or ""),
                   reverse=True)
    return logements


def _pose(ligne, parcelle_id):
    """Ou ce diagnostic est pose, au regard de la parcelle de la fiche."""
    if parcelle_id is None:
        return "sans_parcelle" if not ligne["parcelle_carte"] else "ailleurs"
    if ligne["parcelle_carte"] != parcelle_id:
        return "ailleurs" if ligne["parcelle_carte"] else "sans_parcelle"
    return "approchee" if ligne["parcelle_id"] is None else "sur_la_parcelle"


def voisinage(adresse, combien=8):
    """
    Adresses proches par l'ecriture, quand la recherche exacte ne donne rien.

    Evite le « aucun résultat » sec : on propose les voies qui partagent des
    mots avec la recherche.
    """
    mots = set(normaliser_adresse(adresse).split())
    if not mots:
        return []
    with connexion() as conn:
        lignes = conn.execute(
            "SELECT DISTINCT adresse FROM dpe WHERE adresse IS NOT NULL").fetchall()

    scores = []
    for ligne in lignes:
        communs = mots & set(normaliser_adresse(ligne["adresse"]).split())
        if communs:
            scores.append((len(communs), ligne["adresse"]))
    scores.sort(key=lambda x: (-x[0], x[1]))
    return [adresse for _score, adresse in scores[:combien]]


# ---------------------------------------------------------------------
#  Chaine des remplacements
# ---------------------------------------------------------------------

def chaine(n_dpe, interroger_ademe=True):
    """
    Remonte la suite des DPE remplaces, du plus recent au plus ancien.

    Chaque maillon indique d'ou il vient : du cache local, d'une requete
    ciblee a l'ADEME, ou nulle part — et dans ce dernier cas on l'ecrit.
    """
    maillons, vus = [], set()
    courant = str(n_dpe or "").strip()

    with connexion() as conn:
        moissons = _moisson_par_commune(conn)

        while courant and courant not in vus and len(maillons) < MAX_CHAINE:
            vus.add(courant)
            ligne = _lire(conn, courant)

            if ligne is not None:
                maillons.append({**_enrichir(ligne, moissons), "origine": "cache"})
                courant = (ligne.get("n_dpe_remplace") or "").strip()
                continue

            # Absent du cache : soit hors des communes surveillees, soit
            # retire de la base active parce que remplace.
            if not interroger_ademe:
                maillons.append(_maillon_absent(courant, interroge=False))
                break

            jeu, brut, methode = ademe.chercher_par_numero(courant)
            if brut is None:
                maillons.append(_maillon_absent(courant, interroge=True))
                break

            maillons.append({
                "n_dpe": courant,
                "origine": f"ADEME ({methode})",
                "jeu_de_donnees": jeu,
                "jeu_libelle": LIBELLES_JEUX.get(jeu, jeu),
                "encore_publie": True,
                "donnees_brutes": brut,
                "adresse": brut.get("adresse_ban") or brut.get("geo_adresse"),
                "date_etablissement": str(brut.get("date_etablissement_dpe") or "")[:10] or None,
                "etiquette_dpe": brut.get("etiquette_dpe") or brut.get("classe_consommation_energie"),
                "surface_habitable": brut.get("surface_habitable_logement")
                                     or brut.get("surface_thermique_lot"),
            })
            courant = str(brut.get("numero_dpe_remplace")
                          or brut.get("n_dpe_remplace") or "").strip()

    tronquee = bool(courant and courant in vus)
    return {"maillons": maillons, "boucle_detectee": tronquee}


def _maillon_absent(numero, interroge):
    """Un maillon qu'on ne peut pas produire — et on dit pourquoi."""
    if interroge:
        explication = (
            "Introuvable. L'ADEME ne conserve dans ses jeux de données que les "
            "diagnostics en vigueur : un DPE remplacé en est retiré, ses valeurs "
            "ne sont plus accessibles. Si ce bien est dans une commune surveillée, "
            "un import antérieur au remplacement en aurait gardé la trace.")
    else:
        explication = ("Absent du cache local. Ce bien n'est probablement pas dans "
                       "une commune surveillée.")
    return {"n_dpe": numero, "origine": "introuvable", "absent": True,
            "explication": explication}


# ---------------------------------------------------------------------
#  Comparaison de deux DPE
# ---------------------------------------------------------------------

# Ajoutes par le moteur de recherche data-fair, ils ne font pas partie du
# diagnostic : score de pertinence, identifiants internes.
def _est_technique(cle):
    return cle.startswith("_")


# Champs qui changent a chaque re-publication sans rien dire du logement.
BRUIT = ("date_derniere_modification", "date_reception", "identifiant",
         "date_depot", "version")


def _donnees_completes(n_dpe):
    """
    Toutes les colonnes d'un DPE : celles de l'ADEME si elle le sert
    encore, sinon celles que le cache a conservees.
    """
    _jeu, brut, methode = ademe.chercher_par_numero(n_dpe)
    if brut is not None:
        return brut, f"ADEME ({methode})"

    with connexion() as conn:
        ligne = conn.execute(
            "SELECT donnees_brutes_json FROM dpe WHERE n_dpe = ?", (n_dpe,)).fetchone()
    if ligne and ligne["donnees_brutes_json"]:
        try:
            return json.loads(ligne["donnees_brutes_json"]), "cache local"
        except ValueError:
            pass
    return None, None


def comparer(n_dpe_recent, n_dpe_ancien):
    """
    Champs dont la valeur differe entre deux diagnostics.

    C'est ce qui montre exactement ce qui a ete corrige, ou ce que des
    travaux ont change.
    """
    recent, source_recent = _donnees_completes(n_dpe_recent)
    ancien, source_ancien = _donnees_completes(n_dpe_ancien)

    manquants = [numero for numero, donnees in
                 ((n_dpe_recent, recent), (n_dpe_ancien, ancien)) if donnees is None]
    if manquants:
        return {
            "comparables": False,
            "manquants": manquants,
            "message": (
                f"Comparaison impossible : {', '.join(manquants)} n'est plus "
                "accessible. Un DPE remplacé est retiré de la base active de "
                "l'ADEME, et le cache local n'en a pas gardé de trace."),
        }

    differences, techniques = [], []
    for cle in sorted(set(recent) | set(ancien)):
        if _est_technique(cle):
            continue
        avant, apres = ancien.get(cle), recent.get(cle)
        if str(avant) == str(apres):
            continue
        entree = {"champ": cle, "avant": avant, "apres": apres}
        (techniques if any(mot in cle for mot in BRUIT) else differences).append(entree)

    return {
        "comparables": True,
        "recent": {"n_dpe": n_dpe_recent, "source": source_recent},
        "ancien": {"n_dpe": n_dpe_ancien, "source": source_ancien},
        "differences": differences,
        "techniques": techniques,
        "identiques": not differences and not techniques,
    }
