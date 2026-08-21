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
from email.message import EmailMessage
from email.utils import formataddr, formatdate

from app.base import reglages

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
    serveur_config = reglages.smtp()
    if not (serveur_config["hote"] and serveur_config["expediteur"]):
        raise ErreurCourriel(
            "Envoi non configure : renseigner le serveur et l'adresse "
            "d'expedition dans l'ecran Reglages.")
    if not destinataire:
        raise ErreurCourriel("Aucun destinataire enregistre dans les Reglages.")

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
                                  context=contexte, timeout=30) as serveur:
                _authentifier(serveur, serveur_config)
                serveur.send_message(message)
        else:
            with smtplib.SMTP(serveur_config["hote"], serveur_config["port"],
                              timeout=30) as serveur:
                serveur.ehlo()
                # STARTTLS quand le serveur l'annonce : on ne fait pas
                # transiter un mot de passe en clair sans le dire.
                if serveur.has_extn("starttls"):
                    serveur.starttls(context=ssl.create_default_context())
                    serveur.ehlo()
                elif serveur_config["motdepasse"]:
                    logger.warning(
                        "le serveur SMTP %s n'annonce pas STARTTLS : "
                        "le mot de passe partirait en clair, envoi refuse",
                        serveur_config["hote"])
                    raise ErreurCourriel(
                        f"{serveur_config['hote']} n'offre pas STARTTLS ; "
                        "refus d'envoyer le mot de passe en clair. Cocher "
                        "« SSL direct » et utiliser le port 465.")
                _authentifier(serveur, serveur_config)
                serveur.send_message(message)
    except ErreurCourriel:
        raise
    except (smtplib.SMTPException, OSError, ssl.SSLError) as erreur:
        raise ErreurCourriel(f"{type(erreur).__name__} : {erreur}") from erreur

    logger.info("courriel envoye a %s — %s", destinataire, sujet)
    return True


def _authentifier(serveur, serveur_config):
    """S'authentifie si des identifiants sont fournis. Certains relais
    internes n'en demandent pas."""
    if serveur_config["utilisateur"]:
        serveur.login(serveur_config["utilisateur"], serveur_config["motdepasse"])
