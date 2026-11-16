# -*- coding: utf-8 -*-
"""
api/identification.py — F2 : identifier un bien depuis les chiffres d'une annonce.
"""

import logging

from fastapi import APIRouter, Body, HTTPException

from app.metier import identification

logger = logging.getLogger(__name__)

routeur = APIRouter(prefix="/api/identification", tags=["identification"])


@routeur.post("")
def identifier(corps: dict = Body(...)):
    """
    Classe les logements par ressemblance avec une annonce.

    Corps attendu :
        {"criteres": {"surface": 144, "conso_ep": 216, ...},
         "tolerances": {"surface": 3},        (facultatif)
         "filtres": {"commune": "Mimizan"}}   (facultatif)

    Renvoie l'entonnoir, le classement complet et le diagnostic. Aucun
    logement n'est ecarte : c'est tout l'interet (CDC F2).
    """
    try:
        combien = int(corps.get("combien") or 40)
        if not 1 <= combien <= 500:
            raise ValueError
    except (TypeError, ValueError):
        raise HTTPException(status_code=400,
                            detail="Nombre de résultats : un entier de 1 à 500.") from None
    try:
        return identification.identifier(
            criteres=corps.get("criteres") or {},
            tolerances=corps.get("tolerances"),
            filtres=corps.get("filtres"),
            combien=combien,
        )
    except ValueError as erreur:
        # Un chiffre illisible, une tolerance nulle : le message dit lequel.
        raise HTTPException(status_code=400, detail=str(erreur)) from erreur
