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
import re
import math

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
    # Leurs contours sont conserves : la fiche d'un bien les dessine, avec
    # les parcelles voisines. L'agregat seul ne suffisait plus.
    if progression:
        progression(f"cadastre — {len(objets_batiments)} bâtiments à rattacher")
    orphelins = 0
    batiments = []

    for objet in objets_batiments:
        type_bati = (objet.get("properties") or {}).get("type")
        for anneau in geometrie.anneaux_exterieurs(objet.get("geometry")):
            longitude, latitude = geometrie.centre(anneau)
            identifiant = index.trouver(longitude, latitude)
            surface = geometrie.surface_m2(anneau)
            boite = geometrie.boite_englobante([anneau])

            if identifiant is None:
                orphelins += 1
            else:
                fiche = fiches[identifiant]
                fiche["emprise_batie_m2"] += surface
                fiche["nb_batiments"] += 1

            batiments.append((
                code_insee, identifiant, type_bati, round(surface, 1),
                boite[1], boite[3], boite[0], boite[2],
                json.dumps({"type": "Polygon", "coordinates": [anneau]},
                           separators=(",", ":")),
            ))

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

        # Les batiments se remplacent en bloc : le cadastre republie la
        # commune entiere, et leurs identifiants ne sont pas stables.
        conn.execute("DELETE FROM batiment WHERE code_insee = ?", (code_insee,))
        conn.executemany(
            "INSERT INTO batiment (code_insee, parcelle_id, type, surface_m2, "
            "  lat_min, lat_max, lon_min, lon_max, geometrie_json, importe_le) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (ligne + (maintenant,) for ligne in batiments))

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


# ---------------------------------------------------------------------
#  Extrait cadastral d'un bien
# ---------------------------------------------------------------------

MARGE_EXTRAIT_M = 35        # ce qu'on montre autour de la parcelle


def _degres(metres, latitude):
    """Convertit une marge en metres en degres, aux deux axes."""
    lat = metres / geometrie.METRES_PAR_DEGRE_LAT
    lon = metres / (geometrie.METRES_PAR_DEGRE_LAT
                    * max(math.cos(math.radians(latitude)), 0.01))
    return lon, lat


def _dans_le_cadre(conn, table, code_insee, cadre, colonnes):
    """Objets dont la boite englobante croise le cadre."""
    lon_min, lat_min, lon_max, lat_max = cadre
    return conn.execute(
        f"SELECT {colonnes} FROM {table} "
        "WHERE code_insee = ? AND lat_max >= ? AND lat_min <= ? "
        "  AND lon_max >= ? AND lon_min <= ?",
        (code_insee, lat_min, lat_max, lon_min, lon_max)).fetchall()


def extrait(n_dpe, marge_m=MARGE_EXTRAIT_M):
    """
    De quoi dessiner un extrait cadastral autour d'un bien.

    Une parcelle seule ne se lit pas : c'est le voisinage qui donne
    l'echelle et l'orientation, et le bati qui montre ce qui est construit.
    On renvoie donc la parcelle, ses voisines et les batiments du cadre.
    """
    parcelle = parcelle_de(n_dpe)
    if parcelle is None:
        return None

    code_insee = parcelle["code_insee"]
    marge_lon, marge_lat = _degres(marge_m, parcelle["latitude"] or 46.0)
    cadre = (parcelle["lon_min"] - marge_lon, parcelle["lat_min"] - marge_lat,
             parcelle["lon_max"] + marge_lon, parcelle["lat_max"] + marge_lat)

    with connexion() as conn:
        voisines = _dans_le_cadre(
            conn, "parcelle", code_insee, cadre,
            "id, section, numero, contenance_m2, geometrie_json")
        batiments = _dans_le_cadre(
            conn, "batiment", code_insee, cadre,
            "parcelle_id, type, surface_m2, geometrie_json")

    def forme(ligne):
        try:
            return json.loads(ligne["geometrie_json"])
        except (TypeError, ValueError):
            return None

    return {
        "parcelle": parcelle,
        "cadre": {"lon_min": cadre[0], "lat_min": cadre[1],
                  "lon_max": cadre[2], "lat_max": cadre[3]},
        # Un cadastre importe avant qu'on ne conserve les contours donne un
        # extrait complet en apparence — parcelles et voisines — mais sans
        # aucun bati. Le dire ici est le seul moyen pour la fiche de le
        # signaler et d'offrir de le completer.
        "batiments_manquants": batiments_manquants(code_insee),
        "voisines": [
            {"id": ligne["id"], "section": ligne["section"], "numero": ligne["numero"],
             "contenance_m2": ligne["contenance_m2"], "geometrie": forme(ligne)}
            for ligne in voisines
            if ligne["id"] != parcelle["id"] and forme(ligne)
        ],
        "batiments": [
            {"parcelle_id": ligne["parcelle_id"], "type": ligne["type"],
             "surface_m2": ligne["surface_m2"], "geometrie": forme(ligne),
             "sur_la_parcelle": ligne["parcelle_id"] == parcelle["id"]}
            for ligne in batiments if forme(ligne)
        ],
    }


# Au-dela, le navigateur peine a tracer et la carte devient illisible :
# mieux vaut demander de zoomer que de rendre une bouillie de polygones.
MAX_CARTE = 1200


def pour_carte(code_insee, cadre, limite=MAX_CARTE):
    """
    Les parcelles visibles dans un cadre, avec ce qu'on sait d'elles.

    Renvoyer la commune entiere n'est pas envisageable : les geometries de
    Mimizan pesent 3,8 Mo pour 11 444 parcelles. On filtre donc par le
    cadre affiche, en s'appuyant sur l'index des boites englobantes.

    Chaque parcelle porte deux drapeaux — un DPE connu, une vente connue —
    dont le croisement fait les quatre couleurs de la carte. C'est ce
    croisement qui informe : une parcelle vendue sans DPE recent, ou
    diagnostiquee sans vente, ne racontent pas la meme histoire.
    """
    lon_min, lat_min, lon_max, lat_max = cadre
    with connexion() as conn:
        lignes = conn.execute(
            "SELECT p.id, p.section, p.numero, p.contenance_m2,"
            "       p.emprise_batie_m2, p.nb_batiments, p.latitude, p.longitude,"
            "       p.geometrie_json,"
            "       count(DISTINCT d.n_dpe) AS dpe,"
            "       max(d.date_etablissement) AS dpe_dernier,"
            "       min(d.n_dpe) AS n_dpe,"
            "       count(DISTINCT mp.mutation_id) AS ventes"
            "  FROM parcelle p"
            "  LEFT JOIN dpe d ON d.parcelle_id = p.id"
            "  LEFT JOIN mutation_parcelle mp ON mp.parcelle_id = p.id"
            " WHERE p.code_insee = ?"
            "   AND p.lat_max >= ? AND p.lat_min <= ?"
            "   AND p.lon_max >= ? AND p.lon_min <= ?"
            " GROUP BY p.id"
            # Les parcelles renseignees passent d'abord : si le cadre est
            # trop large pour tout envoyer, autant garder les informatives.
            " ORDER BY (count(DISTINCT d.n_dpe) > 0) DESC,"
            "          (count(DISTINCT mp.mutation_id) > 0) DESC, p.id"
            " LIMIT ?",
            (str(code_insee), lat_min, lat_max, lon_min, lon_max,
             int(limite) + 1)).fetchall()

    tronque = len(lignes) > int(limite)
    resultats = []
    for ligne in lignes[:int(limite)]:
        entree = dict(ligne)
        try:
            entree["geometrie"] = json.loads(entree.pop("geometrie_json"))
        except (TypeError, ValueError):
            continue
        entree["dpe"] = entree["dpe"] or 0
        entree["ventes"] = entree["ventes"] or 0
        resultats.append(entree)

    return {"parcelles": resultats, "tronque": tronque, "limite": int(limite)}


def chercher_sur_carte(code_insee, texte, combien=8):
    """
    Trouve un point de la commune, par adresse ou par reference cadastrale.

    Les deux entrees se melangent volontairement dans une seule boite : on
    cherche « rue des Pins » ou « AB 123 » selon ce qu'on a sous la main, et
    distinguer les deux champs obligerait a savoir lequel remplir.
    """
    recherche = " ".join(str(texte or "").split()).strip()
    if len(recherche) < 2:
        return []

    code_insee = str(code_insee)
    resultats, vus = [], set()

    # Reference cadastrale : « AB123 », « AB 123 », « AB0123 », ou
    # l'identifiant complet tel que la fiche l'affiche.
    #
    # Les deux ecritures du numero doivent passer : la colonne le garde
    # sans zeros de remplissage (« 148 ») quand l'identifiant les porte
    # (« AT0148 »). On interroge donc les deux formes — sans quoi la
    # reference lue sur la fiche ne se retrouverait pas sur la carte.
    compact = re.sub(r"[^A-Za-z0-9]", "", recherche).upper()
    if compact:
        with connexion() as conn:
            for ligne in conn.execute(
                    "SELECT id, section, numero, latitude, longitude"
                    "  FROM parcelle WHERE code_insee = ?"
                    "   AND (upper(section) || upper(numero) LIKE ?"
                    "        OR upper(id) LIKE ?) LIMIT ?",
                    (code_insee, f"%{compact}%", f"%{compact}%", combien)):
                vus.add(ligne["id"])
                resultats.append({
                    "type": "parcelle",
                    "libelle": f"Parcelle {ligne['section']}{ligne['numero']}",
                    "parcelle_id": ligne["id"],
                    "latitude": ligne["latitude"], "longitude": ligne["longitude"],
                })

    # Adresses : celles des DPE de la commune, qui portent une position.
    reste = combien - len(resultats)
    if reste > 0:
        motif = f"%{recherche.lower()}%"
        with connexion() as conn:
            for ligne in conn.execute(
                    "SELECT adresse, parcelle_id,"
                    "       avg(latitude) AS latitude, avg(longitude) AS longitude,"
                    "       count(*) AS diagnostics, min(n_dpe) AS n_dpe"
                    "  FROM dpe"
                    " WHERE code_insee = ? AND adresse IS NOT NULL"
                    "   AND lower(adresse) LIKE ?"
                    " GROUP BY lower(trim(adresse))"
                    " ORDER BY count(*) DESC, adresse LIMIT ?",
                    (code_insee, motif, reste)):
                if ligne["latitude"] is None:
                    continue
                resultats.append({
                    "type": "adresse",
                    "libelle": ligne["adresse"],
                    "parcelle_id": ligne["parcelle_id"],
                    "n_dpe": ligne["n_dpe"],
                    "diagnostics": ligne["diagnostics"],
                    "latitude": ligne["latitude"], "longitude": ligne["longitude"],
                })
    return resultats


def batiments_manquants(code_insee):
    """
    Le cadastre de cette commune a-t-il ete importe sans les contours ?

    C'est le cas de ceux importes avant qu'on ne les conserve : la fiche ne
    peut alors rien dessiner dessus, et il faut refaire l'import une fois.

    Une table `batiment` vide ne suffit pas a conclure : une commune de
    foret et de labours n'a legitimement aucun bati, et la signaler
    « incomplete » la ferait retelecharger a chaque recherche, sans fin.
    Le compte agregat `nb_batiments`, lui, etait deja renseigne par
    l'ancien import : s'il est positif alors que la table est vide, la
    commune a bien du bati et ce sont ses contours qui manquent.
    """
    with connexion() as conn:
        attendus = conn.execute(
            "SELECT coalesce(sum(nb_batiments), 0) FROM parcelle WHERE code_insee = ?",
            (str(code_insee),)).fetchone()[0]
        batis = conn.execute(
            "SELECT count(*) FROM batiment WHERE code_insee = ?",
            (str(code_insee),)).fetchone()[0]
    return attendus > 0 and batis == 0
