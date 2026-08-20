# -*- coding: utf-8 -*-
"""
planificateur.py — L'import hebdomadaire automatique (CDC 8).

APScheduler tourne dans un thread du meme processus : pas de second
conteneur, pas de cron systeme a configurer sur le NAS.

Le fuseau est explicite. Sans lui, la tache se declencherait en UTC, soit
deux heures plus tot en ete — d'ou le TZ=Europe/Paris du compose.
"""

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app import config
from app.metier import import_dpe

logger = logging.getLogger(__name__)

_planificateur = None
IDENTIFIANT = "import-hebdomadaire"


def _tache():
    """Lance l'import et avale l'erreur : elle est deja tracee au journal."""
    logger.info("import hebdomadaire declenche")
    try:
        import_dpe.importer(declencheur="planifie")
    except Exception as erreur:                     # noqa: BLE001
        logger.error("import hebdomadaire en echec : %s", erreur)


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
        name="Import hebdomadaire des DPE",
        # Si le NAS etait eteint a l'heure prevue, on rattrape au demarrage
        # dans l'heure qui suit, mais on ne cumule pas les executions ratees.
        coalesce=True,
        misfire_grace_time=3600,
        max_instances=1,
    )
    _planificateur.start()
    logger.info("import hebdomadaire planifie : %s %dh00 (%s)",
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
