# -*- coding: utf-8 -*-
"""
client_http.py — Appels HTTP vers les API publiques.

Deux points repris tels quels des scripts d'origine, obtenus par essais
successifs et qu'il ne faut surtout pas "simplifier" :

1. L'identifiant de navigateur. Le pare-feu applicatif de l'ADEME renvoie
   403 aux agents inhabituels (dont l'agent par defaut de Python). On se
   presente donc comme un Chrome ordinaire.

2. Le magasin de certificats. Sous Linux le magasin du systeme suffit, mais
   `certifi` est installe par securite : c'est ce qui evitait deja les
   erreurs SSL sous Windows.

On utilise `urllib` de la bibliotheque standard, comme les scripts : c'est
exactement le chemin de code qui a ete valide contre l'API reelle.
"""

import json
import logging
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

ENTETES = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/126.0.0.0 Safari/537.36"),
    "Accept": "application/json",
}

DELAI = 90            # secondes
TENTATIVES = 3        # sur incident reseau uniquement
ATTENTE = (1, 3, 8)   # secondes entre deux tentatives


class ErreurSource(Exception):
    """Une source de donnees n'a pas repondu, ou a repondu une erreur.

    On leve plutot que de renvoyer un resultat vide : le CDC 7 demande de
    dire ce qui s'est passe, jamais un simple « aucun resultat »."""


def _contexte_ssl():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:      # pragma: no cover - certifi est dans requirements
        return ssl.create_default_context()


CONTEXTE = _contexte_ssl()


def appeler(url, silencieux=False):
    """
    Appelle une URL et renvoie le JSON decode.

    Leve ErreurSource si le serveur refuse ou ne repond pas. Une panne
    reseau passagere est retentee ; une erreur HTTP franche (403, 404) ne
    l'est pas, elle ne se resoudra pas toute seule.
    """
    derniere = None
    for essai in range(TENTATIVES):
        try:
            requete = urllib.request.Request(url, headers=ENTETES)
            with urllib.request.urlopen(requete, timeout=DELAI, context=CONTEXTE) as reponse:
                return json.loads(reponse.read().decode("utf-8"))

        except urllib.error.HTTPError as erreur:
            corps = erreur.read().decode("utf-8", "ignore")[:200].strip()
            message = f"HTTP {erreur.code} — {corps or erreur.reason}"
            if not silencieux:
                logger.warning("%s sur %s", message, url[:120])
            raise ErreurSource(message) from erreur

        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as erreur:
            derniere = f"{type(erreur).__name__} : {erreur}"
            if essai < TENTATIVES - 1:
                if not silencieux:
                    logger.info("nouvel essai apres %s", derniere)
                time.sleep(ATTENTE[essai])

    raise ErreurSource(f"injoignable apres {TENTATIVES} tentatives — {derniere}")


def construire_url(base, parametres):
    """Assemble une URL avec ses parametres correctement encodes."""
    return f"{base}?{urllib.parse.urlencode(parametres)}"
