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

from app.base import sauvegarde
from app.metier import alertes, import_dpe, mutations
from app.sources.dvf_archive import ArchiveIntrouvable

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


@routeur.get("/ventes/profondeur")
def profondeur_ventes(code_insee: str = None):
    """Jusqu'ou remonte l'historique des ventes conserve en base.

    Sans commune precisee, c'est celle qui est surveillee — lue dans les
    reglages. L'ecran ne peut pas la fournir : ses champs dorment masques
    et vides tant qu'on n'a pas clique sur « Modifier ».
    """
    return mutations.profondeur(code_insee or alertes.commune_surveillee() or None)


@routeur.post("/ventes/archive", status_code=200)
def reprendre_archive(code_insee: str = None, dep: str = None):
    """
    Reprend les millesimes que la source officielle ne sert plus.

    Une commune, ou tout un departement (`dep`). Sans rien, c'est la
    commune surveillee : le cas courant ne demande donc aucun choix.

    Repond a la fin, contrairement a l'import ADEME. Mesure sur les
    Landes — le plus gros cas, 327 communes : 8 s d'import, le
    telechargement de 34 Mo dominant largement. Un 202 obligerait a un
    second canal de suivi pour un geste qu'on ne fait qu'une fois.
    """
    if dep and code_insee:
        # Preferer l'un en taisant l'autre serait pire qu'un refus : on
        # croirait avoir repris une commune et on aurait pris tout le
        # departement — 327 communes et 38 Mo au lieu de quelques-uns.
        raise HTTPException(
            status_code=400,
            detail="Preciser une commune OU un departement, pas les deux.")
    if not dep:
        code_insee = code_insee or alertes.commune_surveillee()
        if not code_insee:
            raise HTTPException(
                status_code=400,
                detail="Aucune commune surveillee : choisissez-la dans "
                       "« Alerte par courriel » ou « Secteurs », ou "
                       "indiquez un departement.")
    try:
        return mutations.reprendre_archive(
            code_insee=None if dep else code_insee, dep=dep or None)
    except ValueError as erreur:
        # Trois issues distinctes, parce qu'elles n'appellent pas la meme
        # reaction : corriger sa saisie (400), constater que la
        # compilation ne couvre pas ce departement (404), ou reessayer
        # plus tard (502). Les confondre enverrait chercher le probleme
        # au mauvais endroit.
        raise HTTPException(status_code=400, detail=str(erreur)) from erreur
    except ArchiveIntrouvable as erreur:
        raise HTTPException(status_code=404, detail=str(erreur)) from erreur
    except Exception as erreur:                      # noqa: BLE001
        logger.warning("reprise d'archive DVF impossible : %s", erreur)
        raise HTTPException(status_code=502, detail=str(erreur)) from erreur


@routeur.get("/sauvegardes")
def etat_sauvegardes():
    """Ou en sont les copies datees de la base."""
    return sauvegarde.etat()


@routeur.post("/sauvegardes", status_code=200)
def sauvegarder_maintenant():
    """
    Ecrit une copie tout de suite.

    Repond a la fin : quelques secondes pour quelques dizaines de
    mega-octets, et l'utilisateur veut savoir si elle s'est VERIFIEE.
    """
    resultat = sauvegarde.sauvegarder()
    if not resultat["faite"]:
        raise HTTPException(status_code=500, detail=resultat["raison"])
    return {**resultat, "etat": sauvegarde.etat()}
