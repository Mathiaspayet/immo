# -*- coding: utf-8 -*-
"""
F2 — identification d'un bien depuis les chiffres d'une annonce.

L'exigence centrale du CDC : ne jamais eliminer sans expliquer.
"""

import pytest

from app.metier import identification
from tests.conftest import inserer_dpe

TOLERANCES = {"surface": 3.0, "conso": 5.0, "ges": 1.5}


@pytest.fixture()
def quartier(base):
    """Un petit lot de logements, dont un qui correspond a l'annonce."""
    inserer_dpe(n_dpe="CIBLE", adresse="19 Avenue des Oiseaux",
                surface_habitable=149.0, conso_ep_m2=215.2, conso_ef_m2=158.0,
                ges_m2=7.0, etiquette_dpe="D", etiquette_ges="B")
    inserer_dpe(n_dpe="PROCHE", adresse="40 Avenue du Parc",
                surface_habitable=147.1, conso_ep_m2=211.8, conso_ef_m2=145.0,
                ges_m2=7.0, etiquette_dpe="D", etiquette_ges="B")
    inserer_dpe(n_dpe="LOIN", adresse="3 Rue Lointaine",
                surface_habitable=62.0, conso_ep_m2=90.0, conso_ef_m2=70.0,
                ges_m2=2.0, etiquette_dpe="B", etiquette_ges="A")
    inserer_dpe(n_dpe="SANS_CHIFFRES", adresse="9 Rue Muette",
                surface_habitable=None, conso_ep_m2=None, conso_ef_m2=None,
                ges_m2=None, etiquette_dpe="D", etiquette_ges="B")


ANNONCE = {"surface": 144.0, "conso_ep": 216.0, "conso_ef": 158.0, "ges": 7.0}


def test_rien_n_est_elimine(quartier):
    """
    Le bien recherche fait 149 m2 alors que l'annonce en annonce 144 : un
    filtre strict a +/- 3 m2 le ferait disparaitre. Il doit rester classe.
    """
    resultat = identification.identifier(ANNONCE, tolerances=TOLERANCES)
    numeros = [ligne["n_dpe"] for ligne in resultat["resultats"]]
    assert "CIBLE" in numeros
    # Seul le logement sans aucun chiffre comparable sort du classement.
    assert resultat["classes"] == 3
    assert resultat["examines"] == 4


def test_le_meilleur_candidat_arrive_en_tete(quartier):
    resultat = identification.identifier(ANNONCE, tolerances=TOLERANCES)
    assert resultat["resultats"][0]["n_dpe"] == "CIBLE"


def test_entonnoir_critere_par_critere(quartier):
    resultat = identification.identifier(ANNONCE, tolerances=TOLERANCES)
    par_critere = {etape["critere"]: etape for etape in resultat["entonnoir"]}

    # 144 +/- 3 m2 : ni 149 ni 147,1 n'entrent.
    assert par_critere["surface"]["seuls"] == 0
    # 216 +/- 5 kWh : 215,2 et 211,8 entrent tous les deux.
    assert par_critere["conso_ep"]["seuls"] == 2
    # Le cumul ne peut que decroitre.
    cumules = [etape["cumules"] for etape in resultat["entonnoir"]]
    assert cumules == sorted(cumules, reverse=True)


def test_l_entonnoir_signale_les_criteres_peu_renseignes(quartier):
    resultat = identification.identifier(ANNONCE, tolerances=TOLERANCES)
    par_critere = {etape["critere"]: etape for etape in resultat["entonnoir"]}
    # Trois logements sur quatre portent une surface.
    assert par_critere["surface"]["renseignes"] == 3


def test_diagnostic_designe_le_chiffre_a_suspecter(quartier):
    """
    Quand l'entonnoir se ferme, le message doit nommer le critere sur lequel
    le mieux classe s'ecarte — pas seulement l'etape ou le cumul s'annule.
    """
    resultat = identification.identifier(ANNONCE, tolerances=TOLERANCES)
    assert resultat["diagnostic"]
    assert "surface habitable" in resultat["diagnostic"]
    assert "19 Avenue des Oiseaux" in resultat["diagnostic"]
    assert "rien n'a été éliminé" in resultat["diagnostic"].lower()


def test_une_tolerance_plus_large_rouvre_l_entonnoir(quartier):
    resultat = identification.identifier(
        ANNONCE, tolerances={**TOLERANCES, "surface": 10.0})
    par_critere = {etape["critere"]: etape for etape in resultat["entonnoir"]}
    assert par_critere["surface"]["seuls"] == 2
    assert resultat["diagnostic"] is None       # l'entonnoir ne se ferme plus


def test_valeur_absente_n_est_pas_un_ecart(quartier):
    """Un critere non renseigne vaut None, jamais zero : ce n'est pas un
    logement qui colle parfaitement."""
    resultat = identification.identifier({"surface": 149.0}, tolerances=TOLERANCES)
    par_numero = {l["n_dpe"]: l for l in resultat["resultats"]}
    assert "SANS_CHIFFRES" not in par_numero
    assert par_numero["CIBLE"]["ecarts"]["surface"] == 0.0


def test_classement_sur_les_seules_etiquettes(quartier):
    """Sans aucun chiffre, on classe sur la concordance des classes."""
    resultat = identification.identifier(
        {"etiquette_dpe": "D", "etiquette_ges": "B"}, tolerances=TOLERANCES)
    assert resultat["resultats"][0]["etiquettes_concordantes"] == 2


def test_message_quand_le_cache_est_vide(base):
    resultat = identification.identifier(ANNONCE, tolerances=TOLERANCES)
    assert "cache est vide" in resultat["diagnostic"]


def test_message_quand_aucun_critere_n_est_saisi(quartier):
    resultat = identification.identifier({}, tolerances=TOLERANCES)
    assert "Saisissez au moins un chiffre" in resultat["diagnostic"]
