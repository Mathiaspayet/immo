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

from app.base import reglages
from app.metier import alertes, veille
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
    serveur = reglages.smtp()
    communes = veille.communes_en_cache()
    return {
        "active": bool(parametres.get("alerte_active")),
        "destinataire": parametres.get("alerte_destinataire") or "",
        "code_insee": parametres.get("alerte_code_insee") or "",
        "zone": parametres.get("alerte_zone") or "",
        "smtp_configure": bool(serveur["hote"] and serveur["expediteur"]),
        "smtp_hote": serveur["hote"],
        "smtp_authentifie": bool(serveur["utilisateur"]),
        # D'ou vient la configuration en vigueur : les Reglages, ou les
        # variables d'environnement laissees en repli. Le dire evite de
        # chercher pourquoi un changement d'ecran ne prend pas effet.
        "smtp_source": serveur["source"],
        "en_attente": len(alertes.candidats(limite=500)),
        # De quoi peupler les deux listes de choix. Les secteurs etant
        # propres a une commune, ils sont donnes par commune : l'ecran
        # change la seconde liste sans repasser par le serveur.
        "communes": [{"code_insee": c["code_insee"], "nom": c["nom"],
                      "dpe": c["dpe"]} for c in communes],
        "zones_par_commune": {c["code_insee"]: veille.zones_en_cache(c["code_insee"])
                              for c in communes},
    }


@routeur.post("/essai")
def essai(corps: dict = Body(default={})):
    """Envoie un message de controle. L'echec remonte tel quel : ici, on
    veut precisement le voir."""
    try:
        return alertes.essai((corps or {}).get("destinataire"))
    except ErreurCourriel as erreur:
        raise HTTPException(status_code=400, detail=str(erreur)) from erreur
