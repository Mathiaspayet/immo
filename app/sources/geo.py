# -*- coding: utf-8 -*-
"""
geo.py — API Decoupage administratif (geo.api.gouv.fr).

Sert a resoudre un code postal en communes reelles : le 40200 couvre
Mimizan, mais aussi Aureilhan et Saint-Paul-en-Born. C'est ce qui permet
d'enregistrer un code INSEE fiable a cote de chaque DPE, plutot que de se
fier au nom de commune renvoye par l'ADEME.
"""

import logging

from app.sources.client_http import ErreurSource, appeler, construire_url

logger = logging.getLogger(__name__)

BASE = "https://geo.api.gouv.fr/communes"


def communes_du_code_postal(code_postal):
    """
    Renvoie [{"code_insee":..., "nom":..., "code_postal":...}, ...].

    Une panne de cette API ne doit pas empecher l'import des DPE : elle est
    utile, pas indispensable. On renvoie donc une liste vide en cas d'echec,
    et l'import se poursuit sans code INSEE.
    """
    url = construire_url(BASE, {"codePostal": code_postal, "fields": "nom,code,codesPostaux"})
    try:
        reponse = appeler(url)
    except ErreurSource as erreur:
        logger.warning("geo.api.gouv.fr indisponible (%s) — import sans code INSEE", erreur)
        return []

    communes = []
    for entree in reponse or []:
        communes.append({
            "code_insee": entree.get("code"),
            "nom": entree.get("nom"),
            "code_postal": code_postal,
        })
    return communes
