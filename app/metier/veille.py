# -*- coding: utf-8 -*-
"""
veille.py — L'ecran principal : les DPE recents, filtres et dedoublonnes.

Un DPE est obligatoire AVANT la mise en vente. Un diagnostic tout frais
precede donc souvent l'annonce de plusieurs semaines : c'est la fonction qui
justifie l'application (CDC F1).

Tout se joue en SQL, sur la base locale. Aucun appel a l'ADEME n'est
declenche ici — l'import est un traitement separe.

Rappel a garder en tete en lisant les resultats : un DPE recent ne signifie
pas une vente. Ce peut etre une mise en location, un audit avant travaux ou
un dossier MaPrimeRenov'. La proportion de faux positifs est importante.
"""

import csv
import datetime
import io
import logging

from app.base import reglages
from app.base.connexion import connexion, transaction

logger = logging.getLogger(__name__)

# Colonnes renvoyees a l'interface. `donnees_brutes_json` en est exclu :
# c'est plusieurs kilo-octets par ligne, inutile pour une liste.
COLONNES = [
    "n_dpe", "code_insee", "code_postal", "commune", "adresse", "latitude",
    "longitude", "zone", "distance_zone_m", "date_etablissement",
    "surface_habitable", "type_batiment", "etiquette_dpe", "etiquette_ges",
    "conso_ep_m2", "conso_ef_m2", "ges_m2", "cout_annuel",
    "annee_construction", "n_dpe_remplace", "importe_le", "vu_le",
]


def filtres_par_defaut():
    """Filtres initiaux de l'ecran, tires des reglages."""
    parametres = reglages.tous()
    return {
        "fenetre_jours": parametres["fenetre_jours"],
        "commune": (parametres["communes"][0].get("commune") or "")
                   if parametres["communes"] else "",
        "type_batiment": parametres["type_batiment"],
        "surface_min": parametres["surface_min"],
        "surface_max": parametres["surface_max"],
        "zone": "",
        "etiquettes": [],
        "seulement_nouveaux": False,
    }


def _conditions(filtres):
    """Construit la clause WHERE et ses parametres."""
    clauses, parametres = [], []

    jours = filtres.get("fenetre_jours")
    if jours:
        depuis = datetime.date.today() - datetime.timedelta(days=int(jours))
        clauses.append("date_etablissement >= ?")
        parametres.append(depuis.isoformat())

    if filtres.get("commune"):
        clauses.append("lower(commune) LIKE ?")
        parametres.append(f"%{str(filtres['commune']).lower()}%")

    if filtres.get("code_postal"):
        clauses.append("code_postal = ?")
        parametres.append(str(filtres["code_postal"]))

    if filtres.get("zone"):
        clauses.append("zone = ?")
        parametres.append(filtres["zone"])

    if filtres.get("type_batiment"):
        clauses.append("lower(type_batiment) LIKE ?")
        parametres.append(f"%{str(filtres['type_batiment']).lower()}%")

    # Les bornes de surface ne s'appliquent qu'aux lignes qui portent une
    # surface : ecarter les valeurs manquantes ferait disparaitre des biens
    # sans que rien ne l'explique.
    if filtres.get("surface_min") not in (None, ""):
        clauses.append("(surface_habitable IS NULL OR surface_habitable >= ?)")
        parametres.append(float(filtres["surface_min"]))
    if filtres.get("surface_max") not in (None, ""):
        clauses.append("(surface_habitable IS NULL OR surface_habitable <= ?)")
        parametres.append(float(filtres["surface_max"]))

    etiquettes = [str(e).upper() for e in (filtres.get("etiquettes") or []) if e]
    if etiquettes:
        clauses.append(f"etiquette_dpe IN ({', '.join('?' * len(etiquettes))})")
        parametres.extend(etiquettes)

    if filtres.get("seulement_nouveaux"):
        clauses.append("vu_le IS NULL")

    return (" AND ".join(clauses) or "1 = 1"), parametres


