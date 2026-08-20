# -*- coding: utf-8 -*-
"""
zones.py — Separation bourg / plage.

Mimizan-Plage n'est pas une commune distincte : meme code postal, meme code
INSEE que le bourg. Aucun champ administratif ne permet donc de les
separer. On rattache chaque logement au point de reference le plus proche,
et les points sont modifiables dans l'ecran Reglages (CDC F1).
"""

from app.metier.coordonnees import distance_m


def rattacher(latitude, longitude, zones):
    """
    Renvoie (nom_de_zone, distance_en_metres), ou (None, None) si le
    logement n'a pas de position exploitable.
    """
    if latitude is None or longitude is None or not zones:
        return None, None

    meilleure, distance_min = None, None
    for nom, point in zones.items():
        try:
            lat_ref, lon_ref = float(point[0]), float(point[1])
        except (TypeError, ValueError, IndexError):
            continue
        d = distance_m(latitude, longitude, lat_ref, lon_ref)
        if distance_min is None or d < distance_min:
            meilleure, distance_min = nom, d

    if meilleure is None:
        return None, None
    return meilleure, round(distance_min)
