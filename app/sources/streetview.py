# -*- coding: utf-8 -*-
"""
streetview.py — La vue de rue d'un bien (Google Street View Static).

Ecart assume au CDC 9 (« aucune donnee transmise a un service tiers hors
des API publiques listees en section 4 ») : consulter une fiche envoie les
coordonnees du bien a Google. Ce choix a ete fait en connaissance de
cause, faute d'alternative couvrante — mesure sur Panoramax, l'equivalent
ouvert de l'IGN : 89 prises de vue dans les 200 m a Launaguet, ZERO dans
le bourg de Mimizan.

Deux precautions en attenuent la portee :

  - l'image passe par le NAS. Le navigateur n'appelle jamais Google, ce
    qui preserve la regle du CDC 3 — aucune requete de la page vers un
    tiers — et garde la cle hors du navigateur ;
  - le catalogue est interroge AVANT l'image. Cette consultation est
    gratuite, dit si une vue existe, et donne la position reelle de la
    prise de vue : on en deduit vers ou tourner l'objectif pour viser la
    maison, plutot que de recevoir un cliche oriente au hasard.

Sans cle, tout ceci se tait et la fiche garde son simple lien.
"""

import hashlib
import json
import logging
import math
import pathlib
import urllib.error
import urllib.parse
import urllib.request

from app import config
from app.base import reglages
from app.sources.client_http import CONTEXTE, ENTETES, ErreurSource

logger = logging.getLogger(__name__)

CATALOGUE = "https://maps.googleapis.com/maps/api/streetview/metadata"
IMAGE = "https://maps.googleapis.com/maps/api/streetview"
DELAI = 15

LARGEUR, HAUTEUR = 640, 400
# Un champ un peu resserre : a 90 degres la maison visee n'occupe qu'un
# tiers du cliche, noyee entre ses voisines.
CHAMP = 70


def cle():
    """La cle d'API, ou une chaine vide si la vue de rue est desactivee."""
    return str(reglages.lire("streetview_cle") or "").strip()


def active():
    return bool(cle())


def _cap(depuis, vers):
    """
    Le cap a suivre pour aller d'un point a l'autre, en degres.

    Sert a tourner l'objectif vers la maison : la camera est sur la voie,
    le bien est de cote, et sans cap on recoit ce que le vehicule avait
    devant lui — souvent la route.
    """
    lat1, lon1 = (math.radians(v) for v in depuis)
    lat2, lon2 = (math.radians(v) for v in vers)
    delta = lon2 - lon1
    y = math.sin(delta) * math.cos(lat2)
    x = (math.cos(lat1) * math.sin(lat2)
         - math.sin(lat1) * math.cos(lat2) * math.cos(delta))
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def _demander(url, parametres):
    requete = urllib.request.Request(
        f"{url}?{urllib.parse.urlencode(parametres)}", headers=ENTETES)
    with urllib.request.urlopen(requete, timeout=DELAI, context=CONTEXTE) as reponse:
        return reponse.read(), reponse.headers.get("Content-Type", "")


def catalogue(latitude, longitude, rayon=60):
    """
    Y a-t-il une vue pres de ce point, et ou se trouve la camera ?

    Cette consultation ne coute rien : elle evite de payer une image qui
    n'existe pas, et de l'afficher sous forme de rectangle gris.
    """
    if not active():
        return None
    try:
        brut, _ = _demander(CATALOGUE, {
            "location": f"{latitude},{longitude}",
            "radius": int(rayon), "key": cle(),
        })
        donnees = json.loads(brut.decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as erreur:
        raise ErreurSource(f"vue de rue injoignable ({type(erreur).__name__})") from erreur

    statut = donnees.get("status")
    if statut != "OK":
        # ZERO_RESULTS est le cas courant : rien n'a ete photographie la.
        if statut not in ("ZERO_RESULTS", "NOT_FOUND"):
            logger.warning("vue de rue : statut %s", statut)
        return {"disponible": False, "statut": statut}

    position = donnees.get("location") or {}
    return {
        "disponible": True,
        "statut": statut,
        "pano": donnees.get("pano_id"),
        "date": donnees.get("date"),
        "latitude": position.get("lat"),
        "longitude": position.get("lng"),
        "copyright": donnees.get("copyright"),
    }


def _dossier():
    chemin = config.CHEMIN_BASE.parent / "vues-rue"
    chemin.mkdir(parents=True, exist_ok=True)
    return chemin


def _empreinte(pano, cap):
    return hashlib.sha1(f"{pano}|{round(cap)}|{LARGEUR}x{HAUTEUR}|{CHAMP}"
                        .encode("utf-8")).hexdigest()


def image(latitude, longitude):
    """
    Le cliche de rue le plus proche, tourne vers le bien.

    Renvoie (octets, type) ou None si rien n'a ete photographie la.

    Le resultat est garde sur disque : une meme fiche se consulte plusieurs
    fois, et chaque image est facturee. La cle du cache est la prise de vue
    et le cap, pas les coordonnees du bien — deux maisons voisines partagent
    souvent la meme photo.
    """
    fiche = catalogue(latitude, longitude)
    if not fiche or not fiche["disponible"]:
        return None

    cap = _cap((fiche["latitude"], fiche["longitude"]), (latitude, longitude))
    chemin = _dossier() / f"{_empreinte(fiche['pano'], cap)}.jpg"
    if chemin.exists():
        return chemin.read_bytes(), "image/jpeg"

    try:
        octets, type_contenu = _demander(IMAGE, {
            "size": f"{LARGEUR}x{HAUTEUR}",
            # `pano` plutot que des coordonnees : on demande EXACTEMENT la
            # prise de vue que le catalogue vient de designer.
            "pano": fiche["pano"],
            "heading": round(cap), "fov": CHAMP, "pitch": 5,
            "return_error_code": "true", "key": cle(),
        })
    except (urllib.error.URLError, OSError) as erreur:
        raise ErreurSource(f"vue de rue indisponible ({type(erreur).__name__})") from erreur

    if "image" not in type_contenu:
        raise ErreurSource("vue de rue : reponse inattendue de la source")

    chemin.write_bytes(octets)
    logger.info("vue de rue %s mise en cache (%.0f ko)", fiche["pano"], len(octets) / 1024)
    return octets, type_contenu
