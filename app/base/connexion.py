# -*- coding: utf-8 -*-
"""
connexion.py — Ouverture de la base SQLite.

Pourquoi une connexion par operation plutot qu'une connexion partagee :
une connexion SQLite ne se promene pas entre threads sans precaution, et
l'application en a plusieurs (les requetes web, le planificateur, l'import
en tache de fond). Ouvrir puis fermer coute quelques microsecondes sur un
fichier local ; c'est le prix de la tranquillite.
"""

import logging
import sqlite3
from contextlib import contextmanager

from app import config

logger = logging.getLogger(__name__)


@contextmanager
def connexion():
    """Ouvre une connexion configuree, et la referme quoi qu'il arrive."""
    config.CHEMIN_BASE.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(config.CHEMIN_BASE), timeout=30.0)
    # isolation_level = None : on pilote les transactions nous-memes, sans
    # que le module python en ouvre une dans notre dos.
    conn.isolation_level = None
    # row_factory : les lignes se lisent par nom de colonne, pas par indice.
    conn.row_factory = sqlite3.Row

    # WAL : un lecteur ne bloque plus un ecrivain. L'import hebdomadaire peut
    # donc tourner pendant qu'on consulte l'ecran Veille.
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    # Si une autre connexion ecrit, on patiente au lieu d'echouer aussitot.
    conn.execute("PRAGMA busy_timeout = 30000")
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def transaction():
    """
    Ouvre une transaction : tout reussit, ou rien n'est ecrit.

    C'est l'exigence du CDC 8 — un import interrompu ne doit jamais laisser
    la base a moitie remplie. BEGIN IMMEDIATE prend le verrou d'ecriture tout
    de suite, ce qui evite d'echouer au milieu du travail.
    """
    with connexion() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except Exception:
            conn.execute("ROLLBACK")
            raise
        else:
            conn.execute("COMMIT")
