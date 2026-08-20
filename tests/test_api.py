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

def _moisson(code_insee, il_y_a_heures, nom="Essai"):
    """Inscrit une commune au registre, moissonnee il y a N heures."""
    import datetime

    from app.base.connexion import transaction
    quand = (datetime.datetime.now()
             - datetime.timedelta(hours=il_y_a_heures)).isoformat(timespec="seconds")
    with transaction() as conn:
        conn.execute(
            "INSERT INTO commune (code_insee, nom, code_postal, derniere_maj_dpe) "
            "VALUES (?, ?, '00000', ?) ON CONFLICT(code_insee) DO UPDATE SET "
            "derniere_maj_dpe = excluded.derniere_maj_dpe",
            (code_insee, nom, quand))


def test_commune_a_jour_ne_declenche_rien(client):
    _moisson("40184", il_y_a_heures=2, nom="Mimizan")
    corps = client.post("/api/communes/40184/preparer").json()
    assert corps["lance"] is False
    assert corps["raison"] == "a_jour"
    assert corps["en_cache"] is True


def test_commune_perimee_est_rafraichie(client, monkeypatch):
    """Au-dela du seuil, la moisson repart — sans bloquer la consultation."""
    lances = []
    monkeypatch.setattr("app.metier.import_dpe.lancer_en_tache_de_fond",
                        lambda declencheur, code_insee=None, avec_dpe=True, avec_cadastre=False: lances.append(code_insee))
    _moisson("40184", il_y_a_heures=48, nom="Mimizan")

    corps = client.post("/api/communes/40184/preparer").json()
    assert corps["lance"] is True
    assert corps["raison"] == "perimee"
    assert lances == ["40184"]


def test_commune_jamais_consultee_est_moissonnee(client, monkeypatch):
    """
    C'est le pivot du parcours : choisir une commune inconnue doit suffire
    a la rendre consultable, sans rien declarer nulle part.
    """
    lances = []
    monkeypatch.setattr("app.metier.import_dpe.lancer_en_tache_de_fond",
                        lambda declencheur, code_insee=None, avec_dpe=True, avec_cadastre=False: lances.append(code_insee))

    corps = client.post("/api/communes/31282/preparer").json()
    assert corps["lance"] is True
    assert corps["raison"] == "jamais_moissonnee"
    assert corps["en_cache"] is False
    assert lances == ["31282"]


def test_une_commune_inconnue_est_moissonnee_meme_seuil_desactive(client, monkeypatch):
    """
    Le seuil a zero coupe le rafraichissement, pas la premiere moisson :
    sans elle, l'ecran n'aurait rien a montrer.
    """
    lances = []
    monkeypatch.setattr("app.metier.import_dpe.lancer_en_tache_de_fond",
                        lambda declencheur, code_insee=None, avec_dpe=True, avec_cadastre=False: lances.append(code_insee))
    client.put("/api/reglages", json={"rafraichir_apres_heures": 0})

    assert client.post("/api/communes/31282/preparer").json()["lance"] is True

    # En revanche une commune deja moissonnee n'est plus rafraichie.
    lances.clear()
    _moisson("40184", il_y_a_heures=500, nom="Mimizan")
    corps = client.post("/api/communes/40184/preparer").json()
    assert corps["lance"] is False
    assert corps["raison"] == "a_jour"
    assert lances == []


def test_recherche_de_commune_signale_ce_qui_est_en_cache(client, monkeypatch):
    monkeypatch.setattr("app.sources.geo.chercher", lambda nom, limite=8: [
        {"code_insee": "31282", "nom": "Launaguet", "code_postal": "31140",
         "codes_postaux": ["31140"], "population": 9173, "departement": "Haute-Garonne"},
        {"code_insee": "31281", "nom": "Launac", "code_postal": "31330",
         "codes_postaux": ["31330"], "population": 1335, "departement": "Haute-Garonne"},
    ])
    inserer_dpe(n_dpe="A", adresse="1 rue", commune="Launaguet", code_insee="31282")

    communes = client.get("/api/communes/recherche", params={"q": "laun"}).json()["communes"]
    par_insee = {c["code_insee"]: c for c in communes}
    assert par_insee["31282"]["en_cache"] is True and par_insee["31282"]["dpe"] == 1
    assert par_insee["31281"]["en_cache"] is False and par_insee["31281"]["dpe"] == 0


def test_recherche_trop_courte_refusee(client):
    assert client.get("/api/communes/recherche", params={"q": "l"}).status_code == 422


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


# =====================================================================
#  Lot 3 — recherche cadastrale
# =====================================================================

def _parcelle(client, identifiant, contenance, emprise, batiments=1, code_insee="31282"):
    from app.base.connexion import transaction
    with transaction() as conn:
        conn.execute(
            "INSERT INTO parcelle (id, code_insee, section, numero, contenance_m2, "
            "  emprise_batie_m2, nb_batiments, latitude, longitude, importe_le) "
            "VALUES (?,?,'AA','001',?,?,?,43.66,1.44,'2026-08-20T10:00:00')",
            (identifiant, code_insee, contenance, emprise, batiments))


