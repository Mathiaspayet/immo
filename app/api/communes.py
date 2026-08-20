# -*- coding: utf-8 -*-
"""
api/communes.py — Les communes disponibles dans le cache.

Sert a remplir les listes deroulantes des ecrans Veille et Identifier :
plutot que de faire deviner un nom de commune, on propose celles que
l'application connait reellement, avec leur volume.
"""

import logging

from fastapi import APIRouter

from app.metier import veille

logger = logging.getLogger(__name__)

routeur = APIRouter(prefix="/api/communes", tags=["communes"])


@routeur.get("")
def lister():
    """
    Communes en cache, de la mieux fournie a la moins fournie.

    Chacune porte son code INSEE — c'est par lui que les ecrans filtrent,
    le nom variant d'une base ADEME a l'autre.
    """
    communes = veille.communes_en_cache()
    return {
        "communes": communes,
        "total": sum(c["dpe"] for c in communes),
        # Secteurs effectivement portes : sert a masquer le filtre quand il
        # n'a rien a filtrer.
        "zones": veille.zones_en_cache(),
    }
