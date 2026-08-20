# -*- coding: utf-8 -*-
"""
Verification des routes HTTP, sans reseau exterieur.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import application
from app.metier import import_dpe
from tests.conftest import inserer_dpe


@pytest.fixture()
def client(base):
    with TestClient(application) as client:
        yield client


def test_sonde_de_sante(client):
    reponse = client.get("/api/sante")
    assert reponse.status_code == 200
    assert reponse.json()["statut"] == "ok"


def test_veille_renvoie_filtres_resume_et_resultats(client):
    inserer_dpe(date_etablissement="2026-08-01")
    corps = client.get("/api/veille?fenetre_jours=3650").json()
    assert set(corps) == {"filtres", "resume", "resultats"}
    assert corps["resume"]["total"] == 1


def test_export_csv_est_telechargeable(client):
    inserer_dpe(date_etablissement="2026-08-01")
    reponse = client.get("/api/veille/export.csv?fenetre_jours=3650")
    assert reponse.status_code == 200
    assert "attachment" in reponse.headers["content-disposition"]
    assert reponse.headers["content-type"].startswith("text/csv")


def test_marquage_des_vus(client):
    inserer_dpe(date_etablissement="2026-08-01")
    assert client.post("/api/veille/vus", json={}).json()["marques"] == 1
    assert client.post("/api/veille/vus", json={}).json()["marques"] == 0


def test_reglage_invalide_repond_400_avec_un_message_lisible(client):
    reponse = client.put("/api/reglages", json={"surface_min": 900, "surface_max": 10})
    assert reponse.status_code == 400
    assert "surface" in reponse.json()["detail"].lower()


def test_deux_imports_simultanes_sont_refuses(client, monkeypatch):
    """
    Deux imports en parallele se disputeraient le verrou d'ecriture de
    SQLite : le second doit etre refuse proprement, pas planter.
    """
    monkeypatch.setitem(import_dpe._etat, "en_cours", True)
    try:
        reponse = client.post("/api/import")
        assert reponse.status_code == 409
        assert "deja en cours" in reponse.json()["detail"]
    finally:
        monkeypatch.setitem(import_dpe._etat, "en_cours", False)


def test_interface_servie_a_la_racine(client):
    reponse = client.get("/")
    assert reponse.status_code == 200
    assert "Veille immobilière" in reponse.text


def test_les_routes_api_priment_sur_les_fichiers(client):
    """Le montage des fichiers statiques sur « / » ne doit pas capter /api."""
    assert client.get("/api/import/statut").status_code == 200
