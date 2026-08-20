# -*- coding: utf-8 -*-
"""
api/alertes.py — Etat et essai de l'alerte courriel (F6).

L'envoi reel part a la suite de l'import quotidien, pas d'ici. Cet
endpoint sert a verifier la configuration SMTP sans attendre qu'un DPE
paraisse : sans lui, on ne saurait qu'un mot de passe est faux qu'au
premier bien manque.
"""

import logging

from fastapi import APIRouter, Body, HTTPException

from app import config
from app.base import reglages
from app.metier import alertes
from app.sources.courriel import ErreurCourriel

logger = logging.getLogger(__name__)

routeur = APIRouter(prefix="/api/alertes", tags=["alertes"])


@routeur.get("")
def etat():
    """
    De quoi l'ecran Reglages peut-il dire que l'alerte est prete ?

    On ne renvoie JAMAIS les identifiants : seulement s'ils sont presents.
    Le mot de passe SMTP ne doit pas voyager jusqu'au navigateur.
    """
    parametres = reglages.tous()
    return {
        "active": bool(parametres.get("alerte_active")),
        "destinataire": parametres.get("alerte_destinataire") or "",
        "zone": parametres.get("alerte_zone") or "",
        "smtp_configure": config.smtp_configure(),
        "smtp_hote": config.SMTP_HOTE or "",
        "smtp_authentifie": bool(config.SMTP_UTILISATEUR),
        "en_attente": len(alertes.candidats(limite=500)),
    }


@routeur.post("/essai")
def essai(corps: dict = Body(default={})):
    """Envoie un message de controle. L'echec remonte tel quel : ici, on
    veut precisement le voir."""
    try:
        return alertes.essai((corps or {}).get("destinataire"))
    except ErreurCourriel as erreur:
        raise HTTPException(status_code=400, detail=str(erreur)) from erreur
