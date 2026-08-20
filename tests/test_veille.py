# -*- coding: utf-8 -*-
"""
Verification de l'ecran Veille : filtres, dedoublonnage, marquage.
"""

import datetime

import pytest

from app.base import reglages
from app.metier import veille
from tests.conftest import inserer_dpe


def jours(n):
    return (datetime.date.today() - datetime.timedelta(days=n)).isoformat()


FILTRES = {"fenetre_jours": 120, "surface_min": 80, "surface_max": 400,
           "type_batiment": "maison"}


def test_une_seule_ligne_par_adresse(base):
    """Une adresse peut porter plusieurs DPE : seul le plus recent compte."""
    inserer_dpe(n_dpe="A", adresse="12 rue des Pins", date_etablissement=jours(5))
    inserer_dpe(n_dpe="B", adresse="12 RUE DES PINS ", date_etablissement=jours(60))

    resultats = veille.lister(FILTRES)
    assert len(resultats) == 1
    assert resultats[0]["n_dpe"] == "A"


def test_les_adresses_absentes_ne_sont_pas_regroupees(base):
    """Sans adresse, deux DPE distincts doivent rester deux lignes."""
    inserer_dpe(n_dpe="A", adresse=None, date_etablissement=jours(5))
    inserer_dpe(n_dpe="B", adresse=None, date_etablissement=jours(6))
    assert len(veille.lister(FILTRES)) == 2


def test_fenetre_temporelle(base):
    inserer_dpe(n_dpe="recent", date_etablissement=jours(10))
    inserer_dpe(n_dpe="ancien", adresse="2 rue Ancienne", date_etablissement=jours(300))

    assert len(veille.lister(FILTRES)) == 1
    assert len(veille.lister({**FILTRES, "fenetre_jours": 365})) == 2


def test_bornes_de_surface(base):
    inserer_dpe(n_dpe="petite", adresse="a", surface_habitable=40.0, date_etablissement=jours(3))
    inserer_dpe(n_dpe="bonne", adresse="b", surface_habitable=120.0, date_etablissement=jours(3))
    inserer_dpe(n_dpe="grande", adresse="c", surface_habitable=900.0, date_etablissement=jours(3))

    retenus = {ligne["n_dpe"] for ligne in veille.lister(FILTRES)}
    assert retenus == {"bonne"}


def test_surface_absente_conservee(base):
    """
    Une surface manquante ne doit pas faire disparaitre un bien : ce serait
    l'ecarter sans que rien ne l'explique.
    """
    inserer_dpe(n_dpe="sans-surface", surface_habitable=None, date_etablissement=jours(3))
    assert len(veille.lister(FILTRES)) == 1


def test_filtre_par_secteur(base):
    inserer_dpe(n_dpe="A", adresse="a", zone="bourg", date_etablissement=jours(3))
    inserer_dpe(n_dpe="B", adresse="b", zone="plage", date_etablissement=jours(3))

    resultats = veille.lister({**FILTRES, "zone": "plage"})
    assert [ligne["n_dpe"] for ligne in resultats] == ["B"]


def test_filtre_par_etiquette(base):
    inserer_dpe(n_dpe="A", adresse="a", etiquette_dpe="A", date_etablissement=jours(3))
    inserer_dpe(n_dpe="G", adresse="g", etiquette_dpe="G", date_etablissement=jours(3))

    resultats = veille.lister({**FILTRES, "etiquettes": ["a"]})   # casse indifferente
    assert [ligne["n_dpe"] for ligne in resultats] == ["A"]


def test_marquage_des_nouveautes(base):
    inserer_dpe(n_dpe="A", adresse="a", date_etablissement=jours(3))
    inserer_dpe(n_dpe="B", adresse="b", date_etablissement=jours(4), vu_le="2026-01-01T00:00:00")

    assert veille.resume(FILTRES)["nouveaux"] == 1
    assert len(veille.lister({**FILTRES, "seulement_nouveaux": True})) == 1

    assert veille.marquer_vus(["A"]) == 1
    assert veille.resume(FILTRES)["nouveaux"] == 0
    # Deja marque : la seconde fois ne change rien.
    assert veille.marquer_vus(["A"]) == 0


def test_tri_du_plus_recent_au_plus_ancien(base):
    for n, age in [("vieux", 100), ("recent", 2), ("moyen", 40)]:
        inserer_dpe(n_dpe=n, adresse=n, date_etablissement=jours(age))
    assert [l["n_dpe"] for l in veille.lister(FILTRES)] == ["recent", "moyen", "vieux"]


def test_anciennete_calculee(base):
    inserer_dpe(date_etablissement=jours(13))
    assert veille.lister(FILTRES)[0]["anciennete_jours"] == 13


