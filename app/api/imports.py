# -*- coding: utf-8 -*-
"""
api/imports.py — Declenchement et suivi de l'import ADEME.

Le POST ne rend pas la main a la fin de l'import : il le lance et repond
aussitot. L'interface interroge ensuite /statut. Un import complet dure
plusieurs dizaines de secondes ; une requete qui attendrait la fin serait
coupee par le navigateur, et l'utilisateur n'aurait aucun retour (CDC 7).
"""

import logging

from fastapi import APIRouter, HTTPException

from app.metier import import_dpe

logger = logging.getLogger(__name__)

routeur = APIRouter(prefix="/api/import", tags=["import"])


@routeur.post("", status_code=202)
def lancer(code_insee: str = None):
    """
    Force une moisson : une commune precise, ou tout le registre.

    Sur le chemin normal, personne n'a besoin de ce bouton — consulter une
    commune suffit a la mettre a jour. Il reste pour les reglages.
    """
    try:
        import_dpe.lancer_en_tache_de_fond(declencheur="manuel", code_insee=code_insee)
    except RuntimeError as erreur:
        # 409 : la demande est legitime, mais l'etat actuel l'empeche.
        raise HTTPException(status_code=409, detail=str(erreur)) from erreur
    return {"lance": True, "etat": import_dpe.etat()}


@routeur.get("/statut")
def statut():
    """Progression de l'import en cours, ou resultat du dernier."""
    return import_dpe.etat()


@routeur.get("/age")
def age():
    """Heures ecoulees depuis la derniere moisson reussie."""
    return {"age_heures": import_dpe.age_dernier_import()}


@routeur.get("/journal")
def journal(limite: int = 20):
    """Les derniers imports, succes comme echecs (CDC 8)."""
    return {"imports": import_dpe.journal(limite)}
