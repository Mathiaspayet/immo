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


# =====================================================================
#  Lot 2 — identification et fiche
# =====================================================================

def test_identification_renvoie_entonnoir_et_classement(client):
    inserer_dpe(n_dpe="A", adresse="19 Avenue des Oiseaux",
                surface_habitable=149.0, conso_ep_m2=215.2, etiquette_dpe="D")
    reponse = client.post("/api/identification", json={
        "criteres": {"surface": 144, "conso_ep": 216},
        "tolerances": {"surface": 3, "conso": 5, "ges": 1.5},
    })
    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["examines"] == 1
    assert [etape["critere"] for etape in corps["entonnoir"]] == ["surface", "conso_ep"]
    assert corps["resultats"][0]["n_dpe"] == "A"


def test_fiche_sans_parametre_repond_400(client):
    reponse = client.get("/api/fiche")
    assert reponse.status_code == 400
    assert "numéro de DPE" in reponse.json()["detail"]


def test_fiche_par_adresse(client):
    inserer_dpe(n_dpe="A", adresse="12 Rue des Pins", date_etablissement="2026-01-09")
    corps = client.get("/api/fiche", params={"adresse": "12 RUE DES PINS"}).json()
    assert len(corps["diagnostics"]) == 1


def test_fiche_adresse_inconnue_propose_des_voisines(client):
    inserer_dpe(n_dpe="A", adresse="12 Rue des Pins")
    corps = client.get("/api/fiche", params={"adresse": "40 Rue des Pins"}).json()
    assert corps["diagnostics"] == []
    assert "12 Rue des Pins" in corps["suggestions"]


def test_chaine_sans_appel_reseau(client):
    inserer_dpe(n_dpe="RECENT", adresse="1 Rue Test", n_dpe_remplace="ANCIEN")
    inserer_dpe(n_dpe="ANCIEN", adresse="1 Rue Test")
    corps = client.get("/api/fiche/chaine",
                       params={"n_dpe": "RECENT", "interroger_ademe": False}).json()
    assert [m["n_dpe"] for m in corps["maillons"]] == ["RECENT", "ANCIEN"]


# =====================================================================
#  Rafraichissement paresseux
# =====================================================================

def test_rafraichissement_ne_part_pas_si_la_moisson_est_recente(client):
    import datetime

    from app.base.connexion import transaction
    recent = datetime.datetime.now().isoformat(timespec="seconds")
    with transaction() as conn:
        conn.execute("INSERT INTO journal_import (source, debut, fin, statut) "
                     "VALUES ('essai', ?, ?, 'succes')", (recent, recent))

    corps = client.post("/api/import/si-perime").json()
    assert corps["lance"] is False
    assert corps["raison"] == "a_jour"
    assert corps["age_heures"] < 1


def test_rafraichissement_desactivable(client):
    """Un seuil a zero coupe completement le rafraichissement automatique."""
    client.put("/api/reglages", json={"rafraichir_apres_heures": 0})
    corps = client.post("/api/import/si-perime").json()
    assert corps["lance"] is False
    assert corps["raison"] == "desactive"


def test_age_du_dernier_import(client):
    assert client.get("/api/import/age").json()["age_heures"] is None


def test_liste_des_communes(client):
    inserer_dpe(n_dpe="A", adresse="1 rue", commune="Mimizan", code_insee="40184")
    inserer_dpe(n_dpe="B", adresse="2 rue", commune="Aureilhan", code_insee="40019")
    corps = client.get("/api/communes").json()
    assert corps["total"] == 2
    assert {c["code_insee"] for c in corps["communes"]} == {"40184", "40019"}


def test_la_veille_ne_se_limite_plus_a_une_commune_par_defaut(client):
    """
    Le serveur ne devine plus la commune : sans filtre explicite, toutes les
    communes du cache remontent.
    """
    inserer_dpe(n_dpe="A", adresse="1 rue", commune="Mimizan", code_insee="40184",
                date_etablissement="2026-08-01")
    inserer_dpe(n_dpe="B", adresse="2 rue", commune="Aureilhan", code_insee="40019",
                date_etablissement="2026-08-01")
    corps = client.get("/api/veille", params={"fenetre_jours": 3650}).json()
    assert corps["resume"]["total"] == 2


def test_filtre_par_code_insee_sur_l_api(client):
    inserer_dpe(n_dpe="A", adresse="1 rue", commune="Mimizan", code_insee="40184",
                date_etablissement="2026-08-01")
    inserer_dpe(n_dpe="B", adresse="2 rue", commune="Aureilhan", code_insee="40019",
                date_etablissement="2026-08-01")
    corps = client.get("/api/veille",
                       params={"fenetre_jours": 3650, "code_insee": "40019"}).json()
    assert [l["n_dpe"] for l in corps["resultats"]] == ["B"]
