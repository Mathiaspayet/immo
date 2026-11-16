# -*- coding: utf-8 -*-
"""
Le mot de passe : ce qui est ferme, comment on l'ouvre, ce qui est garde.
"""

import re
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import config
from app.base import reglages
from app.base.connexion import transaction
from app.main import application
from app.metier import acces
from app.sources import courriel

BON = "un mot de passe solide"


@pytest.fixture(autouse=True)
def barriere(monkeypatch):
    """Ici, la barriere est levee — c'est elle qu'on eprouve."""
    monkeypatch.setattr("app.main.EXIGER_ACCES", True)
    monkeypatch.setattr(config, "COURRIEL_ACCES", "")
    monkeypatch.setattr(config, "URL_PUBLIQUE", "")


@pytest.fixture()
def client(base):
    with TestClient(application) as client:
        yield client


@pytest.fixture()
def envois(monkeypatch, base):
    """Le serveur d'envoi configure, et les messages gardes au lieu de partir."""
    reglages.ecrire({"smtp_hote": "smtp.exemple.fr", "smtp_expediteur": "veille@exemple.fr",
                     "alerte_destinataire": "proprietaire@exemple.fr"})
    partis = []

    def envoyer(destinataire, sujet, texte, html=None, **_):
        partis.append({"a": destinataire, "sujet": sujet, "texte": texte, "html": html})
        return True

    monkeypatch.setattr(courriel, "envoyer", envoyer)
    return partis


def _jeton(message):
    return re.search(r"#acces=([\w-]+)", message["texte"]).group(1)


def _initialiser(client, envois, motdepasse=BON):
    assert client.post("/api/acces/lien").status_code == 200
    reponse = client.post("/api/acces/definir",
                          json={"jeton": _jeton(envois[-1]), "motdepasse": motdepasse})
    assert reponse.status_code == 200, reponse.text
    return reponse


# ---------------------------------------------------------------------
#  Ce qui est ferme, ce qui ne l'est pas
# ---------------------------------------------------------------------

def test_sans_mot_de_passe_l_api_est_fermee_des_le_premier_lancement(client):
    assert client.get("/api/veille").status_code == 401
    assert client.put("/api/reglages", json={"alerte_destinataire": "intrus@exemple.fr"}
                      ).status_code == 401
    assert client.get("/api/reglages").status_code == 401
    assert client.get("/openapi.json").status_code == 401
    assert client.get("/api/documentation").status_code == 401
    # Une adresse mal formee retombe du cote ferme.
    assert client.get("/api/acces/").status_code in (401, 404)


def test_la_sonde_l_ecran_et_l_etat_restent_ouverts(client):
    assert client.get("/api/sante").status_code == 200
    assert client.get("/").status_code == 200
    assert client.get("/js/acces.js").status_code == 200
    etat = client.get("/api/acces").json()
    assert etat["initialise"] is False and etat["connecte"] is False


def test_l_etat_ne_montre_l_adresse_que_masquee(client, envois):
    etat = client.get("/api/acces").json()
    assert etat["destinataire"] == "p" + "•" * len("roprietaire") + "@exemple.fr"
    assert "proprietaire" not in client.get("/api/acces").text
    assert etat["envoi_possible"] is True


def test_masquer():
    assert acces.masquer("ab@gmail.com") == "a•••@gmail.com"
    assert acces.masquer("") == "" and acces.masquer("sans-arobase") == ""


# ---------------------------------------------------------------------
#  Le lien
# ---------------------------------------------------------------------

def test_le_lien_part_a_l_adresse_des_alertes_et_ramene_a_la_page(client, envois):
    reponse = client.post("/api/acces/lien", headers={"Origin": "http://nas.local:8020"})
    assert reponse.status_code == 200
    assert envois[0]["a"] == "proprietaire@exemple.fr"
    assert "choisir" in envois[0]["sujet"]
    assert re.search(r"http://nas\.local:8020/#acces=[\w-]{40,}", envois[0]["texte"])


