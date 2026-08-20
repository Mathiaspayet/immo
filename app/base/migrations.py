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
            conn.executescript(chemin.read_text(encoding="utf-8"))
            conn.execute(
                "INSERT INTO migration (nom, applique_le) VALUES (?, ?)",
                (chemin.name, datetime.datetime.now().isoformat(timespec="seconds")),
            )
            jouees.append(chemin.name)

        if jouees:
            logger.info("%d migration(s) appliquee(s)", len(jouees))
        return jouees
