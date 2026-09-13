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
from app.metier import geometrie, veille
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

def index_spatial(code_insee):
    """
    L'index des parcelles d'une commune, construit une fois.

    Public : les deux passes de rattachement — stricte puis approchee — le
    partagent. Le reconstruire deux fois coute 11 444 geometries relues
    pour rien.
    """
    return _index_depuis_la_base(code_insee)


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


# Un diagnostic geocode sur la chaussee est a quelques metres de sa
# parcelle. Au-dela, ce n'est plus « devant » : c'est ailleurs.
RAYON_APPROCHE_M = 10.0
# ... et il faut que la gagnante le soit NETTEMENT. Sans ce garde, une
# adresse sans numero de rue — geocodee au milieu de la voie, a egale
# distance des deux cotes — serait attribuee a pile ou face.
ECART_MINIMAL_M = 2.0


def rattacher_approche(code_insee, index=None,
                       rayon=RAYON_APPROCHE_M, ecart=ECART_MINIMAL_M):
    """
    Rapproche d'une parcelle les diagnostics qu'aucune ne contient.

    C'est une ESTIMATION, et elle est rangee a part de `parcelle_id` :
    l'ecran doit pouvoir dire « position approchee », et la fiche continuer
    a lire l'historique des ventes sur la seule parcelle certaine.

    Deux conditions, toutes deux necessaires :

      - la parcelle est a moins de `rayon` metres. Sur Mimizan, les
        diagnostics concernes sont a 0,5 - 4 m de leur parcelle : ils sont
        poses sur la chaussee, devant. A 36 m on n'est plus devant ;
      - aucune autre ne la suit a moins de `ecart` metres. Les adresses
        SANS NUMERO de rue sont geocodees au milieu de la voie, a egale
        distance des parcelles des deux cotes : les departager serait
        inventer. Elles restent sans parcelle, et la carte les montre pour
        ce qu'elles sont — un point, pas une parcelle.
    """
    code_insee = str(code_insee).strip()
    if index is None:
        index = _index_depuis_la_base(code_insee)
    if not len(index):
        return {"rattaches": 0, "ecartes": 0}

    with connexion() as conn:
        candidats = conn.execute(
            "SELECT n_dpe, latitude, longitude FROM dpe "
            " WHERE code_insee = ? AND latitude IS NOT NULL"
            "   AND parcelle_id IS NULL",
            (code_insee,)).fetchall()

    couples, ecartes = [], 0
    for ligne in candidats:
        proches = index.voisines(ligne["longitude"], ligne["latitude"], rayon)
        if not proches:
            ecartes += 1
            continue
        distance, identifiant = proches[0]
        if len(proches) > 1 and proches[1][0] - distance < ecart:
            ecartes += 1
            continue
        couples.append((identifiant, round(distance, 1), ligne["n_dpe"]))

    if couples:
        with transaction() as conn:
            conn.executemany(
                "UPDATE dpe SET parcelle_approchee = ?, distance_parcelle_m = ? "
                " WHERE n_dpe = ?", couples)
    return {"rattaches": len(couples), "ecartes": ecartes}


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


def _depuis_la_ligne(ligne):
    if ligne is None:
        return None
    parcelle = dict(ligne)
    try:
        parcelle["geometrie"] = json.loads(parcelle.pop("geometrie_json"))
    except (TypeError, ValueError):
        parcelle.pop("geometrie_json", None)
    return parcelle


def parcelle_de(n_dpe):
    """La parcelle qui porte ce DPE, geometrie comprise — pour la fiche."""
    with connexion() as conn:
        return _depuis_la_ligne(conn.execute(
            "SELECT p.* FROM parcelle p "
            "JOIN dpe d ON d.parcelle_id = p.id WHERE d.n_dpe = ?",
            (str(n_dpe),)).fetchone())


