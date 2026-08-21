# -*- coding: utf-8 -*-
"""
test_mutations.py — L'historique des ventes (DVF).

Le defaut a ne jamais laisser passer est arithmetique : le fichier source
repete `valeur_fonciere` sur chaque ligne d'une meme vente. Additionner ces
lignes multiplie le prix. Sur Mimizan, 1 118 mutations sur 2 054 tiennent
sur plusieurs lignes — le cas est majoritaire, pas marginal.
"""

import pytest

from app.base.connexion import connexion, transaction
from app.metier import mutations
from app.sources import dvf
from app.sources.client_http import ErreurSource
from tests.conftest import inserer_dpe


def _ligne(id_mutation, parcelle, valeur, **champs):
    """Une ligne du CSV DVF, les champs non precises etant vides."""
    ligne = {
        "id_mutation": id_mutation, "date_mutation": "2024-11-04",
        "nature_mutation": "Vente", "valeur_fonciere": str(valeur),
        "code_commune": "40184", "id_parcelle": parcelle,
        "type_local": "", "surface_reelle_bati": "", "surface_terrain": "",
    }
    ligne.update(champs)
    return ligne


def _parcelle(identifiant, code_insee="40184"):
    with transaction() as conn:
        conn.execute(
            "INSERT INTO parcelle (id, code_insee, section, numero, contenance_m2,"
            "  emprise_batie_m2, nb_batiments, latitude, longitude, importe_le)"
            " VALUES (?,?,'AA','001',800,120,1,44.2,-1.2,'2026-08-20T10:00:00')",
            (identifiant, code_insee))


def test_une_vente_sur_plusieurs_lignes_garde_son_prix(base, monkeypatch):
    """
    Le coeur du sujet. Une vente a 400 000 EUR etalee sur quatre lignes —
    trois parcelles, deux locaux — doit rester a 400 000, pas monter a
    1 600 000.
    """
    lignes = [
        _ligne("M1", "40184000AA0265", 400000, surface_terrain="10"),
        _ligne("M1", "40184000AA0266", 400000, type_local="Maison",
               surface_reelle_bati="80", surface_terrain="296"),
        _ligne("M1", "40184000AA0266", 400000, type_local="Dépendance",
               surface_reelle_bati="30", surface_terrain="296"),
        _ligne("M1", "40184000AA0267", 400000, type_local="Dépendance",
               surface_reelle_bati="124", surface_terrain="153"),
    ]
    monkeypatch.setattr("app.sources.dvf.telecharger",
                        lambda code, progression=None: lignes)
    _parcelle("40184000AA0266")

    resume = mutations.importer("40184")
    assert resume["mutations"] == 1
    assert resume["lignes"] == 4

    ventes = mutations.pour_parcelle("40184000AA0266")
    assert len(ventes) == 1
    vente = ventes[0]
    assert vente["valeur_fonciere"] == 400000        # et non 1 600 000
    assert vente["nb_parcelles"] == 3
    assert vente["nb_locaux"] == 3
    # Les surfaces bâties, elles, s'additionnent : chaque local est distinct.
    assert vente["surface_bati_m2"] == 234
    # Le terrain se compte par parcelle : 296 ne doit pas etre compte deux fois.
    assert vente["surface_terrain_m2"] == 459


def test_le_prix_au_m2_se_tait_quand_il_serait_faux(base, monkeypatch):
    """
    Rapporter le prix d'une maison, d'un garage et d'un terrain a la seule
    surface batie donnerait un chiffre faux — et flatteur.
    """
    lignes = [
        _ligne("M1", "40184000AA0266", 400000, type_local="Maison",
               surface_reelle_bati="80"),
        _ligne("M1", "40184000AA0266", 400000, type_local="Dépendance",
               surface_reelle_bati="30"),
    ]
    monkeypatch.setattr("app.sources.dvf.telecharger",
                        lambda code, progression=None: lignes)
    _parcelle("40184000AA0266")
    mutations.importer("40184")

    vente = mutations.pour_parcelle("40184000AA0266")[0]
    assert vente["prix_m2"] is None
    assert vente["prix_m2_incertain"] is True