def test_export_csv(base):
    inserer_dpe(adresse="1 rue de l'Essai", date_etablissement=jours(3))
    contenu = veille.exporter_csv(FILTRES)

    assert contenu.startswith("﻿")          # BOM attendu par Excel
    lignes = contenu.splitlines()
    assert lignes[0].count(";") > 10             # separateur point-virgule
    assert "1 rue de l'Essai" in lignes[1]


def test_resume_par_secteur(base):
    inserer_dpe(n_dpe="A", adresse="a", zone="bourg", date_etablissement=jours(3))
    inserer_dpe(n_dpe="B", adresse="b", zone="plage", date_etablissement=jours(3))
    inserer_dpe(n_dpe="C", adresse="c", zone=None, date_etablissement=jours(3))

    resume = veille.resume(FILTRES)
    assert resume["par_zone"] == {"bourg": 1, "plage": 1, "hors secteur": 1}
    assert resume["total"] == 3


# ---------------------------------------------------------------------
#  Reglages
# ---------------------------------------------------------------------

def test_reglages_par_defaut(base):
    valeurs = reglages.tous()
    assert valeurs["communes"][0]["code_postal"] == "40200"
    assert set(valeurs["zones"]) == {"bourg", "plage"}


def test_reglage_enregistre_et_relu(base):
    reglages.ecrire({"fenetre_jours": 45})
    assert reglages.lire("fenetre_jours") == 45


@pytest.mark.parametrize("valeurs, extrait", [
    ({"surface_min": 500, "surface_max": 100}, "depasse"),
    ({"communes": []}, "au moins une commune"),
    ({"communes": [{"code_postal": "abc"}]}, "Code postal invalide"),
    ({"zones": {"plage": [200, 0]}}, "hors des bornes"),
    ({"zones": {"plage": ["nord"]}}, "latitude et longitude"),
    ({"fenetre_jours": 0}, "compris entre"),
    ({"type_batiment": "chateau"}, "maison"),
    ({"inconnu": 1}, "inconnu"),
])
def test_reglages_refuses(base, valeurs, extrait):
    """Un reglage aberrant doit etre refuse avec un message comprehensible."""
    with pytest.raises(ValueError) as erreur:
        reglages.ecrire(valeurs)
    assert extrait in str(erreur.value)


def test_marquage_avec_liste_vide_ne_marque_rien(base):
    """
    Une selection vide ne doit pas etre confondue avec « tout marquer » :
    l'utilisateur perdrait tous ses badges d'un coup.
    """
    inserer_dpe(n_dpe="A", adresse="a", date_etablissement=jours(3))
    assert veille.marquer_vus([]) == 0
    assert veille.resume(FILTRES)["nouveaux"] == 1

    assert veille.marquer_vus(None) == 1
    assert veille.resume(FILTRES)["nouveaux"] == 0


# ---------------------------------------------------------------------
#  Communes : plusieurs, et identifiees par leur code INSEE
# ---------------------------------------------------------------------

def test_le_cache_couvre_plusieurs_communes(base):
    """
    Un code postal couvre souvent plusieurs communes : le 40200 en compte
    cinq. L'application doit toutes les proposer, pas seulement la premiere.
    """
    inserer_dpe(n_dpe="M1", adresse="1 rue A", commune="Mimizan", code_insee="40184")
    inserer_dpe(n_dpe="M2", adresse="2 rue A", commune="Mimizan", code_insee="40184")
    inserer_dpe(n_dpe="A1", adresse="3 rue B", commune="Aureilhan", code_insee="40019")

    communes = veille.communes_en_cache()
    assert [c["nom"] for c in communes] == ["Mimizan", "Aureilhan"]   # tri par volume
    assert [c["dpe"] for c in communes] == [2, 1]


def test_les_variantes_d_ecriture_sont_regroupees(base):
    """
    L'ADEME ecrit « Sainte-Eulalie-en-Born », « STE EULALIE EN BORN » ou
    « SAINTE-EULALIE-EN-BORN » selon les lignes. Aucun LIKE ne les rattrape
    toutes ; le code INSEE, lui, est le meme.
    """
    for numero, ecriture in [("A", "Sainte-Eulalie-en-Born"),
                             ("B", "STE EULALIE EN BORN"),
                             ("C", "SAINTE-EULALIE-EN-BORN")]:
        inserer_dpe(n_dpe=numero, adresse=f"{numero} rue", commune=ecriture,
                    code_insee="40257")

    communes = veille.communes_en_cache()
    assert len(communes) == 1
    assert communes[0]["dpe"] == 3
    assert len(communes[0]["variantes"]) == 3


