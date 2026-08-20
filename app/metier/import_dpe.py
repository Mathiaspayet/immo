# -*- coding: utf-8 -*-
"""
import_dpe.py — Recuperation des DPE et mise en cache en base.

Trois exigences du cahier des charges se rejoignent ici :

  - CDC 4 : aucun appel externe ne doit etre declenche par l'affichage
    d'une page. On telecharge donc tout d'avance, et l'ecran Veille ne lit
    que la base.

  - CDC 8 : un echec ne doit jamais laisser la base dans un etat partiel.
    L'ecriture se fait en une seule transaction, apres que tout a ete
    telecharge et transforme.

  - CDC 7 : toute operation longue affiche sa progression. L'etat courant
    est publie au fil de l'eau et lisible par l'API.

On enregistre toutes les lignes du code postal, sans appliquer les filtres
de surface ou de type : ces filtres appartiennent a l'affichage. Les
changer ne doit pas obliger a retelecharger.
"""

import datetime
import json
import logging
import threading

from app.base import reglages
from app.base.connexion import connexion, transaction
from app.metier import coordonnees, zones
from app.metier.valeurs import entier, nombre, texte
from app.sources import ademe, geo
from app.sources.client_http import ErreurSource

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------
#  Etat courant, partage entre le thread d'import et l'API
# ---------------------------------------------------------------------
_verrou = threading.Lock()
_etat = {
    "en_cours": False,
    "declencheur": None,
    "debut": None,
    "fin": None,
    "etape": "",
    "lignes": 0,
    "ajouts": 0,
    "statut": None,      # succes | echec
    "message": None,
    "journal_id": None,
}


def etat():
    """Copie de l'etat courant, pour l'API de progression."""
    with _verrou:
        return dict(_etat)


def _publier(**champs):
    with _verrou:
        _etat.update(champs)


def _maintenant():
    return datetime.datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------------
#  Transformation d'une ligne ADEME en enregistrement `dpe`
# ---------------------------------------------------------------------

def transformer(ligne, correspondances, points_de_zone, jeu, code_postal_demande,
                communes_par_insee=None, zones_code_insee=""):
    """Convertit une ligne brute de l'API en dictionnaire pret pour la base."""
    lire = lambda concept: ligne.get(correspondances[concept]) if correspondances.get(concept) else None

    n_dpe = texte(lire("numero_dpe"))
    if not n_dpe:
        return None      # sans numero, la ligne n'est pas identifiable

    position = coordonnees.extraire(
        geopoint=lire("geopoint"), x=lire("x_lambert"), y=lire("y_lambert"),
        latitude=lire("latitude"), longitude=lire("longitude"))
    latitude, longitude = position if position else (None, None)

    # La base ancienne ne porte aucun nom de commune : seul son code
    # INSEE l'identifie. On le traduit avec le referentiel de
    # geo.api.gouv.fr, sans quoi tout le filtrage par commune tomberait.
    # Le nom officiel du referentiel prime sur celui de l'ADEME : d'une base
    # a l'autre la meme commune s'ecrit « Mimizan », « MIMIZAN » ou
    # « PONTENX LES FORGES », ce qui eclaterait les regroupements.
    code_insee = texte(lire("code_insee"))
    officiel = (communes_par_insee or {}).get(code_insee) or {}
    commune = officiel.get("nom") or texte(lire("commune"))

    # Les secteurs ne valent que dans la commune ou leurs reperes ont ete
    # places : ailleurs, le « point le plus proche » n'a aucun sens.
    if zones_code_insee and code_insee != zones_code_insee:
        zone, distance = None, None
    else:
        zone, distance = zones.rattacher(latitude, longitude, points_de_zone)

    return {
        "n_dpe": n_dpe,
        "code_insee": code_insee,
        "code_postal": texte(lire("code_postal")) or code_postal_demande,
        "commune": commune,
        "adresse": texte(lire("adresse")),
        "latitude": latitude,
        "longitude": longitude,
        "zone": zone,
        "distance_zone_m": distance,
        "date_etablissement": (texte(lire("date")) or "")[:10] or None,
        "surface_habitable": nombre(lire("surface")),
        "type_batiment": texte(lire("type_batiment")),
        "etiquette_dpe": (texte(lire("etiquette_dpe")) or "").upper() or None,
        "etiquette_ges": (texte(lire("etiquette_ges")) or "").upper() or None,
        "conso_ep_m2": nombre(lire("conso_primaire")),
        "conso_ef_m2": nombre(lire("conso_finale")),
        "ges_m2": nombre(lire("ges_m2")),
        "cout_annuel": nombre(lire("cout_annuel")),
        "annee_construction": entier(lire("annee")),
        "n_dpe_remplace": texte(lire("n_dpe_remplace")),
        "jeu_de_donnees": jeu,
        # On conserve la ligne telle qu'elle est arrivee : les besoins
        # evolueront et la base ADEME compte plus de 200 colonnes (CDC 6).
        # Seules les colonnes demandees y figurent ; elargir la selection
        # se fait dans sources/ademe.py, sans toucher au schema.
        "donnees_brutes_json": json.dumps(ligne, ensure_ascii=False),
    }


