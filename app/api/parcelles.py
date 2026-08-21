# -*- coding: utf-8 -*-
"""
api/parcelles.py — F3 : la recherche cadastrale.
"""

import logging

from fastapi import APIRouter, HTTPException, Query

from app.metier import mutations, parcelles

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


@routeur.get("/carte")
def carte(code_insee: str = Query(...),
          bbox: str = Query(..., description="lon_min,lat_min,lon_max,lat_max"),
          limite: int = Query(parcelles.MAX_CARTE, ge=1, le=3000)):
    """
    Les parcelles visibles dans un cadre, avec leurs drapeaux.

    Le filtrage par cadre n'est pas un confort : les geometries d'une
    commune comme Mimizan pesent 3,8 Mo pour 11 444 parcelles, et les
    envoyer d'un bloc rendrait la carte inutilisable sur telephone.
    """
    try:
        lon_min, lat_min, lon_max, lat_max = (float(v) for v in bbox.split(","))
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="bbox attendu sous la forme lon_min,lat_min,lon_max,lat_max.")
    if lon_min > lon_max or lat_min > lat_max:
        raise HTTPException(status_code=400, detail="bbox incoherent.")

    return parcelles.pour_carte(code_insee, (lon_min, lat_min, lon_max, lat_max),
                                limite=limite)


@routeur.get("/chercher")
def chercher(code_insee: str = Query(...),
             q: str = Query(..., min_length=2)):
    """Une adresse ou une reference cadastrale, pour se rendre sur la carte."""
    return {"resultats": parcelles.chercher_sur_carte(code_insee, q)}


@routeur.get("/ventes")
def ventes(n_dpe: str = Query(...)):
    """
    L'historique des ventes du bien, via sa parcelle (DVF).

    Le rattachement passe par le foncier et jamais par l'adresse : DVF et
    le cadastre partagent `id_parcelle`, la ou l'orthographe d'une adresse
    varie d'une base a l'autre.
    """
    return {"ventes": mutations.pour_dpe(n_dpe)}


@routeur.get("/extrait")
def extrait(n_dpe: str = Query(...)):
    """
    De quoi dessiner l'extrait cadastral d'un bien : sa parcelle, les
    parcelles voisines, et les batiments du cadre.
    """
    return {"extrait": parcelles.extrait(n_dpe)}


@routeur.get("/du-dpe")
def du_dpe(n_dpe: str = Query(...)):
    """La parcelle qui porte ce DPE — sert a l'extrait de la fiche."""
    return {"parcelle": parcelles.parcelle_de(n_dpe)}
