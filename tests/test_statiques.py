# -*- coding: utf-8 -*-
"""
test_statiques.py — Les fichiers de l'interface et leur fraicheur.

Un defaut invisible en developpement, et desagreable en production : sans
consigne de cache, le navigateur reutilise un fichier sans rien demander.
Apres une mise a jour par Watchtower, un index.html neuf s'est ainsi
retrouve a cote d'un veille.js d'une version precedente — les champs
existaient, le code qui les remplit non.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import application


@pytest.fixture()
def client(base):
    with TestClient(application) as c:
        yield c


@pytest.mark.parametrize("chemin", ["/", "/js/veille.js", "/js/api.js",
                                    "/css/socle.css"])
def test_les_fichiers_de_l_interface_se_revalident(client, chemin):
    reponse = client.get(chemin)
    assert reponse.status_code == 200
    cache = reponse.headers.get("cache-control", "")
    assert "no-cache" in cache, (
        f"{chemin} sans consigne de cache : le navigateur peut servir une "
        "version perimee apres une mise a jour.")
    # L'ETag est ce qui rend la revalidation gratuite : sans lui, chaque
    # chargement retelechargerait tout.
    assert reponse.headers.get("etag")


def test_la_revalidation_ne_renvoie_pas_le_corps(client):
    """Le cout de « no-cache » doit rester une requete vide."""
    etag = client.get("/js/veille.js").headers["etag"]
    reponse = client.get("/js/veille.js", headers={"If-None-Match": etag})
    assert reponse.status_code == 304
    assert reponse.content == b""


def test_l_interface_et_son_code_sont_servis_ensemble(client):
    """
    Les champs de l'ecran et le code qui les remplit doivent venir de la
    meme version. On le verifie par un temoin : un identifiant present
    dans le HTML doit etre connu du script qui le peuple.
    """
    html = client.get("/").text
    js = client.get("/js/veille.js").text
    for identifiant in ("r-alerte-commune", "r-smtp-hote", "r-smtp-port"):
        assert f'id="{identifiant}"' in html, f"{identifiant} absent du HTML"
        assert identifiant in js, f"{identifiant} absent du script"
