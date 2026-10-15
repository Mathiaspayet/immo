# -*- coding: utf-8 -*-
"""
test_client_http.py — Les appels aux sources : ce qui se retente, et ce qui non.

Un 502 ou un 503 est la signature d'un serveur public surcharge un matin de
parution : il se retente. Un 403 ou un 404 ne se resoudra pas tout seul.
"""

import io
import urllib.error

import pytest

from app.sources import ademe, client_http
from app.sources.client_http import ErreurSource


class _Reponse(io.BytesIO):
    headers = {"ETag": "abc"}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _serveur(monkeypatch, codes):
    """Rend les codes dans l'ordre : un entier leve HTTPError, None repond."""
    appels = []

    def urlopen(requete, timeout=None, context=None):
        appels.append(requete.get_method())
        code = codes[min(len(appels) - 1, len(codes) - 1)]
        if code is None:
            return _Reponse(b'{"ok": true}')
        raise urllib.error.HTTPError(requete.full_url, code, "refus", {}, io.BytesIO(b""))

    monkeypatch.setattr(client_http.urllib.request, "urlopen", urlopen)
    return appels


def test_un_serveur_surcharge_est_retente(monkeypatch):
    appels = _serveur(monkeypatch, [503, 429, None])
    assert client_http.appeler("https://exemple/api") == {"ok": True}
    assert len(appels) == 3


def test_un_refus_definitif_ne_l_est_pas(monkeypatch):
    appels = _serveur(monkeypatch, [404])
    with pytest.raises(ErreurSource, match="HTTP 404"):
        client_http.appeler("https://exemple/api")
    assert len(appels) == 1


def test_les_tentatives_ont_une_fin(monkeypatch):
    appels = _serveur(monkeypatch, [502])
    with pytest.raises(urllib.error.HTTPError):
        client_http.ouvrir("https://exemple/fichier")
    assert len(appels) == client_http.TENTATIVES


def test_une_requete_head_rend_les_en_tetes(monkeypatch):
    appels = _serveur(monkeypatch, [500, None])
    _, entetes = client_http.ouvrir("https://exemple/fichier", methode="HEAD")
    assert entetes["ETag"] == "abc" and appels == ["HEAD", "HEAD"]


def test_le_schema_de_l_ademe_est_garde_une_journee(monkeypatch):
    """Il etait relu a chaque import et a chaque recherche par numero."""
    lectures = []
    monkeypatch.setattr(ademe, "appeler", lambda url: lectures.append(url) or
                        [{"key": "numero_dpe"}, {"key": "date_etablissement_dpe"}])
    premier = ademe.lire_schema("existant")
    second = ademe.lire_schema("existant")
    assert premier == second and len(lectures) == 1
    ademe.lire_schema("neuf")
    assert len(lectures) == 2

    monkeypatch.setattr(ademe, "DUREE_SCHEMA", 0)
    ademe.lire_schema("existant")
    assert len(lectures) == 3