def _requete(filtres, limite=None):
    """
    Une ligne par adresse, le DPE le plus recent.

    La fonction de fenetrage ROW_NUMBER fait le dedoublonnage en une passe,
    la ou le script d'origine devait tout charger en memoire. Les adresses
    absentes sont regroupees par numero de DPE, faute de mieux.
    """
    ou, parametres = _conditions(filtres)
    colonnes = ", ".join(COLONNES)
    sql = f"""
        WITH retenus AS (
            SELECT {colonnes},
                   ROW_NUMBER() OVER (
                       PARTITION BY COALESCE(lower(trim(adresse)), n_dpe)
                       ORDER BY date_etablissement DESC, n_dpe DESC
                   ) AS rang
            FROM dpe
            WHERE {ou}
        )
        SELECT {colonnes} FROM retenus
        WHERE rang = 1
        ORDER BY date_etablissement DESC, adresse
    """
    if limite:
        sql += " LIMIT ?"
        parametres = parametres + [int(limite)]
    return sql, parametres


def lister(filtres=None, limite=500):
    """Les DPE correspondant aux filtres, du plus recent au plus ancien."""
    filtres = filtres or filtres_par_defaut()
    sql, parametres = _requete(filtres, limite)

    aujourdhui = datetime.date.today()
    resultats = []
    with connexion() as conn:
        for ligne in conn.execute(sql, parametres):
            entree = dict(ligne)
            date = entree.get("date_etablissement")
            entree["anciennete_jours"] = None
            if date:
                try:
                    entree["anciennete_jours"] = (
                        aujourdhui - datetime.date.fromisoformat(date)).days
                except ValueError:
                    pass
            entree["nouveau"] = entree.get("vu_le") is None
            resultats.append(entree)
    return resultats


def resume(filtres=None):
    """Compteurs de l'en-tete : total, nouveautes, repartition par secteur."""
    lignes = lister(filtres, limite=None)
    par_zone = {}
    for ligne in lignes:
        cle = ligne.get("zone") or "hors secteur"
        par_zone[cle] = par_zone.get(cle, 0) + 1

    with connexion() as conn:
        total_base = conn.execute("SELECT count(*) FROM dpe").fetchone()[0]
        dernier = conn.execute(
            "SELECT fin, statut, lignes, ajouts, message FROM journal_import "
            "WHERE statut IN ('succes', 'echec') ORDER BY id DESC LIMIT 1"
        ).fetchone()

    return {
        "total": len(lignes),
        "nouveaux": sum(1 for ligne in lignes if ligne["nouveau"]),
        "par_zone": par_zone,
        "total_base": total_base,
        "dernier_import": dict(dernier) if dernier else None,
    }


def marquer_vus(numeros=None):
    """
    Marque des DPE comme consultes : leur badge « nouveau » disparait.

    Sans liste, tout ce qui est en base est marque — c'est le bouton
    « tout marquer comme vu » de l'interface.
    """
    maintenant = datetime.datetime.now().isoformat(timespec="seconds")
    with transaction() as conn:
        if numeros:
            marques = ", ".join("?" * len(numeros))
            curseur = conn.execute(
                f"UPDATE dpe SET vu_le = ? WHERE vu_le IS NULL AND n_dpe IN ({marques})",
                [maintenant] + list(numeros))
        else:
            curseur = conn.execute(
                "UPDATE dpe SET vu_le = ? WHERE vu_le IS NULL", (maintenant,))
        return curseur.rowcount or 0


def exporter_csv(filtres=None):
    """
    Export CSV du tableau courant (CDC 7 : tout tableau est exportable).

    Separateur point-virgule et BOM UTF-8 : c'est ce qu'attend Excel en
    configuration francaise, sans quoi les accents sont illisibles.
    """
    lignes = lister(filtres, limite=None)
    colonnes = COLONNES + ["anciennete_jours", "nouveau"]

    tampon = io.StringIO()
    redacteur = csv.DictWriter(tampon, fieldnames=colonnes, delimiter=";",
                               extrasaction="ignore")
    redacteur.writeheader()
    redacteur.writerows(lignes)
    return "﻿" + tampon.getvalue()