def test_l_adresse_du_conteneur_prime_sur_celle_de_l_ecran(client, envois, monkeypatch):
    monkeypatch.setattr(config, "COURRIEL_ACCES", "nas@exemple.fr")
    client.post("/api/acces/lien")
    assert envois[0]["a"] == "nas@exemple.fr"


def test_l_adresse_publique_posee_ferme_la_porte_a_un_lien_detourne(client, envois, monkeypatch):
    monkeypatch.setattr(config, "URL_PUBLIQUE", "https://immo.exemple.fr")
    client.post("/api/acces/lien", headers={"Origin": "https://pirate.exemple"})
    assert "https://immo.exemple.fr/#acces=" in envois[0]["texte"]
    assert "pirate" not in envois[0]["texte"]


def test_sans_adresse_ou_sans_serveur_le_lien_ne_part_pas(client, monkeypatch):
    assert client.post("/api/acces/lien").status_code == 503
    reglages.ecrire({"alerte_destinataire": "proprietaire@exemple.fr"})
    reponse = client.post("/api/acces/lien")
    assert reponse.status_code == 503
    assert "serveur d'envoi" in reponse.json()["detail"]


def test_pas_plus_d_un_lien_par_minute(client, envois):
    assert client.post("/api/acces/lien").status_code == 200
    reponse = client.post("/api/acces/lien")
    assert reponse.status_code == 429
    assert reponse.headers["retry-after"] == "60"
    assert len(envois) == 1


def test_un_lien_qui_n_est_pas_parti_ne_compte_pas(client, envois, monkeypatch):
    def refuse(*_, **__):
        raise courriel.ErreurCourriel("serveur injoignable")

    monkeypatch.setattr(courriel, "envoyer", refuse)
    reponse = client.post("/api/acces/lien")
    assert reponse.status_code == 502 and "injoignable" in reponse.json()["detail"]
    with transaction() as conn:
        assert conn.execute("SELECT COUNT(*) FROM acces_jeton").fetchone()[0] == 0


# ---------------------------------------------------------------------
#  Choisir le mot de passe
# ---------------------------------------------------------------------

def test_le_lien_choisit_le_mot_de_passe_et_connecte(client, envois):
    reponse = _initialiser(client, envois)
    cookie = reponse.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert "secure" not in cookie            # HTTP sur le reseau local
    assert client.get("/api/veille").status_code == 200
    etat = client.get("/api/acces").json()
    assert etat["initialise"] and etat["connecte"]
    # Le proprietaire est prevenu.
    assert "choisi" in envois[-1]["sujet"]


def test_derriere_https_le_cookie_est_securise(client, envois):
    client.post("/api/acces/lien")
    reponse = client.post("/api/acces/definir", headers={"X-Forwarded-Proto": "https"},
                          json={"jeton": _jeton(envois[-1]), "motdepasse": BON})
    assert "secure" in reponse.headers["set-cookie"].lower()


def test_un_lien_ne_sert_qu_une_fois(client, envois):
    _initialiser(client, envois)
    jeton = _jeton(envois[0])
    reponse = client.post("/api/acces/definir", json={"jeton": jeton, "motdepasse": "autre chose encore"})
    assert reponse.status_code == 400
    assert "plus valable" in reponse.json()["detail"]


def test_un_lien_expire_ne_sert_plus(client, envois):
    client.post("/api/acces/lien")
    with transaction() as conn:
        conn.execute("UPDATE acces_jeton SET expire_le = '2000-01-01T00:00:00'")
    reponse = client.post("/api/acces/definir", json={"jeton": _jeton(envois[0]), "motdepasse": BON})
    assert reponse.status_code == 400


