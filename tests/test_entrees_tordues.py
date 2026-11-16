# -*- coding: utf-8 -*-
"""
Les demandes mal formees : un refus qui dit pourquoi, jamais une erreur
du serveur.

Chaque cas ci-dessous repondait 500 — ou, pire, etait accepte — lors du
passage en revue de novembre 2026. L'ecran n'envoie rien de tel ; l'API,
elle, doit tenir quand meme.
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.main import application
from app.metier import import_dpe
from tests.conftest import inserer_dpe


@pytest.fixture()
def client(base):
    inserer_dpe(n_dpe="A", code_insee="40184")
    with TestClient(application) as client:
        yield client


def _envoyer(client, methode, chemin, corps=None):
    if corps is None:
        return client.request(methode, chemin)
    # A la main : `json=` refuserait d'ecrire « Infinity ».
    return client.request(methode, chemin, content=json.dumps(corps),
                          headers={"Content-Type": "application/json"})


@pytest.mark.parametrize("methode, chemin, corps", [
    ("GET", "/api/veille?surface_min=1e309", None),
    ("GET", "/api/veille?surface_max=inf", None),
    ("GET", "/api/parcelles/carte?code_insee=40184&bbox=-1.3,44.2,-1.2,44.3&surface_min=1e309", None),
    ("POST", "/api/veille/vus", {"numeros": [1, None, {"a": 1}]}),
    ("POST", "/api/veille/vus", {"numeros": "pas-une-liste"}),
    ("POST", "/api/alertes/essai", {"smtp": "x"}),
    ("POST", "/api/alertes/essai", {"smtp": {"port": "abc", "hote": "127.0.0.1"}}),
    ("POST", "/api/alertes/essai", {"smtp": {"hote": ["a"]}}),
    ("POST", "/api/alertes/essai", {"destinataire": 12}),
    ("POST", "/api/estimation", {"bien": "x"}),
    ("POST", "/api/estimation", {"bien": {}, "saisie": "x"}),
    ("GET", "/api/import/journal?limite=-3", None),
    ("GET", "/api/alertes/journal?limite=0", None),
    ("POST", "/api/communes/abcde/preparer", None),
    ("POST", "/api/communes/4018/preparer", None),
    ("POST", "/api/import?code_insee=abc", None),
    ("GET", "/api/import/ventes/profondeur?code_insee=abc", None),
    ("POST", "/api/import/ventes/archive?code_insee=abc", None),
    ("POST", "/api/estimation/preparer?departement=zz", None),
    ("POST", "/api/estimation/preparer?departement=9", None),
])
def test_une_demande_mal_formee_est_refusee_proprement(client, methode, chemin, corps):
    reponse = _envoyer(client, methode, chemin, corps)
    assert reponse.status_code in (400, 422), f"{reponse.status_code} : {reponse.text[:200]}"
    assert reponse.json()["detail"]


def test_un_code_insee_fantaisiste_ne_lance_rien(client):
    """« abcde » lancait une vraie moisson : trois requetes a l'ADEME, puis
    une ligne d'echec au journal."""
    reponse = client.post("/api/communes/abcde/preparer")
    assert "Code INSEE invalide" in reponse.json()["detail"]
    assert import_dpe.etat()["en_cours"] is False
    assert import_dpe.journal(5) == []


@pytest.mark.parametrize("code, attendu", [
    ("40184", "40184"), (" 40184 ", "40184"), ("2a004", "2A004"), ("2B033", "2B033"),
    ("97411", "97411"), ("4018", None), ("401840", None), ("abcde", None), ("2C004", None),
    ("", None), (None, None), ("../..", None),
])
def test_ce_qu_est_un_code_insee(code, attendu):
    from app.metier import valeurs
    assert valeurs.code_insee(code) == attendu


def test_marquer_vus_accepte_toujours_une_liste_de_numeros(client):
    assert client.post("/api/veille/vus", json={"numeros": ["A"]}).json() == {"marques": 1}
    assert client.post("/api/veille/vus", json={"numeros": []}).json() == {"marques": 0}
    assert client.post("/api/veille/vus", json={}).json() == {"marques": 0}


# ---------------------------------------------------------------------
#  L'estimation : des refus qui parlent francais
# ---------------------------------------------------------------------

BIEN = {"type": "maison", "surface": 122, "latitude": 44.2135, "longitude": -1.2883,
        "code_insee": "40184"}


@pytest.mark.parametrize("bien, saisie, extrait", [
    ({**BIEN, "latitude": "x"}, {}, "Position du bien illisible"),
    ({**BIEN, "latitude": 95}, {}, "Position du bien illisible"),
    ({**BIEN, "pieces": "abc"}, {}, "Pièces principales"),
    ({**BIEN, "annee_construction": "mil neuf cent"}, {}, "Année de construction"),
    ({**BIEN, "dependances": -2}, {}, "Dépendances"),
])
def test_un_bien_mal_decrit_est_refuse_en_clair(base, bien, saisie, extrait):
    """Le message etait celui de Python : « could not convert string to float: 'x' »."""
    from app.metier import estimation
    with pytest.raises(ValueError, match=extrait) as refus:
        estimation.estimer(bien, saisie)
    assert "could not convert" not in str(refus.value)
