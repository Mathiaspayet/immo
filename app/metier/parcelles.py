# -*- coding: utf-8 -*-
"""
parcelles.py — F3 : la recherche cadastrale.

On cherche un terrain : telle surface de parcelle, telle emprise batie au
sol. Une maison de 120 m2 habitables de plain-pied occupe environ 120 m2 au
sol ; la meme sur deux niveaux, 60 a 70 m2.

Et surtout, le recoupement que demande le CDC : une parcelle qui coche vos
criteres de terrain ET qui porte un DPE recent est un candidat serieux —
les deux signaux sont independants.

Repris de scripts_existants/parcelles.py.
"""

import datetime
import json
import logging

from app.base.connexion import connexion, transaction
from app.metier import geometrie
from app.sources import cadastre

logger = logging.getLogger(__name__)

COLONNES = [
    "id", "code_insee", "prefixe", "section", "numero", "contenance_m2",
    "emprise_batie_m2", "nb_batiments", "latitude", "longitude",
    "lat_min", "lat_max", "lon_min", "lon_max", "geometrie_json",
]

_MAJ = ", ".join(f"{c} = excluded.{c}" for c in COLONNES if c != "id")
SQL_UPSERT = (
    f"INSERT INTO parcelle ({', '.join(COLONNES)}, importe_le) "
    f"VALUES ({', '.join('?' * len(COLONNES))}, ?) "
    f"ON CONFLICT(id) DO UPDATE SET {_MAJ}, importe_le = excluded.importe_le"
)


def _maintenant():
    return datetime.datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------------
#  Import
# ---------------------------------------------------------------------

def importer_cadastre(code_insee, progression=None):
    """
    Telecharge le cadastre d'une commune, rattache les batiments aux
    parcelles, puis les DPE deja connus.

    Tout est calcule avant la moindre ecriture : un echec ne laisse pas un
    cadastre a moitie pose.
    """
    code_insee = str(code_insee).strip()

    objets_parcelles = cadastre.telecharger_couche(code_insee, "parcelles", progression)
    objets_batiments = cadastre.telecharger_couche(code_insee, "batiments", progression)

    # --- Index spatial des parcelles ---------------------------------
    if progression:
        progression(f"cadastre — indexation de {len(objets_parcelles)} parcelles")
    index = geometrie.IndexSpatial()
    fiches = {}

    for objet in objets_parcelles:
        proprietes = objet.get("properties") or {}
        identifiant = proprietes.get("id")
        anneaux = geometrie.anneaux_exterieurs(objet.get("geometry"))
        if not identifiant or not anneaux:
            continue
        boite = geometrie.boite_englobante(anneaux)
        longitude, latitude = geometrie.centre(anneaux[0])
        fiches[identifiant] = {
            "id": identifiant,
            "code_insee": code_insee,
            "prefixe": proprietes.get("prefixe"),
            "section": proprietes.get("section"),
            "numero": proprietes.get("numero"),
            # La contenance est la surface officielle publiee par le
            # cadastre : on ne la recalcule pas.
            "contenance_m2": _nombre(proprietes.get("contenance")),
            "emprise_batie_m2": 0.0,
            "nb_batiments": 0,
            "latitude": latitude,
            "longitude": longitude,
            "lon_min": boite[0], "lat_min": boite[1],
            "lon_max": boite[2], "lat_max": boite[3],
            "geometrie_json": json.dumps(objet.get("geometry"), separators=(",", ":")),
        }
        index.ajouter(identifiant, anneaux)

    # --- Rattachement des batiments ----------------------------------
    if progression:
        progression(f"cadastre — {len(objets_batiments)} bâtiments à rattacher")
    orphelins = 0
    for objet in objets_batiments:
        for anneau in geometrie.anneaux_exterieurs(objet.get("geometry")):
            longitude, latitude = geometrie.centre(anneau)
            identifiant = index.trouver(longitude, latitude)
            if identifiant is None:
                orphelins += 1
                continue
            fiche = fiches[identifiant]
            fiche["emprise_batie_m2"] += geometrie.surface_m2(anneau)
            fiche["nb_batiments"] += 1

    if not fiches:
        from app.sources.client_http import ErreurSource
        raise ErreurSource(f"Aucune parcelle exploitable pour la commune {code_insee}.")

    # --- Ecriture ------------------------------------------------------
    if progression:
        progression(f"cadastre — enregistrement de {len(fiches)} parcelles")
    maintenant = _maintenant()
    with transaction() as conn:
        for fiche in fiches.values():
            fiche["emprise_batie_m2"] = round(fiche["emprise_batie_m2"], 1)
            conn.execute(SQL_UPSERT, [fiche[c] for c in COLONNES] + [maintenant])
        conn.execute("UPDATE commune SET derniere_maj_cadastre = ? WHERE code_insee = ?",
                     (maintenant, code_insee))

    rattaches = rattacher_dpe(code_insee, index=index)

    logger.info("cadastre %s : %d parcelles, %d batiments orphelins, %d DPE rattaches",
                code_insee, len(fiches), orphelins, rattaches)
    return {
        "code_insee": code_insee,
        "parcelles": len(fiches),
        "batiments": len(objets_batiments),
        "batiments_orphelins": orphelins,
        "dpe_rattaches": rattaches,
        "message": (f"{len(fiches)} parcelles, {len(objets_batiments)} bâtiments, "
                    f"{rattaches} DPE rattachés"),
    }


