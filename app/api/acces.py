# -*- coding: utf-8 -*-
"""
api/acces.py — Se connecter, choisir ou changer le mot de passe.

Ces routes sont les seules, avec la sonde de sante, qu'on atteint sans
etre connecte (voir main.py) — sauf `changer`, qui demande l'actuel ET une
session. La regle est ecrite dans metier/acces.py ; ici on ne fait que la
traduire en HTTP et poser le cookie.

Le cookie est HttpOnly — aucun script de la page ne le lit — et
SameSite=Strict : un autre site ne peut pas le faire partir avec une
requete qu'il forgerait. Il n'est « Secure » que derriere HTTPS : sur le
reseau local, l'application se sert en HTTP, et un cookie Secure n'y
reviendrait jamais.
"""

import logging

from fastapi import APIRouter, Body, HTTPException, Request, Response

from app import config
from app.metier import acces

logger = logging.getLogger(__name__)

routeur = APIRouter(prefix="/api/acces", tags=["acces"])


def _refus(refus):
    entetes = {"Retry-After": str(refus.attente)} if refus.attente else None
    return HTTPException(status_code=refus.statut, detail=str(refus), headers=entetes)


def _appareil(requete):
    return requete.headers.get("user-agent") or ""


def _en_https(requete):
    transmis = requete.headers.get("x-forwarded-proto", "").split(",")[0].strip()
    return requete.url.scheme == "https" or transmis == "https"


def _poser(reponse, requete, jeton):
    reponse.set_cookie(acces.COOKIE, jeton, max_age=acces.DUREE_COOKIE, path="/",
                       httponly=True, samesite="strict", secure=_en_https(requete))


def _adresse_de_l_application(requete):
    """
    Ou le lien doit ramener : l'adresse posee dans le conteneur, sinon celle
    que montre le navigateur qui le demande — l'en-tete Origin, qui survit
    au proxy inverse quand l'hote, lui, peut avoir ete reecrit.
    """
    if config.URL_PUBLIQUE:
        return config.URL_PUBLIQUE
    origine = (requete.headers.get("origin") or "").strip()
    if origine.startswith(("http://", "https://")):
        return origine.rstrip("/")
    return str(requete.base_url).rstrip("/")


@routeur.get("")
def etat(requete: Request):
    """Connecte ou non, mot de passe choisi ou non, et ou part le lien (masque)."""
    return acces.etat(requete.cookies.get(acces.COOKIE))


@routeur.post("/lien")
def lien(requete: Request):
    """Envoie le lien qui choisit ou remplace le mot de passe."""
    try:
        return acces.envoyer_lien(_adresse_de_l_application(requete))
    except acces.RefusAcces as refus:
        raise _refus(refus) from refus


@routeur.post("/definir")
def definir(requete: Request, reponse: Response, corps: dict = Body(...)):
    """Pose le mot de passe avec le jeton du lien, et connecte ce navigateur."""
    try:
        jeton = acces.definir(corps.get("jeton"), corps.get("motdepasse"), _appareil(requete))
    except acces.RefusAcces as refus:
        raise _refus(refus) from refus
    _poser(reponse, requete, jeton)
    return {"connecte": True}


@routeur.post("/connexion")
def connexion(requete: Request, reponse: Response, corps: dict = Body(...)):
    try:
        jeton = acces.connecter(corps.get("motdepasse"), _appareil(requete))
    except acces.RefusAcces as refus:
        raise _refus(refus) from refus
    _poser(reponse, requete, jeton)
    return {"connecte": True}


@routeur.post("/changer")
def changer(requete: Request, reponse: Response, corps: dict = Body(...)):
    """Remplace le mot de passe. Les autres appareils sont deconnectes."""
    try:
        jeton = acces.changer(corps.get("actuel"), corps.get("nouveau"), _appareil(requete))
    except acces.RefusAcces as refus:
        raise _refus(refus) from refus
    _poser(reponse, requete, jeton)
    return {"connecte": True}


@routeur.post("/deconnexion")
def deconnexion(requete: Request, reponse: Response, corps: dict | None = Body(default=None)):
    """Ferme cette session, ou toutes avec `partout`."""
    partout = bool((corps or {}).get("partout"))
    acces.deconnecter(requete.cookies.get(acces.COOKIE), partout=partout)
    reponse.delete_cookie(acces.COOKIE, path="/", httponly=True, samesite="strict",
                          secure=_en_https(requete))
    return {"connecte": False}
