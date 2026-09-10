# -*- coding: utf-8 -*-
"""
test_sauvegarde.py — Les copies datees de la base.

Ce qui est en jeu ne se retelecharge pas : DVF ne se consulte que sur cinq
ans, et le millesime qui sort de la fenetre ne subsiste plus que dans cette
base. Les defauts gardes ici sont donc ceux qui ne se voient qu'au moment
de restaurer — c'est-a-dire trop tard.
"""

import datetime
import sqlite3

import pytest

from app import config
from app.base import sauvegarde
from app.base.connexion import connexion, transaction


@pytest.fixture()
def dossier_copies(base, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CHEMIN_SAUVEGARDES", tmp_path / "sauvegardes")
    return tmp_path / "sauvegardes"


def _peupler(n=40):
    with transaction() as conn:
        conn.executemany(
            "INSERT INTO mutation (id, code_insee, date_mutation, nature,"
            " valeur_fonciere, nb_parcelles, nb_locaux, types_locaux_json,"
            " importe_le) VALUES (?,'40184','2018-05-10','Vente',300000,1,1,"
            " '[]','2026-01-01T10:00:00')",
            [(f"M{i}",) for i in range(n)])


def test_la_copie_contient_vraiment_les_donnees(dossier_copies):
    """Une copie de la bonne taille peut etre vide : on recompte."""
    _peupler(40)
    resultat = sauvegarde.sauvegarder()
    assert resultat["faite"] is True
    assert resultat["verifie"] is True

    chemin = dossier_copies / resultat["fichier"]
    conn = sqlite3.connect(f"file:{chemin}?mode=ro", uri=True)
    try:
        assert conn.execute("SELECT count(*) FROM mutation").fetchone()[0] == 40
    finally:
        conn.close()


def test_la_copie_prend_les_ecritures_recentes(dossier_copies):
    """
    Le vrai piege du mode WAL : les ecritures recentes vivent dans un
    fichier `-wal` a cote. Copier le seul `.db` rendrait une base
    incomplete, et le defaut ne se verrait qu'a la restauration.
    """
    _peupler(10)
    # Ecriture juste avant la copie : elle est encore dans le WAL.
    with transaction() as conn:
        conn.execute(
            "INSERT INTO mutation (id, code_insee, date_mutation, nature,"
            " valeur_fonciere, nb_parcelles, nb_locaux, types_locaux_json,"
            " importe_le) VALUES ('TARD','40184','2018-06-01','Vente',1,1,1,"
            " '[]','2026-01-01T10:00:00')")

    resultat = sauvegarde.sauvegarder()
    chemin = dossier_copies / resultat["fichier"]
    conn = sqlite3.connect(f"file:{chemin}?mode=ro", uri=True)
    try:
        assert conn.execute(
            "SELECT count(*) FROM mutation WHERE id = 'TARD'").fetchone()[0] == 1
    finally:
        conn.close()


def test_une_copie_douteuse_est_refusee_et_retiree(dossier_copies, monkeypatch):
    """
    Sauvegarder une base corrompue PUIS faire tourner la rotation est la
    maniere classique de perdre ses donnees en croyant les proteger. Une
    copie qui ne se verifie pas ne doit donc jamais compter.
    """
    _peupler(10)
    monkeypatch.setattr(sauvegarde, "_verifier",
                        lambda chemin, attendus: (False, "quick_check : casse"))
    resultat = sauvegarde.sauvegarder()

    assert resultat["faite"] is False
    assert "casse" in resultat["raison"]
    assert list(dossier_copies.glob("*.db")) == [], (
        "la copie douteuse est restee sur le disque")


def test_une_copie_ratee_ne_chasse_pas_les_bonnes(dossier_copies, monkeypatch):
    """La rotation ne doit pas tourner sur un echec."""
    _peupler(10)
    bonne = sauvegarde.sauvegarder()
    assert bonne["faite"]

    monkeypatch.setattr(sauvegarde, "_verifier",
                        lambda chemin, attendus: (False, "illisible"))
    sauvegarde.sauvegarder()

    restantes = [c["fichier"] for c in sauvegarde.copies()]
    assert bonne["fichier"] in restantes


# =====================================================================
#  La rotation : ce qu'on pourra encore recuperer dans six mois
# =====================================================================

def _poser(dossier_copies, quand, nom=None):
    """Une copie factice a une date donnee, ou sous un nom impose."""
    dossier_copies.mkdir(parents=True, exist_ok=True)
    chemin = dossier_copies / (nom or f"veille-{quand:%Y-%m-%d-%H%M}.db")
    chemin.write_bytes(b"x" * 1024)
    return chemin


def test_la_rotation_garde_le_recent_et_l_ancien(dossier_copies):
    """
    Ne garder que les dernieres copies serait un piege : une corruption
    passe rarement inapercue le jour meme, et s'il faut trois semaines
    pour la remarquer, sept jours de retention n'ont plus rien a offrir.
    """
    maintenant = datetime.datetime(2028, 6, 15, 3, 0)
    # Deux ans de sauvegardes quotidiennes.
    for jour in range(730):
        _poser(dossier_copies, maintenant - datetime.timedelta(days=jour))

    sauvegarde._rotation(maintenant)
    restantes = sorted(c["quand"] for c in sauvegarde.copies())

    quotidiennes = [q for q in restantes
                    if q >= maintenant - datetime.timedelta(days=7)]
    assert len(quotidiennes) >= 7, "la semaine ecoulee doit rester entiere"

    mois = {(q.year, q.month) for q in restantes}
    assert len(mois) >= 12, "il faut au moins douze mois distincts"

    # Et l'annee d'avant ne doit pas avoir disparu entierement.
    assert min(restantes) < maintenant - datetime.timedelta(days=365), (
        "plus rien au-dela d'un an : une corruption ancienne serait perdue")
    # Sans pour autant tout garder.
    assert len(restantes) < 60, f"{len(restantes)} copies : rien n'est purge"


def test_la_rotation_ne_touche_pas_aux_fichiers_etrangers(dossier_copies):
    """Le dossier peut etre partage : on ne supprime que ce qu'on a ecrit."""
    dossier_copies.mkdir(parents=True, exist_ok=True)
    intrus = dossier_copies / "notes-importantes.db"
    intrus.write_bytes(b"a garder")
    _poser(dossier_copies, datetime.datetime(2020, 1, 1, 3, 0))

    sauvegarde._rotation(datetime.datetime(2028, 6, 15, 3, 0))
    assert intrus.exists(), "un fichier etranger a ete supprime"


def test_deux_sauvegardes_dans_la_meme_minute_coexistent(dossier_copies):
    """
    Le defaut le plus grave possible ici : le bouton « Sauvegarder
    maintenant » clique juste apres la copie du planificateur portait le
    meme nom, et l'ecrasait.
    """
    _peupler(5)
    # L'HEURE COURANTE, et non une date figee dans le passe : le geste
    # qu'on decrit — cliquer juste apres la copie du planificateur — se
    # fait aujourd'hui. Une date de trois semaines tombait hors de la
    # fenetre quotidienne, ou la retention mensuelle ne garde qu'une copie
    # par mois : le test se battait alors contre une regle legitime, et
    # son verdict dependait de l'ordre du systeme de fichiers.
    quand = datetime.datetime.now().replace(microsecond=0)
    une = sauvegarde.sauvegarder(quand)
    deux = sauvegarde.sauvegarder(quand)

    assert une["faite"] and deux["faite"]
    assert une["fichier"] != deux["fichier"], "la seconde copie ecrase la premiere"
    presentes = {c["fichier"] for c in sauvegarde.copies()}
    assert une["fichier"] in presentes and deux["fichier"] in presentes


def test_l_etat_signale_une_sauvegarde_trop_vieille(dossier_copies):
    """Mieux vaut le voir a l'ecran qu'au moment de restaurer."""
    _poser(dossier_copies, datetime.datetime.now() - datetime.timedelta(days=5))
    etat = sauvegarde.etat()
    assert etat["alerte"], "cinq jours sans copie doit alerter"

    _poser(dossier_copies, datetime.datetime.now())
    assert sauvegarde.etat()["alerte"] is None


def test_sans_aucune_copie_l_etat_le_dit(dossier_copies):
    etat = sauvegarde.etat()
    assert etat["copies"] == 0
    assert etat["alerte"] == "aucune sauvegarde"


def test_une_sauvegarde_tient_en_un_seul_fichier(dossier_copies):
    """
    `backup()` reproduit le mode WAL de la source : la copie trainait un
    `-wal` et un `-shm`, orphelins des la publication. Une sauvegarde doit
    tenir en UN fichier — c'est ce qu'on glisse sur une clef, ce qu'Hyper
    Backup emporte, et ce qu'on rouvrira sans se demander quels fichiers
    vont ensemble.
    """
    _peupler(20)
    resultat = sauvegarde.sauvegarder()
    assert resultat["faite"]

    restants = sorted(p.name for p in dossier_copies.iterdir())
    assert restants == [resultat["fichier"]], f"fichiers en trop : {restants}"


def test_une_tentative_ratee_ne_laisse_rien(dossier_copies, monkeypatch):
    _peupler(20)
    monkeypatch.setattr(sauvegarde, "_verifier",
                        lambda chemin, attendus: (False, "casse"))
    sauvegarde.sauvegarder()
    assert list(dossier_copies.iterdir()) == [], "des debris sont restes"


# =====================================================================
#  La restauration : la seule chose qui compte vraiment
# =====================================================================

def test_une_sauvegarde_se_restaure_par_simple_copie(dossier_copies, tmp_path):
    """
    Le test qui donne son sens a tous les autres. Une sauvegarde qui ne se
    restaure pas ne sert a rien, et on ne l'apprend qu'au pire moment.

    On verifie ici la procedure exacte du README : arreter, remplacer le
    fichier, redemarrer — sans outil, sans ligne de commande SQLite.
    """
    import shutil

    _peupler(120)
    with transaction() as conn:
        conn.execute("INSERT INTO reglage (cle, valeur_json) VALUES"
                     " ('alerte_destinataire', '\"moi@exemple.fr\"')")

    copie = sauvegarde.sauvegarder()
    assert copie["faite"]

    # Sinistre : la base vivante est perdue.
    config.CHEMIN_BASE.unlink(missing_ok=True)
    for annexe in ("-wal", "-shm"):
        config.CHEMIN_BASE.with_name(
            config.CHEMIN_BASE.name + annexe).unlink(missing_ok=True)

    # Restauration : une copie de fichier, rien de plus.
    shutil.copy(dossier_copies / copie["fichier"], config.CHEMIN_BASE)

    with connexion() as conn:
        assert conn.execute("SELECT count(*) FROM mutation").fetchone()[0] == 120
        assert conn.execute(
            "SELECT valeur_json FROM reglage WHERE cle = 'alerte_destinataire'"
        ).fetchone()[0] == '"moi@exemple.fr"'
        # Et la base restauree doit rester ECRIVABLE : une copie en lecture
        # seule ou a moitie fermee ne se verrait qu'a la premiere ecriture.
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("INSERT INTO mutation (id, code_insee, date_mutation,"
                     " nature, valeur_fonciere, nb_parcelles, nb_locaux,"
                     " types_locaux_json, importe_le) VALUES ('APRES','40184',"
                     " '2026-01-01','Vente',1,1,1,'[]','2026-01-01')")
        conn.execute("COMMIT")
        assert conn.execute("SELECT count(*) FROM mutation").fetchone()[0] == 121


def test_la_base_restauree_repasse_les_migrations_sans_dommage(dossier_copies):
    """Au redemarrage, l'application applique les migrations : sur une base
    restauree elles ne doivent rien casser ni rien rejouer."""
    from app.base import migrations

    _peupler(30)
    copie = sauvegarde.sauvegarder()

    import shutil
    config.CHEMIN_BASE.unlink(missing_ok=True)
    shutil.copy(dossier_copies / copie["fichier"], config.CHEMIN_BASE)

    jouees = migrations.appliquer()
    assert jouees == [], f"migrations rejouees sur une base a jour : {jouees}"
    with connexion() as conn:
        assert conn.execute("SELECT count(*) FROM mutation").fetchone()[0] == 30


def test_deux_copies_de_la_meme_seconde_sont_departagees():
    """
    Deux copies d'une meme minute — « ...-1430.db » et « ...-143000.db » —
    se lisent a la MEME seconde. Sans le nom pour les departager, la
    decision suivait l'ordre d'arrivee, donc celui du systeme de fichiers :
    le meme code gardait l'une ici et l'autre la.

    Le test qui l'a revele passait en local et echouait sur le serveur
    d'integration. Une instabilite est pire qu'un echec franc — elle se
    prend pour de la malchance, et on relance.

    On presente donc le meme couple dans les DEUX ordres : la regle doit
    trancher, pas le hasard.
    """
    quand = datetime.datetime(2026, 8, 24, 14, 30)
    maintenant = quand + datetime.timedelta(days=20)
    a = {"fichier": "veille-2026-08-24-1430.db", "quand": quand, "octets": 1}
    b = {"fichier": "veille-2026-08-24-143000.db", "quand": quand, "octets": 1}

    un = sauvegarde._a_garder([a, b], maintenant)
    deux = sauvegarde._a_garder([b, a], maintenant)
    assert un == deux, (
        "la copie conservee depend de l'ordre d'arrivee, donc du systeme "
        "de fichiers")
    assert len(un) == 1, "la retention mensuelle n'en garde qu'une"