def _nombre(valeur):
    try:
        return float(valeur)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------
#  Recoupement DPE x parcelle
# ---------------------------------------------------------------------

def _index_depuis_la_base(code_insee):
    """Reconstruit l'index spatial depuis les geometries enregistrees."""
    index = geometrie.IndexSpatial()
    with connexion() as conn:
        for ligne in conn.execute(
                "SELECT id, geometrie_json FROM parcelle WHERE code_insee = ?",
                (code_insee,)):
            try:
                forme = json.loads(ligne["geometrie_json"])
            except (TypeError, ValueError):
                continue
            index.ajouter(ligne["id"], geometrie.anneaux_exterieurs(forme))
    return index


def rattacher_dpe(code_insee, index=None, tous=False):
    """
    Rattache les DPE d'une commune a leur parcelle.

    Par defaut seuls les DPE encore orphelins sont traites : c'est ce qu'on
    veut apres une moisson de DPE, quand le cadastre est deja pose.
    """
    code_insee = str(code_insee).strip()
    if index is None:
        index = _index_depuis_la_base(code_insee)
    if not len(index):
        return 0

    condition = "" if tous else " AND parcelle_id IS NULL"
    with connexion() as conn:
        candidats = conn.execute(
            "SELECT n_dpe, latitude, longitude FROM dpe "
            "WHERE code_insee = ? AND latitude IS NOT NULL" + condition,
            (code_insee,)).fetchall()

    couples = []
    for ligne in candidats:
        identifiant = index.trouver(ligne["longitude"], ligne["latitude"])
        if identifiant:
            couples.append((identifiant, ligne["n_dpe"]))

    if couples:
        with transaction() as conn:
            conn.executemany("UPDATE dpe SET parcelle_id = ? WHERE n_dpe = ?", couples)
    return len(couples)


def age_cadastre(code_insee):
    """Heures depuis le dernier import du cadastre de cette commune, ou None."""
    with connexion() as conn:
        ligne = conn.execute(
            "SELECT derniere_maj_cadastre FROM commune WHERE code_insee = ?",
            (str(code_insee),)).fetchone()
    if ligne is None or not ligne["derniere_maj_cadastre"]:
        return None
    try:
        quand = datetime.datetime.fromisoformat(ligne["derniere_maj_cadastre"])
    except ValueError:
        return None
    return (datetime.datetime.now() - quand).total_seconds() / 3600


# ---------------------------------------------------------------------
#  Recherche
# ---------------------------------------------------------------------

CHAMPS = ["id", "section", "numero", "contenance_m2", "emprise_batie_m2",
          "nb_batiments", "latitude", "longitude"]