def parcelle(identifiant):
    """
    Une parcelle par son identifiant cadastral.

    Sert a ouvrir une fiche depuis la carte : la plupart des parcelles ne
    portent aucun DPE — sur une vue courante de Mimizan, 468 sur 550 — et
    il faut pouvoir les consulter tout de meme.
    """
    with connexion() as conn:
        return _depuis_la_ligne(conn.execute(
            "SELECT * FROM parcelle WHERE id = ?", (str(identifiant),)).fetchone())


def diagnostics_de(identifiant):
    """
    Les diagnostics portes par une parcelle, du plus recent au plus ancien.

    Sans eux, cliquer une parcelle qui en porte plusieurs n'en montrait
    qu'UN — celui dont le numero vient le premier dans l'ordre
    alphabetique — et rien ne disait que les autres existaient.

    Ce n'est pas un cas rare. Beaucoup d'adresses de l'ADEME n'ont pas de
    numero de rue et sont geocodees au centre de la voie ou de la
    residence : sur Mimizan, 2 420 diagnostics partagent leur position avec
    un autre, et un seul point en porte 180.

    `parcelle_carte` sert de clef : elle reunit l'appartenance stricte et
    le rattachement approche, comme la carte elle-meme.
    """
    colonnes = ", ".join(veille.COLONNES)
    with connexion() as conn:
        return [dict(ligne) for ligne in conn.execute(
            f"SELECT {colonnes}, (parcelle_id IS NULL) AS position_approchee"
            "   FROM dpe WHERE parcelle_carte = ?"
            "  ORDER BY date_etablissement DESC, n_dpe DESC",
            (str(identifiant),))]


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
    """L'extrait cadastral autour du bien porteur de ce DPE."""
    return extrait_de(parcelle_de(n_dpe), marge_m)


def extrait_parcelle(identifiant, marge_m=MARGE_EXTRAIT_M):
    """Le meme extrait, demande par la parcelle — le chemin de la carte."""
    return extrait_de(parcelle(identifiant), marge_m)


def extrait_de(parcelle, marge_m=MARGE_EXTRAIT_M):
    """
    De quoi dessiner un extrait cadastral autour d'une parcelle.

    Une parcelle seule ne se lit pas : c'est le voisinage qui donne
    l'echelle et l'orientation, et le bati qui montre ce qui est construit.
    On renvoie donc la parcelle, ses voisines et les batiments du cadre.
    """
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
# Le plafond de parcelles renvoyees d'un coup. Relevé de 1 600 a 3 000
# quand la carte a su descendre au zoom 13 : a cette echelle une commune
# entiere tient a l'ecran, et Mimizan y compte 2 239 parcelles
# renseignees. Le plafond ne tient que parce que la reponse est ALLEGEE
# a ces zooms-la — voir `pour_carte`, `avec_geometrie`.
MAX_CARTE = 3000

# Six decimales valent ~11 cm : bien au-dela de ce qu'un contour cadastral
# affiche a l'ecran peut rendre, et bien en deca des 16 chiffres que
# `json.dumps` ecrivait par defaut (« -1.2426787850467291 »). 28 % du
# poids de la reponse partaient en decimales invisibles.
DECIMALES_CARTE = 6

# Les diagnostics qu'aucune parcelle ne porte, poses en losange. Ils ne
# coutent pas de geometrie : le plafond peut etre large.
MAX_POINTS = 1000

# A partir de quelle SURFACE REVENDIQUEE PAR DIAGNOSTIC une parcelle
# cesse d'etre un bon approximant.
#
# Colorer une parcelle, c'est dire « ce terrain est diagnostique ». Sur
# les 900 m² d'une maison, c'est vrai, et c'est meme plus juste que le
# point de l'ADEME — geocode a l'adresse, donc sur la chaussee. Sur les
# 18 hectares de 401840000K0051, un seul diagnostic peint une foret
# entiere.
#
# Le seuil ne se lit pas au nombre de batiments : le cadastre compte les
# garages et les abris, et un meme batiment peut porter plusieurs
# logements — 109 diagnostics pour 17 batiments sur une parcelle de
# Mimizan. C'est la surface par diagnostic qui discrimine. Releve sur les
# 762 parcelles diagnostiquees de Mimizan :
#
#     jusqu'a 1 000 m²   : 636 parcelles
#     1 000 a 3 000 m²   : 118
#     3 000 a 10 000 m²  :  25
#     plus de 10 000 m²  :   5
#
# 754 sur 762 sont irreprochables ; le seuil n'attrape que les 30 autres.
M2_PAR_DIAGNOSTIC = 3000


