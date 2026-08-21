# -*- coding: utf-8 -*-
"""
F4 — fiche d'un bien, chronologie, chaine des remplacements, comparaison.

Aucun de ces tests n'appelle le reseau : la chaine est demandee avec
`interroger_ademe=False`, et la comparaison passe par des donnees injectees.
"""

import json

import pytest

from app.metier import fiche
from app.metier.valeurs import normaliser_adresse
from tests.conftest import inserer_dpe


# ---------------------------------------------------------------------
#  Normalisation des adresses
# ---------------------------------------------------------------------

@pytest.mark.parametrize("ecriture", [
    "8bis Cité des Tilleuls 40200 Mimizan",
    "8BIS CITE DES TILLEULS 40200 MIMIZAN",
    "  8bis  Cité   des Tilleuls, 40200 Mimizan  ",
    "8bis Cité-des-Tilleuls 40200 Mimizan",
])
def test_orthographes_equivalentes(ecriture):
    """
    L'orthographe varie d'une base ADEME a l'autre. Sans normalisation, la
    chronologie d'un meme bien se couperait en plusieurs.
    """
    reference = normaliser_adresse("8bis Cité des Tilleuls 40200 Mimizan")
    assert normaliser_adresse(ecriture) == reference


def test_adresses_reellement_differentes():
    assert normaliser_adresse("8 rue des Pins") != normaliser_adresse("9 rue des Pins")


# ---------------------------------------------------------------------
#  Chronologie
# ---------------------------------------------------------------------

@pytest.fixture()
def maison(base):
    """Une maison diagnostiquee trois fois, sur deux generations de bases."""
    inserer_dpe(n_dpe="ANCIEN", adresse="12 Rue des Pins 40200 Mimizan",
                date_etablissement="2014-06-02", jeu_de_donnees="ancien",
                etiquette_dpe="E", surface_habitable=120.0,
                importe_le="2026-08-01T08:00:00")
    inserer_dpe(n_dpe="MOYEN", adresse="12 RUE DES PINS 40200 MIMIZAN",
                date_etablissement="2022-03-15", jeu_de_donnees="existant",
                etiquette_dpe="D", surface_habitable=120.0,
                importe_le="2026-08-01T08:00:00")
    inserer_dpe(n_dpe="RECENT", adresse="12 Rue des Pins 40200 Mimizan",
                date_etablissement="2026-01-09", jeu_de_donnees="existant",
                etiquette_dpe="C", surface_habitable=121.0,
                n_dpe_remplace="MOYEN", importe_le="2026-08-01T08:00:00")
    with_journal()


def with_journal(revu="2026-08-20T09:00:00", code_insee="40184"):
    """
    Reproduit fidelement ce qu'un import laisse derriere lui.

    Le detail qui compte : `revu_le` et `derniere_maj_dpe` portent le meme
    horodatage — l'import les ecrit dans la meme transaction, a partir de
    la meme valeur — tandis que `journal_import.fin` est postérieur, la
    cloture venant apres l'ecriture.

    L'ancien jeu d'essai posait `revu_le` egal a `fin`, ce qui n'arrive
    jamais en vrai. Il validait donc une comparaison fausse, et le defaut
    qu'elle causait — toute la chronologie affichee « retiree » — est
    passe inapercu jusqu'a une verification sur donnees reelles.
    """
    from app.base.connexion import transaction

    fin = "2026-08-20T09:00:07"           # sept secondes plus tard, comme en vrai
    with transaction() as conn:
        conn.execute(
            "INSERT INTO journal_import (source, debut, fin, statut) "
            "VALUES ('essai', ?, ?, 'succes')", (revu, fin))
        conn.execute(
            "INSERT INTO commune (code_insee, nom, code_postal, derniere_maj_dpe) "
            "VALUES (?, 'Mimizan', '40200', ?) "
            "ON CONFLICT(code_insee) DO UPDATE SET "
            "  derniere_maj_dpe = excluded.derniere_maj_dpe", (code_insee, revu))
        # Tout ce qui a ete revu lors de cet import est encore publie.
        conn.execute("UPDATE dpe SET code_insee = ? WHERE code_insee IS NULL",
                     (code_insee,))
        conn.execute("UPDATE dpe SET revu_le = ? WHERE n_dpe != 'MOYEN'", (revu,))
        conn.execute("UPDATE dpe SET revu_le = '2026-02-01T08:00:00' WHERE n_dpe = 'MOYEN'")


def test_chronologie_toutes_bases_confondues(maison):
    resultat = fiche.historique(adresse="12 Rue des Pins 40200 Mimizan")
    numeros = [d["n_dpe"] for d in resultat["diagnostics"]]
    assert numeros == ["ANCIEN", "MOYEN", "RECENT"]      # du plus ancien au plus recent
    assert {d["jeu_de_donnees"] for d in resultat["diagnostics"]} == {"ancien", "existant"}