def lister(code_insee, filtres=None, limite=400, avec_geometrie=True):
    """
    Parcelles d'une commune repondant aux criteres de terrain.

    Chaque parcelle porte le compte des DPE qu'elle abrite et la date du
    plus recent : c'est le recoupement que demande le CDC F3, et c'est lui
    qui distingue un terrain qui correspond d'un terrain qui bouge.
    """
    filtres = filtres or {}
    clauses = ["p.code_insee = ?"]
    parametres = [str(code_insee)]

    for cle, colonne, operateur in [
        ("terrain_min", "p.contenance_m2", ">="),
        ("terrain_max", "p.contenance_m2", "<="),
        ("emprise_min", "p.emprise_batie_m2", ">="),
        ("emprise_max", "p.emprise_batie_m2", "<="),
    ]:
        valeur = filtres.get(cle)
        if valeur not in (None, ""):
            clauses.append(f"{colonne} {operateur} ?")
            parametres.append(float(valeur))

    if filtres.get("batie"):
        clauses.append("p.nb_batiments > 0")

    # Un DPE recent sur la parcelle : le signal qui fait la difference.
    jours = filtres.get("dpe_depuis_jours")
    if jours:
        limite_date = (datetime.date.today()
                       - datetime.timedelta(days=int(jours))).isoformat()
        jointure = ("LEFT JOIN dpe d ON d.parcelle_id = p.id "
                    "AND d.date_etablissement >= ?")
        parametres_jointure = [limite_date]
    else:
        jointure = "LEFT JOIN dpe d ON d.parcelle_id = p.id"
        parametres_jointure = []

    ayant = "HAVING count(d.n_dpe) > 0" if filtres.get("avec_dpe") or jours else ""

    colonnes = ", ".join(f"p.{c}" for c in CHAMPS)
    if avec_geometrie:
        colonnes += ", p.geometrie_json"

    sql = f"""
        SELECT {colonnes},
               count(d.n_dpe) AS dpe,
               max(d.date_etablissement) AS dpe_recent,
               group_concat(DISTINCT d.adresse) AS adresses
        FROM parcelle p
        {jointure}
        WHERE {' AND '.join(clauses)}
        GROUP BY p.id
        {ayant}
        ORDER BY dpe_recent DESC NULLS LAST, p.contenance_m2 DESC
        LIMIT ?
    """
    with connexion() as conn:
        lignes = conn.execute(sql, parametres_jointure + parametres + [int(limite)]).fetchall()

    resultats = []
    for ligne in lignes:
        entree = dict(ligne)
        if avec_geometrie and entree.get("geometrie_json"):
            try:
                entree["geometrie"] = json.loads(entree.pop("geometrie_json"))
            except (TypeError, ValueError):
                entree.pop("geometrie_json", None)
        entree["adresses"] = ([a for a in (entree.get("adresses") or "").split(",") if a]
                              if entree.get("adresses") else [])
        resultats.append(entree)
    return resultats


def resume(code_insee):
    """Ce que le cadastre de cette commune contient, pour l'en-tete."""
    with connexion() as conn:
        ligne = conn.execute(
            "SELECT count(*) AS parcelles, "
            "       sum(nb_batiments > 0) AS baties, "
            "       sum(nb_batiments) AS batiments "
            "FROM parcelle WHERE code_insee = ?", (str(code_insee),)).fetchone()
        rattaches = conn.execute(
            "SELECT count(*) FROM dpe WHERE code_insee = ? AND parcelle_id IS NOT NULL",
            (str(code_insee),)).fetchone()[0]

    return {
        "parcelles": ligne["parcelles"] or 0,
        "baties": ligne["baties"] or 0,
        "batiments": ligne["batiments"] or 0,
        "dpe_rattaches": rattaches,
        "age_heures": age_cadastre(code_insee),
    }


def parcelle_de(n_dpe):
    """La parcelle qui porte ce DPE, geometrie comprise — pour la fiche."""
    with connexion() as conn:
        ligne = conn.execute(
            "SELECT p.* FROM parcelle p "
            "JOIN dpe d ON d.parcelle_id = p.id WHERE d.n_dpe = ?",
            (str(n_dpe),)).fetchone()
    if ligne is None:
        return None
    parcelle = dict(ligne)
    try:
        parcelle["geometrie"] = json.loads(parcelle.pop("geometrie_json"))
    except (TypeError, ValueError):
        parcelle.pop("geometrie_json", None)
    return parcelle
