# -*- coding: utf-8 -*-
"""
api/veille.py — Endpoints de l'ecran Veille.

Cette couche ne fait que traduire des parametres HTTP en filtres et
renvoyer du JSON. Toute la logique est dans metier/veille.py, et aucune
de ces routes ne declenche d'appel externe (CDC 4).
"""

import datetime
import logging

from fastapi import APIRouter, Body, Query
from fastapi.responses import Response

from app.metier import veille

logger = logging.getLogger(__name__)

routeur = APIRouter(prefix="/api/veille", tags=["veille"])


def _filtres(fenetre_jours, commune, code_postal, zone, type_batiment,
             surface_min, surface_max, etiquettes, seulement_nouveaux):
    """Assemble les filtres, en completant par les valeurs des reglages."""
    defauts = veille.filtres_par_defaut()
    return {
        "fenetre_jours": defauts["fenetre_jours"] if fenetre_jours is None else fenetre_jours,
        "commune": defauts["commune"] if commune is None else commune,
        "code_postal": code_postal or "",
        "zone": zone or "",
        "type_batiment": defauts["type_batiment"] if type_batiment is None else type_batiment,
        "surface_min": defauts["surface_min"] if surface_min is None else surface_min,
        "surface_max": defauts["surface_max"] if surface_max is None else surface_max,
        "etiquettes": etiquettes or [],
        "seulement_nouveaux": seulement_nouveaux,
    }


PARAMETRES = dict(
    fenetre_jours=Query(None, ge=1, le=3650, description="Fenetre en jours"),
    commune=Query(None, description="Filtre sur le nom de commune"),
    code_postal=Query(None),
    zone=Query(None, description="bourg, plage, ..."),
    type_batiment=Query(None),
    surface_min=Query(None, ge=0),
    surface_max=Query(None, ge=0),
    etiquettes=Query(None, description="Classes energetiques retenues"),
    seulement_nouveaux=Query(False),
)


@routeur.get("")
def lister(fenetre_jours: int = PARAMETRES["fenetre_jours"],
           commune: str = PARAMETRES["commune"],
           code_postal: str = PARAMETRES["code_postal"],
           zone: str = PARAMETRES["zone"],
           type_batiment: str = PARAMETRES["type_batiment"],
           surface_min: float = PARAMETRES["surface_min"],
           surface_max: float = PARAMETRES["surface_max"],
           etiquettes: list[str] = PARAMETRES["etiquettes"],
           seulement_nouveaux: bool = PARAMETRES["seulement_nouveaux"],
           limite: int = Query(500, ge=1, le=5000)):
    """Les DPE retenus, une ligne par adresse, du plus recent au plus ancien."""
    filtres = _filtres(fenetre_jours, commune, code_postal, zone, type_batiment,
                       surface_min, surface_max, etiquettes, seulement_nouveaux)
    return {
        "filtres": filtres,
        "resume": veille.resume(filtres),
        "resultats": veille.lister(filtres, limite=limite),
    }


@routeur.get("/export.csv")
def exporter(fenetre_jours: int = PARAMETRES["fenetre_jours"],
             commune: str = PARAMETRES["commune"],
             code_postal: str = PARAMETRES["code_postal"],
             zone: str = PARAMETRES["zone"],
             type_batiment: str = PARAMETRES["type_batiment"],
             surface_min: float = PARAMETRES["surface_min"],
             surface_max: float = PARAMETRES["surface_max"],
             etiquettes: list[str] = PARAMETRES["etiquettes"],
             seulement_nouveaux: bool = PARAMETRES["seulement_nouveaux"]):
    """Le meme tableau, en CSV ouvrable directement dans Excel."""
    filtres = _filtres(fenetre_jours, commune, code_postal, zone, type_batiment,
                       surface_min, surface_max, etiquettes, seulement_nouveaux)
    contenu = veille.exporter_csv(filtres)
    nom = f"veille-dpe-{datetime.date.today():%Y-%m-%d}.csv"
    return Response(
        content=contenu.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nom}"'},
    )


@routeur.post("/vus")
def marquer_vus(corps: dict = Body(default=None)):
    """
    Fait disparaitre le badge « nouveau ».

    Sans liste de numeros, tout est marque : c'est le bouton
    « tout marquer comme vu ».
    """
    numeros = (corps or {}).get("numeros")
    marques = veille.marquer_vus(numeros)
    return {"marques": marques}
