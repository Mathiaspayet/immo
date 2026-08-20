# -*- coding: utf-8 -*-
"""
cadastre.py — Cadastre Etalab, en GeoJSON par commune.

Deux couches par commune : les parcelles (le decoupage foncier, avec la
contenance officielle) et les batiments (leur emprise au sol). Les fichiers
arrivent compresses en gzip ; a l'echelle d'une commune ils pesent quelques
megaoctets et se telechargent en quelques secondes.
"""

import gzip
import json
import logging
import urllib.error
import urllib.request

from app.sources.client_http import CONTEXTE, ENTETES, ErreurSource

logger = logging.getLogger(__name__)

RACINE = "https://cadastre.data.gouv.fr/data/etalab-cadastre/latest/geojson/communes"
COUCHES = ("parcelles", "batiments")
DELAI = 300        # ces fichiers sont plus gros que du JSON d'API


def url_couche(code_insee, couche):
    departement = code_insee[:2]
    # La Corse et l'outre-mer ont des codes a trois caracteres de prefixe.
    if code_insee[:2] in ("2A", "2B"):
        departement = code_insee[:2]
    elif code_insee[:3] in ("971", "972", "973", "974", "976"):
        departement = code_insee[:3]
    return (f"{RACINE}/{departement}/{code_insee}/"
            f"cadastre-{code_insee}-{couche}.json.gz")


def telecharger_couche(code_insee, couche, progression=None):
    """
    Recupere une couche et renvoie ses objets GeoJSON.

    Leve ErreurSource si la commune est absente du cadastre — c'est le cas
    de l'Alsace-Moselle sur certaines couches, et de quelques communes
    fusionnees dont le millesime n'a pas suivi.
    """
    if couche not in COUCHES:
        raise ValueError(f"couche inconnue : {couche}")

    url = url_couche(code_insee, couche)
    if progression:
        progression(f"cadastre — téléchargement des {couche}")

    try:
        requete = urllib.request.Request(url, headers=ENTETES)
        with urllib.request.urlopen(requete, timeout=DELAI, context=CONTEXTE) as reponse:
            compresse = reponse.read()
    except urllib.error.HTTPError as erreur:
        if erreur.code == 404:
            raise ErreurSource(
                f"La commune {code_insee} n'a pas de couche « {couche} » dans le "
                "cadastre ouvert. Certaines communes en sont absentes — "
                "l'Alsace-Moselle a son propre livre foncier."
            ) from erreur
        raise ErreurSource(f"cadastre : HTTP {erreur.code} sur {couche}") from erreur
    except Exception as erreur:                      # noqa: BLE001
        raise ErreurSource(f"cadastre injoignable ({type(erreur).__name__})") from erreur

    try:
        objets = json.loads(gzip.decompress(compresse).decode("utf-8"))["features"]
    except (OSError, ValueError, KeyError) as erreur:
        raise ErreurSource(f"cadastre : fichier {couche} illisible") from erreur

    logger.info("cadastre %s / %s : %d objets (%.1f Mo compresses)",
                code_insee, couche, len(objets), len(compresse) / 1024 / 1024)
    if progression:
        progression(f"cadastre — {len(objets)} {couche}")
    return objets