COLONNES = [
    "n_dpe", "code_insee", "code_postal", "commune", "adresse", "latitude",
    "longitude", "zone", "distance_zone_m", "date_etablissement",
    "surface_habitable", "type_batiment", "etiquette_dpe", "etiquette_ges",
    "conso_ep_m2", "conso_ef_m2", "ges_m2", "cout_annuel",
    "annee_construction", "n_dpe_remplace", "jeu_de_donnees",
    "donnees_brutes_json",
]

# A la mise a jour, on ne touche ni a `importe_le` ni a `vu_le` : la
# premiere appartient a l'historique, la seconde a l'utilisateur.
# `revu_le` en revanche est rafraichi a chaque passage : c'est lui qui dit
# que l'ADEME sert encore cette ligne (voir 002_lot2.sql).
_MAJ = ", ".join(f"{c} = excluded.{c}" for c in COLONNES if c != "n_dpe")

SQL_UPSERT = (
    f"INSERT INTO dpe ({', '.join(COLONNES)}, importe_le, revu_le, vu_le) "
    f"VALUES ({', '.join('?' * len(COLONNES))}, ?, ?, ?) "
    f"ON CONFLICT(n_dpe) DO UPDATE SET {_MAJ}, revu_le = excluded.revu_le"
)


# ---------------------------------------------------------------------
#  Import complet
# ---------------------------------------------------------------------

def importer(declencheur="manuel", jeux=None):
    """
    Telecharge les DPE de toutes les communes surveillees et les enregistre.

    `jeux` limite l'import a certaines bases ADEME ; par defaut, celles des
    reglages. Leve RuntimeError si un import tourne deja : deux imports
    simultanes se disputeraient le verrou d'ecriture de SQLite.
    """
    with _verrou:
        if _etat["en_cours"]:
            raise RuntimeError("Un import est deja en cours.")
        _etat.update({"en_cours": True, "declencheur": declencheur,
                      "debut": _maintenant(), "fin": None, "etape": "demarrage",
                      "lignes": 0, "ajouts": 0, "statut": None,
                      "message": None, "journal_id": None})

    journal_id = _ouvrir_journal(declencheur)
    _publier(journal_id=journal_id)

    try:
        resume = _executer(jeux)
    except Exception as erreur:                      # noqa: BLE001
        message = str(erreur) or type(erreur).__name__
        logger.exception("import en echec : %s", message)
        _fermer_journal(journal_id, "echec", 0, 0, message)
        _publier(en_cours=False, fin=_maintenant(), statut="echec", message=message)
        raise
    else:
        _fermer_journal(journal_id, "succes", resume["lignes"], resume["ajouts"],
                        resume["message"])
        _publier(en_cours=False, fin=_maintenant(), statut="succes",
                 message=resume["message"], lignes=resume["lignes"],
                 ajouts=resume["ajouts"], etape="termine")
        return resume


def _referentiel_communes(communes):
    """
    Codes INSEE des communes surveillees, via geo.api.gouv.fr.

    Indispensable a la base ancienne, qui ne connait les communes QUE par
    leur code INSEE (voir ademe.cle_de_filtrage). Renvoie
    (par_insee, insee_par_code_postal).
    """
    par_insee, par_code_postal = {}, {}
    for entree in communes:
        code_postal = str(entree["code_postal"]).strip()
        trouvees = geo.communes_du_code_postal(code_postal)
        par_code_postal[code_postal] = [c["code_insee"] for c in trouvees
                                        if c.get("code_insee")]
        for commune in trouvees:
            if commune.get("code_insee"):
                par_insee[commune["code_insee"]] = commune
    return par_insee, par_code_postal