def test_un_mot_de_passe_trop_court_est_refuse_sans_bruler_le_lien(client, envois):
    client.post("/api/acces/lien")
    jeton = _jeton(envois[0])
    reponse = client.post("/api/acces/definir", json={"jeton": jeton, "motdepasse": "court"})
    assert reponse.status_code == 400 and "10 caractères" in reponse.json()["detail"]
    assert client.post("/api/acces/definir", json={"jeton": jeton, "motdepasse": BON}).status_code == 200


def test_rien_n_est_garde_en_clair(client, envois):
    _initialiser(client, envois)
    session = client.cookies.get(acces.COOKIE)
    jeton = _jeton(envois[0])
    brut = sqlite3.connect(config.CHEMIN_BASE).iterdump()
    tout = "\n".join(brut)
    assert BON not in tout and session not in tout and jeton not in tout


# ---------------------------------------------------------------------
#  Se connecter
# ---------------------------------------------------------------------

def test_connexion(client, envois):
    _initialiser(client, envois)
    client.cookies.clear()
    assert client.get("/api/veille").status_code == 401
    assert client.post("/api/acces/connexion", json={"motdepasse": "pas le bon !"}).status_code == 401
    assert client.post("/api/acces/connexion", json={"motdepasse": BON}).status_code == 200
    assert client.get("/api/veille").status_code == 200


def test_sans_mot_de_passe_choisi_on_ne_se_connecte_pas(client):
    reponse = client.post("/api/acces/connexion", json={"motdepasse": BON})
    assert reponse.status_code == 409


def test_les_essais_repetes_doivent_patienter(client, envois):
    _initialiser(client, envois)
    for _ in range(acces.ESSAIS_LIBRES):
        assert client.post("/api/acces/connexion", json={"motdepasse": "faux faux faux"}).status_code == 401
    # Meme le bon doit attendre son tour : sinon l'attente ne freinerait rien.
    reponse = client.post("/api/acces/connexion", json={"motdepasse": BON})
    assert reponse.status_code == 429 and int(reponse.headers["retry-after"]) >= 1


def test_une_session_trop_ancienne_tombe(client, envois):
    _initialiser(client, envois)
    with transaction() as conn:
        conn.execute("UPDATE acces_session SET expire_le = '2000-01-01T00:00:00'")
    assert client.get("/api/veille").status_code == 401


def test_une_visite_prolonge_la_session(client, envois):
    _initialiser(client, envois)
    with transaction() as conn:
        conn.execute("UPDATE acces_session SET vu_le = '2000-01-01T00:00:00',"
                     " expire_le = '2999-01-01T00:00:00'")
    client.get("/api/veille")
    with transaction() as conn:
        vu, expire = conn.execute("SELECT vu_le, expire_le FROM acces_session").fetchone()
    assert vu > "2000" and expire < "2999"


# ---------------------------------------------------------------------
#  Changer, oublier, se deconnecter
# ---------------------------------------------------------------------

def test_changer_demande_l_actuel_et_deconnecte_les_autres(client, envois):
    _initialiser(client, envois)
    with TestClient(application) as autre:
        assert autre.post("/api/acces/connexion", json={"motdepasse": BON}).status_code == 200
        assert client.post("/api/acces/changer",
                           json={"actuel": "pas le bon !", "nouveau": "tout nouveau mot"}
                           ).status_code == 401
        assert client.post("/api/acces/changer",
                           json={"actuel": BON, "nouveau": "tout nouveau mot"}).status_code == 200
        assert client.get("/api/veille").status_code == 200
        assert autre.get("/api/veille").status_code == 401
    assert "changé" in envois[-1]["sujet"]


def test_changer_sans_session_est_refuse(client, envois):
    _initialiser(client, envois)
    client.cookies.clear()
    reponse = client.post("/api/acces/changer", json={"actuel": BON, "nouveau": "tout nouveau mot"})
    assert reponse.status_code == 401


