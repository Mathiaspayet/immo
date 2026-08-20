# -*- coding: utf-8 -*-
"""
api/communes.py — Choisir une commune, et l'avoir prete a consulter.

C'est le pivot du parcours : l'utilisateur cherche une commune par son nom,
la choisit, et l'application se charge d'aller chercher les DPE s'il ne les
a pas — sans qu'il ait rien a declarer nulle part.
"""

import logging

from fastapi import APIRouter, Query

from app.metier import import_dpe, veille
from app.sources import geo

logger = logging.getLogger(__name__)

routeur = APIRouter(prefix="/api/communes", tags=["communes"])


@routeur.get("")
def lister():
    """
    Communes deja consultees, de la mieux fournie a la moins fournie.

    Chacune porte son code INSEE — c'est par lui que les ecrans filtrent, le
    nom variant d'une base ADEME a l'autre.
    """
    communes = veille.communes_en_cache()
    ages = {c["code_insee"]: import_dpe.age_commune(c["code_insee"]) for c in communes}
    for commune in communes:
        age = ages.get(commune["code_insee"])
        commune["age_heures"] = None if age is None else round(age, 1)

    return {
        "communes": communes,
        "total": sum(c["dpe"] for c in communes),
        # Secteurs effectivement portes : sert a masquer le filtre quand il
        # n'a rien a filtrer.
        "zones": veille.zones_en_cache(),
    }


@routeur.get("/recherche")
def rechercher(q: str = Query(..., min_length=2, description="Début du nom de commune")):
    """
    Communes de France dont le nom approche `q`, deja consultees ou non.

    Le drapeau `en_cache` distingue celles qui repondront immediatement de
    celles qu'il faudra d'abord moissonner.
    """
    connues = {c["code_insee"]: c for c in veille.communes_en_cache()}
    resultats = []
    for commune in geo.chercher(q):
        connue = connues.get(commune["code_insee"])
        resultats.append({**commune,
                          "en_cache": connue is not None,
                          "dpe": connue["dpe"] if connue else 0})
    return {"communes": resultats}


@routeur.post("/{code_insee}/preparer")
def preparer(code_insee: str):
    """
    Rend une commune consultable : la moissonne si elle manque ou si elle
    date, ne fait rien si elle est a jour.

    Repond toujours 200 — ne rien avoir a faire est le cas courant, pas une
    erreur. `raison` dit ce qui a ete decide.
    """
    return import_dpe.preparer_commune(code_insee)