def test_le_prix_au_m2_s_affiche_quand_il_est_juste(base, monkeypatch):
    """Une maison seule, sur une parcelle seule : la division a un sens."""
    lignes = [_ligne("M1", "40184000AT0148", 261030, type_local="Maison",
                     surface_reelle_bati="62", surface_terrain="314")]
    monkeypatch.setattr("app.sources.dvf.telecharger",
                        lambda code, progression=None: lignes)
    _parcelle("40184000AT0148")
    mutations.importer("40184")

    vente = mutations.pour_parcelle("40184000AT0148")[0]
    assert vente["prix_m2"] == 4210            # 261030 / 62
    assert vente["prix_m2_incertain"] is False


def test_les_ventes_se_retrouvent_depuis_un_dpe(base, monkeypatch):
    """Le rattachement passe par la parcelle, jamais par l'adresse."""
    lignes = [_ligne("M1", "40184000AT0148", 261030, type_local="Maison",
                     surface_reelle_bati="62")]
    monkeypatch.setattr("app.sources.dvf.telecharger",
                        lambda code, progression=None: lignes)
    _parcelle("40184000AT0148")
    mutations.importer("40184")

    inserer_dpe(n_dpe="D1", adresse="53 Chemin des Roseaux")
    with transaction() as conn:
        conn.execute("UPDATE dpe SET parcelle_id = '40184000AT0148'"
                     " WHERE n_dpe = 'D1'")

    ventes = mutations.pour_dpe("D1")
    assert len(ventes) == 1
    assert ventes[0]["valeur_fonciere"] == 261030
    # Un DPE sans parcelle ne doit pas faire tomber la fiche.
    inserer_dpe(n_dpe="D2", adresse="ailleurs")
    assert mutations.pour_dpe("D2") == []
    assert mutations.pour_dpe("INEXISTANT") == []


def test_le_reimport_remplace_sans_doubler(base, monkeypatch):
    """DVF republie la commune entiere et corrige parfois le passe."""
    lignes = [_ligne("M1", "40184000AT0148", 261030, type_local="Maison",
                     surface_reelle_bati="62")]
    monkeypatch.setattr("app.sources.dvf.telecharger",
                        lambda code, progression=None: lignes)
    _parcelle("40184000AT0148")

    mutations.importer("40184")
    mutations.importer("40184")

    assert len(mutations.pour_parcelle("40184000AT0148")) == 1
    with connexion() as conn:
        assert conn.execute("SELECT count(*) FROM mutation").fetchone()[0] == 1
        assert conn.execute(
            "SELECT count(*) FROM mutation_parcelle").fetchone()[0] == 1


def test_une_ligne_sans_parcelle_est_ecartee(base, monkeypatch):
    """Sans parcelle, la vente ne pourrait se rattacher a rien."""
    lignes = [_ligne("M1", "", 100000, type_local="Maison")]
    monkeypatch.setattr("app.sources.dvf.telecharger",
                        lambda code, progression=None: lignes)
    assert mutations.importer("40184")["mutations"] == 0


def test_les_communes_sans_dvf_sont_annoncees():
    """L'Alsace-Moselle tient son propre livre foncier."""
    for code in ("57123", "67482", "68066", "97601"):
        assert dvf.indisponible(code)
    for code in ("40184", "31282", "2A004", "97411"):
        assert dvf.indisponible(code) is None

    with pytest.raises(ErreurSource, match="livre foncier"):
        dvf.telecharger("67482")


def test_l_url_suit_le_departement():
    assert dvf.url_annee("40184", 2024).endswith("/2024/communes/40/40184.csv")
    assert dvf.url_annee("97411", 2024).endswith("/2024/communes/974/97411.csv")


def test_une_commune_sans_ventes_est_signalee(base):
    """Comme pour le bati : une base montee avant DVF resterait muette."""
    assert mutations.manquantes("40184") is False      # pas de cadastre non plus
    _parcelle("40184000AT0148")
    assert mutations.manquantes("40184") is True
