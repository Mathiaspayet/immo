# -*- coding: utf-8 -*-
"""
dvf_archive.py — Recuperer les millesimes que la source officielle ne
sert plus.

DVF ne se consulte que sur cinq ans. Ce n'est pas une limite d'Etalab :
le jeu officiel de la DGFiP n'offre lui aussi que cinq millesimes
(verifie le 24/08/2026 — 2021 a 2025, et rien avant). La restriction est
en amont, et aucune requete ne la contourne.

Reste ce que d'autres ont archive pendant que c'etait servi. Une
compilation departementale, publiee sur data.gouv.fr, couvre 2018 a 2022.
Pour Mimizan elle apporte 1 222 ventes de 2018, 2019 et 2020 — trois
annees qu'aucune source vivante ne rend plus.

Deux precautions, parce que cette source n'est pas de meme nature que les
autres :

  - elle est FIGEE (derniere mise a jour : mai 2023) et n'est donc pas
    guettee. On la lit une fois, pour reprendre l'ancien ; le courant
    continue de venir de geo-dvf ;
  - ses `id_mutation` sont ceux de SA chaine de publication, sans rapport
    avec ceux d'Etalab. Sur 2021, les deux decrivent les memes 574 ventes
    avec 15 identifiants en commun. C'est l'empreinte — date, montant,
    parcelles — qui les rapproche, et elle reconnait 574 des 574.

L'adresse du fichier porte une date dans son chemin ; on la demande donc
a l'API de data.gouv.fr plutot que de l'ecrire en dur.
"""

import csv
import io
import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from app.sources.client_http import CONTEXTE, ENTETES, ErreurSource

logger = logging.getLogger(__name__)

JEU = ("https://www.data.gouv.fr/api/1/datasets/"
       "compilation-des-donnees-de-valeurs-foncieres-dvf-par-departement/")
DELAI = 600


def departement(code_insee):
    code = str(code_insee).strip()
    return code[:3] if code[:2] == "97" else code[:2]


def _ressource(dep):
    """L'adresse du fichier departemental, demandee au catalogue."""
    try:
        requete = urllib.request.Request(JEU, headers=ENTETES)
        with urllib.request.urlopen(requete, timeout=120, context=CONTEXTE) as reponse:
            catalogue = json.load(reponse)
    except Exception as erreur:                      # noqa: BLE001
        raise ErreurSource(
            f"Catalogue data.gouv.fr injoignable ({type(erreur).__name__})"
        ) from erreur

    for ressource in catalogue.get("resources", []):
        titre = (ressource.get("title") or "").strip()
        # Les titres sont de la forme « 40 - Landes ».
        if titre.split("-")[0].strip() == dep:
            return ressource.get("url"), titre
    raise ErreurSource(
        f"Aucune archive DVF pour le departement {dep} dans la compilation.")


def telecharger(code_insee, progression=None):
    """
    Les lignes archivees d'une commune, au format de geo-dvf.

    Le fichier est departemental — 34 Mo pour les Landes — et se lit au
    fil de l'eau : on ne garde que la commune demandee, sans jamais poser
    l'ensemble en memoire.
    """
    code_insee = str(code_insee).strip()
    dep = departement(code_insee)
    url, titre = _ressource(dep)
    if progression:
        progression(f"archive DVF « {titre} »…")

    try:
        requete = urllib.request.Request(url, headers=ENTETES)
        with urllib.request.urlopen(requete, timeout=DELAI, context=CONTEXTE) as reponse:
            flux = io.TextIOWrapper(reponse, encoding="utf-8", errors="replace")
            lignes = [l for l in csv.DictReader(flux)
                      if (l.get("code_commune") or "").strip() == code_insee]
    except urllib.error.HTTPError as erreur:
        raise ErreurSource(f"Archive DVF : HTTP {erreur.code}") from erreur
    except Exception as erreur:                      # noqa: BLE001
        raise ErreurSource(
            f"Archive DVF injoignable ({type(erreur).__name__})") from erreur

    annees = sorted({(l.get("date_mutation") or "")[:4] for l in lignes} - {""})
    logger.info("archive dvf %s : %d lignes, millesimes %s",
                code_insee, len(lignes), ", ".join(annees) or "aucun")
    return lignes
