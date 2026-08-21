# -*- coding: utf-8 -*-
"""
conftest.py — Preparation commune aux tests.

La variable d'environnement est posee AVANT tout import de l'application :
app/config.py la lit au moment de son chargement. Chaque test travaille
ainsi sur une base jetable, jamais sur /data/veille.db.
"""

import os
import pathlib
import tempfile

DOSSIER = tempfile.mkdtemp(prefix="veille-tests-")
os.environ["VEILLE_BASE"] = str(pathlib.Path(DOSSIER) / "veille.db")
os.environ["VEILLE_PLANIFICATEUR"] = "0"

import pytest                                    # noqa: E402

from app.base import migrations                  # noqa: E402
from app.base.connexion import connexion, transaction  # noqa: E402


# Toutes les tables que l'application remplit. Une table oubliee ici fuit
# d'un test a l'autre : les mutations d'un test se retrouvaient dans le
# suivant, qui echouait sur une contrainte d'unicite.
TABLES = ("dpe", "parcelle", "batiment", "mutation", "mutation_parcelle",
          "commune", "reglage", "journal_import")


def _vider(conn):
    for table in TABLES:
        conn.execute(f"DELETE FROM {table}")


@pytest.fixture()
def base():
    """Une base vide, migree, pour chaque test."""
    migrations.appliquer()
    with transaction() as conn:
        _vider(conn)
    yield
    with transaction() as conn:
        _vider(conn)


def inserer_dpe(**champs):
    """Insere un DPE de test, les champs non precises prenant des valeurs sures."""
    ligne = {
        "n_dpe": "DPE-1", "adresse": "1 rue de l'Essai", "commune": "Mimizan",
        "code_postal": "40200", "date_etablissement": "2026-08-01",
        "surface_habitable": 120.0, "type_batiment": "maison",
        "etiquette_dpe": "D", "zone": "bourg", "jeu_de_donnees": "existant",
        "importe_le": "2026-08-01T10:00:00", "vu_le": None,
        "latitude": 44.2011, "longitude": -1.2286,
    }
    ligne.update(champs)
    colonnes = ", ".join(ligne)
    valeurs = ", ".join("?" * len(ligne))
    with transaction() as conn:
        conn.execute(f"INSERT INTO dpe ({colonnes}) VALUES ({valeurs})", list(ligne.values()))
    return ligne
