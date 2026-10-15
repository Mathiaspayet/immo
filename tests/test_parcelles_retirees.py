# -*- coding: utf-8 -*-
"""
test_parcelles_retirees.py — Les parcelles que le cadastre ne publie plus.

Une parcelle divisee ou fusionnee change d'identifiant. L'ancienne restait
en base pour toujours : elle chevauchait ses heritieres sur la carte et
captait des diagnostics. Elle est desormais RETIREE — hors de la carte et
du rattachement —, mais gardee avec sa filiation : DVF cite les parcelles
telles qu'elles etaient au jour de la vente.
"""

import pytest

from app.base.connexion import connexion
from app.metier import fiche, mutations, parcelles
from tests.conftest import inserer_dpe

LON, LAT, COTE = -1.2900, 44.2100, 0.0004


def _carre(lon, lat, largeur=COTE, hauteur=COTE):
    return [[lon, lat], [lon + largeur, lat], [lon + largeur, lat + hauteur],
            [lon, lat + hauteur], [lon, lat]]


def _parcelle(ident, anneau):
    return {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [anneau]},
            "properties": {"id": ident, "section": "AB", "numero": ident[-4:],
                           "contenance": 1000, "prefixe": "000"}}


def _cadastre(monkeypatch, objets):
    monkeypatch.setattr("app.sources.cadastre.telecharger_couche",
                        lambda code, couche, progression=None:
                            list(objets) if couche == "parcelles" else [])
    return parcelles.importer_cadastre("40184")


# La parcelle d'origine, sa voisine qui ne bouge pas, et la division en deux lots.
AVANT = [_parcelle("40184000AB0180", _carre(LON, LAT)),
         _parcelle("40184000AB0900", _carre(LON + 0.01, LAT))]
APRES = [_parcelle("40184000AB0450", _carre(LON, LAT, largeur=COTE / 2)),
         _parcelle("40184000AB0451", _carre(LON + COTE / 2, LAT, largeur=COTE / 2)),
         _parcelle("40184000AB0900", _carre(LON + 0.01, LAT))]
DANS_LE_PREMIER_LOT = (LAT + COTE / 2, LON + COTE / 4)


@pytest.fixture()
def divisee(base, monkeypatch):
    """AB0180, vendue en 2022 et diagnostiquee, puis divisee en AB0450 et AB0451."""
    inserer_dpe(n_dpe="D0", adresse="13 Rue des Ecoles", code_insee="40184",
                latitude=DANS_LE_PREMIER_LOT[0], longitude=DANS_LE_PREMIER_LOT[1])
    _cadastre(monkeypatch, AVANT)
    monkeypatch.setattr("app.sources.dvf.telecharger", lambda code, progression=None: [{
        "id_mutation": "V2022", "date_mutation": "2022-06-23", "nature_mutation": "Vente",
        "valeur_fonciere": "300000", "code_commune": "40184", "id_parcelle": "40184000AB0180",
        "type_local": "Maison", "surface_reelle_bati": "100", "surface_terrain": "1000"}])
    mutations.importer("40184")
    with connexion() as conn:
        assert conn.execute("SELECT parcelle_id FROM dpe WHERE n_dpe = 'D0'"
                            ).fetchone()[0] == "40184000AB0180"
    return _cadastre(monkeypatch, APRES)


def test_la_parcelle_divisee_est_retiree_avec_sa_filiation(divisee):
    assert divisee["retirees"] == 1
    with connexion() as conn:
        etats = dict(conn.execute("SELECT id, retiree_le IS NOT NULL FROM parcelle").fetchall())
        filiation = conn.execute("SELECT ancienne, nouvelle FROM parcelle_filiation"
                                 " ORDER BY nouvelle").fetchall()
    assert etats == {"40184000AB0180": 1, "40184000AB0900": 0,
                     "40184000AB0450": 0, "40184000AB0451": 0}
    assert [tuple(l) for l in filiation] == [("40184000AB0180", "40184000AB0450"),
                                             ("40184000AB0180", "40184000AB0451")]


def test_son_diagnostic_rejoint_le_bon_lot(divisee):
    with connexion() as conn:
        assert conn.execute("SELECT parcelle_id FROM dpe WHERE n_dpe = 'D0'"
                            ).fetchone()[0] == "40184000AB0450"
    assert parcelles.a_la_position("40184", *DANS_LE_PREMIER_LOT) == "40184000AB0450"


def test_elle_quitte_la_carte_sans_emporter_ses_ventes(divisee):
    cadre = (LON - 0.001, LAT - 0.001, LON + 0.02, LAT + 0.001)
    carte = {p["id"]: p for p in parcelles.pour_carte("40184", cadre)["parcelles"]}
    assert "40184000AB0180" not in carte
    assert carte["40184000AB0450"]["ventes_origine"] == 1
    assert carte["40184000AB0451"]["ventes"] == 1


def test_la_fiche_d_un_lot_montre_la_vente_d_origine(divisee):
    lieu = fiche.lieu(parcelle_id="40184000AB0451")
    vente, = lieu["ventes"]
    assert vente["id"] == "V2022"
    assert vente["parcelle_d_origine"] == "40184000AB0180"
    assert vente["reference_d_origine"] == "AB0180"


def test_la_fiche_de_l_ancienne_dit_ce_qu_elle_est_devenue(divisee):
    lieu = fiche.lieu(parcelle_id="40184000AB0180")
    assert lieu["parcelle"]["retiree_le"]
    assert [h["reference"] for h in lieu["parcelle"]["heritieres"]] == ["AB0450", "AB0451"]


def test_une_fusion_donne_une_heritiere_commune(base, monkeypatch):
    _cadastre(monkeypatch, [_parcelle("40184000AB0001", _carre(LON, LAT)),
                            _parcelle("40184000AB0002", _carre(LON + COTE, LAT)),
                            _parcelle("40184000AB0900", _carre(LON + 0.01, LAT))])
    _cadastre(monkeypatch, [_parcelle("40184000AB0003", _carre(LON, LAT, largeur=2 * COTE)),
                            _parcelle("40184000AB0900", _carre(LON + 0.01, LAT))])
    with connexion() as conn:
        filiation = sorted(tuple(l) for l in conn.execute(
            "SELECT ancienne, nouvelle FROM parcelle_filiation"))
    assert filiation == [("40184000AB0001", "40184000AB0003"),
                         ("40184000AB0002", "40184000AB0003")]


def test_un_telechargement_tronque_ne_retire_rien(base, monkeypatch):
    """Dix parcelles connues, cinq recues : c'est le fichier qui manque,
    pas le cadastre qui a change."""
    dix = [_parcelle(f"40184000AB{n:04d}", _carre(LON + n * 0.001, LAT)) for n in range(10)]
    _cadastre(monkeypatch, dix)
    resume = _cadastre(monkeypatch, dix[:5])
    assert resume["retirees"] == 0
    with connexion() as conn:
        assert conn.execute("SELECT count(*) FROM parcelle WHERE retiree_le IS NOT NULL"
                            ).fetchone()[0] == 0


def test_une_parcelle_qui_reparait_n_est_plus_retiree(divisee, monkeypatch):
    _cadastre(monkeypatch, AVANT + APRES[:2])
    with connexion() as conn:
        assert conn.execute("SELECT retiree_le FROM parcelle WHERE id = '40184000AB0180'"
                            ).fetchone()[0] is None
        assert conn.execute("SELECT count(*) FROM parcelle_filiation").fetchone()[0] == 0
