# -*- coding: utf-8 -*-
"""
test_config.py — Le vide vaut absent.

Le compose declarait chaque variable avec SON defaut, qui dupliquait celui
du code. Docker substitue a la creation du conteneur, ce qui grave la
valeur dedans ; Watchtower remplace l'image mais conserve
l'environnement. Un defaut du compose survit donc a toutes les mises a
jour et diverge du code des qu'on le change.

C'est arrive : le compose posait « mon » le 20 aout, le code est passe a
« * » le meme soir, et le conteneur deploye entre-temps est reste
hebdomadaire — l'ecran annoncant « chaque jour » d'apres le code tandis
que le planificateur suivait « mon » grave dans le conteneur.

Le compose passe desormais une chaine vide, et c'est config.py qui
tranche.
"""

import importlib

import pytest


def _recharger(monkeypatch, **variables):
    from app import config
    for nom, valeur in variables.items():
        if valeur is None:
            monkeypatch.delenv(nom, raising=False)
        else:
            monkeypatch.setenv(nom, valeur)
    return importlib.reload(config)


VIDES = {
    "VEILLE_IMPORT_JOUR": "*",
    "VEILLE_IMPORT_HEURE": 7,
    "VEILLE_LOG": "INFO",
}


@pytest.mark.parametrize("nom, attendu", sorted(VIDES.items(), key=str))
def test_une_variable_vide_retombe_sur_le_defaut_du_code(monkeypatch, nom, attendu):
    """Une chaine vide n'est pas un choix : c'est l'absence de choix."""
    config = _recharger(monkeypatch, **{nom: ""})
    obtenu = {"VEILLE_IMPORT_JOUR": config.IMPORT_JOUR,
              "VEILLE_IMPORT_HEURE": config.IMPORT_HEURE,
              "VEILLE_LOG": config.NIVEAU_LOG}[nom]
    assert obtenu == attendu


def test_une_valeur_choisie_prime_toujours(monkeypatch):
    """Le repli ne doit pas ecraser un choix explicite : c'est par la que
    passe un .env pose a cote du compose."""
    config = _recharger(monkeypatch, VEILLE_IMPORT_JOUR="mon",
                        VEILLE_IMPORT_HEURE="19")
    assert config.IMPORT_JOUR == "mon"
    assert config.IMPORT_HEURE == 19


def test_le_planificateur_vide_reste_actif(monkeypatch):
    """Vide veut dire « rien de choisi », donc le defaut : actif. Seul un
    « 0 » explicite le desactive."""
    assert _recharger(monkeypatch, VEILLE_PLANIFICATEUR="").PLANIFICATEUR_ACTIF
    assert not _recharger(monkeypatch, VEILLE_PLANIFICATEUR="0").PLANIFICATEUR_ACTIF


def test_le_compose_ne_duplique_plus_le_defaut_du_code(monkeypatch):
    """
    Le garde-fou qui compte : un defaut reintroduit dans le compose se
    regraverait dans le conteneur et survivrait aux mises a jour. La panne
    ne se verrait qu'a l'usage, des semaines plus tard.
    """
    import pathlib
    import re

    compose = (pathlib.Path(__file__).resolve().parent.parent
               / "docker-compose.synology.yml").read_text(encoding="utf-8")
    fautifs = []
    for nom in ("VEILLE_IMPORT_JOUR", "VEILLE_IMPORT_HEURE",
                "VEILLE_PLANIFICATEUR", "VEILLE_LOG"):
        trouve = re.search(rf"{nom}:\s*\$\{{{nom}:-(.*?)\}}", compose)
        assert trouve, f"{nom} absent du compose"
        if trouve.group(1).strip():
            fautifs.append(f"{nom} = {trouve.group(1)!r}")
    assert not fautifs, (
        "ces defauts seraient graves dans le conteneur a sa creation et "
        "survivraient aux mises a jour : " + ", ".join(fautifs))


def test_le_fuseau_garde_son_defaut(monkeypatch):
    """TZ est lue par le systeme autant que par l'application : vide, elle
    vaudrait UTC, et l'import de 7 h partirait a 9 h en ete."""
    assert _recharger(monkeypatch, TZ="").FUSEAU == "Europe/Paris"