def test_le_nom_officiel_prime_sur_celui_de_l_ademe(base):
    from app.base.connexion import transaction
    with transaction() as conn:
        conn.execute("INSERT INTO commune (code_insee, nom, code_postal) "
                     "VALUES ('40257', 'Sainte-Eulalie-en-Born', '40200')")
    inserer_dpe(n_dpe="A", adresse="1 rue", commune="STE EULALIE EN BORN",
                code_insee="40257")
    assert veille.communes_en_cache()[0]["nom"] == "Sainte-Eulalie-en-Born"


def test_filtre_par_code_insee_insensible_aux_variantes(base):
    inserer_dpe(n_dpe="A", adresse="1 rue", commune="STE EULALIE EN BORN",
                code_insee="40257", date_etablissement="2026-08-01")
    inserer_dpe(n_dpe="B", adresse="2 rue", commune="Sainte-Eulalie-en-Born",
                code_insee="40257", date_etablissement="2026-08-01")
    inserer_dpe(n_dpe="C", adresse="3 rue", commune="Mimizan",
                code_insee="40184", date_etablissement="2026-08-01")

    filtres = {**FILTRES, "code_insee": "40257"}
    assert {l["n_dpe"] for l in veille.lister(filtres)} == {"A", "B"}

    # Le nom seul en aurait manque une.
    par_nom = {**FILTRES, "commune": "Sainte-Eulalie-en-Born"}
    assert {l["n_dpe"] for l in veille.lister(par_nom)} == {"B"}


def test_le_code_insee_prime_sur_le_nom(base):
    inserer_dpe(n_dpe="A", adresse="1 rue", commune="Mimizan", code_insee="40184",
                date_etablissement="2026-08-01")
    filtres = {**FILTRES, "code_insee": "40184", "commune": "Aureilhan"}
    assert [l["n_dpe"] for l in veille.lister(filtres)] == ["A"]


def test_les_secteurs_ne_debordent_pas_sur_les_communes_voisines(base):
    """
    Le decoupage bourg / plage est interne a Mimizan. Sans restriction, un
    logement d'Aureilhan se verrait etiqueter « bourg » parce que c'est le
    repere le plus proche — a 2 km. Aucun seuil de distance ne separe
    proprement les deux, seule la commune le fait.
    """
    from app.metier.import_dpe import transformer

    correspondances = {"numero_dpe": "n", "code_insee": "i", "latitude": "lat",
                       "longitude": "lon", "adresse": "a"}
    zones_points = {"bourg": [44.2011, -1.2286], "plage": [44.2044, -1.2914]}

    mimizan = transformer(
        {"n": "M", "i": "40184", "lat": 44.2015, "lon": -1.2280, "a": "1 rue"},
        correspondances, zones_points, "existant", "40200", None, "40184")
    assert mimizan["zone"] == "bourg"

    aureilhan = transformer(
        {"n": "A", "i": "40019", "lat": 44.2200, "lon": -1.2000, "a": "2 rue"},
        correspondances, zones_points, "existant", "40200", None, "40184")
    assert aureilhan["zone"] is None
    assert aureilhan["distance_zone_m"] is None

    # Reglage vide : les secteurs s'appliquent partout, comme avant.
    partout = transformer(
        {"n": "A", "i": "40019", "lat": 44.2200, "lon": -1.2000, "a": "2 rue"},
        correspondances, zones_points, "existant", "40200", None, "")
    assert partout["zone"] == "bourg"


def test_les_secteurs_disponibles_suivent_le_contenu(base):
    """
    En surveillant un autre territoire, plus aucun logement ne porte de
    secteur : le filtre correspondant n'a plus rien a filtrer et doit
    disparaitre de l'ecran.
    """
    assert veille.zones_en_cache() == []

    inserer_dpe(n_dpe="A", adresse="1 rue", zone="bourg")
    inserer_dpe(n_dpe="B", adresse="2 rue", zone="plage")
    inserer_dpe(n_dpe="C", adresse="3 rue", zone="bourg")
    assert veille.zones_en_cache() == ["bourg", "plage"]    # tri par volume

    inserer_dpe(n_dpe="D", adresse="4 rue", zone=None)
    assert veille.zones_en_cache() == ["bourg", "plage"]


@pytest.mark.parametrize("valeur, valide", [
    ("40184", True), ("31282", True), ("", True),      # vide = partout
    ("401", False), ("401845", False), ("40 18", False),
])
def test_reglage_commune_des_secteurs(base, valeur, valide):
    if valide:
        reglages.ecrire({"zones_code_insee": valeur})
        assert reglages.lire("zones_code_insee") == valeur
    else:
        with pytest.raises(ValueError, match="Code INSEE invalide"):
            reglages.ecrire({"zones_code_insee": valeur})