def test_mot_de_passe_oublie_un_nouveau_lien_le_remplace(client, envois):
    _initialiser(client, envois)
    client.cookies.clear()
    with transaction() as conn:          # la minute entre deux liens
        conn.execute("UPDATE acces_jeton SET cree_le = '2000-01-01T00:00:00'")
    assert client.post("/api/acces/lien").status_code == 200
    assert "changer" in envois[-1]["sujet"]
    client.post("/api/acces/definir", json={"jeton": _jeton(envois[-1]), "motdepasse": "le remplacant"})
    client.cookies.clear()
    assert client.post("/api/acces/connexion", json={"motdepasse": BON}).status_code == 401
    assert client.post("/api/acces/connexion", json={"motdepasse": "le remplacant"}).status_code == 200


def test_deconnexion(client, envois):
    _initialiser(client, envois)
    assert client.post("/api/acces/deconnexion").status_code == 200
    assert client.get("/api/veille").status_code == 401


def test_deconnecter_partout(client, envois):
    _initialiser(client, envois)
    with TestClient(application) as autre:
        autre.post("/api/acces/connexion", json={"motdepasse": BON})
        client.post("/api/acces/deconnexion", json={"partout": True})
        assert autre.get("/api/veille").status_code == 401


def test_le_recours_du_nas_emet_un_jeton_sans_rythme(base):
    premier = acces.emettre_jeton(verifier_rythme=False)
    second = acces.emettre_jeton(verifier_rythme=False)
    assert premier != second
    session = acces.definir(second, BON)
    assert acces.session_valide(session)


# ---------------------------------------------------------------------
#  Ou mene le lien
# ---------------------------------------------------------------------

PIRATE = {"Origin": "https://pirate.example"}
CHEZ_MOI = {"Origin": "https://immo.exemple.fr"}


@pytest.mark.parametrize("origine, locale", [
    ("http://192.168.1.20:8020", True), ("http://10.0.0.4", True), ("http://127.0.0.1:8000", True),
    ("http://localhost:8020", True), ("http://nas:8020", True), ("http://nas.local:8020", True),
    ("http://diskstation.lan", True), ("http://[fd12::1]:8020", True), ("http://100.72.1.9:8020", True),
    ("https://immo.exemple.fr", False), ("https://pirate.example", False),
    ("http://8.8.8.8", False), ("http://192.168.1.20.pirate.example", False),
    ("http://[2001:4860:4860::8888]", False), ("", False), ("pas une adresse", False),
])
def test_ce_qui_est_une_adresse_du_reseau_local(origine, locale):
    assert acces.est_locale(origine) is locale


def test_une_origine_forgee_ne_detourne_pas_le_premier_lien(client, envois):
    """
    La faille : sans etre connecte, on faisait partir vers le proprietaire
    un courriel AUTHENTIQUE dont le lien menait chez soi — il n'y avait
    plus qu'a y lire le jeton, et a choisir le mot de passe a sa place.
    """
    reponse = client.post("/api/acces/lien", headers=PIRATE)

    assert reponse.status_code == 409
    assert "VEILLE_URL" in reponse.json()["detail"]
    assert envois == []
    with transaction() as conn:
        assert conn.execute("SELECT COUNT(*) FROM acces_jeton").fetchone()[0] == 0


def test_une_origine_forgee_mene_a_l_adresse_du_proprietaire(client, envois):
    """Mot de passe oublie : le lien suit l'adresse d'ou l'on s'est deja connecte."""
    _initialiser(client, envois)
    client.cookies.clear()
    assert client.post("/api/acces/connexion", headers=CHEZ_MOI,
                       json={"motdepasse": BON}).status_code == 200
    client.cookies.clear()
    with transaction() as conn:          # la minute entre deux liens
        conn.execute("UPDATE acces_jeton SET cree_le = '2000-01-01T00:00:00'")

    reponse = client.post("/api/acces/lien", headers=PIRATE)

    assert reponse.status_code == 200
    assert reponse.json()["meme_adresse"] is False
    assert "https://immo.exemple.fr/#acces=" in envois[-1]["texte"]
    assert "pirate" not in envois[-1]["texte"] and "pirate" not in envois[-1]["html"]
    assert "pirate" not in reponse.text and "immo.exemple" not in reponse.text