def _arrondir(valeur, decimales=DECIMALES_CARTE):
    """Arrondit les coordonnees d'une geometrie GeoJSON, en place."""
    if isinstance(valeur, list):
        return [_arrondir(element, decimales) for element in valeur]
    if isinstance(valeur, float):
        return round(valeur, decimales)
    return valeur


def pour_carte(code_insee, cadre, limite=MAX_CARTE, filtres_dpe=None,
               avec_geometrie=True):
    """
    Les parcelles visibles dans un cadre, avec ce qu'on sait d'elles.

    Renvoyer la commune entiere n'est pas envisageable : les geometries de
    Mimizan pesent 3,8 Mo pour 11 444 parcelles. On filtre donc par le
    cadre affiche, en s'appuyant sur l'index des boites englobantes.

    Chaque parcelle porte deux drapeaux — un DPE connu, une vente connue —
    dont le croisement fait les couleurs de la carte. C'est ce croisement
    qui informe : une parcelle vendue sans DPE recent, ou diagnostiquee
    sans vente, ne racontent pas la meme histoire.

    `filtres_dpe` RESSERRE le drapeau « DPE » sans toucher a celui des
    ventes : la carte se colore alors selon les seuls diagnostics qui
    repondent aux criteres de l'ecran — les trois derniers mois, les
    maisons de plus de 120 m², les classes F et G. C'est la carte
    elle-meme qui repond, au lieu d'une liste posee a cote.

    Le rattachement APPROCHE compte ici, et seulement ici : une parcelle
    situee a un metre d'un diagnostic geocode sur la chaussee est bien la
    sienne pour l'oeil. `dpe_approche` dit combien le sont, pour que la
    carte puisse le marquer au lieu de le taire.

    ON NE REND QUE CE DONT ON SAIT QUELQUE CHOSE. Une parcelle sans
    diagnostic retenu ni vente connue n'est pas envoyee du tout. Elle
    l'etait, en voile blanc, et c'etaient 9 205 parcelles sur les 11 444
    de Mimizan — 80 % de la reponse pour dire « rien ». Le contour reste
    visible : il vient de la couche parcellaire de l'IGN, qui est une
    tuile, pas une geometrie a transporter.

    `avec_geometrie=False` REND UNE POSITION AU LIEU D'UN CONTOUR. C'est
    ce que demande la carte quand elle recule assez pour montrer une
    commune entiere : au zoom 13, un pixel vaut 13,7 m et une parcelle
    n'en couvre que deux ou trois — son contour exact ne se voit pas, il
    se paie seulement. Mesure sur Mimizan, commune entiere : 1 538 Ko
    avec les contours, et ce qu'il faut pour poser un point a la place.
    """
    lon_min, lat_min, lon_max, lat_max = cadre
    ou_dpe, parametres_dpe = ("1 = 1", [])
    if filtres_dpe:
        ou_dpe, parametres_dpe = veille.conditions_dpe(filtres_dpe, prefixe="d.")

    # Le detail ne se paie que s'il se voit. Sans contour, on n'a pas
    # besoin non plus de la contenance ni du bati : rien de tout cela ne
    # se lit a cette echelle, et tout se relit d'un clic sur la fiche.
    colonnes = ("p.section, p.numero, p.contenance_m2, p.emprise_batie_m2,"
                " p.nb_batiments, p.geometrie_json," if avec_geometrie else "")
    with connexion() as conn:
        lignes = conn.execute(
            "SELECT p.id, p.latitude, p.longitude,"
            f"      {colonnes}"
            "       count(DISTINCT d.n_dpe) AS dpe,"
            "       count(DISTINCT CASE WHEN d.parcelle_id IS NULL"
            "                           THEN d.n_dpe END) AS dpe_approche,"
            "       max(d.date_etablissement) AS dpe_dernier,"
            "       min(d.n_dpe) AS n_dpe,"
            "       count(DISTINCT mp.mutation_id) AS ventes"
            "  FROM parcelle p"
            # `parcelle_carte` est une colonne GENEREE, et indexee :
            # le meme calcul ecrit en clair dans la jointure privait la
            # requete de tous ses index (migration 011).
            "  LEFT JOIN dpe d ON d.parcelle_carte = p.id"
            f"   AND {ou_dpe}"
            "  LEFT JOIN mutation_parcelle mp ON mp.parcelle_id = p.id"
            " WHERE p.code_insee = ?"
            "   AND p.lat_max >= ? AND p.lat_min <= ?"
            "   AND p.lon_max >= ? AND p.lon_min <= ?"
            " GROUP BY p.id"
            # Rien de connu, rien a envoyer.
            " HAVING count(DISTINCT d.n_dpe) > 0"
            "     OR count(DISTINCT mp.mutation_id) > 0"
            # Si le plafond mord, autant qu'il morde sur les ventes seules :
            # un diagnostic est ce qu'on vient chercher ici.
            " ORDER BY (count(DISTINCT d.n_dpe) > 0) DESC, p.id"
            " LIMIT ?",
            parametres_dpe + [str(code_insee), lat_min, lat_max, lon_min, lon_max,
                              int(limite) + 1]).fetchall()

    tronque = len(lignes) > int(limite)
    resultats = []
    for ligne in lignes[:int(limite)]:
        entree = dict(ligne)
        if avec_geometrie:
            try:
                geometrie = json.loads(entree.pop("geometrie_json"))
                geometrie["coordinates"] = _arrondir(geometrie.get("coordinates"))
                entree["geometrie"] = geometrie
            except (TypeError, ValueError, AttributeError):
                # Un contour illisible n'est pas affichable : on la tait
                # plutot que d'envoyer une parcelle qui ne se dessinera pas.
                continue
        else:
            # Sans contour, c'est la position qui place la marque — et une
            # parcelle sans position n'en a aucune.
            if entree["latitude"] is None or entree["longitude"] is None:
                continue
            entree["latitude"] = _arrondir(entree["latitude"])
            entree["longitude"] = _arrondir(entree["longitude"])
        entree["dpe"] = entree["dpe"] or 0
        entree["dpe_approche"] = entree["dpe_approche"] or 0
        entree["ventes"] = entree["ventes"] or 0
        # Trop vaste pour que sa couleur veuille dire quelque chose. La
        # carte la laissera en retrait et posera les diagnostics la ou ils
        # sont vraiment. Sans contour il n'y a rien a peindre : la
        # question ne se pose qu'ici.
        surface = entree.get("contenance_m2") or 0
        entree["trop_vaste"] = bool(
            avec_geometrie and entree["dpe"]
            and surface / entree["dpe"] > M2_PAR_DIAGNOSTIC)
        resultats.append(entree)

    # Il n'y a plus qu'une sorte de troncature. Tant que le voile existait,
    # le plafond mordait presque toujours sur lui — 1 549 parcelles pour un
    # plafond de 1 600 sur un ecran large — et il fallait distinguer ce
    # manque anodin d'un vrai. Maintenant que seules les parcelles
    # renseignees sont rendues, tronquer, c'est cacher.
    _situer_les_trop_vastes(resultats, ou_dpe, parametres_dpe)

    points, points_tronques = _dpe_sans_parcelle(code_insee, cadre, filtres_dpe,
                                                 leger=not avec_geometrie)
    return {"parcelles": resultats, "tronque": tronque, "limite": int(limite),
            "points": points, "points_tronques": points_tronques}