def _executer(jeux=None):
    parametres = reglages.tous()
    communes = parametres["communes"]
    points_de_zone = parametres["zones"]
    jeux = list(jeux or parametres["jeux_de_donnees"])

    _publier(etape="resolution des communes")
    communes_par_insee, insee_par_code_postal = _referentiel_communes(communes)

    enregistrements = {}
    detail, avertissements = [], []

    for jeu in jeux:
        _publier(etape=f"lecture du schema ({ademe.JEUX[jeu]})")
        try:
            correspondances, _champs = ademe.preparer(jeu)
        except ErreurSource as erreur:
            # Une base indisponible ne doit pas faire echouer les autres :
            # la veille F1 ne depend que de « existant ».
            avertissements.append(f"{ademe.JEUX[jeu]} ignoree ({erreur})")
            logger.warning("%s ignoree : %s", jeu, erreur)
            continue

        for entree in communes:
            code_postal = str(entree["code_postal"]).strip()

            # La base ancienne se filtre par code INSEE, les recentes par
            # code postal. Confondre les deux ramene une autre commune sans
            # la moindre erreur visible.
            if jeu == "ancien":
                valeurs = insee_par_code_postal.get(code_postal) or []
                if not valeurs:
                    avertissements.append(
                        f"{ademe.JEUX[jeu]} : codes INSEE du {code_postal} "
                        "indisponibles (geo.api.gouv.fr), commune ignoree")
                    continue
            else:
                valeurs = [code_postal]

            for valeur in valeurs:
                _publier(etape=f"telechargement {ademe.JEUX[jeu]} — {valeur}")

                def progression(nombre_lignes, message):
                    _publier(etape=f"telechargement — {message}", lignes=nombre_lignes)

                try:
                    lignes = ademe.telecharger(valeur, correspondances, jeu=jeu,
                                               progression=progression)
                except ErreurSource as erreur:
                    avertissements.append(f"{ademe.JEUX[jeu]} / {valeur} : {erreur}")
                    logger.warning("%s / %s : %s", jeu, valeur, erreur)
                    continue

                retenues = 0
                for ligne in lignes:
                    enregistrement = transformer(ligne, correspondances,
                                                 points_de_zone, jeu, code_postal,
                                                 communes_par_insee,
                                                 parametres["zones_code_insee"])
                    if enregistrement:
                        enregistrements[enregistrement["n_dpe"]] = enregistrement
                        retenues += 1
                detail.append(f"{jeu}/{valeur} : {retenues}")
                logger.info("%s / %s : %d ligne(s) exploitables sur %d",
                            jeu, valeur, retenues, len(lignes))

    if not enregistrements:
        raise ErreurSource(
            "L'ADEME n'a renvoye aucune ligne exploitable. Verifiez les codes "
            "postaux surveilles dans les reglages. "
            + (" ".join(avertissements) if avertissements else "")
        )

    # --- Ecriture, en une seule transaction ----------------------------
    _publier(etape="enregistrement en base", lignes=len(enregistrements))
    maintenant = _maintenant()

    with transaction() as conn:
        connus = {ligne["n_dpe"] for ligne in conn.execute("SELECT n_dpe FROM dpe")}
        premier_import = not connus

        ajouts = 0
        for enregistrement in enregistrements.values():
            ajouts += enregistrement["n_dpe"] not in connus

            # Au tout premier import, tout est « nouveau » : marquer les
            # lignes comme deja vues evite de noyer l'ecran sous les badges.
            # Le marquage ne sert qu'a signaler les arrivees ulterieures.
            vu_le = maintenant if premier_import else None

            conn.execute(SQL_UPSERT,
                         [enregistrement[c] for c in COLONNES]
                         + [maintenant, maintenant, vu_le])

        for commune in communes_par_insee.values():
            conn.execute(
                "INSERT INTO commune (code_insee, nom, code_postal, derniere_maj_dpe) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(code_insee) DO UPDATE SET nom = excluded.nom, "
                "  code_postal = excluded.code_postal, "
                "  derniere_maj_dpe = excluded.derniere_maj_dpe",
                (commune["code_insee"], commune["nom"], commune["code_postal"], maintenant))

        purges = _purger(conn, parametres["purge_mois"])

    message = (f"{len(enregistrements)} DPE traites ({'; '.join(detail)}), "
               f"{ajouts} nouveau(x)")
    if purges:
        message += f", {purges} purge(s)"
    if premier_import:
        message += " — premier import, rien n'est signale comme nouveau"
    if avertissements:
        message += " | " + " ; ".join(avertissements[:3])

    return {"lignes": len(enregistrements), "ajouts": ajouts,
            "purges": purges, "avertissements": avertissements,
            "message": message}


