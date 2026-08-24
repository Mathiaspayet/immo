# -*- coding: utf-8 -*-
"""
test_streetview.py — La vue de rue de la fiche.

Ecart assume au CDC 9 : consulter une fiche transmet les coordonnees du
bien a un tiers. Deux garde-fous en limitent la portee, et sont verrouilles
ici — la cle ne sort jamais du serveur, et rien ne part sans cle.
"""

import json

import pytest

from app.base import reglages
from app.sources import streetview
from tests.conftest import inserer_dpe

CLE = "AIza-cle-tres-secrete"


@pytest.fixture()
def client(base):
    from fastapi.testclient import TestClient

    from app.main import application
    with TestClient(application) as c:
        yield c


def test_sans_cle_rien_ne_part(base, monkeypatch):
    """
    Le defaut est le silence : aucune requete, aucune coordonnee
    transmise, et la fiche garde son simple lien.
    """
    appels = []
    monkeypatch.setattr("app.sources.streetview._demander",
                        lambda *a, **k: appels.append(a) or (b"", ""))

    assert streetview.active() is False
    assert streetview.catalogue(44.2, -1.23) is None
    assert appels == []


def test_la_cle_ne_sort_jamais_du_serveur(client):
    """
    Une cle d'API se facture a qui la trouve. Elle est donc masquee comme
    le mot de passe SMTP, et l'image passe par le NAS precisement pour
    qu'elle n'ait pas a atteindre le navigateur.
    """
    reglages.ecrire({"streetview_cle": CLE})

    public = reglages.tous()
    assert public["streetview_cle"] == reglages.MASQUE
    assert public["streetview_cle_defini"] is True
    assert CLE not in json.dumps(public)
    assert CLE not in client.get("/api/reglages").text
    assert CLE not in client.get("/api/alertes").text

    # Seul l'envoi la lit.
    assert reglages.lire("streetview_cle") == CLE


def test_le_masque_conserve_la_cle(base):
    """L'ecran affiche des puces et les renvoie : les prendre au mot
    effacerait la cle au premier enregistrement."""
    reglages.ecrire({"streetview_cle": CLE})
    reglages.ecrire({"streetview_cle": reglages.MASQUE})
    assert reglages.lire("streetview_cle") == CLE

    reglages.ecrire({"streetview_cle": ""})
    assert reglages.lire("streetview_cle") == ""


def test_le_catalogue_precede_l_image(base, monkeypatch):
    """
    La consultation du catalogue ne coute rien et dit si une vue existe :
    sans elle on paierait une image absente, pour afficher un rectangle
    gris.
    """
    reglages.ecrire({"streetview_cle": CLE})
    demandes = []

    def faux(url, parametres):
        demandes.append(url)
        return json.dumps({"status": "ZERO_RESULTS"}).encode(), "application/json"

    monkeypatch.setattr("app.sources.streetview._demander", faux)
    assert streetview.image(44.2, -1.23) is None
    # Une seule requete : le catalogue. L'image n'a pas ete demandee.
    assert demandes == [streetview.CATALOGUE]


def test_l_objectif_se_tourne_vers_le_bien(base, monkeypatch):
    """
    La camera est sur la voie, le bien est de cote. Sans cap, on recoit ce
    que le vehicule avait devant lui — souvent la route.
    """
    reglages.ecrire({"streetview_cle": CLE})
    envoyes = {}

    def faux(url, parametres):
        if url == streetview.CATALOGUE:
            # Prise de vue au SUD du bien : l'objectif doit viser le nord.
            return json.dumps({
                "status": "OK", "pano_id": "PANO-1",
                "location": {"lat": 44.1990, "lng": -1.2300},
            }).encode(), "application/json"
        envoyes.update(parametres)
        return b"\xff\xd8\xff-des-octets-jpeg", "image/jpeg"

    monkeypatch.setattr("app.sources.streetview._demander", faux)
    octets, type_contenu = streetview.image(44.2000, -1.2300)

    assert type_contenu == "image/jpeg"
    assert envoyes["pano"] == "PANO-1"       # exactement la vue designee
    assert abs(envoyes["heading"] - 0) < 5   # plein nord
    assert "key" in envoyes


def test_le_cliche_est_garde_en_cache(base, monkeypatch):
    """Une meme fiche se consulte plusieurs fois, et chaque image se paie."""
    reglages.ecrire({"streetview_cle": CLE})
    images = []

    def faux(url, parametres):
        if url == streetview.CATALOGUE:
            return json.dumps({
                "status": "OK", "pano_id": "PANO-CACHE",
                "location": {"lat": 44.1990, "lng": -1.2300},
            }).encode(), "application/json"
        images.append(parametres)
        return b"\xff\xd8\xff-jpeg", "image/jpeg"

    monkeypatch.setattr("app.sources.streetview._demander", faux)
    premier = streetview.image(44.2000, -1.2300)
    second = streetview.image(44.2000, -1.2300)

    assert premier == second
    assert len(images) == 1, "la seconde consultation ne doit rien refacturer"


def test_l_endpoint_se_tait_sans_cle(client):
    inserer_dpe(n_dpe="D1", adresse="1 rue", latitude=44.2, longitude=-1.23)
    reponse = client.get("/api/parcelles/vue-rue", params={"n_dpe": "D1"})
    assert reponse.status_code == 404


def test_l_endpoint_repond_404_sans_cliche(client, monkeypatch):
    """Rien de photographie la est le cas courant, pas une panne."""
    reglages.ecrire({"streetview_cle": CLE})
    inserer_dpe(n_dpe="D1", adresse="1 rue", latitude=44.2, longitude=-1.23)
    monkeypatch.setattr(
        "app.sources.streetview._demander",
        lambda url, p: (json.dumps({"status": "ZERO_RESULTS"}).encode(),
                        "application/json"))

    reponse = client.get("/api/parcelles/vue-rue", params={"n_dpe": "D1"})
    assert reponse.status_code == 404


def test_l_endpoint_sert_l_image_sans_divulguer_la_cle(client, monkeypatch):
    reglages.ecrire({"streetview_cle": CLE})
    inserer_dpe(n_dpe="D1", adresse="1 rue", latitude=44.2, longitude=-1.23)

    def faux(url, parametres):
        if url == streetview.CATALOGUE:
            return json.dumps({
                "status": "OK", "pano_id": "P", "date": "2024-06",
                "location": {"lat": 44.199, "lng": -1.23},
            }).encode(), "application/json"
        return b"\xff\xd8\xff-image", "image/jpeg"

    monkeypatch.setattr("app.sources.streetview._demander", faux)
    reponse = client.get("/api/parcelles/vue-rue", params={"n_dpe": "D1"})

    assert reponse.status_code == 200
    assert reponse.headers["content-type"] == "image/jpeg"
    assert reponse.content == b"\xff\xd8\xff-image"
    assert CLE not in reponse.text
    assert CLE not in str(reponse.headers)


def test_un_bien_sans_position_ne_fait_pas_tomber(client):
    reglages.ecrire({"streetview_cle": CLE})
    inserer_dpe(n_dpe="D1", adresse="1 rue", latitude=None, longitude=None)
    assert client.get("/api/parcelles/vue-rue",
                      params={"n_dpe": "D1"}).status_code == 404
