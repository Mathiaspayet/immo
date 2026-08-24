# -*- coding: utf-8 -*-
"""
courriel.py — L'envoi SMTP.

Isole dans sa propre source pour une raison pratique : le reste de
l'application doit pouvoir etre teste sans serveur de mail. Tout ce qui
parle a un serveur passe par `envoyer`, que les tests remplacent.

L'application n'a ni compte ni cle d'API ailleurs : les identifiants SMTP
sont ses seuls secrets. Ils viennent de l'ecran Reglages, ou a defaut de
l'environnement (voir base/reglages.py, fonction `smtp`).
"""

import logging
import smtplib
import ssl
import time
from email.message import EmailMessage
from email.utils import formataddr, formatdate

from app.base import reglages

logger = logging.getLogger(__name__)

# Un serveur injoignable doit se declarer vite : une minute d'attente sur
# un bouton de controle donne l'impression que rien ne se passe. Le delai
# se paie deux fois quand l'hote a une adresse v4 ET v6 — on vise donc la
# moitie du temps qu'on juge acceptable.
DELAI = 12


class ErreurCourriel(Exception):
    """L'envoi a echoue. Jamais fatale : l'import prime sur l'alerte."""


class Trace:
    """
    Le journal d'un envoi, etape par etape.

    « Ca ne marche pas » ne se debogue pas : il faut savoir OU. La
    connexion a-t-elle abouti ? Le serveur a-t-il annonce STARTTLS ?
    L'authentification est-elle passee ? Chaque reponse ecarte une moitie
    des causes possibles.

    Ne contient JAMAIS le mot de passe, meme en cas d'echec : cette trace
    est destinee a etre affichee.
    """

    def __init__(self):
        self.etapes = []
        self._depart = time.monotonic()

    def noter(self, nom, etat, detail=""):
        self.etapes.append({
            "nom": nom, "etat": etat, "detail": str(detail)[:400],
            "ms": round((time.monotonic() - self._depart) * 1000),
        })
        return self

    def dernier_echec(self):
        for etape in reversed(self.etapes):
            if etape["etat"] == "echec":
                return etape
        return None


def envoyer(destinataire, sujet, texte, html=None, trace=None):
    """
    Envoie un message. Leve ErreurCourriel si le serveur refuse.

    Le corps part en texte brut ET en HTML : le texte reste lisible dans un
    client qui n'affiche pas le second, et c'est aussi ce qui evite qu'un
    message tout-HTML soit classe en indesirable.

    `trace` recoit le detail de chaque etape, pour le diagnostic.
    """
    trace = trace if trace is not None else Trace()
    serveur_config = reglages.smtp()
    if not (serveur_config["hote"] and serveur_config["expediteur"]):
        trace.noter("configuration", "echec",
                    "serveur ou adresse d'expedition absents")
        raise ErreurCourriel(
            "Envoi non configure : renseigner le serveur et l'adresse "
            "d'expedition dans l'ecran Reglages.")
    if not destinataire:
        trace.noter("configuration", "echec", "aucun destinataire")
        raise ErreurCourriel("Aucun destinataire enregistre dans les Reglages.")

    trace.noter(
        "configuration", "ok",
        f"{serveur_config['hote']}:{serveur_config['port']} · "
        + ("SSL direct" if serveur_config["ssl"] else "STARTTLS")
        + " · de " + serveur_config["expediteur"]
        + " vers " + str(destinataire)
        + (f" · identifiant {serveur_config['utilisateur']}"
           if serveur_config["utilisateur"] else " · sans authentification"))

    message = EmailMessage()
    message["Subject"] = sujet
    message["From"] = formataddr(("Veille immobilière", serveur_config["expediteur"]))
    message["To"] = destinataire
    message["Date"] = formatdate(localtime=True)
    message.set_content(texte)
    if html:
        message.add_alternative(html, subtype="html")

    try:
        if serveur_config["ssl"]:
            contexte = ssl.create_default_context()
            with smtplib.SMTP_SSL(serveur_config["hote"], serveur_config["port"],
                                  context=contexte, timeout=DELAI) as serveur:
                trace.noter("connexion", "ok", "TLS etabli d'emblee (port SSL)")
                _authentifier(serveur, serveur_config, trace)
                serveur.send_message(message)
                trace.noter("envoi", "ok", "le serveur a accepte le message")
        else:
            with smtplib.SMTP(serveur_config["hote"], serveur_config["port"],
                              timeout=DELAI) as serveur:
                trace.noter("connexion", "ok", "connexion en clair etablie")
                serveur.ehlo()
                # STARTTLS quand le serveur l'annonce : on ne fait pas
                # transiter un mot de passe en clair sans le dire.
                if serveur.has_extn("starttls"):
                    serveur.starttls(context=ssl.create_default_context())
                    serveur.ehlo()
                    trace.noter("chiffrement", "ok", "STARTTLS accepte")
                elif serveur_config["motdepasse"]:
                    trace.noter(
                        "chiffrement", "echec",
                        "le serveur n'annonce pas STARTTLS sur ce port")
                    logger.warning(
                        "le serveur SMTP %s n'annonce pas STARTTLS : "
                        "le mot de passe partirait en clair, envoi refuse",
                        serveur_config["hote"])
                    raise ErreurCourriel(
                        f"{serveur_config['hote']} n'offre pas STARTTLS sur le "
                        f"port {serveur_config['port']} ; refus d'envoyer le "
                        "mot de passe en clair. Choisir « SSL direct » avec le "
                        "port 465, ou verifier le port STARTTLS (souvent 587).")
                else:
                    trace.noter("chiffrement", "attention",
                                "sans STARTTLS, mais aucun mot de passe a proteger")
                _authentifier(serveur, serveur_config, trace)
                serveur.send_message(message)
                trace.noter("envoi", "ok", "le serveur a accepte le message")
    except ErreurCourriel:
        raise
    except smtplib.SMTPAuthenticationError as erreur:
        trace.noter("authentification", "echec", f"{erreur.smtp_code} {erreur.smtp_error}")
        raise ErreurCourriel(
            f"Identifiants refuses ({erreur.smtp_code}). Verifier que "
            "l'identifiant est l'adresse complete, et que l'acces "
            "POP3/IMAP est autorise dans le compte du fournisseur.") from erreur
    except (smtplib.SMTPException, OSError, ssl.SSLError) as erreur:
        # L'etape en cours est celle qui suit la derniere reussie.
        derniere = trace.etapes[-1]["nom"] if trace.etapes else "connexion"
        suivante = {"configuration": "connexion", "connexion": "dialogue",
                    "chiffrement": "authentification",
                    "authentification": "envoi"}.get(derniere, derniere)
        trace.noter(suivante, "echec", f"{type(erreur).__name__} : {erreur}")
        raise ErreurCourriel(f"{type(erreur).__name__} : {erreur}") from erreur

    logger.info("courriel envoye a %s — %s", destinataire, sujet)
    return True


def _authentifier(serveur, serveur_config, trace=None):
    """S'authentifie si des identifiants sont fournis. Certains relais
    internes n'en demandent pas."""
    if not serveur_config["utilisateur"]:
        if trace:
            trace.noter("authentification", "ignoree", "aucun identifiant fourni")
        return
    serveur.login(serveur_config["utilisateur"], serveur_config["motdepasse"])
    if trace:
        trace.noter("authentification", "ok",
                    f"« {serveur_config['utilisateur']} » accepte")
