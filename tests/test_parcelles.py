# -*- coding: utf-8 -*-
"""
F3 — recherche cadastrale et recoupement avec les DPE.

Aucun appel reseau : les parcelles sont injectees directement.
"""

import json
import math

import pytest

from app.base.connexion import transaction
from app.metier import parcelles
from tests.conftest import inserer_dpe

LAT, LON = 43.6600, 1.4400            # Launaguet
COTE = 0.0009                          # ~100 m


def carre(indice):
    """Un carre de ~100 m, decale de `indice` cases vers l'est."""
    x = LON + indice * COTE * 2
    return [[x, LAT], [x + COTE, LAT], [x + COTE, LAT + COTE], [x, LAT + COTE], [x, LAT]]


def inserer_parcelle(identifiant, indice=0, code_insee="31282", contenance=800.0,
                     emprise=120.0, batiments=1):
    anneau = carre(indice)
    longitude = sum(p[0] for p in anneau[:-1]) / 4
    latitude = sum(p[1] for p in anneau[:-1]) / 4
    with transaction() as conn:
        conn.execute(
            "INSERT INTO parcelle (id, code_insee, section, numero, contenance_m2, "
            "  emprise_batie_m2, nb_batiments, latitude, longitude, "
            "  lat_min, lat_max, lon_min, lon_max, geometrie_json, importe_le) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (identifiant, code_insee, "AA", identifiant[-3:], contenance, emprise,
             batiments, latitude, longitude, LAT, LAT + COTE,
             anneau[0][0], anneau[1][0],
             json.dumps({"type": "Polygon", "coordinates": [anneau]}),
             "2026-08-20T10:00:00"))
    return {"id": identifiant, "centre": (longitude, latitude)}


@pytest.fixture()
def cadastre(base):
    """Trois parcelles : une petite, une au gabarit, une trop grande."""
    inserer_parcelle("P-PETITE", indice=0, contenance=250.0, emprise=90.0)
    inserer_parcelle("P-BONNE", indice=1, contenance=800.0, emprise=120.0)
    inserer_parcelle("P-GRANDE", indice=2, contenance=50_000.0, emprise=0.0, batiments=0)


def test_filtre_par_surface_de_terrain(cadastre):
    retenues = parcelles.lister("31282", {"terrain_min": 400, "terrain_max": 2000},
                                avec_geometrie=False)
    assert [p["id"] for p in retenues] == ["P-BONNE"]


def test_filtre_par_emprise_batie(cadastre):
    retenues = parcelles.lister("31282", {"emprise_min": 100}, avec_geometrie=False)
    assert [p["id"] for p in retenues] == ["P-BONNE"]


def test_filtre_batie(cadastre):
    retenues = parcelles.lister("31282", {"batie": True}, avec_geometrie=False)
    assert {p["id"] for p in retenues} == {"P-PETITE", "P-BONNE"}


def test_une_commune_ne_voit_pas_le_cadastre_d_une_autre(cadastre):
    inserer_parcelle("AILLEURS", indice=5, code_insee="40184")
    assert len(parcelles.lister("31282", {}, avec_geometrie=False)) == 3
    assert len(parcelles.lister("40184", {}, avec_geometrie=False)) == 1


# ---------------------------------------------------------------------
#  Recoupement avec les DPE (CDC F3)
# ---------------------------------------------------------------------

def test_recoupement_dpe_parcelle(cadastre):
    """
    « Une adresse presente dans deux modules est un candidat quasi
    certain » : la parcelle porte le compte de ses DPE et la date du plus
    recent.
    """
    inserer_dpe(n_dpe="D1", adresse="1 rue", code_insee="31282",
                date_etablissement="2026-08-01")
    inserer_dpe(n_dpe="D2", adresse="2 rue", code_insee="31282",
                date_etablissement="2026-05-01")
    with transaction() as conn:
        conn.execute("UPDATE dpe SET parcelle_id = 'P-BONNE' WHERE n_dpe IN ('D1','D2')")

    par_id = {p["id"]: p for p in parcelles.lister("31282", {}, avec_geometrie=False)}
    assert par_id["P-BONNE"]["dpe"] == 2
    assert par_id["P-BONNE"]["dpe_recent"] == "2026-08-01"
    assert set(par_id["P-BONNE"]["adresses"]) == {"1 rue", "2 rue"}
    assert par_id["P-PETITE"]["dpe"] == 0


