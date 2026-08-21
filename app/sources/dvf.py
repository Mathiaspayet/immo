# -*- coding: utf-8 -*-
"""
dvf.py — Demandes de valeurs foncieres, en CSV par commune et par annee.

DVF recense les mutations immobilieres enregistrees par la DGFiP. Etalab en
publie une version geocodee, decoupee par commune — la meme forme que le
cadastre, et surtout la meme clef : `id_parcelle`. C'est ce qui permet de
rattacher une vente a un bien sans jamais passer par l'adresse, dont
l'orthographe varie.

Deux limites de la source, a connaitre avant de s'y fier :

  - l'Alsace-Moselle (57, 67, 68) et Mayotte en sont ABSENTS : ces
    territoires ont leur propre livre foncier ;
  - une mutation peut porter sur plusieurs parcelles et plusieurs locaux.
    `valeur_fonciere` vaut alors pour l'ENSEMBLE et se repete a l'identique
    sur chaque ligne. Mesure sur Mimizan : 1 118 mutations sur 2 054 tiennent
    sur plusieurs lignes, et sommer les lignes d'une vente a 400 000 € en
    annonce 1 600 000. Le regroupement se fait dans metier/mutations.py.
"""

import csv
import io
import logging
import urllib.error
import urllib.request

from app.sources.client_http import CONTEXTE, ENTETES, ErreurSource

logger = logging.getLogger(__name__)

RACINE = "https://files.data.gouv.fr/geo-dvf/latest/csv"
DELAI = 180

# Millesimes publies. DVF parait deux fois l'an et le plus recent est
# partiel : l'annee en cours ne porte que les ventes deja enregistrees.
ANNEES = (2021, 2022, 2023, 2024, 2025)

# Departements sans DVF, faute d'un cadastre de meme nature.
SANS_DVF = {"57", "67", "68", "976"}


def indisponible(code_insee):
    """Pourquoi cette commune n'aura pas de DVF, ou None si elle en a."""
    code = str(code_insee)
    if code[:3] == "976" or code[:2] in SANS_DVF:
        return ("L'Alsace-Moselle et Mayotte tiennent leur propre livre "
                "foncier : DVF ne les couvre pas.")
    return None


def url_annee(code_insee, annee):
    departement = code_insee[:3] if code_insee[:2] == "97" else code_insee[:2]
    return f"{RACINE}/{annee}/communes/{departement}/{code_insee}.csv"


def telecharger(code_insee, annees=ANNEES, progression=None):
    """
    Recupere les mutations d'une commune, tous millesimes confondus.

    Un millesime absent n'est pas une erreur : une petite commune peut
    n'avoir enregistre aucune vente cette annee-la. On ne leve que si
    AUCUNE annee ne repond — la, c'est la commune qui n'est pas couverte.
    """
    raison = indisponible(code_insee)
    if raison:
        raise ErreurSource(raison)

    lignes, annees_vues = [], []
    for annee in annees:
        if progression:
            progression(f"ventes — {annee}")
        contenu = _telecharger_annee(code_insee, annee)
        if contenu is None:
            continue
        annees_vues.append(annee)
        lignes.extend(csv.DictReader(io.StringIO(contenu)))

    if not annees_vues:
        raise ErreurSource(
            f"Aucune donnee DVF pour la commune {code_insee}. Elle est "
            "peut-etre hors couverture, ou n'a enregistre aucune vente.")

    logger.info("dvf %s : %d lignes sur %d millesime(s)",
                code_insee, len(lignes), len(annees_vues))
    if progression:
        progression(f"ventes — {len(lignes)} lignes")
    return lignes


def _telecharger_annee(code_insee, annee):
    """Le CSV d'une annee, ou None si ce millesime ne concerne pas la commune."""
    url = url_annee(code_insee, annee)
    try:
        requete = urllib.request.Request(url, headers=ENTETES)
        with urllib.request.urlopen(requete, timeout=DELAI, context=CONTEXTE) as reponse:
            return reponse.read().decode("utf-8")
    except urllib.error.HTTPError as erreur:
        if erreur.code in (403, 404):
            logger.info("dvf %s : pas de millesime %s", code_insee, annee)
            return None
        raise ErreurSource(f"DVF : HTTP {erreur.code} sur {annee}") from erreur
    except Exception as erreur:                      # noqa: BLE001
        raise ErreurSource(f"DVF injoignable ({type(erreur).__name__})") from erreur
