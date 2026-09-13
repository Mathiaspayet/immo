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


def _dans_le_cadre(cadre, latitude, longitude):
    """Le point tombe-t-il dans l'etendue connue de cette commune ?"""
    if not cadre:
        return False
    for borne in ("lat_min", "lat_max", "lon_min", "lon_max"):
        if cadre.get(borne) is None:
            return False
    return (cadre["lat_min"] <= latitude <= cadre["lat_max"]
            and cadre["lon_min"] <= longitude <= cadre["lon_max"])


@routeur.get("/ici")
def ici(latitude: float = Query(..., ge=-90, le=90, description="Latitude GPS"),
        longitude: float = Query(..., ge=-180, le=180, description="Longitude GPS")):
    """
    Quelle commune se trouve a cette position, et l'a-t-on deja moissonnee ?

    C'est ce que demande le bouton « Me localiser » quand le telephone
    rend une position : la carte sait s'y rendre toute seule, mais elle ne
    sait pas si elle a quelque chose a y montrer.

    ON REGARDE D'ABORD CHEZ SOI. Si le point tombe dans l'etendue d'une
    commune deja en base — et d'une seule —, la reponse est immediate et
    RIEN NE SORT DU SERVEUR. C'est le cas courant : on se localise chez
    soi, dans la commune qu'on suit. Le referentiel de l'Etat n'est
    interroge que lorsqu'on est ailleurs, la ou il faut bien un nom pour
    proposer un telechargement — et la position n'y part qu'arrondie a la
    centaine de metres (voir `geo.commune_a`).

    Cette etendue est celle des DPE connus, donc plus petite que la
    commune reelle : un point dans un coin sans diagnostic passe par le
    referentiel, qui repond juste. L'inverse — deux cadres qui se
    recouvrent — renvoie aussi au referentiel, car le cadre ne tranche
    plus.

    `source` dit lequel des deux chemins a repondu. Repond toujours 200 :
    ne pas savoir ou l'on est n'est pas une erreur.
    """
    connues = veille.communes_en_cache()
    candidates = [c for c in connues if _dans_le_cadre(c.get("cadre"), latitude, longitude)]

    if len(candidates) == 1:
        commune = candidates[0]
        return {"commune": {"code_insee": commune["code_insee"], "nom": commune["nom"],
                            "code_postal": commune.get("code_postal"),
                            "departement": None},
                "en_cache": True, "dpe": commune["dpe"], "source": "cadre"}

    trouvee = geo.commune_a(latitude, longitude)
    if not trouvee:
        return {"commune": None, "en_cache": False, "dpe": 0, "source": None}

    connue = next((c for c in connues if c["code_insee"] == trouvee["code_insee"]), None)
    return {"commune": {"code_insee": trouvee["code_insee"], "nom": trouvee["nom"],
                        "code_postal": trouvee.get("code_postal"),
                        "departement": trouvee.get("departement")},
            "en_cache": connue is not None, "dpe": connue["dpe"] if connue else 0,
            "source": "referentiel"}


@routeur.post("/{code_insee}/preparer")
def preparer(code_insee: str,
             besoin: str = Query("dpe", pattern="^(dpe|cadastre)$",
                                 description="« cadastre » ajoute les parcelles")):
    """
    Rend une commune consultable : la moissonne si elle manque ou si elle
    date, ne fait rien si elle est a jour.

    Repond toujours 200 — ne rien avoir a faire est le cas courant, pas une
    erreur. `raison` dit ce qui a ete decide.
    """
    return import_dpe.preparer_commune(code_insee, besoin=besoin)