def test_le_lien_suit_une_adresse_deja_connue(client, envois):
    _initialiser(client, envois)
    client.post("/api/acces/connexion", headers=CHEZ_MOI, json={"motdepasse": BON})
    client.cookies.clear()
    with transaction() as conn:
        conn.execute("UPDATE acces_jeton SET cree_le = '2000-01-01T00:00:00'")

    reponse = client.post("/api/acces/lien", headers=CHEZ_MOI)

    assert reponse.json()["meme_adresse"] is True
    assert "https://immo.exemple.fr/#acces=" in envois[-1]["texte"]


def test_se_servir_de_l_application_fait_connaitre_son_adresse(client, envois):
    """Une session deja ouverte avant cette protection n'a pas a se reconnecter."""
    _initialiser(client, envois)
    assert acces.origines_de_confiance() == []      # « testserver » n'envoie pas d'Origin

    assert client.post("/api/veille/vus", headers=CHEZ_MOI, json={}).status_code == 200

    assert acces.origines_de_confiance() == ["https://immo.exemple.fr"]


def test_sans_session_une_adresse_n_est_jamais_retenue(client, envois):
    _initialiser(client, envois)
    client.cookies.clear()

    client.post("/api/veille/vus", headers=PIRATE, json={})
    client.post("/api/acces/connexion", headers=PIRATE, json={"motdepasse": "pas le bon !"})
    client.get("/api/acces", headers=PIRATE)

    assert acces.origines_de_confiance() == []


def test_une_page_d_un_autre_site_ne_fait_pas_retenir_son_adresse(client, envois):
    _initialiser(client, envois)
    client.post("/api/veille/vus", json={},
                headers={"Origin": "https://voisin.exemple.fr", "Sec-Fetch-Site": "same-site"})
    assert acces.origines_de_confiance() == []


def test_on_ne_garde_que_les_adresses_recentes(base):
    for numero in range(acces.ORIGINES_GARDEES + 5):
        acces.retenir_origine(f"https://adresse{numero}.exemple.fr")
    assert len(acces.origines_de_confiance()) == acces.ORIGINES_GARDEES
    acces.retenir_origine("javascript:alert(1)")
    acces.retenir_origine("https://exemple.fr/chemin?x=1")
    assert len(acces.origines_de_confiance()) == acces.ORIGINES_GARDEES


def test_un_lien_deja_utilise_ne_fait_pas_patienter(client, envois):
    """« Un lien vient de partir » : faux, quand celui-la a deja servi."""
    _initialiser(client, envois)
    client.cookies.clear()
    assert client.post("/api/acces/lien").status_code == 200
    assert client.post("/api/acces/lien").status_code == 429


# ---------------------------------------------------------------------
#  Ce qu'on laisse voir, et entrer, sans connexion
# ---------------------------------------------------------------------

def test_la_sonde_ne_dit_que_ok_sans_connexion(client, envois):
    assert client.get("/api/sante").json() == {"statut": "ok"}
    _initialiser(client, envois)
    assert {"version", "base", "prochain_import"} <= set(client.get("/api/sante").json())


def test_un_corps_enorme_est_refuse_avant_d_etre_lu(client):
    gros = '{"motdepasse": "' + "x" * 5000 + '"}'
    reponse = client.post("/api/acces/connexion", content=gros,
                          headers={"Content-Type": "application/json"})
    assert reponse.status_code == 413


def test_un_envoi_par_morceaux_est_refuse_sans_connexion(client):
    def morceaux():
        yield b'{"motdepasse": "'
        yield b'x" }'

    reponse = client.post("/api/acces/connexion", content=morceaux(),
                          headers={"Content-Type": "application/json"})
    assert reponse.status_code == 411
