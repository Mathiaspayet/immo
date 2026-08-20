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
