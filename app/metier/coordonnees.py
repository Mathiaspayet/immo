# -*- coding: utf-8 -*-
"""
coordonnees.py — Positionnement des logements.

La base de l'ADEME fournit selon les lignes :
  - un point deja en latitude/longitude (`_geopoint`, ajoute par data-fair),
  - ou des coordonnees Lambert-93 en metres, la projection officielle
    francaise, qu'il faut convertir.

La conversion ci-dessous est reprise telle quelle de
`scripts_existants/dpe_recents.py`, ou elle avait ete verifiee au
centimetre contre pyproj. On ne depend donc pas de pyproj, qui tirerait
PROJ et une quinzaine de megaoctets dans l'image.
"""

import math

from app.metier.valeurs import nombre

# Constantes officielles de la projection Lambert-93 (IGN).
E_GRS80 = 0.0818191910428158        # excentricite de l'ellipsoide GRS80
N_L93 = 0.725607765053267           # exposant de la projection conique
C_L93 = 11754255.426096             # constante de projection
XS_L93, YS_L93 = 700000.0, 12655612.049876   # coordonnees du pole
LON0_L93 = math.radians(3.0)        # meridien d'origine : 3 degres est

# Bornes de la France metropolitaine, Corse comprise.
#
# L'ADEME sert des `_geopoint` aberrants : 39 lignes du 40200 portaient
# ainsi la latitude -5,98 — en plein golfe de Guinee. Sans ce garde-fou,
# elles se voyaient attribuer un secteur (le point de reference le plus
# proche l'emporte, meme a 5 500 km) et piquaient un marqueur sur la carte.
# Mieux vaut declarer la position inconnue que la placer n'importe ou.
LAT_MIN, LAT_MAX = 41.0, 51.6
LON_MIN, LON_MAX = -5.6, 9.8


def en_france(latitude, longitude):
    """Vrai si le point tombe dans les bornes de la France metropolitaine."""
    return (latitude is not None and longitude is not None
            and LAT_MIN <= latitude <= LAT_MAX
            and LON_MIN <= longitude <= LON_MAX)


def lambert93_vers_wgs84(x, y):
    """Convertit des coordonnees Lambert-93 (metres) en (latitude, longitude)."""
    dx, dy = x - XS_L93, y - YS_L93
    rayon = math.hypot(dx, dy)
    if rayon == 0:
        return None
    gamma = math.atan2(dx, -dy)
    longitude = LON0_L93 + gamma / N_L93
    latiso = -math.log(abs(rayon / C_L93)) / N_L93

    # La latitude ne se calcule pas directement : on l'approche par
    # iterations successives, qui convergent en une poignee de tours.
    phi = 2 * math.atan(math.exp(latiso)) - math.pi / 2
    for _ in range(30):
        sinus = E_GRS80 * math.sin(phi)
        phi = 2 * math.atan(((1 + sinus) / (1 - sinus)) ** (E_GRS80 / 2)
                            * math.exp(latiso)) - math.pi / 2
    return math.degrees(phi), math.degrees(longitude)


def wgs84_vers_lambert93(latitude, longitude):
    """Conversion inverse. Sert surtout a verifier la precision de l'aller."""
    phi = math.radians(latitude)
    sinus = E_GRS80 * math.sin(phi)
    latiso = math.log(math.tan(math.pi / 4 + phi / 2)
                      * ((1 - sinus) / (1 + sinus)) ** (E_GRS80 / 2))
    rayon = C_L93 * math.exp(-N_L93 * latiso)
    gamma = N_L93 * (math.radians(longitude) - LON0_L93)
    return XS_L93 + rayon * math.sin(gamma), YS_L93 - rayon * math.cos(gamma)


def depuis_geopoint(valeur):
    """Lit un `_geopoint` data-fair, de la forme "44.2011,-1.2286"."""
    if not valeur or "," not in str(valeur):
        return None
    morceaux = str(valeur).split(",")
    latitude, longitude = nombre(morceaux[0]), nombre(morceaux[1])
    if latitude is None or longitude is None:
        return None
    if not en_france(latitude, longitude):
        return None
    return latitude, longitude


def extraire(geopoint=None, x=None, y=None, latitude=None, longitude=None):
    """
    (latitude, longitude) d'un logement, quel que soit le format d'origine,
    ou None si la ligne ne porte aucune position exploitable.

    Trois formats se presentent selon la base :
      - `_geopoint`, deja projete par data-fair ;
      - deux colonnes latitude / longitude, sur la base d'avant 2021 ;
      - du Lambert-93 en metres, a convertir.
    """
    point = depuis_geopoint(geopoint)
    if point is not None:
        return point

    latitude, longitude = nombre(latitude), nombre(longitude)
    if en_france(latitude, longitude) and (latitude or longitude):
        return latitude, longitude

    x, y = nombre(x), nombre(y)
    # Le seuil ecarte les zeros et les valeurs aberrantes : une abscisse
    # Lambert-93 en France metropolitaine depasse toujours 100 000 metres.
    if x and y and x > 1000:
        point = lambert93_vers_wgs84(x, y)
        if point and en_france(*point):
            return point
    return None


def distance_m(lat1, lon1, lat2, lon2):
    """
    Distance approchee en metres entre deux points proches.

    Approximation plane suffisante a l'echelle d'une commune : l'erreur
    reste sous le metre sur quelques kilometres, et on ne compare ici que
    des distances entre elles.
    """
    d_lat = (lat2 - lat1) * 110540.0
    d_lon = (lon2 - lon1) * 110540.0 * math.cos(math.radians(lat1))
    return math.hypot(d_lat, d_lon)