def _situer_les_trop_vastes(resultats, ou_dpe, parametres_dpe):
    """
    Donne a chaque parcelle trop vaste la POSITION de ses diagnostics.

    Sur une parcelle de la taille d'une maison, la couleur suffit : elle
    dit ou est le logement mieux que ne le ferait le point de l'ADEME,
    pose sur la chaussee. Sur dix-huit hectares, elle ne dit plus rien, et
    ce sont les points qui portent le peu qu'on sait.

    Modifie `resultats` sur place. Ne concerne qu'une poignee de parcelles
    — 30 sur 762 a Mimizan — donc le cout est negligeable, et nul quand
    le cadre n'en contient aucune.
    """
    vastes = [e["id"] for e in resultats if e.get("trop_vaste")]
    if not vastes:
        return

    trous = ",".join("?" * len(vastes))
    with connexion() as conn:
        lignes = conn.execute(
            "SELECT d.parcelle_carte AS parcelle, d.n_dpe, d.latitude, d.longitude"
            "  FROM dpe d"
            f" WHERE d.parcelle_carte IN ({trous})"
            "   AND d.latitude IS NOT NULL AND d.longitude IS NOT NULL"
            f"   AND {ou_dpe}"
            " ORDER BY d.date_etablissement DESC, d.n_dpe",
            vastes + parametres_dpe).fetchall()

    par_parcelle = {}
    for ligne in lignes:
        par_parcelle.setdefault(ligne["parcelle"], []).append({
            "n_dpe": ligne["n_dpe"],
            "latitude": _arrondir(ligne["latitude"]),
            "longitude": _arrondir(ligne["longitude"]),
        })
    for entree in resultats:
        if entree.get("trop_vaste"):
            entree["diagnostics"] = par_parcelle.get(entree["id"], [])


