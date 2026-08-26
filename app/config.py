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


def _reglage(nom, defaut):
    """
    Une variable d'environnement, en traitant le VIDE comme absent.

    Ce n'est pas une coquetterie. Le compose declarait chaque variable avec
    son propre defaut — `${VEILLE_IMPORT_JOUR:-*}` — qui DUPLIQUAIT celui
    du code. Docker substitue a la creation du conteneur, ce qui grave la
    valeur dedans ; Watchtower, lui, remplace l'image mais conserve
    l'environnement existant. Un defaut du compose survit donc a toutes les
    mises a jour, et se met a diverger du code des qu'on le change.

    Cas vecu : le compose posait `mon` en aout, le code est passe a `*` le
    meme soir, et le conteneur deploye entre-temps est reste hebdomadaire
    pendant des semaines — l'ecran annoncant « chaque jour » d'apres le
    code, tandis que le planificateur suivait `mon` grave dans le conteneur.

    Le compose passe desormais une chaine VIDE quand l'utilisateur n'a rien
    choisi, et c'est le defaut ci-dessous qui tranche. Une seule source de
    verite, qui suit les mises a jour d'image.
    """
    return os.environ.get(nom) or defaut

# --- Base de donnees -------------------------------------------------
# Sur le NAS, /data est un volume monte : la base survit aux mises a jour
# de l'image. Sans ce volume, tout serait perdu a chaque redeploiement.
CHEMIN_BASE = pathlib.Path(_reglage("VEILLE_BASE", "/data/veille.db"))

# Ou vont les copies datees de la base. A cote d'elle par defaut, donc sur
# le meme volume : cela protege de l'effacement et de la corruption, pas de
# la panne du disque. Pour cela il faut que la sauvegarde du NAS (Hyper
# Backup) les voie — d'ou l'interet de pointer ceci vers un dossier partage
# monte dans le conteneur. Voir docker-compose.synology.yml.
CHEMIN_SAUVEGARDES = pathlib.Path(
    _reglage("VEILLE_SAUVEGARDES", str(CHEMIN_BASE.parent / "sauvegardes")))

# --- Serveur ---------------------------------------------------------
HOTE = _reglage("VEILLE_HOTE", "0.0.0.0")
PORT = int(_reglage("VEILLE_PORT", "8000"))

# --- Journalisation --------------------------------------------------
NIVEAU_LOG = _reglage("VEILLE_LOG", "INFO").upper()

# --- Planificateur ---------------------------------------------------
# Import quotidien : l'alerte F6 le suit, et l'ADEME publie 79 % des DPE le
# jour meme de leur reception. Attendre la semaine perdrait cette fraicheur.
# Le fuseau vient de TZ (Europe/Paris dans le compose) : sans lui,
# APScheduler declencherait les taches en UTC.
FUSEAU = _reglage("TZ", "Europe/Paris")
IMPORT_JOUR = _reglage("VEILLE_IMPORT_JOUR", "*")     # tous les jours
IMPORT_HEURE = int(_reglage("VEILLE_IMPORT_HEURE", "7"))
PLANIFICATEUR_ACTIF = _reglage("VEILLE_PLANIFICATEUR", "1") != "0"

# --- Identite du build (injectee par GitHub Actions) -----------------
VERSION = os.environ.get("BUILD_VERSION", "dev")
DATE_BUILD = os.environ.get("BUILD_DATE", "inconnue")

# --- Chemins internes ------------------------------------------------
RACINE = pathlib.Path(__file__).resolve().parent
DOSSIER_WEB = RACINE / "web"
