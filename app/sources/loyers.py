# -*- coding: utf-8 -*-
"""
loyers.py — La « carte des loyers » : un loyer d'annonce par commune.

Publiee chaque annee par l'ANIL et le ministere du Logement, sur
data.gouv.fr. Un loyer predit au m2, charges comprises, pour chaque
commune de France (hors Mayotte), avec son intervalle de prediction.

Elle ne sert PAS a estimer une valeur : l'etude l'a montre, un seul loyer
par commune ne dit rien de plus que la surface — 26 a 31 % d'erreur, et
un biais de -20 % a Mimizan, ou la location saisonniere fait le marche.
Elle sert a dire ce qu'un prix implique : « a ce prix, rendement brut
d'environ 4 % ».

L'adresse des fichiers porte une date ; on la demande donc a l'API de
data.gouv.fr, comme pour l'archive DVF, en remontant d'un millesime si
celui de l'annee n'est pas encore paru.
"""

import csv
import datetime
import io
import json
import logging
import urllib.error
import urllib.request

from app.sources.client_http import CONTEXTE, ENTETES, ErreurSource

logger = logging.getLogger(__name__)

API = "https://www.data.gouv.fr/api/1/datasets/"
JEU = "carte-des-loyers-indicateurs-de-loyers-dannonce-par-commune-en-{annee}"
DELAI = 180

# Le millesime 2025, verifie le 24/09/2026. Recours si l'API ne repond
# pas : les fichiers eux-memes sont servis par un autre hote.
RECOURS = {
    "millesime": "2025",
    "maison": ("https://static.data.gouv.fr/resources/carte-des-loyers-indicateurs-de-loyers-"
               "dannonce-par-commune-en-2025/20251211-145039/pred-mai-mef-dhup.csv"),
    "appartement": ("https://static.data.gouv.fr/resources/carte-des-loyers-indicateurs-de-loyers-"
                    "dannonce-par-commune-en-2025/20251211-145010/pred-app-mef-dhup.csv"),
}


def _lire_url(url, delai=DELAI):
    requete = urllib.request.Request(url, headers=ENTETES)
    with urllib.request.urlopen(requete, timeout=delai, context=CONTEXTE) as reponse:
        return reponse.read()


def ressources(aujourdhui=None):
    """
    Les deux fichiers — maisons, appartements — du millesime le plus recent.

    Renvoie {"millesime": "2025", "maison": url, "appartement": url}. Les
    titres sont lus, pas devines : le jeu contient aussi des declinaisons
    par nombre de pieces qu'il ne faut pas confondre avec l'ensemble.
    """
    annee = (aujourdhui or datetime.date.today()).year
    for millesime in range(annee, annee - 3, -1):
        try:
            jeu = json.loads(_lire_url(API + JEU.format(annee=millesime) + "/", delai=60))
        except urllib.error.HTTPError as erreur:
            if erreur.code == 404:
                continue
            break
        except Exception:                            # noqa: BLE001
            break
        trouve = {"millesime": str(millesime)}
        for ressource in jeu.get("resources", []):
            titre = (ressource.get("title") or "").lower()
            if "piece" in titre or "pièce" in titre:
                continue
            if "maison" in titre:
                trouve["maison"] = ressource.get("url")
            elif "appartement" in titre:
                trouve["appartement"] = ressource.get("url")
        if trouve.get("maison") and trouve.get("appartement"):
            return trouve
    logger.info("carte des loyers : API indisponible, recours au millesime %s", RECOURS["millesime"])
    return dict(RECOURS)


def lire_csv(contenu, type_bien, millesime):
    """
    [(code_insee, type, loyer, bas, haut, millesime), ...]. Separe pour
    etre teste sans reseau. Le fichier est en Latin-1, separe par des
    points-virgules, avec des virgules decimales.
    """
    texte = contenu.decode("latin-1") if isinstance(contenu, bytes) else contenu
    lignes = []
    for ligne in csv.DictReader(io.StringIO(texte), delimiter=";"):
        def nombre(cle):
            try:
                return float(str(ligne.get(cle, "")).replace(",", "."))
            except ValueError:
                return None
        code, loyer = (ligne.get("INSEE_C") or "").strip(), nombre("loypredm2")
        if code and loyer:
            lignes.append((code, type_bien, loyer, nombre("lwr.IPm2"), nombre("upr.IPm2"), millesime))
    return lignes


def telecharger():
    """Les loyers de toutes les communes, maisons et appartements."""
    urls = ressources()
    lignes = []
    for type_bien in ("maison", "appartement"):
        try:
            contenu = _lire_url(urls[type_bien])
        except Exception as erreur:                  # noqa: BLE001
            raise ErreurSource(f"carte des loyers injoignable ({type(erreur).__name__})") from erreur
        lignes.extend(lire_csv(contenu, type_bien, urls["millesime"]))
    if not lignes:
        raise ErreurSource("carte des loyers : aucun loyer lu")
    return lignes
