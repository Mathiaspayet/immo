# -*- coding: utf-8 -*-
"""
insee.py — Indices Notaires-Insee des prix des logements anciens.

Ils ne servent qu'a une chose : PROJETER une estimation sur les mois que
DVF ne couvre pas encore. DVF parait deux fois l'an avec six mois de
retard ; l'indice, lui, parait chaque trimestre environ deux mois apres la
fin du trimestre (le deuxieme trimestre 2026 est sorti le 8 septembre).

Ils ne peuvent pas servir d'indice LOCAL : l'Insee ne les publie que pour
la France, la province, l'Ile-de-France en detail, trois regions (Hauts-de-
France, Auvergne-Rhone-Alpes, Provence-Alpes-Cote d'Azur) et trois
agglomerations. Rien pour la Nouvelle-Aquitaine, aucun departement hors
Ile-de-France. L'indice local vient donc de DVF (voir metier/estimation.py) ;
mesure sur la Nouvelle-Aquitaine, il suit celui des maisons de province a un
ou deux points pres sur cinq ans, ce qui valide la methode.

Source publique, sans cle : le service SDMX de la Banque de donnees
macroeconomiques de l'Insee. Rien d'autre ne sort que la requete elle-meme.
"""

import logging
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

from app.sources.client_http import CONTEXTE, ENTETES, ErreurSource

logger = logging.getLogger(__name__)

URL = "https://bdm.insee.fr/series/sdmx/data/IPLA-IPLNA-2015"
# Il peut etre lu au moment d'estimer : on n'attend pas indefiniment.
DELAI = 45

TYPES = {"IPLA_M": "maison", "IPLA_A": "appartement"}

# La zone officielle la plus proche d'un departement. L'ordre compte : on
# prend la plus fine qui existe pour le type demande.
_IDF = {"75", "77", "78", "91", "92", "93", "94", "95"}
_REGIONS = {
    "R32": {"02", "59", "60", "62", "80"},                                   # Hauts-de-France
    "R84": {"01", "03", "07", "15", "26", "38", "42", "43", "63", "69", "73", "74"},  # AURA
    "R93": {"04", "05", "06", "13", "83", "84"},                             # PACA
}
_OUTRE_MER = {"971", "972", "973", "974"}


def zones_candidates(departement):
    """Les zones de l'indice, de la plus fine a la plus large, pour ce departement."""
    dep = str(departement)
    if dep in _IDF:
        return [f"D{dep}", "R11", "FM"]
    for region, deps in _REGIONS.items():
        if dep in deps:
            return [region, "PR", "FM"]
    if dep in _OUTRE_MER:
        return ["FR-D976"]
    return ["PR", "FM"]


def telecharger():
    """
    Toutes les series brutes des logements anciens, maisons et appartements.

    Renvoie [(zone, type, trimestre, indice), ...] — trimestre au format
    « 2026-Q2 », comme ailleurs dans l'application.
    """
    try:
        requete = urllib.request.Request(URL, headers=ENTETES)
        with urllib.request.urlopen(requete, timeout=DELAI, context=CONTEXTE) as reponse:
            contenu = reponse.read()
    except urllib.error.HTTPError as erreur:
        raise ErreurSource(f"Insee : HTTP {erreur.code}") from erreur
    except Exception as erreur:                      # noqa: BLE001
        raise ErreurSource(f"Insee injoignable ({type(erreur).__name__})") from erreur
    return lire(contenu)


def lire(contenu):
    """Extrait les observations du flux SDMX. Separe pour etre teste sans reseau."""
    racine = ET.fromstring(contenu)
    observations = []
    for serie in racine.iter():
        if not serie.tag.endswith("Series"):
            continue
        attributs = serie.attrib
        type_bien = TYPES.get(attributs.get("INDICATEUR", ""))
        if type_bien is None or attributs.get("CORRECTION") != "BRUT":
            continue
        zone = attributs.get("REF_AREA")
        for obs in serie:
            if not obs.tag.endswith("Obs"):
                continue
            periode, valeur = obs.attrib.get("TIME_PERIOD"), obs.attrib.get("OBS_VALUE")
            try:
                observations.append((zone, type_bien, periode, float(valeur)))
            except (TypeError, ValueError):
                continue
    if not observations:
        raise ErreurSource("Insee : aucune serie de logements anciens dans la reponse")
    return observations
