# -*- coding: utf-8 -*-
"""
references.py — Les ventes d'un departement, nettoyees pour apprendre.

L'estimation apprend a l'echelle du DEPARTEMENT. L'etude l'a etabli sur la
Nouvelle-Aquitaine : un modele appris sur toute la region ne fait jamais
mieux, meme pour la Creuse et ses 1 700 ventes par an, et la commune seule
est trop maigre. On telecharge donc, a la premiere estimation dans un
departement, ses cinq millesimes DVF — de 3 a 14 Mo — et on les
rafraichit quand un nouveau millesime parait.

LE NETTOYAGE garde ce dont le prix designe sans ambiguite UN bien :

  - une vente (ou une VEFA) d'exactement un logement — une maison ou un
    appartement, dependances admises — et d'aucun local d'activite. Une
    mutation qui vend deux maisons a un prix global qu'on ne sait pas
    repartir ;
  - un prix au m2 entre 300 et 25 000 EUR : on ecarte l'impossible (echange
    deguise, erreur de saisie), pas l'inhabituel ;
  - pas de « maison » sur plus de 5 ha : c'est une exploitation.

Les terrains a batir vendus NUS (aucun local) sont gardes a part : ils
donnent la valeur du sol, pour la methode sol + construction.

Le terrain d'une mutation se somme sur les couples DISTINCTS (parcelle,
nature de culture, surface) : chaque ligne DVF repete la surface de sa
parcelle, et une parcelle vendue avec deux locaux compterait sinon deux
fois son terrain.
"""

import datetime
import json
import logging

import numpy as np

from app.base.connexion import connexion, transaction
from app.sources import dvf, dvf_archive

logger = logging.getLogger(__name__)

NATURES = {"Vente", "Vente en l'état futur d'achèvement", "Vente terrain à bâtir"}
LOGEMENTS = {"Maison", "Appartement"}
ACTIVITE = "Local industriel. commercial ou assimilé"


def departement_de(code_insee):
    return dvf_archive.departement(code_insee)


