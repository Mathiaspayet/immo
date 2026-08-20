# -*- coding: utf-8 -*-
"""
api/identification.py — F2 : identifier un bien depuis les chiffres d'une annonce.
"""

import logging

from fastapi import APIRouter, Body

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
    return identification.identifier(
        criteres=corps.get("criteres") or {},
        tolerances=corps.get("tolerances"),
        filtres=corps.get("filtres"),
        combien=int(corps.get("combien") or 40),
    )
