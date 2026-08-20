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

def transformer(ligne, correspondances, points_de_zone, jeu, code_postal_demande):
    """Convertit une ligne brute de l'API en dictionnaire pret pour la base."""
    lire = lambda concept: ligne.get(correspondances[concept]) if correspondances.get(concept) else None

    n_dpe = texte(lire("numero_dpe"))
    if not n_dpe:
        return None      # sans numero, la ligne n'est pas identifiable

    position = coordonnees.extraire(
        geopoint=lire("geopoint"), x=lire("x_lambert"), y=lire("y_lambert"))
    latitude, longitude = position if position else (None, None)
    zone, distance = zones.rattacher(latitude, longitude, points_de_zone)

    return {
        "n_dpe": n_dpe,
        "code_insee": texte(lire("code_insee")),
        "code_postal": texte(lire("code_postal")) or code_postal_demande,
        "commune": texte(lire("commune")),
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

# A la mise a jour, on ne touche ni a `importe_le` ni a `vu_le` : ce sont
# les deux seules colonnes qui appartiennent a l'utilisateur, pas a l'ADEME.
_MAJ = ", ".join(f"{c} = excluded.{c}" for c in COLONNES if c != "n_dpe")

SQL_UPSERT = (
    f"INSERT INTO dpe ({', '.join(COLONNES)}, importe_le, vu_le) "
    f"VALUES ({', '.join('?' * len(COLONNES))}, ?, ?) "
    f"ON CONFLICT(n_dpe) DO UPDATE SET {_MAJ}"
)


# ---------------------------------------------------------------------
#  Import complet
# ---------------------------------------------------------------------

def importer(declencheur="manuel", jeu="existant"):
    """
    Telecharge les DPE de toutes les communes surveillees et les enregistre.

    Renvoie un resume. Leve RuntimeError si un import tourne deja : deux
    imports simultanes se disputeraient le verrou d'ecriture de SQLite.
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
        resume = _executer(jeu)
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


def _executer(jeu):
    parametres = reglages.tous()
    communes = parametres["communes"]
    points_de_zone = parametres["zones"]

    _publier(etape="lecture du schema de l'ADEME")
    correspondances, _champs = ademe.preparer(jeu)

    # --- Telechargement -----------------------------------------------
    enregistrements = {}
    detail_communes = []
    for entree in communes:
        code_postal = str(entree["code_postal"]).strip()
        _publier(etape=f"telechargement du {code_postal}")

        def progression(nombre_lignes, message, _cp=code_postal):
            _publier(etape=f"telechargement — {message}", lignes=nombre_lignes)

        lignes = ademe.telecharger(code_postal, correspondances, jeu=jeu,
                                   progression=progression)
        retenues = 0
        for ligne in lignes:
            enregistrement = transformer(ligne, correspondances, points_de_zone,
                                         jeu, code_postal)
            if enregistrement:
                enregistrements[enregistrement["n_dpe"]] = enregistrement
                retenues += 1
        detail_communes.append(f"{code_postal} : {retenues}")
        logger.info("%s : %d ligne(s) exploitables sur %d", code_postal, retenues, len(lignes))

    if not enregistrements:
        raise ErreurSource(
            "L'ADEME n'a renvoye aucune ligne exploitable. Verifiez les codes "
            "postaux surveilles dans les reglages."
        )

    # --- Codes INSEE (facultatif, n'interrompt pas l'import) -----------
    _publier(etape="resolution des communes")
    referentiel = {}
    for entree in communes:
        for commune in geo.communes_du_code_postal(str(entree["code_postal"]).strip()):
            if commune.get("nom"):
                referentiel[commune["nom"].lower()] = commune

    # --- Ecriture, en une seule transaction ----------------------------
    _publier(etape="enregistrement en base", lignes=len(enregistrements))
    maintenant = _maintenant()

    with transaction() as conn:
        connus = {ligne["n_dpe"] for ligne in conn.execute("SELECT n_dpe FROM dpe")}
        premier_import = not connus

        ajouts = 0
        for enregistrement in enregistrements.values():
            nouveau = enregistrement["n_dpe"] not in connus
            ajouts += nouveau

            # Code INSEE : celui de l'ADEME s'il existe, sinon celui deduit
            # du nom de commune via geo.api.gouv.fr.
            if not enregistrement["code_insee"] and enregistrement["commune"]:
                trouve = referentiel.get(enregistrement["commune"].lower())
                if trouve:
                    enregistrement["code_insee"] = trouve["code_insee"]

            # Au tout premier import, tout est « nouveau » : marquer les
            # lignes comme deja vues evite de noyer l'ecran sous les badges.
            # Le marquage ne sert qu'a signaler les arrivees ulterieures.
            vu_le = maintenant if premier_import else None

            conn.execute(SQL_UPSERT,
                         [enregistrement[c] for c in COLONNES] + [maintenant, vu_le])

        for commune in referentiel.values():
            conn.execute(
                "INSERT INTO commune (code_insee, nom, code_postal, derniere_maj_dpe) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(code_insee) DO UPDATE SET nom = excluded.nom, "
                "  code_postal = excluded.code_postal, "
                "  derniere_maj_dpe = excluded.derniere_maj_dpe",
                (commune["code_insee"], commune["nom"], commune["code_postal"], maintenant))

        purges = _purger(conn, parametres["purge_mois"])

    message = (f"{len(enregistrements)} DPE traites ({'; '.join(detail_communes)}), "
               f"{ajouts} nouveau(x)")
    if purges:
        message += f", {purges} purge(s)"
    if premier_import:
        message += " — premier import, rien n'est signale comme nouveau"

    return {"lignes": len(enregistrements), "ajouts": ajouts,
            "purges": purges, "message": message}


def _purger(conn, purge_mois):
    """Supprime les DPE trop anciens (CDC 9 : 24 mois par defaut)."""
    limite = (datetime.date.today()
              - datetime.timedelta(days=int(float(purge_mois) * 30.44)))
    curseur = conn.execute(
        "DELETE FROM dpe WHERE date_etablissement IS NOT NULL "
        "AND date_etablissement < ?", (limite.isoformat(),))
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
