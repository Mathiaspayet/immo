# -*- coding: utf-8 -*-
"""
api/parcelles.py — F3 : la recherche cadastrale.
"""

import logging

from fastapi import APIRouter, HTTPException, Query, Response

from app.base.connexion import connexion
from app.metier import mutations, parcelles
from app.sources import streetview
from app.sources.client_http import ErreurSource

logger = logging.getLogger(__name__)

routeur = APIRouter(prefix="/api/parcelles", tags=["parcelles"])


@routeur.get("/carte")
def carte(code_insee: str = Query(...),
          bbox: str = Query(..., description="lon_min,lat_min,lon_max,lat_max"),
          limite: int = Query(parcelles.MAX_CARTE, ge=1, le=3000),
          fenetre_jours: int = Query(None, ge=1, le=36500,
                                     description="ne garder que les DPE de moins de N jours"),
          zone: str = Query(""),
          type_batiment: str = Query(""),
          surface_min: float = Query(None, ge=0),
          surface_max: float = Query(None, ge=0),
          etiquettes: str = Query("", description="classes separees par une virgule"),
          seulement_nouveaux: bool = Query(False),
          geometries: bool = Query(True, description=
              "false : une position au lieu d'un contour, pour les zooms larges")):
    """
    Les parcelles visibles dans un cadre, avec leurs drapeaux.

    Le filtrage par cadre n'est pas un confort : les geometries d'une
    commune comme Mimizan pesent 3,8 Mo pour 11 444 parcelles, et les
    envoyer d'un bloc rendrait la carte inutilisable sur telephone.

    Les criteres optionnels ne changent QUE le drapeau « DPE » : c'est la
    carte qui repond a la question posee, en se recolorant, plutot qu'une
    liste ouverte a cote d'elle.
    """
    try:
        lon_min, lat_min, lon_max, lat_max = (float(v) for v in bbox.split(","))
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="bbox attendu sous la forme lon_min,lat_min,lon_max,lat_max.")
    if lon_min > lon_max or lat_min > lat_max:
        raise HTTPException(status_code=400, detail="bbox incoherent.")

    criteres = {
        "fenetre_jours": fenetre_jours,
        "zone": zone,
        "type_batiment": type_batiment,
        "surface_min": surface_min,
        "surface_max": surface_max,
        "etiquettes": [e for e in etiquettes.split(",") if e.strip()],
        "seulement_nouveaux": seulement_nouveaux,
    }
    # Aucun critere : le drapeau reste « un DPE, quel qu'il soit ». C'est
    # l'affichage standard, et il ne doit rien couter de plus.
    filtres = criteres if any(
        v not in (None, "", [], False) for v in criteres.values()) else None

    return parcelles.pour_carte(code_insee, (lon_min, lat_min, lon_max, lat_max),
                                limite=limite, filtres_dpe=filtres,
                                avec_geometrie=geometries)


@routeur.get("/chercher")
def chercher(code_insee: str = Query(...),
             q: str = Query(..., min_length=2)):
    """Une adresse ou une reference cadastrale, pour se rendre sur la carte."""
    return {"resultats": parcelles.chercher_sur_carte(code_insee, q)}


@routeur.get("/fiche-parcelle")
def fiche_parcelle(parcelle_id: str = Query(...)):
    """
    Tout ce qu'on sait d'une parcelle : contour, bati, ventes, et les
    diagnostics qu'elle porte.

    La carte montre beaucoup de parcelles sans aucun DPE — 468 sur 550
    dans une vue courante de Mimizan — et cliquer dessus doit mener
    quelque part. Mais celles qui en portent PLUSIEURS meritent la meme
    fiche : ouvrir l'un des diagnostics au hasard, sans dire que les
    autres existent, etait le defaut.
    """
    parcelle = parcelles.parcelle(parcelle_id)
    if parcelle is None:
        raise HTTPException(status_code=404,
                            detail=f"Parcelle {parcelle_id} inconnue.")
    return {
        "parcelle": parcelle,
        "extrait": parcelles.extrait_parcelle(parcelle_id),
        "ventes": mutations.pour_parcelle(parcelle_id),
        "diagnostics": parcelles.diagnostics_de(parcelle_id),
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


@routeur.get("/vue-rue")
def vue_rue(n_dpe: str = Query(None), latitude: float = Query(None),
            longitude: float = Query(None)):
    """
    Le cliche de rue d'un bien, servi par le NAS.

    L'image transite par ici et non par le navigateur : la page ne fait
    ainsi aucune requete vers un tiers (CDC 3), et la cle d'API ne quitte
    jamais le serveur. Le NAS, lui, interroge bien Google — c'est l'ecart
    au CDC 9, assume et documente.

    404 quand rien n'a ete photographie la : c'est le cas courant, pas une
    panne, et la fiche s'en accommode.
    """
    if not streetview.active():
        raise HTTPException(status_code=404, detail="Vue de rue desactivee.")

    if n_dpe:
        with connexion() as conn:
            ligne = conn.execute(
                "SELECT latitude, longitude FROM dpe WHERE n_dpe = ?",
                (str(n_dpe),)).fetchone()
        if ligne is None or ligne["latitude"] is None:
            raise HTTPException(status_code=404, detail="Bien sans position connue.")
        latitude, longitude = ligne["latitude"], ligne["longitude"]

    if latitude is None or longitude is None:
        raise HTTPException(status_code=400,
                            detail="Indiquez un n_dpe, ou une latitude et une longitude.")

    try:
        cliche = streetview.image(latitude, longitude)
    except ErreurSource as erreur:
        raise HTTPException(status_code=502, detail=str(erreur)) from erreur
    if cliche is None:
        raise HTTPException(status_code=404,
                            detail="Aucune vue de rue a cet endroit.")

    octets, type_contenu = cliche
    # Le cliche ne change pas : le navigateur peut le garder longtemps.
    return Response(content=octets, media_type=type_contenu,
                    headers={"Cache-Control": "private, max-age=86400"})


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
