# -*- coding: utf-8 -*-
"""
main.py — Assemblage de l'application.

Un seul conteneur, un seul processus : FastAPI sert a la fois l'API REST,
les fichiers de l'interface et le planificateur (CDC 3).

L'ordre de montage compte : les routes /api sont declarees avant les
fichiers statiques, sinon le montage sur « / » les capterait toutes.
"""

import logging

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import config, planificateur
from app.api import communes as api_communes
from app.api import alertes as api_alertes
from app.api import fiche as api_fiche
from app.api import identification as api_identification
from app.api import imports as api_imports
from app.api import parcelles as api_parcelles
from app.api import reglages as api_reglages
from app.api import veille as api_veille
from app.base import migrations

logging.basicConfig(
    level=getattr(logging, config.NIVEAU_LOG, logging.INFO),
    format="%(asctime)s  %(levelname)-7s %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def cycle_de_vie(application: FastAPI):
    """Ce qui se passe au demarrage et a l'arret du conteneur."""
    logger.info("veille immobiliere — version %s (%s)", config.VERSION, config.DATE_BUILD)
    logger.info("base de donnees : %s", config.CHEMIN_BASE)

    # Le schema se met a jour tout seul : rien a lancer a la main sur le NAS
    # apres une mise a jour de l'image par Watchtower.
    migrations.appliquer()
    planificateur.demarrer()
    try:
        yield
    finally:
        planificateur.arreter()
        logger.info("arret propre")


application = FastAPI(
    title="Veille immobiliere",
    description="Reperer les maisons susceptibles d'etre vendues, avant les annonces.",
    version=config.VERSION,
    lifespan=cycle_de_vie,
    # L'application n'est pas exposee publiquement (CDC 9), la documentation
    # interactive reste donc accessible : elle est utile pour deboguer.
    docs_url="/api/documentation",
    redoc_url=None,
)

application.include_router(api_veille.routeur)
application.include_router(api_communes.routeur)
application.include_router(api_imports.routeur)
application.include_router(api_identification.routeur)
application.include_router(api_fiche.routeur)
application.include_router(api_parcelles.routeur)
application.include_router(api_reglages.routeur)
application.include_router(api_alertes.routeur)


@application.get("/api/sante", tags=["technique"])
def sante():
    """Sonde de sante : utilisee par Docker, et par l'interface au demarrage."""
    return {
        "statut": "ok",
        "version": config.VERSION,
        "date_build": config.DATE_BUILD,
        "base": str(config.CHEMIN_BASE),
        "prochain_import": planificateur.prochaine_execution(),
    }


class StatiquesRevalidees(StaticFiles):
    """
    Les fichiers de l'interface, avec obligation de revalider.

    Starlette pose un ETag et un Last-Modified, mais aucun Cache-Control.
    Sans consigne, le navigateur applique sa propre heuristique et peut
    reutiliser un fichier SANS RIEN DEMANDER — c'est ainsi qu'apres une mise
    a jour par Watchtower, un index.html neuf s'est retrouve a cote d'un
    veille.js d'une version precedente : les champs existaient, le code qui
    les remplit non.

    « no-cache » ne veut pas dire « ne garde rien » : le navigateur garde le
    fichier, mais demande a chaque fois s'il a change. L'ETag rend la
    reponse vide (304) quand ce n'est pas le cas — le cout est une requete
    sans corps, sur un reseau local.

    Les fichiers portant une empreinte dans leur nom pourraient etre mis en
    cache pour un an ; aucun n'en porte ici, l'interface n'ayant pas d'etape
    de construction (CDC 3).
    """

    def file_response(self, *args, **kwargs):
        reponse = super().file_response(*args, **kwargs)
        reponse.headers["Cache-Control"] = "no-cache, must-revalidate"
        return reponse


# Monte en dernier : tout ce qui n'est pas /api est un fichier de l'interface.
application.mount(
    "/", StatiquesRevalidees(directory=str(config.DOSSIER_WEB), html=True), name="web")
