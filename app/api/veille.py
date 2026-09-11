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
             surface_min, surface_max, etiquettes, seulement_nouveaux,
             code_insee="", avec_defauts=True):
    """
    Assemble les filtres, en completant par les valeurs des reglages.

    `avec_defauts=False` les prend au PIED DE LA LETTRE : un critere
    absent est un critere absent, et non « celui des reglages ».

    La distinction n'est pas theorique. La carte colore ses parcelles
    selon les criteres de l'ecran ; sans ce choix, la liste posee sous
    elle recevait EN PLUS les defauts enregistres — une fenetre de 120
    jours, des bornes de surface — et annoncait 57 diagnostics la ou la
    carte en montrait tout autre chose. Deux reponses differentes a la
    meme question, sur le meme ecran.
    """
    defauts = veille.filtres_par_defaut() if avec_defauts else {
        "fenetre_jours": None, "type_batiment": "",
        "surface_min": "", "surface_max": "",
    }
    return {
        "fenetre_jours": defauts["fenetre_jours"] if fenetre_jours is None else fenetre_jours,
        # Pas de commune par defaut : l'ecran propose desormais toutes
        # celles du cache, et c'est a l'utilisateur de choisir. Le serveur
        # n'a plus a deviner laquelle l'interesse.
        "commune": commune or "",
        "code_insee": code_insee or "",
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
    code_insee=Query(None, description="Filtre exact sur la commune"),
    zone=Query(None, description="bourg, plage, ..."),
    type_batiment=Query(None),
    surface_min=Query(None, ge=0),
    surface_max=Query(None, ge=0),
    etiquettes=Query(None, description="Classes energetiques retenues"),
    seulement_nouveaux=Query(False),
    defauts=Query(True, description="completer les criteres absents par les reglages"),
)


@routeur.get("")
def lister(fenetre_jours: int = PARAMETRES["fenetre_jours"],
           commune: str = PARAMETRES["commune"],
           code_postal: str = PARAMETRES["code_postal"],
           code_insee: str = PARAMETRES["code_insee"],
           zone: str = PARAMETRES["zone"],
           type_batiment: str = PARAMETRES["type_batiment"],
           surface_min: float = PARAMETRES["surface_min"],
           surface_max: float = PARAMETRES["surface_max"],
           etiquettes: list[str] = PARAMETRES["etiquettes"],
           seulement_nouveaux: bool = PARAMETRES["seulement_nouveaux"],
           defauts: bool = PARAMETRES["defauts"],
           limite: int = Query(500, ge=1, le=5000)):
    """Les DPE retenus, une ligne par adresse, du plus recent au plus ancien."""
    filtres = _filtres(fenetre_jours, commune, code_postal, zone, type_batiment,
                       surface_min, surface_max, etiquettes, seulement_nouveaux,
                       code_insee, avec_defauts=defauts)
    return {
        "filtres": filtres,
        "resume": veille.resume(filtres),
        "resultats": veille.lister(filtres, limite=limite),
    }


@routeur.get("/export.csv")
def exporter(fenetre_jours: int = PARAMETRES["fenetre_jours"],
             commune: str = PARAMETRES["commune"],
             code_postal: str = PARAMETRES["code_postal"],
             code_insee: str = PARAMETRES["code_insee"],
             zone: str = PARAMETRES["zone"],
             type_batiment: str = PARAMETRES["type_batiment"],
             surface_min: float = PARAMETRES["surface_min"],
             surface_max: float = PARAMETRES["surface_max"],
             etiquettes: list[str] = PARAMETRES["etiquettes"],
             seulement_nouveaux: bool = PARAMETRES["seulement_nouveaux"],
             defauts: bool = PARAMETRES["defauts"]):
    """Le meme tableau, en CSV ouvrable directement dans Excel."""
    filtres = _filtres(fenetre_jours, commune, code_postal, zone, type_batiment,
                       surface_min, surface_max, etiquettes, seulement_nouveaux,
                       code_insee, avec_defauts=defauts)
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
