# -*- coding: utf-8 -*-
"""
planificateur.py — L'import quotidien automatique et les alertes (CDC 8).

APScheduler tourne dans un thread du meme processus : pas de second
conteneur, pas de cron systeme a configurer sur le NAS.

Le fuseau est explicite. Sans lui, la tache se declencherait en UTC, soit
deux heures plus tot en ete — d'ou le TZ=Europe/Paris du compose.
"""

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app import config
from app.base import sauvegarde
from app.metier import alerte_ventes, alertes, import_dpe, mutations

logger = logging.getLogger(__name__)

_planificateur = None
IDENTIFIANT = "import-quotidien"


def _tache():
    """Lance l'import, puis l'alerte. Avale les erreurs : elles sont deja
    tracees au journal, et un planificateur qui leve s'arrete."""
    logger.info("import quotidien declenche")
    try:
        import_dpe.importer(declencheur="planifie")
    except Exception as erreur:                     # noqa: BLE001
        # L'import a echoue : rien de neuf n'est entre en base, donc rien a
        # signaler. On ne tente pas l'alerte, qui n'aurait rien a dire.
        logger.error("import quotidien en echec : %s", erreur)
        return

    # L'alerte suit l'import (CDC 8). Elle ne leve pas, mais on protege
    # quand meme : une moisson reussie ne doit jamais etre annulee par un
    # serveur de courriel injoignable.
    try:
        resultat = alertes.envoyer_si_besoin()
        if resultat["envoye"]:
            logger.info("alerte envoyee : %d bien(s)", resultat["biens"])
        else:
            logger.info("pas d'alerte (%s)", resultat["raison"])
    except Exception as erreur:                     # noqa: BLE001
        logger.error("alerte en echec : %s", erreur)

    _ventes()
    _sauvegarder()


def _sauvegarder():
    """
    Une copie datee, apres l'import.

    Apres et non avant : c'est l'etat le plus recent qu'on veut pouvoir
    retrouver. Elle ne leve jamais — un disque plein ne doit pas faire
    echouer une moisson reussie — et une copie qui ne se verifie pas ne
    remplace rien.
    """
    try:
        resultat = sauvegarde.sauvegarder()
        if resultat["faite"]:
            logger.info("sauvegarde %s (%.1f Mo)",
                        resultat["fichier"], resultat["octets"] / 1e6)
        else:
            logger.error("sauvegarde non faite : %s", resultat["raison"])
    except Exception as erreur:                     # noqa: BLE001
        logger.error("sauvegarde en echec : %s", erreur)


def _ventes():
    """
    Guette la publication DVF, et n'importe que si elle a bouge.

    DVF parait deux fois l'an. Le controle quotidien est une requete HEAD
    par millesime — quelques centaines d'octets — et l'import complet, lui,
    ne part qu'aux deux ou trois jours de l'annee ou il a quelque chose a
    apprendre. Guetter la donnee plutot que sa publication couterait un
    megaoctet par jour pour le meme resultat.
    """
    code_insee = alertes.commune_surveillee()
    if not code_insee:
        logger.info("pas de commune surveillee : ventes non guettees")
        return
    try:
        etat = mutations.publication(code_insee)
    except Exception as erreur:                     # noqa: BLE001
        logger.error("publication DVF injoignable : %s", erreur)
        return

    if etat["premier_releve"]:
        # Rien a comparer : on vient d'apprendre les signatures. Un import
        # ici ne ferait que relire ce que la base contient deja.
        logger.info("dvf %s : signatures relevees pour la premiere fois",
                    code_insee)
        return
    if not etat["changees"]:
        logger.debug("dvf %s : rien de neuf", code_insee)
        return

    logger.info("dvf %s : millesime(s) republie(s) %s",
                code_insee, etat["changees"])
    try:
        mutations.importer(code_insee)
    except Exception as erreur:                     # noqa: BLE001
        logger.error("import DVF en echec : %s", erreur)
        return

    try:
        resultat = alerte_ventes.envoyer_si_besoin()
        if resultat["envoye"]:
            logger.info("alerte ventes envoyee : %d vente(s)", resultat["ventes"])
        else:
            logger.info("pas d'alerte ventes (%s)", resultat["raison"])
    except Exception as erreur:                     # noqa: BLE001
        logger.error("alerte ventes en echec : %s", erreur)


def demarrer():
    """Demarre le planificateur. Sans effet si VEILLE_PLANIFICATEUR=0."""
    global _planificateur

    if not config.PLANIFICATEUR_ACTIF:
        logger.info("planificateur desactive")
        return None
    if _planificateur is not None:
        return _planificateur

    _planificateur = BackgroundScheduler(timezone=config.FUSEAU)
    _planificateur.add_job(
        _tache,
        CronTrigger(day_of_week=config.IMPORT_JOUR, hour=config.IMPORT_HEURE,
                    minute=0, timezone=config.FUSEAU),
        id=IDENTIFIANT,
        name="Import quotidien, alertes, guet des ventes, sauvegarde",
        # Si le NAS etait eteint a l'heure prevue, on rattrape au demarrage
        # dans l'heure qui suit, mais on ne cumule pas les executions ratees.
        coalesce=True,
        misfire_grace_time=3600,
        max_instances=1,
    )
    _planificateur.start()
    logger.info("import quotidien planifie : %s %dh00 (%s)",
                config.IMPORT_JOUR, config.IMPORT_HEURE, config.FUSEAU)
    return _planificateur


def arreter():
    global _planificateur
    if _planificateur is not None:
        _planificateur.shutdown(wait=False)
        _planificateur = None


def prochaine_execution():
    """Date de la prochaine execution, en texte, pour l'ecran Reglages."""
    if _planificateur is None:
        return None
    tache = _planificateur.get_job(IDENTIFIANT)
    if tache is None or tache.next_run_time is None:
        return None
    return tache.next_run_time.isoformat(timespec="seconds")
