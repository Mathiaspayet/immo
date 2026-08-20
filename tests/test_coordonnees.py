# -*- coding: utf-8 -*-
"""
Verification de la conversion Lambert-93, reprise de dpe_recents.py.

C'est le calcul le plus delicat de l'application : une erreur y placerait
silencieusement les logements du mauvais cote de la commune, et le
rattachement bourg / plage deviendrait faux sans que rien ne le signale.
"""

import pytest

from app.metier.coordonnees import (distance_m, extraire, lambert93_vers_wgs84,
                                    wgs84_vers_lambert93)
from app.metier.zones import rattacher

MIMIZAN_BOURG = (44.2011, -1.2286)
MIMIZAN_PLAGE = (44.2044, -1.2914)


def test_point_de_definition_de_la_projection():
    """(700000, 6600000) vaut exactement 3 degres est, 46,5 degres nord."""
    latitude, longitude = lambert93_vers_wgs84(700000.0, 6600000.0)
    assert latitude == pytest.approx(46.5, abs=1e-9)
    assert longitude == pytest.approx(3.0, abs=1e-9)


@pytest.mark.parametrize("point", [MIMIZAN_BOURG, MIMIZAN_PLAGE, (48.8566, 2.3522),
                                   (43.2965, 5.3698), (50.6292, 3.0573)])
def test_aller_retour_au_centimetre(point):
    """Convertir puis reconvertir doit ramener au meme endroit."""
    x, y = wgs84_vers_lambert93(*point)
    retour = lambert93_vers_wgs84(x, y)
    assert distance_m(*point, *retour) < 0.01


def test_geopoint_prioritaire_sur_lambert():
    """Quand data-fair fournit deja un point, on ne convertit rien."""
    assert extraire(geopoint="44.2011,-1.2286", x=999999, y=999999) == MIMIZAN_BOURG


def test_repli_sur_lambert93():
    x, y = wgs84_vers_lambert93(*MIMIZAN_BOURG)
    latitude, longitude = extraire(geopoint=None, x=x, y=y)
    assert distance_m(latitude, longitude, *MIMIZAN_BOURG) < 0.01


@pytest.mark.parametrize("geopoint, x, y", [
    ("", 0, 0),                   # ligne sans coordonnees
    (None, None, None),
    ("", 12, 6300000),            # abscisse aberrante, sous le seuil
    ("pas,des,nombres", None, None),
    ("200.0,50.0", None, None),   # latitude hors bornes terrestres
])
def test_coordonnees_inexploitables(geopoint, x, y):
    assert extraire(geopoint=geopoint, x=x, y=y) is None


def test_rattachement_bourg_plage():
    """
    Mimizan-Plage n'a pas de code administratif propre : la separation ne
    peut se faire que par la distance au point de reference.
    """
    zones = {"bourg": MIMIZAN_BOURG, "plage": MIMIZAN_PLAGE}
    nom, distance = rattacher(44.2050, -1.2900, zones)
    assert nom == "plage"
    assert distance < 200

    nom, _ = rattacher(44.2015, -1.2280, zones)
    assert nom == "bourg"


def test_rattachement_sans_position():
    assert rattacher(None, None, {"bourg": MIMIZAN_BOURG}) == (None, None)
