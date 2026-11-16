# -*- coding: utf-8 -*-
"""
Le lancement d'une moisson : ce que l'etat annonce, et a quel moment.

L'ecran suit une moisson en interrogeant /api/import/statut. Il la croit
finie des que l'etat dit « rien ne tourne » : le drapeau doit donc etre
leve avant que quiconque puisse poser la question.
"""

import threading

import pytest
from fastapi.testclient import TestClient

from app.main import application
from app.metier import import_dpe
from app.base.connexion import transaction


@pytest.fixture(autouse=True)
def etat_propre(base):
    import_dpe._publier(en_cours=False, statut=None, message=None, journal_id=None)
    yield
    import_dpe._publier(en_cours=False, statut=None, message=None, journal_id=None)


@pytest.fixture()
def client():
    with TestClient(application) as client:
        yield client


def test_le_drapeau_est_leve_avant_le_premier_appel_reseau(monkeypatch):
    """
    Le nom de la commune se lit au referentiel de l'Etat — un appel reseau,
    trois secondes un jour de lenteur. Le drapeau se levait APRES : pendant
    ce temps l'ecran lisait « rien ne tourne », croyait la moisson finie, et
    ouvrait une carte vide.
    """
    vus = []

    def referentiel(code_insee):
        vus.append(import_dpe.etat()["en_cours"])
        return {"nom": "Mimizan", "code_postal": "40200"}

    monkeypatch.setattr("app.sources.geo.commune_par_insee", referentiel)
    monkeypatch.setattr(import_dpe, "_moissonner",
                        lambda communes, jeux: {"lignes": 0, "ajouts": 0, "message": "ok"})

    import_dpe.importer_commune("40184")

    assert vus == [True]
    assert import_dpe.etat()["en_cours"] is False
    assert import_dpe.etat()["cible"] == "Mimizan"


def test_lancer_annonce_la_moisson_avant_de_rendre_la_main(monkeypatch):
    """Celui qui recoit « c'est lance » lit « en cours » a la question suivante."""
    partie, finir = threading.Event(), threading.Event()

    def moisson(code_insee, **options):
        partie.set()
        finir.wait(5)
        import_dpe._terminer(options["journal_id"],
                             resume={"lignes": 0, "ajouts": 0, "message": "ok"})

    monkeypatch.setattr(import_dpe, "importer_commune", moisson)

    fil = import_dpe.lancer_en_tache_de_fond(code_insee="40184")
    try:
        # Sans attendre que le fil ait fait quoi que ce soit.
        assert import_dpe.etat()["en_cours"] is True
        with pytest.raises(RuntimeError, match="déjà en cours"):
            import_dpe.lancer_en_tache_de_fond(code_insee="40184")
    finally:
        finir.set()
        fil.join(5)
    assert import_dpe.etat()["en_cours"] is False


def test_un_echec_avant_la_moisson_libere_le_drapeau(monkeypatch):
    """Le drapeau ne doit JAMAIS rester leve : plus aucun import ne partirait."""
    def panne(code_insee, **options):
        raise OSError("disque plein")

    monkeypatch.setattr(import_dpe, "importer_commune", panne)

    import_dpe.lancer_en_tache_de_fond(code_insee="40184").join(5)

    etat = import_dpe.etat()
    assert etat["en_cours"] is False
    assert etat["statut"] == "echec" and "disque plein" in etat["message"]
    assert import_dpe.journal(1)[0]["statut"] == "echec"


def test_forcer_une_moisson_sans_commune_le_dit_tout_de_suite(client):
    """
    Leve dans le fil, ce refus n'atteignait personne : le bouton annoncait
    « moisson demarree », puis plus rien.
    """
    reponse = client.post("/api/import")

    assert reponse.status_code == 409
    assert "Aucune commune" in reponse.json()["detail"]
    assert import_dpe.etat()["en_cours"] is False
    assert import_dpe.journal(5) == []


def test_forcer_une_moisson_repond_en_cours(client, monkeypatch):
    with transaction() as conn:
        conn.execute("INSERT INTO commune (code_insee, nom) VALUES ('40184', 'Mimizan')")
    finir = threading.Event()

    def moisson(declencheur="planifie", jeux=None, journal_id=None):
        finir.wait(5)
        import_dpe._terminer(journal_id, resume={"lignes": 0, "ajouts": 0, "message": "ok"})

    monkeypatch.setattr(import_dpe, "importer", moisson)
    try:
        reponse = client.post("/api/import")
        assert reponse.status_code == 202
        assert reponse.json()["etat"]["en_cours"] is True
        assert client.get("/api/import/statut").json()["en_cours"] is True
    finally:
        finir.set()
    for fil in threading.enumerate():
        if fil.name == "import-dpe":
            fil.join(5)
    assert client.get("/api/import/statut").json()["en_cours"] is False