def test_chronologie_depuis_un_numero(maison):
    resultat = fiche.historique(n_dpe="RECENT")
    assert len(resultat["diagnostics"]) == 3


def test_un_dpe_non_revu_est_signale_comme_retire(maison):
    """
    Un DPE remplace est retire de la base active de l'ADEME. Cesser de le
    revoir a l'import est donc le signal de son remplacement.
    """
    resultat = fiche.historique(adresse="12 Rue des Pins 40200 Mimizan")
    par_numero = {d["n_dpe"]: d for d in resultat["diagnostics"]}
    assert par_numero["MOYEN"]["encore_publie"] is False
    assert par_numero["RECENT"]["encore_publie"] is True


def test_une_maison_n_est_pas_signalee_comme_immeuble(maison):
    resultat = fiche.historique(adresse="12 Rue des Pins 40200 Mimizan")
    # ANCIEN et RECENT sont en vigueur, mais RECENT remplace MOYEN :
    # deux logements ? non — c'est un seuil, on verifie juste le comptage.
    assert resultat["en_vigueur"] == 2


def test_plusieurs_logements_a_la_meme_adresse(base):
    """Plusieurs diagnostics en vigueur en meme temps = un immeuble."""
    for numero in ("A", "B", "C"):
        inserer_dpe(n_dpe=numero, adresse="Rue des Hournails 40200 Mimizan",
                    date_etablissement="2026-01-09", surface_habitable=35.0)
    with_journal()
    resultat = fiche.historique(adresse="Rue des Hournails 40200 Mimizan")
    assert resultat["plusieurs_logements"] is True
    assert resultat["en_vigueur"] == 3


def test_un_dpe_revu_avant_la_cloture_reste_publie(maison):
    """
    Le defaut qui rendait la chronologie illisible.

    `revu_le` s'ecrit PENDANT l'import, `journal_import.fin` a sa cloture,
    une poignee de secondes plus tard. Comparer l'un a l'autre declarait
    donc « retirees de la base active » les 4 343 lignes d'une moisson qui
    venait de les rapporter.
    """
    from app.base.connexion import connexion

    with connexion() as conn:
        revu = conn.execute(
            "SELECT revu_le FROM dpe WHERE n_dpe = 'RECENT'").fetchone()[0]
        fin = conn.execute(
            "SELECT fin FROM journal_import ORDER BY id DESC LIMIT 1").fetchone()[0]
    assert revu < fin, "le jeu d'essai doit reproduire l'ecart reel"

    resultat = fiche.historique(adresse="12 Rue des Pins 40200 Mimizan")
    par_numero = {d["n_dpe"]: d for d in resultat["diagnostics"]}
    assert par_numero["RECENT"]["encore_publie"] is True
    assert par_numero["ANCIEN"]["encore_publie"] is True


def test_moissonner_une_commune_ne_retire_pas_les_autres(maison):
    """
    Le repere doit etre par commune. Sinon, consulter Launaguet
    declarerait retire tout le parc de Mimizan, qui n'a pas ete revu a
    cette occasion — et ce sont justement les biens qu'on suit.
    """
    from app.base.connexion import transaction

    with transaction() as conn:
        conn.execute(
            "INSERT INTO commune (code_insee, nom, code_postal, derniere_maj_dpe) "
            "VALUES ('31282', 'Launaguet', '31140', '2026-08-21T10:00:00')")

    resultat = fiche.historique(adresse="12 Rue des Pins 40200 Mimizan")
    par_numero = {d["n_dpe"]: d for d in resultat["diagnostics"]}
    assert par_numero["RECENT"]["encore_publie"] is True


def test_adresse_inconnue_propose_des_voisines(maison):
    resultat = fiche.historique(adresse="12 Rue des Sapins 40200 Mimizan")
    assert resultat["diagnostics"] == []
    assert "Aucun diagnostic connu" in resultat["message"]
    assert "12 Rue des Pins 40200 Mimizan" in fiche.voisinage("Rue des Pins")


# ---------------------------------------------------------------------
#  Chaine des remplacements
# ---------------------------------------------------------------------

def test_chaine_depuis_le_cache(maison):
    resultat = fiche.chaine("RECENT", interroger_ademe=False)
    numeros = [m["n_dpe"] for m in resultat["maillons"]]
    assert numeros == ["RECENT", "MOYEN"]
    assert all(m["origine"] == "cache" for m in resultat["maillons"])


def test_maillon_absent_est_explique_pas_devine(base):
    """
    Jamais de repli silencieux : un DPE introuvable est annonce comme tel,
    avec la raison, plutot que remplace par un resultat approchant.
    """
    inserer_dpe(n_dpe="SEUL", adresse="1 Rue Unique", n_dpe_remplace="DISPARU")
    resultat = fiche.chaine("SEUL", interroger_ademe=False)
    dernier = resultat["maillons"][-1]
    assert dernier["n_dpe"] == "DISPARU"
    assert dernier["absent"] is True
    assert "cache local" in dernier["explication"]


