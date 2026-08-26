# -*- coding: utf-8 -*-
"""
test_config.py — Ce qui releve du deploiement, et ce qui releve du reglage.

Le piege vecu : le compose declarait chaque variable avec SON defaut, qui
dupliquait celui du code. Docker substitue a la creation du conteneur, ce
qui grave la valeur dedans ; Watchtower remplace l'image mais conserve
l'environnement. Un defaut du compose survit donc a toutes les mises a
jour et diverge du code des qu'on le change.

C'est arrive : le compose posait « mon » le 20 aout, le code est passe a
« * » le meme soir, et le conteneur deploye entre-temps est reste
hebdomadaire des semaines — l'ecran annoncant « chaque jour » d'apres le
code tandis que le planificateur suivait « mon » grave dans le conteneur.

Deux corrections en decoulent, et ce fichier garde les deux :
  - l'horaire d'import a QUITTE l'environnement pour les reglages ;
  - ce qui reste dans l'environnement n'y porte plus de defaut duplique.
"""

import importlib
import pathlib
import re

import pytest

COMPOSE = (pathlib.Path(__file__).resolve().parent.parent
           / "docker-compose.synology.yml").read_text(encoding="utf-8")


def _recharger(monkeypatch, **variables):
    from app import config
    for nom, valeur in variables.items():
        if valeur is None:
            monkeypatch.delenv(nom, raising=False)
        else:
            monkeypatch.setenv(nom, valeur)
    return importlib.reload(config)


# =====================================================================
#  L'horaire n'est plus une affaire d'environnement
# =====================================================================

def test_l_horaire_ne_se_lit_plus_dans_l_environnement(base, monkeypatch):
    """
    Le coeur du correctif. Une variable gravee dans le conteneur ne doit
    plus pouvoir imposer un rythme que l'ecran ne peut pas corriger.
    """
    from app import planificateur

    monkeypatch.setenv("VEILLE_IMPORT_JOUR", "mon")
    monkeypatch.setenv("VEILLE_IMPORT_HEURE", "19")
    assert planificateur.horaire() == ("*", 7), (
        "l'environnement dicte encore l'horaire")


def test_l_horaire_suit_les_reglages(base):
    from app.base import reglages
    from app import planificateur

    reglages.ecrire({"import_jour": "mon-fri", "import_heure": 19})
    assert planificateur.horaire() == ("mon-fri", 19)


def test_le_compose_ne_declare_plus_l_horaire():
    """
    Le garde-fou qui compte : reintroduire ces variables les regraverait
    dans le conteneur a sa creation, ou elles survivraient aux mises a
    jour. La panne ne se verrait qu'a l'usage, des semaines plus tard.
    """
    for nom in ("VEILLE_IMPORT_JOUR", "VEILLE_IMPORT_HEURE"):
        assert f"{nom}:" not in COMPOSE, (
            f"{nom} est de retour dans le compose : sa valeur serait gravee "
            "dans le conteneur et survivrait aux mises a jour")


def test_un_horaire_invalide_est_refuse_a_l_ecriture(base):
    """Un cron invalide ne se verrait qu'au demarrage suivant, quand le
    planificateur refuserait de partir — soit trop tard."""
    from app.base import reglages

    with pytest.raises(ValueError, match="import_jour"):
        reglages.ecrire({"import_jour": "lundi"})
    with pytest.raises(ValueError, match="import_heure"):
        reglages.ecrire({"import_heure": 24})


# =====================================================================
#  Ce qui reste dans l'environnement
# =====================================================================

def test_une_variable_vide_retombe_sur_le_defaut_du_code(monkeypatch):
    """Une chaine vide n'est pas un choix : c'est l'absence de choix. Le
    compose en passe une quand l'utilisateur n'a rien decide."""
    assert _recharger(monkeypatch, VEILLE_LOG="").NIVEAU_LOG == "INFO"


def test_le_planificateur_reste_un_choix_de_deploiement(monkeypatch):
    """Celui-la reste dans l'environnement a juste titre : « ce conteneur
    fait-il tourner des taches planifiees ? » n'est pas un reglage metier
    mais une propriete de la machine — un poste de dev dit non."""
    assert _recharger(monkeypatch, VEILLE_PLANIFICATEUR="").PLANIFICATEUR_ACTIF
    assert not _recharger(monkeypatch, VEILLE_PLANIFICATEUR="0").PLANIFICATEUR_ACTIF


def test_les_variables_restantes_n_ont_plus_de_defaut_duplique():
    fautifs = []
    for nom in ("VEILLE_PLANIFICATEUR", "VEILLE_LOG"):
        trouve = re.search(rf"{nom}:\s*\$\{{{nom}:-(.*?)\}}", COMPOSE)
        assert trouve, f"{nom} absent du compose"
        if trouve.group(1).strip():
            fautifs.append(f"{nom} = {trouve.group(1)!r}")
    assert not fautifs, (
        "ces defauts seraient graves dans le conteneur a sa creation : "
        + ", ".join(fautifs))


def test_le_fuseau_garde_son_defaut(monkeypatch):
    """TZ est lue par le systeme autant que par l'application : vide, elle
    vaudrait UTC, et l'import de 7 h partirait a 9 h en ete."""
    assert _recharger(monkeypatch, TZ="").FUSEAU == "Europe/Paris"


def test_changer_l_horaire_replanifie_sans_redemarrer(base, monkeypatch):
    """
    Sans cela, modifier l'heure a l'ecran n'aurait d'effet qu'au prochain
    redemarrage — et l'ecran annoncerait la nouvelle heure pendant que le
    planificateur suivrait l'ancienne. C'est exactement le desaccord que
    tout ce travail vient supprimer.
    """
    import datetime

    from fastapi.testclient import TestClient
    from app import planificateur
    from app.main import application

    # Les tests tournent avec VEILLE_PLANIFICATEUR=0 : on le rallume ici,
    # sans quoi ce test se sauterait et ne garderait rien.
    monkeypatch.setattr("app.config.PLANIFICATEUR_ACTIF", True)
    monkeypatch.setattr("app.planificateur._planificateur", None)
    assert planificateur.demarrer() is not None
    try:
        with TestClient(application) as client:
            avant = planificateur.prochaine_execution()
            reponse = client.put("/api/reglages",
                                 json={"import_jour": "fri", "import_heure": 18})
            assert reponse.status_code == 200
            apres = planificateur.prochaine_execution()

        assert apres and apres != avant, "l'horaire n'a pas ete replanifie"
        quand = datetime.datetime.fromisoformat(apres)
        assert quand.hour == 18
        assert quand.weekday() == 4, "vendredi attendu"
    finally:
        planificateur.arreter()


def test_un_horaire_refuse_ne_replanifie_rien(base):
    """Une valeur invalide doit etre repoussee AVANT d'atteindre le
    planificateur : un cron casse l'empecherait de repartir."""
    from fastapi.testclient import TestClient
    from app.base import reglages
    from app.main import application

    reglages.ecrire({"import_jour": "mon", "import_heure": 6})
    with TestClient(application) as client:
        reponse = client.put("/api/reglages", json={"import_jour": "lundi"})
    assert reponse.status_code == 400
    assert reglages.lire("import_jour") == "mon"
