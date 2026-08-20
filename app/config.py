# -*- coding: utf-8 -*-
"""
config.py — Reglages techniques de l'application.

Tout ce qui depend de la machine (chemins, port, fuseau) se lit dans des
variables d'environnement, jamais en dur dans le code : c'est ce qui permet
a la meme image Docker de tourner sur le NAS et sur un poste de dev.

Les reglages METIER (communes surveillees, tolerances, points de reference)
ne sont pas ici : ils vivent en base, table `reglage`, et se modifient depuis
l'ecran Reglages sans reconstruire l'image.
"""

import os
import pathlib

# --- Base de donnees -------------------------------------------------
# Sur le NAS, /data est un volume monte : la base survit aux mises a jour
# de l'image. Sans ce volume, tout serait perdu a chaque redeploiement.
CHEMIN_BASE = pathlib.Path(os.environ.get("VEILLE_BASE", "/data/veille.db"))

# --- Serveur ---------------------------------------------------------
HOTE = os.environ.get("VEILLE_HOTE", "0.0.0.0")
PORT = int(os.environ.get("VEILLE_PORT", "8000"))

# --- Journalisation --------------------------------------------------
NIVEAU_LOG = os.environ.get("VEILLE_LOG", "INFO").upper()

# --- Planificateur ---------------------------------------------------
# Import quotidien : l'alerte F6 le suit, et l'ADEME publie 79 % des DPE le
# jour meme de leur reception. Attendre la semaine perdrait cette fraicheur.
# Le fuseau vient de TZ (Europe/Paris dans le compose) : sans lui,
# APScheduler declencherait les taches en UTC.
FUSEAU = os.environ.get("TZ", "Europe/Paris")
IMPORT_JOUR = os.environ.get("VEILLE_IMPORT_JOUR", "*")     # tous les jours
IMPORT_HEURE = int(os.environ.get("VEILLE_IMPORT_HEURE", "7"))
PLANIFICATEUR_ACTIF = os.environ.get("VEILLE_PLANIFICATEUR", "1") != "0"

# --- Courriel d'alerte (F6) ------------------------------------------
# Les identifiants SMTP sont les SEULS secrets de l'application. Ils vivent
# donc ici, en variables d'environnement — jamais en base, que l'ecran
# Reglages expose, ni dans le depot, qui est public. Le fichier .env qui les
# porte sur le NAS est ignore par git.
#
# Sans hote configure, l'alerte se desactive d'elle-meme : l'application
# reste utilisable sans courriel, et le dira plutot que d'echouer.
SMTP_HOTE = os.environ.get("VEILLE_SMTP_HOTE", "").strip()
SMTP_PORT = int(os.environ.get("VEILLE_SMTP_PORT", "587"))
SMTP_UTILISATEUR = os.environ.get("VEILLE_SMTP_UTILISATEUR", "").strip()
SMTP_MOTDEPASSE = os.environ.get("VEILLE_SMTP_MOTDEPASSE", "")
SMTP_EXPEDITEUR = os.environ.get("VEILLE_SMTP_EXPEDITEUR", "").strip()
# STARTTLS sur 587, SSL direct sur 465 : les deux se rencontrent.
SMTP_SSL = os.environ.get("VEILLE_SMTP_SSL", "0") == "1"

def smtp_configure():
    """Le minimum vital est-il present pour tenter un envoi ?"""
    return bool(SMTP_HOTE and SMTP_EXPEDITEUR)


# --- Identite du build (injectee par GitHub Actions) -----------------
VERSION = os.environ.get("BUILD_VERSION", "dev")
DATE_BUILD = os.environ.get("BUILD_DATE", "inconnue")

# --- Chemins internes ------------------------------------------------
RACINE = pathlib.Path(__file__).resolve().parent
DOSSIER_WEB = RACINE / "web"
