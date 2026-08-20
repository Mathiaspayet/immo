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


def chercher(nom, limite=8):
    """
    Communes dont le nom approche `nom`, les plus peuplees d'abord.

    Sert a l'ecran de choix de commune : on cherche « laun », on obtient
    Launaguet. Renvoie une liste vide plutot que de lever — une recherche
    qui echoue ne doit pas casser l'ecran.
    """
    nom = str(nom or "").strip()
    if len(nom) < 2:
        return []

    # On demande large pour pouvoir reclasser : le tri de l'API favorise les
    # noms courts. Sur « laun », Launaguet (9 173 habitants) arrivait
    # cinquieme, derriere Launoy (96 habitants).
    url = construire_url(BASE, {
        "nom": nom,
        "fields": "nom,code,codesPostaux,population,departement",
        "limit": max(limite * 3, 20),
        "boost": "population",
    })
    try:
        reponse = appeler(url)
    except ErreurSource as erreur:
        logger.warning("recherche de commune indisponible : %s", erreur)
        return []

    resultats = []
    for entree in reponse or []:
        codes = entree.get("codesPostaux") or []
        resultats.append({
            "code_insee": entree.get("code"),
            "nom": entree.get("nom"),
            "code_postal": codes[0] if codes else None,
            "codes_postaux": codes,
            "population": entree.get("population"),
            "departement": (entree.get("departement") or {}).get("nom"),
        })

    return sorted(resultats, key=lambda c: _pertinence(c, nom))[:limite]


def _sans_accents(texte):
    remplacements = {"é": "e", "è": "e", "ê": "e", "ë": "e", "à": "a", "â": "a",
                     "î": "i", "ï": "i", "ô": "o", "ö": "o", "û": "u", "ù": "u",
                     "ç": "c", "-": " ", "'": " "}
    texte = str(texte or "").lower()
    for ancien, nouveau in remplacements.items():
        texte = texte.replace(ancien, nouveau)
    return texte


def _pertinence(commune, recherche):
    """
    Cle de tri : d'abord la qualite de la correspondance, puis la taille.

    Quand on tape trois lettres, on vise presque toujours une commune qu'on
    connait — donc une commune peuplee. A qualite egale, la plus grande
    passe devant.
    """
    nom = _sans_accents(commune["nom"])
    cible = _sans_accents(recherche)

    if nom == cible:
        rang = 0
    elif nom.startswith(cible):
        rang = 1
    elif any(mot.startswith(cible) for mot in nom.split()):
        rang = 2                      # « La Chapelle-Launay » sur « launay »
    else:
        rang = 3
    return (rang, -(commune.get("population") or 0), nom)


def commune_par_insee(code_insee):
    """Une commune precise, par son code INSEE."""
    url = construire_url(f"{BASE}/{code_insee}",
                         {"fields": "nom,code,codesPostaux,population,departement"})
    try:
        entree = appeler(url)
    except ErreurSource:
        return None
    if not entree:
        return None
    codes = entree.get("codesPostaux") or []
    return {
        "code_insee": entree.get("code"),
        "nom": entree.get("nom"),
        "code_postal": codes[0] if codes else None,
        "codes_postaux": codes,
        "population": entree.get("population"),
        "departement": (entree.get("departement") or {}).get("nom"),
    }


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