def test_filtre_sur_un_dpe_recent(cadastre):
    """Le croisement qui compte : bon gabarit ET diagnostic frais."""
    import datetime
    recent = (datetime.date.today() - datetime.timedelta(days=10)).isoformat()
    vieux = (datetime.date.today() - datetime.timedelta(days=900)).isoformat()

    inserer_dpe(n_dpe="FRAIS", adresse="1 rue", code_insee="31282",
                date_etablissement=recent)
    inserer_dpe(n_dpe="VIEUX", adresse="2 rue", code_insee="31282",
                date_etablissement=vieux)
    with transaction() as conn:
        conn.execute("UPDATE dpe SET parcelle_id = 'P-BONNE' WHERE n_dpe = 'FRAIS'")
        conn.execute("UPDATE dpe SET parcelle_id = 'P-PETITE' WHERE n_dpe = 'VIEUX'")

    retenues = parcelles.lister("31282", {"dpe_depuis_jours": 120}, avec_geometrie=False)
    assert [p["id"] for p in retenues] == ["P-BONNE"]


def test_rattachement_par_la_geometrie(cadastre):
    """
    Un DPE tombe dans la parcelle qui le contient, pas dans sa voisine —
    c'est l'index spatial qui tranche.
    """
    centre_bonne = (LON + COTE * 2 + COTE / 2, LAT + COTE / 2)
    inserer_dpe(n_dpe="DEDANS", adresse="1 rue", code_insee="31282",
                longitude=centre_bonne[0], latitude=centre_bonne[1])
    inserer_dpe(n_dpe="AILLEURS", adresse="2 rue", code_insee="31282",
                longitude=LON + 0.5, latitude=LAT + 0.5)

    assert parcelles.rattacher_dpe("31282") == 1

    from app.base.connexion import connexion
    with connexion() as conn:
        lignes = dict(conn.execute(
            "SELECT n_dpe, parcelle_id FROM dpe").fetchall())
    assert lignes["DEDANS"] == "P-BONNE"
    assert lignes["AILLEURS"] is None


def test_le_rattachement_ne_refait_pas_le_travail(cadastre):
    centre_bonne = (LON + COTE * 2 + COTE / 2, LAT + COTE / 2)
    inserer_dpe(n_dpe="D1", adresse="1 rue", code_insee="31282",
                longitude=centre_bonne[0], latitude=centre_bonne[1])
    assert parcelles.rattacher_dpe("31282") == 1
    assert parcelles.rattacher_dpe("31282") == 0        # deja rattache
    assert parcelles.rattacher_dpe("31282", tous=True) == 1


def test_parcelle_d_un_dpe_pour_la_fiche(cadastre):
    inserer_dpe(n_dpe="D1", adresse="1 rue", code_insee="31282")
    with transaction() as conn:
        conn.execute("UPDATE dpe SET parcelle_id = 'P-BONNE' WHERE n_dpe = 'D1'")

    parcelle = parcelles.parcelle_de("D1")
    assert parcelle["id"] == "P-BONNE"
    assert parcelle["geometrie"]["type"] == "Polygon"
    assert parcelles.parcelle_de("INCONNU") is None


def test_resume_du_cadastre(cadastre):
    resultat = parcelles.resume("31282")
    assert resultat["parcelles"] == 3
    assert resultat["baties"] == 2
    assert resultat["dpe_rattaches"] == 0


def test_resume_d_une_commune_sans_cadastre(base):
    resultat = parcelles.resume("99999")
    assert resultat["parcelles"] == 0
    assert resultat["age_heures"] is None