def _dpe_sans_parcelle(code_insee, cadre, filtres_dpe=None, leger=False):
    """
    Les diagnostics qu'AUCUNE parcelle ne porte, meme par approche.

    Ce sont les adresses sans numero de rue — « Rue de la Poste » — que
    l'ADEME geocode au milieu de la voie, a egale distance des parcelles
    des deux cotes. Les departager serait inventer ; les taire serait pire.
    La carte leur pose un point, et la legende dit ce qu'il vaut.

    `leger` n'en garde que de quoi poser une marque. A l'echelle d'une
    commune entiere il n'y a pas de bulle a ouvrir : la date, la surface
    et l'etiquette ne s'affichent nulle part, et il y a mille de ces
    points — c'est tout de suite du poids pour rien.
    """
    lon_min, lat_min, lon_max, lat_max = cadre
    ou_dpe, parametres = ("1 = 1", [])
    if filtres_dpe:
        ou_dpe, parametres = veille.conditions_dpe(filtres_dpe, prefixe="d.")

    detail = ("d.adresse, d.date_etablissement, d.surface_habitable,"
              " d.etiquette_dpe, d.type_batiment," if not leger else "")
    with connexion() as conn:
        lignes = conn.execute(
            "SELECT d.n_dpe, d.latitude, d.longitude,"
            f"      {detail}"
            "       (d.vu_le IS NULL) AS nouveau"
            "  FROM dpe d"
            " WHERE d.code_insee = ?"
            "   AND d.parcelle_id IS NULL AND d.parcelle_approchee IS NULL"
            "   AND d.latitude IS NOT NULL"
            "   AND d.latitude BETWEEN ? AND ?"
            "   AND d.longitude BETWEEN ? AND ?"
            f"   AND {ou_dpe}"
            " ORDER BY d.date_etablissement DESC"
            " LIMIT ?",
            [str(code_insee), lat_min, lat_max, lon_min, lon_max] + parametres
            + [MAX_POINTS + 1]).fetchall()
    # Le plafond etait atteint SANS RIEN DIRE : la carte montrait 300
    # losanges sur un nombre inconnu. Il se signale maintenant.
    return [dict(ligne) for ligne in lignes[:MAX_POINTS]], len(lignes) > MAX_POINTS


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
