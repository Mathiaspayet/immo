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

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app import config, planificateur
from app.api import communes as api_communes
from app.api import estimation as api_estimation
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

# Ce qu'un autre site ne doit pas pouvoir declencher, meme en simple
# lecture : la vue de rue se facture a chaque cliche, sur la cle de
# l'utilisateur.
LECTURES_PROTEGEES = {"/api/parcelles/vue-rue"}


@application.middleware("http")
async def refuser_les_autres_sites(requete: Request, suite):
    """
    Une page d'un AUTRE site, ouverte dans le meme navigateur, pouvait
    declencher les actions de l'application : l'API n'a pas
    d'authentification — elle vit sur le reseau local (CDC 9) — et une
    requete POST sans corps JSON part sans controle prealable du
    navigateur. Lancer une moisson, reprendre 34 Mo d'archive, faire une
    sauvegarde, ou faire facturer des cliches de rue.

    Les navigateurs disent d'ou vient une requete (`Sec-Fetch-Site`) : on
    refuse celles d'un autre site, sauf les simples lectures. Un lien
    suivi depuis ailleurs ouvre toujours l'application. Sans cet en-tete —
    curl, la sonde de sante, un tres vieux navigateur —, rien ne change.
    Le controle porte sur la vue du navigateur, pas sur l'adresse du
    serveur : il tient derriere un proxy inverse.
    """
    if (requete.headers.get("sec-fetch-site") == "cross-site"
            and (requete.method not in ("GET", "HEAD", "OPTIONS")
                 or requete.url.path in LECTURES_PROTEGEES)):
        logger.warning("requete d'un autre site refusee : %s %s",
                       requete.method, requete.url.path)
        return JSONResponse(status_code=403,
                            content={"detail": "Requête refusée : elle vient d'un autre site."})
    return await suite(requete)


application.include_router(api_veille.routeur)
application.include_router(api_communes.routeur)
application.include_router(api_imports.routeur)
application.include_router(api_identification.routeur)
application.include_router(api_fiche.routeur)
application.include_router(api_parcelles.routeur)
application.include_router(api_reglages.routeur)
application.include_router(api_alertes.routeur)
application.include_router(api_estimation.routeur)


@application.get("/api/sante", tags=["technique"])
def sante():
    """Sonde de sante : utilisee par Docker, et par l'interface au demarrage."""
    _jour, _heure = planificateur.horaire()
    return {
        "statut": "ok",
        "version": config.VERSION,
        "date_build": config.DATE_BUILD,
        "base": str(config.CHEMIN_BASE),
        "prochain_import": planificateur.prochaine_execution(),
        # Le rythme REEL, pas un libelle ecrit en dur. L'ecran annoncait
        # « hebdomadaire » quelle que soit la configuration : juste par
        # hasard sur un deploiement hebdomadaire, faux sur tous les autres.
        # Et c'est precisement la ligne qu'on vient lire pour savoir
        # pourquoi aucun courriel n'est arrive.
        # Lus dans les REGLAGES, pas dans l'environnement : c'est la que
        # l'horaire se choisit desormais, et l'ecran doit montrer ce qui
        # s'applique vraiment.
        "import_jours": _jour,
        "import_heure": _heure,
        "import_fuseau": config.FUSEAU,
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
