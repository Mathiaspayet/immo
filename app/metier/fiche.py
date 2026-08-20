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

import json
import logging

from app.base.connexion import connexion
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
    ligne = conn.execute(
        "SELECT fin FROM journal_import WHERE statut = 'succes' "
        "ORDER BY id DESC LIMIT 1").fetchone()
    return ligne["fin"] if ligne else None


def _enrichir(ligne, dernier_import):
    """Ajoute ce que la base seule ne dit pas."""
    ligne["jeu_libelle"] = LIBELLES_JEUX.get(ligne.get("jeu_de_donnees"), "")
    # Une ligne que le dernier import n'a pas revue n'est plus servie par
    # l'ADEME : c'est la signature d'un DPE remplace ou retire.
    ligne["encore_publie"] = bool(
        dernier_import and ligne.get("revu_le") and ligne["revu_le"] >= dernier_import)
    return ligne


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
        lignes = [dict(l) for l in conn.execute(
            f"SELECT {', '.join(COLONNES)} FROM dpe WHERE adresse IS NOT NULL")]

    # La comparaison se fait sur la forme normalisee : l'orthographe varie
    # d'une base a l'autre, et un LIKE SQL ne suffirait pas.
    diagnostics = [_enrichir(l, dernier) for l in lignes
                   if normaliser_adresse(l["adresse"]) == cible]
    diagnostics.sort(key=lambda l: (str(l.get("date_etablissement") or ""), l["n_dpe"]))

    # Plusieurs diagnostics en vigueur en meme temps a la meme adresse =
    # plusieurs logements. Sans ce signal, la chronologie d'un immeuble
    # ressemblerait a celle d'une maison rediagnostiquee dix fois.
    remplaces = {d.get("n_dpe_remplace") for d in diagnostics if d.get("n_dpe_remplace")}
    en_vigueur = [d for d in diagnostics
                  if d["encore_publie"] and d["n_dpe"] not in remplaces]

    return {
        "adresse": adresse,
        "diagnostics": diagnostics,
        "en_vigueur": len(en_vigueur),
        "plusieurs_logements": len(en_vigueur) > 1,
        "dernier_import": dernier,
        "message": None if diagnostics else (
            f"Aucun diagnostic connu pour « {adresse} ». L'orthographe de la "
            "base diffère parfois de celle de l'annonce : cherchez le bien "
            "depuis l'écran Identifier."),
    }


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
        dernier = _dernier_import(conn)

        while courant and courant not in vus and len(maillons) < MAX_CHAINE:
            vus.add(courant)
            ligne = _lire(conn, courant)

            if ligne is not None:
                maillons.append({**_enrichir(ligne, dernier), "origine": "cache"})
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
