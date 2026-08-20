# -*- coding: utf-8 -*-
"""
api/reglages.py — Lecture et modification des reglages metier.

La validation est celle de base/reglages.py : un seul endroit ou la regle
est ecrite. Un reglage refuse renvoie 400 avec un message en francais,
affichable tel quel dans l'interface (CDC 7).
"""

import logging

from fastapi import APIRouter, Body, HTTPException

from app.base import reglages as base_reglages

logger = logging.getLogger(__name__)

routeur = APIRouter(prefix="/api/reglages", tags=["reglages"])


@routeur.get("")
def lire():
    """Les reglages courants, et les valeurs par defaut pour comparaison."""
    return {"reglages": base_reglages.tous(), "defauts": base_reglages.DEFAUTS}


@routeur.put("")
def modifier(valeurs: dict = Body(...)):
    """Enregistre un lot de reglages."""
    try:
        return {"reglages": base_reglages.ecrire(valeurs)}
    except ValueError as erreur:
        raise HTTPException(status_code=400, detail=str(erreur)) from erreur
