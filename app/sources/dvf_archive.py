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

import collections
import csv
import io
import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from app.sources.client_http import CONTEXTE, ENTETES, ErreurSource


class ArchiveIntrouvable(ErreurSource):
    """Le departement est valide, mais la compilation ne le couvre pas.

    Distinct d'une panne : reessayer n'y changera rien, et l'annoncer
    comme une indisponibilite ferait chercher le probleme du mauvais
    cote. Une saisie fautive, elle, leve ValueError.
    """

logger = logging.getLogger(__name__)

# Ce que la reprise a lu, et non seulement ce qu'elle a rendu. Sans cela
# l'ecran ne pouvait pas dire SUR QUOI le bouton avait agi : le
# departement n'est jamais choisi, il se deduit du code INSEE de la
# commune, et rien ne le montrait.
Archive = collections.namedtuple("Archive", "lignes departement titre url")

JEU = ("https://www.data.gouv.fr/api/1/datasets/"
       "compilation-des-donnees-de-valeurs-foncieres-dvf-par-departement/")
DELAI = 600


def departement(code_insee):
    code = str(code_insee).strip()
    return code[:3] if code[:2] == "97" else code[:2]


def _departement_valide(dep):
    """Normalise un numero de departement saisi a la main.

    Sans ce controle, « 4 » au lieu de « 04 » ne rendrait rien et le
    message parlerait d'une archive absente, alors que c'est la saisie
    qui est en cause.
    """
    code = str(dep).strip().upper()
    if code in ("2A", "2B") or (code.isdigit() and len(code) == 3
                                and code.startswith("97")):
        return code
    if code.isdigit() and len(code) in (1, 2):
        return code.zfill(2)
    raise ValueError(
        f"Numero de departement invalide : {dep!r}. Attendu deux chiffres"
        " (40), « 2A »/« 2B », ou trois chiffres outre-mer (974).")


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
    raise ArchiveIntrouvable(
        f"Aucune archive DVF pour le departement {dep} dans la compilation."
        " Elle ne couvre pas tous les departements.")


def telecharger(code_insee=None, dep=None, progression=None):
    """
    Les lignes archivees, au format de geo-dvf.

    Deux facons de designer ce qu'on veut, et une seule a la fois :

      - `code_insee` : une commune. Le departement s'en deduit — deux
        chiffres, trois outre-mer — et n'est jamais choisi ;
      - `dep` : le departement entier, toutes communes confondues.

    Le fichier est departemental dans les deux cas — 34 Mo pour les
    Landes, 184 878 lignes, 327 communes. Il se lit au fil de l'eau : on
    ne retient que ce qui est demande, sans jamais poser l'ensemble en
    memoire. Prendre tout le departement ne coute donc pas un
    telechargement de plus, seulement les lignes gardees.

    Renvoie l'intitule exact de la ressource lue : c'est le seul moyen de
    verifier, apres coup, que la reprise a porte la ou on le croyait.
    """
    if bool(code_insee) == bool(dep):
        raise ValueError(
            "Preciser une commune OU un departement, pas les deux ni aucun.")

    code_insee = str(code_insee).strip() if code_insee else None
    dep = departement(code_insee) if code_insee else _departement_valide(dep)
    url, titre = _ressource(dep)
    if progression:
        cible = code_insee or f"departement {dep}"
        progression(f"archive DVF « {titre} » — {cible}…")

    try:
        requete = urllib.request.Request(url, headers=ENTETES)
        with urllib.request.urlopen(requete, timeout=DELAI, context=CONTEXTE) as reponse:
            flux = io.TextIOWrapper(reponse, encoding="utf-8", errors="replace")
            lignes = [l for l in csv.DictReader(flux)
                      if code_insee is None
                      or (l.get("code_commune") or "").strip() == code_insee]
    except urllib.error.HTTPError as erreur:
        raise ErreurSource(f"Archive DVF : HTTP {erreur.code}") from erreur
    except Exception as erreur:                      # noqa: BLE001
        raise ErreurSource(
            f"Archive DVF injoignable ({type(erreur).__name__})") from erreur

    annees = sorted({(l.get("date_mutation") or "")[:4] for l in lignes} - {""})
    logger.info("archive dvf %s : ressource « %s », %d lignes, millesimes %s",
                code_insee or f"dep {dep}", titre, len(lignes),
                ", ".join(annees) or "aucun")
    return Archive(lignes=lignes, departement=dep, titre=titre, url=url)
