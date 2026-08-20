# -*- coding: utf-8 -*-
"""
planificateur.py — L'import quotidien automatique et l'alerte (CDC 8).

APScheduler tourne dans un thread du meme processus : pas de second
conteneur, pas de cron systeme a configurer sur le NAS.

Le fuseau est explicite. Sans lui, la tache se declencherait en UTC, soit
deux heures plus tot en ete — d'ou le TZ=Europe/Paris du compose.
"""

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app import config
from app.metier import alertes, import_dpe

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
        name="Import quotidien des DPE, puis alerte",
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