def _nombre(valeur):
    try:
        return float(str(valeur).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _trimestre(date_texte):
    annee, mois = int(date_texte[:4]), int(date_texte[5:7])
    return f"{annee}-Q{(mois - 1) // 3 + 1}"


def nettoyer(lignes, departement):
    """
    Agrege les lignes DVF par mutation et trie ce qui peut servir.

    Renvoie (logements, terrains) : deux listes de tuples prets pour
    l'insertion. `lignes` est un iterable de dictionnaires, lu une seule
    fois — c'est ce qui permet de traiter un departement sans le charger
    entier en memoire.
    """
    mutations = {}
    for ligne in lignes:
        if ligne.get("nature_mutation") not in NATURES:
            continue
        ident = ligne.get("id_mutation")
        if not ident:
            continue
        m = mutations.get(ident)
        if m is None:
            m = mutations[ident] = {
                "date": ligne.get("date_mutation") or "",
                "nature": ligne.get("nature_mutation"),
                "prix": _nombre(ligne.get("valeur_fonciere")),
                "commune": ligne.get("code_commune") or "",
                "terrains": set(), "locaux": set(), "principal": None,
                "lat": [], "lon": [], "a_batir": False,
            }
        surface_terrain = _nombre(ligne.get("surface_terrain"))
        if surface_terrain:
            m["terrains"].add((ligne.get("id_parcelle"), ligne.get("code_nature_culture"),
                               surface_terrain))
        if ligne.get("code_nature_culture") == "AB":
            m["a_batir"] = True
        lat, lon = _nombre(ligne.get("latitude")), _nombre(ligne.get("longitude"))
        if lat is not None and lon is not None:
            m["lat"].append(lat)
            m["lon"].append(lon)
        type_local = ligne.get("type_local")
        if type_local:
            cle = (ligne.get("id_parcelle"), type_local, ligne.get("surface_reelle_bati"),
                   ligne.get("nombre_pieces_principales"), ligne.get("lot1_numero"))
            if cle not in m["locaux"]:
                m["locaux"].add(cle)
                if type_local in LOGEMENTS and m["principal"] is None:
                    numero = " ".join(filter(None, [
                        (ligne.get("adresse_numero") or "").strip(),
                        (ligne.get("adresse_suffixe") or "").strip(),
                        (ligne.get("adresse_nom_voie") or "").strip()]))
                    m["principal"] = {
                        "type": "maison" if type_local == "Maison" else "appartement",
                        "surface": _nombre(ligne.get("surface_reelle_bati")),
                        "pieces": _nombre(ligne.get("nombre_pieces_principales")),
                        "parcelle": ligne.get("id_parcelle"),
                        "adresse": numero or None,
                        "lat": lat, "lon": lon,
                    }

    logements, terrains = [], []
    for ident, m in mutations.items():
        prix, date = m["prix"], m["date"]
        if not prix or len(date) < 10 or not m["lat"]:
            continue
        types = [cle[1] for cle in m["locaux"]]
        nb_logements = sum(1 for t in types if t in LOGEMENTS)
        terrain = sum(s for _, _, s in m["terrains"])
        lat = m["principal"]["lat"] if m["principal"] and m["principal"]["lat"] is not None \
            else sum(m["lat"]) / len(m["lat"])
        lon = m["principal"]["lon"] if m["principal"] and m["principal"]["lon"] is not None \
            else sum(m["lon"]) / len(m["lon"])

        if nb_logements == 1 and ACTIVITE not in types:
            p = m["principal"]
            surface = p["surface"] or 0
            if prix <= 5000 or surface < 12:
                continue
            prix_m2 = prix / surface
            if not 300 <= prix_m2 <= 25000:
                continue
            if p["type"] == "maison" and terrain > 50000:
                continue
            logements.append((
                departement, ident, m["commune"], date, _trimestre(date), p["type"],
                prix, surface, int(p["pieces"]) if p["pieces"] else None, terrain,
                sum(1 for t in types if t == "Dépendance"),
                int(m["nature"] == "Vente en l'état futur d'achèvement"),
                lat, lon, p["parcelle"], p["adresse"]))
        elif not types and m["a_batir"] and terrain > 100 and prix > 3000:
            if 5 <= prix / terrain <= 3000:
                terrains.append((departement, ident, m["commune"], date, _trimestre(date),
                                 prix, terrain, lat, lon))
    return logements, terrains


def importer(departement, progression=None):
    """
    Telecharge et nettoie les millesimes DVF d'un departement, puis remplace
    ses ventes de reference. Leve ErreurSource si AUCUN millesime ne repond.
    """
    departement = str(departement)
    raison = dvf.indisponible(departement + "000")
    if raison:
        raise dvf.ErreurSource(raison)

    logements, terrains, vus = [], [], []
    for annee in dvf.millesimes():
        if progression:
            progression(f"Ventes du département {departement}, millésime {annee}")
        lignes = dvf.lignes_departement(departement, annee)
        if lignes is None:
            continue
        lg, tr = nettoyer(lignes, departement)
        logements.extend(lg)
        terrains.extend(tr)
        vus.append(annee)
    if not vus:
        raise dvf.ErreurSource(f"Aucune donnée DVF pour le département {departement}.")

    signatures = dvf.signatures_departement(departement)
    dates = sorted(l[3] for l in logements)
    maintenant = datetime.datetime.now().isoformat(timespec="seconds")
    with transaction() as conn:
        conn.execute("DELETE FROM vente_reference WHERE departement = ?", (departement,))
        conn.execute("DELETE FROM terrain_reference WHERE departement = ?", (departement,))
        conn.executemany(
            "INSERT OR REPLACE INTO vente_reference (departement, id_mutation, code_insee,"
            " date_vente, trimestre, type, prix, surface, pieces, terrain_m2, dependances,"
            " vefa, latitude, longitude, parcelle_id, adresse)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", logements)
        conn.executemany(
            "INSERT OR REPLACE INTO terrain_reference (departement, id_mutation, code_insee,"
            " date_vente, trimestre, prix, terrain_m2, latitude, longitude)"
            " VALUES (?,?,?,?,?,?,?,?,?)", terrains)
        conn.execute(
            "INSERT INTO departement_reference (departement, importe_le, signatures_json,"
            " ventes, terrains, premiere_vente, derniere_vente) VALUES (?,?,?,?,?,?,?)"
            " ON CONFLICT(departement) DO UPDATE SET importe_le = excluded.importe_le,"
            " signatures_json = excluded.signatures_json, ventes = excluded.ventes,"
            " terrains = excluded.terrains, premiere_vente = excluded.premiere_vente,"
            " derniere_vente = excluded.derniere_vente",
            (departement, maintenant, json.dumps({str(k): v for k, v in signatures.items()}),
             len(logements), len(terrains), dates[0] if dates else None,
             dates[-1] if dates else None))
    logger.info("references %s : %d ventes de logements, %d terrains, millesimes %s",
                departement, len(logements), len(terrains), vus)
    return {"departement": departement, "ventes": len(logements),
            "terrains": len(terrains), "millesimes": vus}


def etat(departement):
    with connexion() as conn:
        ligne = conn.execute("SELECT * FROM departement_reference WHERE departement = ?",
                             (str(departement),)).fetchone()
    return dict(ligne) if ligne else None


def a_rafraichir(departement):
    """Un millesime est-il paru (ou a-t-il ete republie) depuis l'import ?"""
    connu = etat(departement)
    if connu is None:
        return True
    try:
        actuelles = dvf.signatures_departement(departement)
    except dvf.ErreurSource:
        return False                      # on garde ce qu'on a
    anciennes = json.loads(connu["signatures_json"] or "{}")
    return {str(k): v for k, v in actuelles.items()} != anciennes


def departements_importes():
    with connexion() as conn:
        return [l["departement"] for l in conn.execute(
            "SELECT departement FROM departement_reference ORDER BY departement")]


# ---------------------------------------------------------------------
#  Chargement pour le calcul
# ---------------------------------------------------------------------
def charger_ventes(departement):
    """Les ventes du departement, en colonnes numpy — la forme que le calcul attend."""
    with connexion() as conn:
        lignes = conn.execute(
            "SELECT code_insee, date_vente, trimestre, type, prix, surface,"
            " coalesce(pieces, 0) AS pieces, terrain_m2, dependances, vefa, latitude,"
            " longitude, parcelle_id, adresse FROM vente_reference WHERE departement = ?"
            " ORDER BY date_vente, id_mutation", (str(departement),)).fetchall()
    return _colonnes(lignes, numeriques=("prix", "surface", "pieces", "terrain_m2",
                                         "dependances", "vefa", "latitude", "longitude"))


def charger_terrains(departement):
    with connexion() as conn:
        lignes = conn.execute(
            "SELECT id_mutation, code_insee, date_vente, trimestre, prix, terrain_m2,"
            " latitude, longitude FROM terrain_reference WHERE departement = ?"
            " ORDER BY date_vente", (str(departement),)).fetchall()
    return _colonnes(lignes, numeriques=("prix", "terrain_m2", "latitude", "longitude"))


def _colonnes(lignes, numeriques):
    if not lignes:
        return {"n": 0}
    cles = lignes[0].keys()
    donnees = {"n": len(lignes)}
    for cle in cles:
        valeurs = [l[cle] for l in lignes]
        donnees[cle] = (np.array(valeurs, dtype=float) if cle in numeriques
                        else np.array(valeurs, dtype=object))
    return donnees
