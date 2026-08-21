# -*- coding: utf-8 -*-
"""
api/parcelles.py — F3 : la recherche cadastrale.
"""

import logging

from fastapi import APIRouter, HTTPException, Query

from app.metier import mutations, parcelles

logger = logging.getLogger(__name__)

routeur = APIRouter(prefix="/api/parcelles", tags=["parcelles"])


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


@routeur.get("/fiche-parcelle")
def fiche_parcelle(parcelle_id: str = Query(...)):
    """
    Tout ce qu'on sait d'une parcelle qui ne porte aucun DPE.

    La carte en montre beaucoup — 468 sur 550 dans une vue courante de
    Mimizan. Cliquer dessus doit mener quelque part : le contour, le
    voisinage, le bati, et les ventes s'il y en a. C'est la carte
    d'identite du terrain, a defaut de celle d'un logement.
    """
    parcelle = parcelles.parcelle(parcelle_id)
    if parcelle is None:
        raise HTTPException(status_code=404,
                            detail=f"Parcelle {parcelle_id} inconnue.")
    return {
        "parcelle": parcelle,
        "extrait": parcelles.extrait_parcelle(parcelle_id),
        "ventes": mutations.pour_parcelle(parcelle_id),
    }


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
