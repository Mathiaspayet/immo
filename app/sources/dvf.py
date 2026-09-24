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
import datetime
import gzip
import io
import logging
import urllib.error
import urllib.request

from app.sources.client_http import CONTEXTE, ENTETES, ErreurSource

logger = logging.getLogger(__name__)

RACINE = "https://files.data.gouv.fr/geo-dvf/latest/csv"
DELAI = 180

# DVF parait deux fois l'an, et Etalab n'en garde qu'une FENETRE
# GLISSANTE de cinq millesimes. Verifie le 24/08/2026 : 2019 et 2020
# rendent 404 pour toutes les communes, Toulouse comprise, tandis que 2021
# a 2025 repondent.
#
# La liste etait ecrite en dur. Elle se serait donc tue deux fois : en
# manquant le millesime neuf des sa parution, et sans jamais le signaler —
# un millesime absent est traite comme une commune sans vente cette
# annee-la (voir _telecharger_annee), ce qui est le cas legitime le plus
# frequent. L'historique se serait fige a fin 2025 en paraissant complet.
PROFONDEUR = 5


def millesimes(aujourdhui=None):
    """
    Les millesimes a tenter, du plus ancien au plus recent.

    On en demande un de plus que la fenetre ne peut en contenir : l'annee
    en cours n'apparait qu'a la parution d'automne, et la reclamer d'ici la
    ne coute qu'un 404 deja prevu. C'est ce millesime en trop qui fait que
    la nouveaute est prise le jour ou elle parait, sans rien a modifier.
    """
    an = (aujourdhui or datetime.date.today()).year
    return tuple(range(an - PROFONDEUR, an + 1))


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


def telecharger(code_insee, annees=None, progression=None):
    """
    Recupere les mutations d'une commune, tous millesimes confondus.

    Un millesime absent n'est pas une erreur : une petite commune peut
    n'avoir enregistre aucune vente cette annee-la. On ne leve que si
    AUCUNE annee ne repond — la, c'est la commune qui n'est pas couverte.
    """
    raison = indisponible(code_insee)
    if raison:
        raise ErreurSource(raison)

    annees = millesimes() if annees is None else annees
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


def signature_annee(code_insee, annee):
    """
    De quoi reconnaitre une republication, sans telecharger le fichier.

    Il n'existe pas d'API de version chez Etalab. Mais le serveur pose un
    ETag et une date de derniere modification, et une requete HEAD les rend
    pour quelques centaines d'octets. C'est ce qui permet de guetter la
    parution tous les jours sans retirer un megaoctet de CSV a chaque fois.

    Renvoie None si le millesime n'existe pas — c'est le cas courant de
    l'annee en cours avant la parution d'automne.
    """
    url = url_annee(code_insee, annee)
    try:
        requete = urllib.request.Request(url, headers=ENTETES, method="HEAD")
        with urllib.request.urlopen(requete, timeout=DELAI, context=CONTEXTE) as reponse:
            return (reponse.headers.get("ETag")
                    or reponse.headers.get("Last-Modified"))
    except urllib.error.HTTPError as erreur:
        if erreur.code in (403, 404):
            return None
        raise ErreurSource(f"DVF : HTTP {erreur.code} sur {annee}") from erreur
    except Exception as erreur:                      # noqa: BLE001
        raise ErreurSource(f"DVF injoignable ({type(erreur).__name__})") from erreur


def signatures(code_insee, annees=None):
    """Les signatures de tous les millesimes, {annee: signature ou None}."""
    annees = millesimes() if annees is None else annees
    return {annee: signature_annee(code_insee, annee) for annee in annees}


# ---------------------------------------------------------------------
#  Un departement entier, pour l'estimation
# ---------------------------------------------------------------------
# L'estimation apprend sur les ventes de tout le departement, pas de la
# seule commune suivie. Etalab en publie un fichier par departement et par
# annee, compresse : de 0,5 a 3 Mo selon le departement — la Gironde, la
# plus lourde des douze de Nouvelle-Aquitaine, fait 14 Mo pour cinq ans.

DELAI_DEPARTEMENT = 300
TENTATIVES_DEPARTEMENT = 3


def url_departement(departement, annee):
    return f"{RACINE}/{annee}/departements/{departement}.csv.gz"


def lignes_departement(departement, annee):
    """
    Les lignes d'un departement pour un millesime, ou None s'il n'existe pas.

    On rend un ITERATEUR plutot qu'une liste : une
    annee de Gironde, c'est cent mille lignes, et les garder toutes en
    dictionnaires couterait plusieurs centaines de megaoctets a un NAS pour
    rien — l'appelant les agrege au fil de l'eau.
    """
    url = url_departement(departement, annee)
    derniere = None
    for essai in range(TENTATIVES_DEPARTEMENT):
        try:
            requete = urllib.request.Request(url, headers=ENTETES)
            with urllib.request.urlopen(requete, timeout=DELAI_DEPARTEMENT,
                                        context=CONTEXTE) as reponse:
                brut = reponse.read()
            # On garde le fichier COMPRESSE en memoire (quelques Mo) et on le
            # decompresse au fil de la lecture : le texte entier d'une annee
            # de Gironde, c'est trente megaoctets de plus pour rien.
            flux = io.TextIOWrapper(gzip.GzipFile(fileobj=io.BytesIO(brut)), encoding="utf-8")
            return csv.DictReader(flux)
        except urllib.error.HTTPError as erreur:
            if erreur.code in (403, 404):
                logger.info("dvf departement %s : pas de millesime %s", departement, annee)
                return None
            raise ErreurSource(f"DVF : HTTP {erreur.code} sur {departement}/{annee}") from erreur
        except Exception as erreur:                  # noqa: BLE001
            derniere = f"{type(erreur).__name__}"
            logger.info("dvf departement %s/%s : nouvel essai apres %s", departement, annee, derniere)
    raise ErreurSource(f"DVF injoignable pour le departement {departement} ({derniere})")


def signatures_departement(departement, annees=None):
    """Comme `signatures`, pour les fichiers departementaux."""
    annees = millesimes() if annees is None else annees
    resultat = {}
    for annee in annees:
        url = url_departement(departement, annee)
        try:
            requete = urllib.request.Request(url, headers=ENTETES, method="HEAD")
            with urllib.request.urlopen(requete, timeout=DELAI, context=CONTEXTE) as reponse:
                resultat[annee] = (reponse.headers.get("ETag")
                                   or reponse.headers.get("Last-Modified"))
        except urllib.error.HTTPError as erreur:
            if erreur.code in (403, 404):
                resultat[annee] = None
                continue
            raise ErreurSource(f"DVF : HTTP {erreur.code} sur {departement}/{annee}") from erreur
        except Exception as erreur:                  # noqa: BLE001
            raise ErreurSource(f"DVF injoignable ({type(erreur).__name__})") from erreur
    return resultat
