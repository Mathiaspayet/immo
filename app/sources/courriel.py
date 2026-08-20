# -*- coding: utf-8 -*-
"""
courriel.py — L'envoi SMTP.

Isole dans sa propre source pour une raison pratique : le reste de
l'application doit pouvoir etre teste sans serveur de mail. Tout ce qui
parle a un serveur passe par `envoyer`, que les tests remplacent.

L'application n'a ni compte ni cle d'API ailleurs : les identifiants SMTP
sont ses seuls secrets, et ils viennent de l'environnement (voir config).
"""

import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, formatdate

from app import config

logger = logging.getLogger(__name__)


class ErreurCourriel(Exception):
    """L'envoi a echoue. Jamais fatale : l'import prime sur l'alerte."""


def envoyer(destinataire, sujet, texte, html=None):
    """
    Envoie un message. Leve ErreurCourriel si le serveur refuse.

    Le corps part en texte brut ET en HTML : le texte reste lisible dans un
    client qui n'affiche pas le second, et c'est aussi ce qui evite qu'un
    message tout-HTML soit classe en indesirable.
    """
    if not config.smtp_configure():
        raise ErreurCourriel(
            "SMTP non configure : renseigner VEILLE_SMTP_HOTE et "
            "VEILLE_SMTP_EXPEDITEUR dans le .env du conteneur.")
    if not destinataire:
        raise ErreurCourriel("Aucun destinataire enregistre dans les Reglages.")

    message = EmailMessage()
    message["Subject"] = sujet
    message["From"] = formataddr(("Veille immobilière", config.SMTP_EXPEDITEUR))
    message["To"] = destinataire
    message["Date"] = formatdate(localtime=True)
    message.set_content(texte)
    if html:
        message.add_alternative(html, subtype="html")

    try:
        if config.SMTP_SSL:
            contexte = ssl.create_default_context()
            with smtplib.SMTP_SSL(config.SMTP_HOTE, config.SMTP_PORT,
                                  context=contexte, timeout=30) as serveur:
                _authentifier(serveur)
                serveur.send_message(message)
        else:
            with smtplib.SMTP(config.SMTP_HOTE, config.SMTP_PORT, timeout=30) as serveur:
                serveur.ehlo()
                # STARTTLS quand le serveur l'annonce : on ne fait pas
                # transiter un mot de passe en clair sans le dire.
                if serveur.has_extn("starttls"):
                    serveur.starttls(context=ssl.create_default_context())
                    serveur.ehlo()
                elif config.SMTP_MOTDEPASSE:
                    logger.warning(
                        "le serveur SMTP %s n'annonce pas STARTTLS : "
                        "le mot de passe partirait en clair, envoi refuse",
                        config.SMTP_HOTE)
                    raise ErreurCourriel(
                        f"{config.SMTP_HOTE} n'offre pas STARTTLS ; refus "
                        "d'envoyer le mot de passe en clair. Utiliser le "
                        "port 465 avec VEILLE_SMTP_SSL=1.")
                _authentifier(serveur)
                serveur.send_message(message)
    except ErreurCourriel:
        raise
    except (smtplib.SMTPException, OSError, ssl.SSLError) as erreur:
        raise ErreurCourriel(f"{type(erreur).__name__} : {erreur}") from erreur

    logger.info("courriel envoye a %s — %s", destinataire, sujet)
    return True


def _authentifier(serveur):
    """S'authentifie si des identifiants sont fournis. Certains relais
    internes n'en demandent pas."""
    if config.SMTP_UTILISATEUR:
        serveur.login(config.SMTP_UTILISATEUR, config.SMTP_MOTDEPASSE)
