# -*- coding: utf-8 -*-
"""
api/parcelles.py — F3 : la recherche cadastrale.
"""

import logging

from fastapi import APIRouter, Query

from app.metier import parcelles

logger = logging.getLogger(__name__)

routeur = APIRouter(prefix="/api/parcelles", tags=["parcelles"])


@routeur.get("")
def lister(code_insee: str = Query(..., description="Commune, par son code INSEE"),
           terrain_min: float = Query(None, ge=0),
           terrain_max: float = Query(None, ge=0),
           emprise_min: float = Query(None, ge=0),
           emprise_max: float = Query(None, ge=0),
           batie: bool = Query(False, description="Seulement les parcelles bâties"),
           avec_dpe: bool = Query(False, description="Seulement celles portant un DPE"),
           dpe_depuis_jours: int = Query(None, ge=1, le=3650),
           limite: int = Query(400, ge=1, le=3000)):
    """
    Parcelles repondant aux criteres de terrain, avec les DPE qu'elles portent.

    Une parcelle au bon gabarit ET portant un diagnostic recent est le
    croisement que cherche le CDC F3 : deux signaux independants.
    """
    filtres = {
        "terrain_min": terrain_min, "terrain_max": terrain_max,
        "emprise_min": emprise_min, "emprise_max": emprise_max,
        "batie": batie, "avec_dpe": avec_dpe,
        "dpe_depuis_jours": dpe_depuis_jours,
    }
    resultats = parcelles.lister(code_insee, filtres, limite=limite)
    return {
        "filtres": filtres,
        "resume": parcelles.resume(code_insee),
        "resultats": resultats,
        "total": len(resultats),
    }


@routeur.get("/du-dpe")
def du_dpe(n_dpe: str = Query(...)):
    """La parcelle qui porte ce DPE — sert a l'extrait de la fiche."""
    return {"parcelle": parcelles.parcelle_de(n_dpe)}
