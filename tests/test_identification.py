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


def test_les_deux_chiffres_du_dpe_suffisent(quartier):
    """
    Le cas courant : une annonce ne donne que l'energie primaire et le GES.

    Rien d'autre n'est exige, et le bon candidat sort quand meme en tete.
    Mesure sur Mimizan : l'energie primaire seule ramene 4 343 logements a
    65, le GES avec elle a 45.
    """
    resultat = identification.identifier({"conso_ep": 216.0, "ges": 7.0},
                                         tolerances=TOLERANCES)
    assert resultat["resultats"][0]["n_dpe"] == "CIBLE"
    # L'entonnoir ne compte que ce qui a ete renseigne.
    assert [e["critere"] for e in resultat["entonnoir"]] == ["conso_ep", "ges"]


def test_un_seul_chiffre_suffit_aussi(quartier):
    """Chaque critere est facultatif SEPAREMENT, pas seulement en bloc."""
    for critere, valeur in [("conso_ep", 216.0), ("ges", 7.0),
                            ("surface", 144.0), ("conso_ef", 158.0)]:
        resultat = identification.identifier({critere: valeur},
                                             tolerances=TOLERANCES)
        assert resultat["resultats"], f"{critere} seul ne renvoie rien"
        assert [e["critere"] for e in resultat["entonnoir"]] == [critere]


def test_chaque_chiffre_ajoute_resserre_l_entonnoir(quartier):
    """Ce que le formulaire promet : ajouter un chiffre restreint, jamais
    l'inverse."""
    cumuls = []
    criteres = {}
    for cle, valeur in [("conso_ep", 216.0), ("ges", 7.0), ("surface", 144.0)]:
        criteres[cle] = valeur
        resultat = identification.identifier(dict(criteres), tolerances=TOLERANCES)
        cumuls.append(resultat["entonnoir"][-1]["cumules"])
    assert cumuls == sorted(cumuls, reverse=True), cumuls


def test_le_type_n_ecarte_pas_un_dpe_d_avant_2021(base):
    """La base d'avant juillet 2021 ecrit « Logement » : choisir « maison »
    ne doit pas faire disparaitre le DPE de 2019 que cite l'annonce."""
    from app.metier import identification

    inserer_dpe(n_dpe="ANCIEN", type_batiment="Logement", jeu_de_donnees="ancien",
                surface_habitable=120.0, code_insee="40184")
    inserer_dpe(n_dpe="APPART", type_batiment="appartement", surface_habitable=120.0,
                code_insee="40184")
    trouves = {c["n_dpe"] for c in identification._candidats(
        {"code_insee": "40184", "type_batiment": "maison"})}
    assert trouves == {"ANCIEN"}


# ---------------------------------------------------------------------
#  Un critere que la base ne renseigne pas
# ---------------------------------------------------------------------

def test_un_diagnostic_vierge_ne_passe_pas_devant_le_bon_candidat(base):
    """
    Mesure sur Mimizan, annonce du 18 rue des Ecoles : 125 m², 511 kWh,
    19 kg. Un diagnostic de 2015, vierge de toute consommation mais de
    125 m² tout rond, sortait PREMIER avec un ecart de zero — devant le
    seul logement qui collait aux trois chiffres.
    """
    inserer_dpe(n_dpe="LE_BON", adresse="18 Rue des Ecoles", surface_habitable=122.2,
                conso_ep_m2=511.0, ges_m2=19.0)
    inserer_dpe(n_dpe="VIERGE", adresse="15 Avenue de la Gare", surface_habitable=125.0,
                conso_ep_m2=None, conso_ef_m2=None, ges_m2=None)
    inserer_dpe(n_dpe="AILLEURS", adresse="3 Rue Lointaine", surface_habitable=125.0,
                conso_ep_m2=180.0, ges_m2=40.0)

    resultat = identification.identifier({"surface": 125, "conso_ep": 511, "ges": 19},
                                         tolerances=TOLERANCES)

    ordre = [ligne["n_dpe"] for ligne in resultat["resultats"]]
    assert ordre == ["LE_BON", "VIERGE", "AILLEURS"]
    par_numero = {ligne["n_dpe"]: ligne for ligne in resultat["resultats"]}
    # Un critere absent vaut une tolerance : (0 + 1 + 1) / 3.
    assert par_numero["VIERGE"]["ecart_moyen"] == pytest.approx(0.667, abs=0.001)
    assert par_numero["VIERGE"]["ecarts"]["conso_ep"] is None      # et reste dit absent
    assert par_numero["LE_BON"]["ecart_moyen"] < 0.5


def test_un_critere_absent_ne_change_rien_quand_tout_est_renseigne(quartier):
    resultat = identification.identifier(ANNONCE, tolerances=TOLERANCES)
    cible = resultat["resultats"][0]
    attendu = sum(cible["ecarts"][cle] for cle in ("surface", "conso_ep", "conso_ef", "ges")) / 4
    assert cible["ecart_moyen"] == pytest.approx(attendu, abs=0.001)


# ---------------------------------------------------------------------
#  Les saisies qui n'en sont pas
# ---------------------------------------------------------------------

def test_un_chiffre_illisible_est_refuse_et_nomme(quartier):
    """« 1O » pour 10 : le critere disparaissait sans rien dire."""
    with pytest.raises(ValueError, match="(?i)émissions GES.*1O"):
        identification.identifier({"conso_ep": 216, "ges": "1O"}, tolerances=TOLERANCES)


def test_un_champ_vide_reste_ignore(quartier):
    resultat = identification.identifier({"conso_ep": 216, "ges": "", "surface": None},
                                         tolerances=TOLERANCES)
    assert [e["critere"] for e in resultat["entonnoir"]] == ["conso_ep"]
    assert resultat["criteres"] == {"conso_ep": 216.0}


def test_la_virgule_decimale_est_comprise(quartier):
    resultat = identification.identifier({"conso_ep": "215,2"}, tolerances=TOLERANCES)
    assert resultat["resultats"][0]["n_dpe"] == "CIBLE"


@pytest.mark.parametrize("tolerance", [0, -3, "abc"])
def test_une_tolerance_nulle_ou_negative_est_refusee(quartier, tolerance):
    """Negative, elle rendait tous les ecarts negatifs — et tout le monde conforme."""
    with pytest.raises(ValueError, match="tolérance sur la surface"):
        identification.identifier({"surface": 144}, tolerances={"surface": tolerance})


def test_une_tolerance_laissee_vide_reprend_celle_des_reglages(quartier):
    resultat = identification.identifier({"surface": 144}, tolerances={"surface": None, "conso": ""})
    assert resultat["tolerances"]["surface"] == 3.0


@pytest.mark.parametrize("corps", [
    {"criteres": "x"}, {"criteres": {"surface": 100}, "tolerances": "x"},
    {"criteres": {"surface": 100}, "filtres": [1]}, {"criteres": {"surface": float("inf")}},
    {"criteres": {"surface": 100}, "combien": -1}, {"criteres": {"surface": 100}, "combien": "dix"},
    {"criteres": {"surface": True}},
])
def test_une_demande_mal_formee_repond_400_pas_500(quartier, corps):
    import json

    from fastapi.testclient import TestClient

    from app.main import application
    with TestClient(application) as client:
        reponse = client.post("/api/identification", content=json.dumps(corps),
                              headers={"Content-Type": "application/json"})
    assert reponse.status_code == 400, reponse.text
    assert reponse.json()["detail"]
