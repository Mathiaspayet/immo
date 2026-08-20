# -*- coding: utf-8 -*-
"""
geometrie.py — Calculs sur les contours cadastraux.

Repris de scripts_existants/parcelles.py. Rien ici ne depend d'une
bibliotheque geospatiale : le GeoJSON du cadastre donne des degres, et une
projection locale suffit largement a l'echelle d'une commune.

Le morceau qui compte est l'index en grille (plus bas) : comparer chaque
batiment a chaque parcelle serait 11 444 x 14 395 = 165 millions de tests
pour la seule commune de Mimizan.
"""

import math

# A cette latitude, un degre de latitude vaut toujours ~110,54 km ; un degre
# de longitude vaut la meme chose multipliee par le cosinus de la latitude.
METRES_PAR_DEGRE_LAT = 110540.0


def anneaux_exterieurs(geometrie):
    """
    Contours exterieurs d'une geometrie GeoJSON.

    Un Polygon en a un, un MultiPolygon en a plusieurs. Les anneaux
    interieurs (les trous) sont ignores : le cadastre n'en fait pas usage
    pour les parcelles ordinaires.
    """
    if not geometrie:
        return []
    if geometrie.get("type") == "Polygon":
        coordonnees = geometrie.get("coordinates") or []
        return [coordonnees[0]] if coordonnees else []
    if geometrie.get("type") == "MultiPolygon":
        return [polygone[0] for polygone in geometrie.get("coordinates") or [] if polygone]
    return []


def surface_m2(anneau):
    """
    Surface d'un contour ferme, par la formule des lacets.

    Les degres sont projetes en metres avant le calcul, avec le cosinus pris
    a la latitude moyenne du contour — a l'echelle d'une parcelle, l'erreur
    est negligeable.
    """
    if len(anneau) < 3:
        return 0.0
    latitude_moyenne = sum(point[1] for point in anneau) / len(anneau)
    metres_par_degre_lon = METRES_PAR_DEGRE_LAT * math.cos(math.radians(latitude_moyenne))

    total = 0.0
    for i in range(len(anneau)):
        x1, y1 = anneau[i][0] * metres_par_degre_lon, anneau[i][1] * METRES_PAR_DEGRE_LAT
        x2, y2 = anneau[i - 1][0] * metres_par_degre_lon, anneau[i - 1][1] * METRES_PAR_DEGRE_LAT
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def centre(anneau):
    """Point moyen d'un contour : suffisant pour situer un batiment."""
    longitude = sum(point[0] for point in anneau) / len(anneau)
    latitude = sum(point[1] for point in anneau) / len(anneau)
    return longitude, latitude


def point_dans_anneau(longitude, latitude, anneau):
    """
    Le point est-il a l'interieur du contour ? (lancer de rayon)

    On trace une demi-droite horizontale depuis le point et on compte les
    intersections avec le contour : un nombre impair signifie qu'on est
    dedans.
    """
    dedans = False
    j = len(anneau) - 1
    for i in range(len(anneau)):
        xi, yi = anneau[i][0], anneau[i][1]
        xj, yj = anneau[j][0], anneau[j][1]
        if (yi > latitude) != (yj > latitude):
            x_intersection = (xj - xi) * (latitude - yi) / (yj - yi) + xi
            if longitude < x_intersection:
                dedans = not dedans
        j = i
    return dedans


def dans_geometrie(longitude, latitude, anneaux):
    """Le point tombe-t-il dans l'un des contours ?"""
    return any(point_dans_anneau(longitude, latitude, anneau) for anneau in anneaux)


def boite_englobante(anneaux):
    """Rectangle minimal : (lon_min, lat_min, lon_max, lat_max), ou None."""
    longitudes = [p[0] for anneau in anneaux for p in anneau]
    latitudes = [p[1] for anneau in anneaux for p in anneau]
    if not longitudes:
        return None
    return min(longitudes), min(latitudes), max(longitudes), max(latitudes)


# ---------------------------------------------------------------------
#  Index spatial en grille
# ---------------------------------------------------------------------
# Comparer chaque batiment a chaque parcelle serait en O(n x m) : pour
# Mimizan, 11 444 parcelles x 14 395 batiments = 165 millions de tests
# d'appartenance, chacun parcourant des dizaines de sommets. Inutilisable.
#
# On decoupe donc la commune en cases d'environ 110 m de cote, et on note
# pour chaque case les parcelles qui la touchent. Un batiment ne se compare
# alors qu'aux quelques parcelles de sa propre case.

TAILLE_CASE = 0.001        # en degres, soit ~110 m


def case_de(longitude, latitude):
    """Case de la grille contenant un point."""
    return (math.floor(longitude / TAILLE_CASE), math.floor(latitude / TAILLE_CASE))


def cases_couvertes(boite):
    """Cases recouvertes par un rectangle englobant."""
    lon_min, lat_min, lon_max, lat_max = boite
    cases = []
    for ix in range(math.floor(lon_min / TAILLE_CASE), math.floor(lon_max / TAILLE_CASE) + 1):
        for iy in range(math.floor(lat_min / TAILLE_CASE), math.floor(lat_max / TAILLE_CASE) + 1):
            cases.append((ix, iy))
    return cases


class IndexSpatial:
    """
    Grille des parcelles d'une commune, pour retrouver vite celle qui
    contient un point.
    """

    def __init__(self):
        self.grille = {}
        self.geometries = {}

    def ajouter(self, identifiant, anneaux):
        boite = boite_englobante(anneaux)
        if boite is None:
            return
        self.geometries[identifiant] = anneaux
        for case in cases_couvertes(boite):
            self.grille.setdefault(case, []).append(identifiant)

    def trouver(self, longitude, latitude):
        """Identifiant de la parcelle contenant le point, ou None."""
        for identifiant in self.grille.get(case_de(longitude, latitude), ()):
            if dans_geometrie(longitude, latitude, self.geometries[identifiant]):
                return identifiant
        return None

    def __len__(self):
        return len(self.geometries)
