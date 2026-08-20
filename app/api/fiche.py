# -*- coding: utf-8 -*-
"""
api/fiche.py — F4 : fiche d'un bien, chronologie, remplacements, comparaison.

`chaine` et `comparer` peuvent interroger l'ADEME : ce sont des actions
explicites de l'utilisateur sur un bien precis, pas un simple affichage de
page — la regle du CDC 4 reste respectee.
"""

import logging

from fastapi import APIRouter, HTTPException, Query

from app.metier import fiche as metier_fiche

logger = logging.getLogger(__name__)

routeur = APIRouter(prefix="/api/fiche", tags=["fiche"])


@routeur.get("")
def lire(n_dpe: str = Query(None), adresse: str = Query(None)):
    """Chronologie de tous les DPE connus pour une adresse."""
    if not n_dpe and not adresse:
        raise HTTPException(status_code=400,
                            detail="Indiquez un numéro de DPE ou une adresse.")
    resultat = metier_fiche.historique(adresse=adresse, n_dpe=n_dpe)
    if not resultat["diagnostics"] and adresse:
        # Plutot qu'un « aucun résultat » sec, on propose des voies proches.
        resultat["suggestions"] = metier_fiche.voisinage(adresse)
    return resultat


@routeur.get("/chaine")
def chaine(n_dpe: str = Query(...),
           interroger_ademe: bool = Query(True)):
    """Suite des DPE remplaces, du plus recent au plus ancien."""
    return metier_fiche.chaine(n_dpe, interroger_ademe=interroger_ademe)


@routeur.get("/comparer")
def comparer(recent: str = Query(...), ancien: str = Query(...)):
    """Champs dont la valeur differe entre deux diagnostics."""
    return metier_fiche.comparer(recent, ancien)
