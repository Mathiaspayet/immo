# -*- coding: utf-8 -*-
"""
api/estimation.py — Estimer la valeur d'un bien.

Estimer est une action EXPLICITE : rien ne part vers une source tant que
l'utilisateur n'a pas demande une estimation ou la preparation d'un
departement (CDC 4). La premiere fois dans un departement, il faut en
charger les ventes et mesurer la precision — une a deux minutes : c'est
un travail de fond, suivi par /preparation, comme l'import ADEME.
"""

import logging

from fastapi import APIRouter, Body, HTTPException, Query, Response

from app.metier import estimation, references
from app.sources.client_http import ErreurSource

logger = logging.getLogger(__name__)

routeur = APIRouter(prefix="/api/estimation", tags=["estimation"])


@routeur.get("/bien")
def bien(n_dpe: str = Query(None), parcelle_id: str = Query(None)):
    """
    Ce que la base sait deja du bien, pour pre-remplir le formulaire, et
    l'etat de son departement : pret a estimer, ou a preparer d'abord.
    """
    if not n_dpe and not parcelle_id:
        raise HTTPException(status_code=400, detail="Indiquez un diagnostic ou une parcelle.")
    try:
        description = estimation.bien_depuis(n_dpe=n_dpe, parcelle_id=parcelle_id)
    except LookupError as erreur:
        raise HTTPException(status_code=404, detail=str(erreur)) from erreur
    departement = (references.departement_de(description["code_insee"])
                   if description["code_insee"] else None)
    return {"bien": description,
            "departement": estimation.etat_departement(departement) if departement else None,
            "etats": estimation.etats()}


@routeur.get("/departement/{departement}")
def departement(departement: str):
    """Ventes chargees, modele appris, precision mesuree."""
    return estimation.etat_departement(departement)


@routeur.post("/preparer", status_code=202)
def preparer(departement: str = Query(..., min_length=2, max_length=3), forcer: bool = Query(False)):
    """
    Charge les ventes du departement et apprend le modele, en tache de fond.

    Repond aussitot : la Gironde, c'est 115 000 ventes et une douzaine de
    megaoctets a telecharger — une requete qui attendrait la fin serait
    coupee par le navigateur.
    """
    raison = references.dvf.indisponible(departement + "000")
    if raison:
        raise HTTPException(status_code=400, detail=raison)
    try:
        estimation.lancer_preparation(departement, forcer=forcer)
    except RuntimeError as erreur:
        raise HTTPException(status_code=409, detail=str(erreur)) from erreur
    return {"lance": True, "etat": estimation.etat_preparation()}


@routeur.get("/preparation")
def preparation():
    """Ou en est la preparation en cours, ou comment la derniere s'est terminee."""
    return estimation.etat_preparation()


@routeur.post("")
def estimer(corps: dict = Body(...)):
    """
    Estime un bien.

    Corps attendu :
        {"bien": {"type": "maison", "surface": 110, "terrain_m2": 800,
                  "latitude": .., "longitude": .., "code_insee": "40184",
                  "pieces": 5, "annee_construction": 1985, "parcelle_id": ..},
         "saisie": {"etat": "assez_bon"} ou {"travaux": 40000},
                   plus "ajustement" (en %) et "raison", facultatifs,
         "enregistrer": false}

    Avec "enregistrer", l'estimation est gardee : elle pourra etre comparee
    au prix reel le jour ou la vente paraitra dans DVF.
    """
    description = corps.get("bien") or {}
    try:
        resultat = estimation.estimer(description, corps.get("saisie") or {})
    except estimation.PasPret as erreur:
        raise HTTPException(
            status_code=409,
            detail=f"Le département {erreur} n'est pas encore préparé : chargez d'abord ses ventes."
        ) from erreur
    except ValueError as erreur:
        raise HTTPException(status_code=400, detail=str(erreur)) from erreur
    except ErreurSource as erreur:
        raise HTTPException(status_code=502, detail=str(erreur)) from erreur
    if corps.get("enregistrer"):
        resultat["id"] = estimation.enregistrer(resultat, n_dpe=description.get("n_dpe"),
                                                adresse=description.get("adresse"))
    return resultat


@routeur.get("/etats")
def etats():
    """L'echelle d'etat du bati, avec l'effet de chaque niveau."""
    return {"etats": estimation.etats()}


@routeur.get("/enregistrees")
def enregistrees():
    """Les estimations gardees, de la plus recente a la plus ancienne."""
    return {"estimations": estimation.enregistrees()}


@routeur.get("/enregistrees/{ident}")
def enregistree(ident: int):
    trouvee = estimation.enregistree(ident)
    if trouvee is None:
        raise HTTPException(status_code=404, detail=f"Estimation {ident} introuvable.")
    return trouvee


@routeur.delete("/enregistrees/{ident}", status_code=204)
def supprimer(ident: int):
    if not estimation.supprimer(ident):
        raise HTTPException(status_code=404, detail=f"Estimation {ident} introuvable.")
    return Response(status_code=204)
