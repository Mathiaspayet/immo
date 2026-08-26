# -*- coding: utf-8 -*-
"""
api/alertes.py — Etat et essai de l'alerte courriel (F6).

L'envoi reel part a la suite de l'import quotidien, pas d'ici. Cet
endpoint sert a verifier la configuration SMTP sans attendre qu'un DPE
paraisse : sans lui, on ne saurait qu'un mot de passe est faux qu'au
premier bien manque.
"""

import logging

from fastapi import APIRouter, Body

from app import config, planificateur
from app.base import reglages
from app.metier import alertes, veille

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
        # QUAND l'alerte part. Sans cette information, « je n'ai rien recu
        # aujourd'hui » n'a pas de reponse : on ne sait ni a quelle heure
        # le passage a lieu, ni s'il a lieu du tout sur ce conteneur.
        "planificateur": {
            "actif": config.PLANIFICATEUR_ACTIF,
            "heure": config.IMPORT_HEURE,
            "jours": config.IMPORT_JOUR,
            "fuseau": config.FUSEAU,
            "prochaine": planificateur.prochaine_execution(),
        },
        # Les criteres qui decident d'un envoi. Ils sont plus etroits qu'on
        # ne le croit — maisons seules, fenetre glissante — et c'est la
        # premiere explication d'un silence.
        "criteres": {
            "fenetre_jours": parametres.get("fenetre_jours"),
            "type_batiment": parametres.get("type_batiment") or "tous types",
            "surface_min": parametres.get("surface_min"),
            "surface_max": parametres.get("surface_max"),
        },
        # De quoi peupler les deux listes de choix. Les secteurs etant
        # propres a une commune, ils sont donnes par commune : l'ecran
        # change la seconde liste sans repasser par le serveur.
        "communes": [{"code_insee": c["code_insee"], "nom": c["nom"],
                      "dpe": c["dpe"]} for c in communes],
        "zones_par_commune": {c["code_insee"]: veille.zones_en_cache(c["code_insee"])
                              for c in communes},
    }


@routeur.get("/journal")
def journal(limite: int = 15):
    """
    Les dernieres tentatives d'alerte, envoyees ou non.

    C'est la seule reponse consultable a « je n'ai rien recu ce matin » :
    le journal des imports dit que la moisson a reussi, ce qui est vrai
    meme les jours ou aucun courriel ne part.
    """
    return {"tentatives": alertes.journal(limite)}


@routeur.post("/essai")
def essai(corps: dict = Body(default={})):
    """
    Envoie un message de controle et raconte ce qui s'est passe.

    Repond 200 meme en cas d'echec : un echec n'est pas une erreur de
    l'appel, c'est son resultat. Le corps porte la trace pas a pas, que
    l'ecran affiche — sans elle, « ca ne marche pas » reste indeboguable.

    `smtp` porte la configuration AFFICHEE, pas celle enregistree : on
    eprouve ce qu'on voit, puis on enregistre quand cela marche.
    """
    corps = corps or {}
    return alertes.essai(corps.get("destinataire"), brouillon=corps.get("smtp"))
