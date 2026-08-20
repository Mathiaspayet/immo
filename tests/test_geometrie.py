# -*- coding: utf-8 -*-
"""
Verification des calculs cadastraux, repris de parcelles.py.
"""

import math

import pytest

from app.metier.geometrie import (IndexSpatial, anneaux_exterieurs, boite_englobante,
                                  centre, dans_geometrie, point_dans_anneau, surface_m2)

# Un carre de 100 m de cote, quelque part a Mimizan.
LAT, LON = 44.2011, -1.2286
COTE_LAT = 100.0 / 110540.0
COTE_LON = 100.0 / (110540.0 * math.cos(math.radians(LAT)))
CARRE = [[LON, LAT], [LON + COTE_LON, LAT], [LON + COTE_LON, LAT + COTE_LAT],
         [LON, LAT + COTE_LAT], [LON, LAT]]


def test_surface_d_un_carre_de_cent_metres():
    """La formule des lacets doit rendre 10 000 m2 a moins de 1 % pres."""
    assert surface_m2(CARRE) == pytest.approx(10_000, rel=0.01)


def test_surface_d_un_contour_degenere():
    assert surface_m2([[0, 0], [1, 1]]) == 0.0


def test_le_sens_de_parcours_ne_change_rien():
    assert surface_m2(CARRE) == pytest.approx(surface_m2(list(reversed(CARRE))))


def test_point_dedans_et_dehors():
    dedans = (LON + COTE_LON / 2, LAT + COTE_LAT / 2)
    assert point_dans_anneau(*dedans, CARRE) is True
    assert point_dans_anneau(LON - COTE_LON, LAT, CARRE) is False
    assert point_dans_anneau(LON + COTE_LON * 3, LAT, CARRE) is False


def test_centre_du_carre():
    longitude, latitude = centre(CARRE[:-1])       # sans le point de fermeture
    assert longitude == pytest.approx(LON + COTE_LON / 2)
    assert latitude == pytest.approx(LAT + COTE_LAT / 2)


def test_anneaux_selon_le_type_de_geometrie():
    assert anneaux_exterieurs({"type": "Polygon", "coordinates": [CARRE]}) == [CARRE]
    multi = {"type": "MultiPolygon", "coordinates": [[CARRE], [CARRE]]}
    assert len(anneaux_exterieurs(multi)) == 2
    assert anneaux_exterieurs(None) == []
    assert anneaux_exterieurs({"type": "Point", "coordinates": [0, 0]}) == []


def test_boite_englobante():
    lon_min, lat_min, lon_max, lat_max = boite_englobante([CARRE])
    assert (lon_min, lat_min) == pytest.approx((LON, LAT))
    assert lon_max == pytest.approx(LON + COTE_LON)
    assert boite_englobante([]) is None


# ---------------------------------------------------------------------
#  Index spatial
# ---------------------------------------------------------------------

def decaler(anneau, dx, dy):
    return [[p[0] + dx, p[1] + dy] for p in anneau]


def test_l_index_retrouve_la_bonne_parcelle():
    index = IndexSpatial()
    for numero in range(20):
        index.ajouter(f"P{numero}", [decaler(CARRE, numero * COTE_LON * 2, 0)])
    assert len(index) == 20

    # Un point au milieu de la parcelle 7 doit rendre P7, pas une autre.
    vise = decaler(CARRE, 7 * COTE_LON * 2, 0)
    milieu = (vise[0][0] + COTE_LON / 2, vise[0][1] + COTE_LAT / 2)
    assert index.trouver(*milieu) == "P7"


def test_l_index_ne_trouve_rien_hors_des_parcelles():
    index = IndexSpatial()
    index.ajouter("P1", [CARRE])
    assert index.trouver(LON - 1, LAT - 1) is None
    assert index.trouver(LON - COTE_LON, LAT) is None


def test_une_geometrie_vide_n_entre_pas_dans_l_index():
    index = IndexSpatial()
    index.ajouter("vide", [])
    assert len(index) == 0
    assert index.trouver(LON, LAT) is None


def test_l_index_couvre_une_parcelle_plus_grande_qu_une_case():
    """
    Une parcelle de plusieurs hectares deborde de sa case : elle doit etre
    inscrite dans toutes celles qu'elle touche, sinon un batiment situe a
    son extremite ne lui serait jamais rattache.
    """
    grande = [[LON, LAT], [LON + 0.01, LAT], [LON + 0.01, LAT + 0.01],
              [LON, LAT + 0.01], [LON, LAT]]
    index = IndexSpatial()
    index.ajouter("GRANDE", [grande])
    assert index.trouver(LON + 0.009, LAT + 0.009) == "GRANDE"


def test_dans_geometrie_teste_tous_les_contours():
    loin = decaler(CARRE, 0.05, 0.05)
    milieu_loin = (loin[0][0] + COTE_LON / 2, loin[0][1] + COTE_LAT / 2)
    assert dans_geometrie(*milieu_loin, [CARRE]) is False
    assert dans_geometrie(*milieu_loin, [CARRE, loin]) is True