def test_recherche_cadastrale(client):
    _parcelle(client, "P1", 800, 120)
    _parcelle(client, "P2", 50_000, 0, batiments=0)

    corps = client.get("/api/parcelles", params={
        "code_insee": "31282", "terrain_min": 400, "terrain_max": 2000}).json()
    assert corps["total"] == 1
    assert corps["resultats"][0]["id"] == "P1"
    assert corps["resume"]["parcelles"] == 2


def test_recherche_cadastrale_sans_commune_refusee(client):
    assert client.get("/api/parcelles").status_code == 422


def test_parcelle_du_dpe(client):
    from app.base.connexion import transaction
    _parcelle(client, "P1", 800, 120)
    inserer_dpe(n_dpe="D1", adresse="1 rue", code_insee="31282")
    with transaction() as conn:
        conn.execute("UPDATE dpe SET parcelle_id = 'P1' WHERE n_dpe = 'D1'")

    assert client.get("/api/parcelles/du-dpe",
                      params={"n_dpe": "D1"}).json()["parcelle"]["id"] == "P1"
    assert client.get("/api/parcelles/du-dpe",
                      params={"n_dpe": "X"}).json()["parcelle"] is None


def test_preparer_une_commune_pour_le_cadastre(client, monkeypatch):
    """
    Choisir « Chercher par le terrain » doit suffire a declencher le
    telechargement du cadastre, sans rien declarer nulle part.
    """
    appels = []
    monkeypatch.setattr("app.metier.import_dpe.lancer_en_tache_de_fond",
                        lambda declencheur, code_insee=None, avec_dpe=True, avec_cadastre=False:
                        appels.append((code_insee, avec_dpe, avec_cadastre)))
    _moisson("31282", il_y_a_heures=2, nom="Launaguet")

    # Les DPE sont a jour, mais le cadastre manque : on ne telecharge QUE
    # le cadastre. Retelecharger les DPE pour rien couterait une minute.
    corps = client.post("/api/communes/31282/preparer",
                        params={"besoin": "cadastre"}).json()
    assert corps["lance"] is True
    assert corps["raison"] == "cadastre_manquant"
    assert appels == [("31282", False, True)]        # (commune, dpe, cadastre)

    # La meme commune pour les seuls DPE ne declenche rien.
    appels.clear()
    corps = client.post("/api/communes/31282/preparer").json()
    assert corps["lance"] is False and corps["raison"] == "a_jour"
    assert appels == []


def test_une_commune_perimee_reprend_tout(client, monkeypatch):
    """DPE perimes ET cadastre manquant : les deux partent d'un coup."""
    appels = []
    monkeypatch.setattr("app.metier.import_dpe.lancer_en_tache_de_fond",
                        lambda declencheur, code_insee=None, avec_dpe=True, avec_cadastre=False:
                        appels.append((code_insee, avec_dpe, avec_cadastre)))
    _moisson("31282", il_y_a_heures=100, nom="Launaguet")

    corps = client.post("/api/communes/31282/preparer",
                        params={"besoin": "cadastre"}).json()
    assert corps["raison"] == "perimee"
    assert appels == [("31282", True, True)]


def test_besoin_inconnu_refuse(client):
    assert client.post("/api/communes/31282/preparer",
                       params={"besoin": "lune"}).status_code == 422


def test_un_cadastre_sans_bati_se_recharge(client, monkeypatch):
    """
    Le cas d'une base montee depuis une version qui ne gardait pas les
    contours : le cadastre est la, date d'hier, et parait donc a jour.

    Le declarer « a jour » laisserait la fiche dessiner des parcelles nues
    pour toujours. Il doit se recharger — le cadastre seul, les DPE etant
    frais.
    """
    import datetime

    from app.base.connexion import transaction

    appels = []
    monkeypatch.setattr("app.metier.import_dpe.lancer_en_tache_de_fond",
                        lambda declencheur, code_insee=None, avec_dpe=True, avec_cadastre=False:
                        appels.append((code_insee, avec_dpe, avec_cadastre)))
    _moisson("31282", il_y_a_heures=2, nom="Launaguet")
    _parcelle(client, "P1", 800, 120, batiments=2)
    hier = (datetime.datetime.now()
            - datetime.timedelta(hours=24)).isoformat(timespec="seconds")
    with transaction() as conn:
        conn.execute("UPDATE commune SET derniere_maj_cadastre = ? "
                     "WHERE code_insee = '31282'", (hier,))

    corps = client.post("/api/communes/31282/preparer",
                        params={"besoin": "cadastre"}).json()
    assert corps["lance"] is True
    assert appels == [("31282", False, True)]        # (commune, dpe, cadastre)