def test_chaine_ne_boucle_pas(base):
    """Deux DPE qui se remplacent mutuellement ne doivent pas figer l'appel."""
    inserer_dpe(n_dpe="A", adresse="1 Rue Boucle", n_dpe_remplace="B")
    inserer_dpe(n_dpe="B", adresse="1 Rue Boucle", n_dpe_remplace="A")
    resultat = fiche.chaine("A", interroger_ademe=False)
    assert [m["n_dpe"] for m in resultat["maillons"]] == ["A", "B"]
    assert resultat["boucle_detectee"] is True


# ---------------------------------------------------------------------
#  Comparaison
# ---------------------------------------------------------------------

def test_comparaison_champ_par_champ(base, monkeypatch):
    inserer_dpe(n_dpe="AVANT", adresse="1 Rue Test",
                donnees_brutes_json=json.dumps({
                    "etiquette_dpe": "E", "surface_habitable_logement": 120,
                    "_score": 3.2, "date_derniere_modification_dpe": "2022-01-01"}))
    inserer_dpe(n_dpe="APRES", adresse="1 Rue Test",
                donnees_brutes_json=json.dumps({
                    "etiquette_dpe": "C", "surface_habitable_logement": 121,
                    "_score": 9.9, "date_derniere_modification_dpe": "2026-01-01"}))
    # Pas de reseau : l'ADEME ne connait aucun de ces numeros.
    monkeypatch.setattr("app.sources.ademe.chercher_par_numero",
                        lambda numero, jeux=None: (None, None, None))

    resultat = fiche.comparer("APRES", "AVANT")
    assert resultat["comparables"] is True
    champs = {d["champ"]: d for d in resultat["differences"]}

    assert champs["etiquette_dpe"]["avant"] == "E"
    assert champs["etiquette_dpe"]["apres"] == "C"
    # Les cles ajoutees par le moteur de recherche ne sont pas des donnees.
    assert "_score" not in champs
    # Les dates de saisie changent a chaque republication : mises a part.
    assert "date_derniere_modification_dpe" not in champs
    assert any(d["champ"] == "date_derniere_modification_dpe"
               for d in resultat["techniques"])


def test_comparaison_impossible_est_dite(base, monkeypatch):
    inserer_dpe(n_dpe="SEUL", adresse="1 Rue Test", donnees_brutes_json='{"a": 1}')
    monkeypatch.setattr("app.sources.ademe.chercher_par_numero",
                        lambda numero, jeux=None: (None, None, None))

    resultat = fiche.comparer("SEUL", "DISPARU")
    assert resultat["comparables"] is False
    assert "DISPARU" in resultat["manquants"]
    assert "retiré de la base active" in resultat["message"]


def test_une_maison_rediagnostiquee_n_est_pas_un_immeuble(base):
    """
    Ce que le nombre de diagnostics ne peut pas dire.

    Une maison vendue deux fois porte deux DPE, un immeuble aussi. Ce qui
    les separe est la simultaneite : on ne rediagnostique pas le meme
    logement le meme jour, mais on diagnostique un immeuble d'un coup.

    Mesure sur Mimizan : compter les diagnostics traitait 552 adresses en
    immeubles, dont 328 sont de simples maisons revisitees.
    """
    inserer_dpe(n_dpe="V1", adresse="53 Chemin des Roseaux 40200 Mimizan",
                date_etablissement="2024-04-24", surface_habitable=63.0)
    inserer_dpe(n_dpe="V2", adresse="53 Chemin des Roseaux 40200 Mimizan",
                date_etablissement="2026-01-06", surface_habitable=61.8)
    with_journal()

    resultat = fiche.historique(adresse="53 Chemin des Roseaux 40200 Mimizan")
    assert resultat["en_vigueur"] == 2          # les deux sont encore servis
    assert resultat["logements_estimes"] == 1   # mais c'est une seule maison
    assert resultat["plusieurs_logements"] is False


def test_deux_diagnostics_le_meme_jour_font_deux_logements(base):
    """Avenue de Woolsack : deux logements, chacun diagnostique deux fois."""
    for numero, date, surface in [("A1", "2021-12-13", 64.0),
                                  ("B1", "2021-12-13", 100.7),
                                  ("A2", "2026-01-10", 65.0),
                                  ("B2", "2026-01-10", 96.0)]:
        inserer_dpe(n_dpe=numero, adresse="8 Avenue de Woolsack 40200 Mimizan",
                    date_etablissement=date, surface_habitable=surface)
    with_journal()

    resultat = fiche.historique(adresse="8 Avenue de Woolsack 40200 Mimizan")
    assert resultat["logements_estimes"] == 2
    assert resultat["plusieurs_logements"] is True
