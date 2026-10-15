# -*- coding: utf-8 -*-
"""
migrations.py — Mise a jour du schema de la base.

Chaque evolution du schema est un fichier .sql numerote dans `schema/`.
Au demarrage, on applique ceux qui manquent, dans l'ordre, et on note leur
nom dans la table `migration`. Ajouter une table plus tard (le cadastre au
lot 3, le suivi au lot 4) se fera en deposant un `002_...sql` : rien a
executer a la main sur le NAS.

Les scripts utilisent tous CREATE ... IF NOT EXISTS : les rejouer par
accident ne casse rien.
"""

import datetime
import logging
import pathlib

from app.base.connexion import connexion

logger = logging.getLogger(__name__)

DOSSIER_SCHEMA = pathlib.Path(__file__).resolve().parent / "schema"


def appliquer():
    """Applique les migrations manquantes. Renvoie la liste de celles jouees."""
    with connexion() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS migration ("
            "  nom TEXT PRIMARY KEY,"
            "  applique_le TEXT NOT NULL)"
        )
        deja = {ligne["nom"] for ligne in conn.execute("SELECT nom FROM migration")}

        jouees = []
        for chemin in sorted(DOSSIER_SCHEMA.glob("*.sql")):
            if chemin.name in deja:
                continue
            logger.info("migration %s", chemin.name)
            _jouer(conn, chemin)
            jouees.append(chemin.name)

        if jouees:
            logger.info("%d migration(s) appliquee(s)", len(jouees))
        return jouees


def _jouer(conn, chemin):
    """
    Joue une migration et l'inscrit, EN UNE TRANSACTION.

    `CREATE ... IF NOT EXISTS` se rejoue sans dommage, `ALTER TABLE ... ADD
    COLUMN` non : SQLite ne connait pas de IF NOT EXISTS pour lui. Joues
    hors transaction, le script et son inscription pouvaient se separer —
    un conteneur arrete par Watchtower au milieu des cinq ALTER du 007, et
    chaque demarrage suivant echouait sur « duplicate column name » :
    l'application ne repartait plus. SQLite rend le DDL transactionnel ;
    tout passe donc, ou rien.
    """
    nom = chemin.name.replace("'", "''")
    quand = datetime.datetime.now().isoformat(timespec="seconds")
    try:
        conn.executescript(
            "BEGIN IMMEDIATE;\n" + chemin.read_text(encoding="utf-8")
            + f"\n;INSERT INTO migration (nom, applique_le) VALUES ('{nom}', '{quand}');"
            + "\nCOMMIT;")
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