def _purger(conn, purge_mois):
    """
    Supprime ce que l'ADEME ne sert plus depuis trop longtemps (CDC 9).

    La purge porte sur `revu_le`, pas sur la date du diagnostic : purger sur
    la date d'etablissement viderait la chronologie F4, qui remonte a 2013,
    et priverait F2 des DPE anterieurs que cite une annonce. Sur `revu_le`,
    la regle garde tout son sens — on ne conserve pas une donnee qu'on ne
    rafraichit plus.
    """
    limite = (datetime.date.today()
              - datetime.timedelta(days=int(float(purge_mois) * 30.44)))
    curseur = conn.execute(
        "DELETE FROM dpe WHERE revu_le IS NOT NULL AND revu_le < ?",
        (limite.isoformat(),))
    return curseur.rowcount or 0


# ---------------------------------------------------------------------
#  Journal (CDC 8)
# ---------------------------------------------------------------------

def _ouvrir_journal(declencheur):
    with transaction() as conn:
        curseur = conn.execute(
            "INSERT INTO journal_import (source, debut, statut) VALUES (?, ?, 'en_cours')",
            (f"ademe/{declencheur}", _maintenant()))
        return curseur.lastrowid


def _fermer_journal(journal_id, statut, lignes, ajouts, message):
    with transaction() as conn:
        conn.execute(
            "UPDATE journal_import SET fin = ?, statut = ?, lignes = ?, "
            "ajouts = ?, message = ? WHERE id = ?",
            (_maintenant(), statut, lignes, ajouts, (message or "")[:500], journal_id))


# ---------------------------------------------------------------------
#  Rafraichissement paresseux
# ---------------------------------------------------------------------

def age_dernier_import():
    """
    Nombre d'heures depuis la derniere moisson reussie, ou None si la base
    n'en a jamais connu.
    """
    with connexion() as conn:
        ligne = conn.execute(
            "SELECT fin FROM journal_import WHERE statut = 'succes' "
            "AND fin IS NOT NULL ORDER BY id DESC LIMIT 1").fetchone()
    if ligne is None:
        return None
    try:
        fin = datetime.datetime.fromisoformat(ligne["fin"])
    except ValueError:
        return None
    return (datetime.datetime.now() - fin).total_seconds() / 3600


def rafraichir_si_perime(declencheur="recherche", seuil_heures=None):
    """
    Lance un import si la derniere moisson est trop vieille.

    Appelee au lancement d'une recherche, pas a l'affichage d'un ecran : le
    CDC 4 interdit qu'une page consultee declenche un appel externe. Les
    resultats deja en cache s'affichent immediatement, l'import tourne
    derriere et l'ecran se rafraichit quand il aboutit.

    Ne leve jamais : un rafraichissement qui echoue ne doit pas empecher de
    consulter ce qu'on a deja.
    """
    parametres = reglages.tous()
    seuil = parametres["rafraichir_apres_heures"] if seuil_heures is None else seuil_heures
    age = age_dernier_import()

    if not seuil:
        return {"lance": False, "raison": "desactive", "age_heures": age, "seuil_heures": seuil}
    if _etat["en_cours"]:
        return {"lance": False, "raison": "deja_en_cours", "age_heures": age, "seuil_heures": seuil}
    if age is not None and age < float(seuil):
        return {"lance": False, "raison": "a_jour", "age_heures": round(age, 2),
                "seuil_heures": seuil}

    try:
        lancer_en_tache_de_fond(declencheur=declencheur)
    except RuntimeError:
        return {"lance": False, "raison": "deja_en_cours", "age_heures": age,
                "seuil_heures": seuil}

    return {"lance": True,
            "raison": "jamais_importe" if age is None else "perime",
            "age_heures": None if age is None else round(age, 2),
            "seuil_heures": seuil}


def journal(limite=20):
    """Les derniers imports, pour l'ecran Reglages."""
    with connexion() as conn:
        return [dict(ligne) for ligne in conn.execute(
            "SELECT * FROM journal_import ORDER BY id DESC LIMIT ?", (limite,))]


# ---------------------------------------------------------------------
#  Lancement en tache de fond
# ---------------------------------------------------------------------

def lancer_en_tache_de_fond(declencheur="manuel"):
    """
    Demarre un import sans bloquer l'appelant.

    L'interface interroge ensuite /api/import/statut pour suivre l'avancee :
    un import complet prend plusieurs dizaines de secondes, une requete HTTP
    qui attendrait la fin serait coupee par le navigateur.
    """
    with _verrou:
        if _etat["en_cours"]:
            raise RuntimeError("Un import est deja en cours.")

    def travail():
        try:
            importer(declencheur=declencheur)
        except Exception:                            # noqa: BLE001
            pass      # deja journalise et publie dans l'etat

    fil = threading.Thread(target=travail, name="import-dpe", daemon=True)
    fil.start()
    return fil
