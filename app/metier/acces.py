# -*- coding: utf-8 -*-
"""
acces.py — Le mot de passe de l'application.

Un seul mot de passe, aucun compte : l'application n'a qu'un utilisateur.
Ecart assume au CDC 9, qui la voulait sans authentification derriere le
proxy inverse du NAS ; elle a ete demandee protegee.

COMMENT ON LE CHOISIT. Au premier lancement il n'existe pas, et rien ne
permet de distinguer le proprietaire d'un visiteur du reseau. La preuve
est donc la boite aux lettres : un lien part a une adresse que l'ecran ne
permet plus de changer une fois l'application verrouillee — celle posee
dans le conteneur (VEILLE_ACCES_COURRIEL), sinon celle des alertes. Le
meme lien sert a remplacer un mot de passe oublie.

Le lien ne vaut qu'une fois, trente minutes. Il porte le jeton dans le
FRAGMENT de l'adresse (#acces=...) : un fragment ne part jamais vers le
serveur, n'entre donc dans aucun journal, et ne se transmet pas aux sites
qu'on visiterait ensuite.

OU MENE LE LIEN. L'application ne connait pas sa propre adresse, et celui
qui demande le lien n'est pas connecte : ce qu'annonce sa requete ne
prouve rien. Prise au mot, elle permettait de faire partir un courriel
authentique dont le lien menait chez un tiers — qui n'avait plus qu'a y
lire le jeton. Le lien ne mene donc qu'a une adresse de confiance :
celle posee dans le conteneur (VEILLE_URL), une adresse d'ou le
proprietaire s'est deja servi de l'application mot de passe a l'appui,
ou une adresse du reseau local, qu'un tiers exterieur ne peut pas tenir.

CE QUI EST GARDE. Rien en clair : le mot de passe est derive par scrypt
(sel aleatoire, 16 Mo de memoire par essai), les jetons et les sessions
ne sont conserves que par leur empreinte SHA-256. Une sauvegarde de la
base — il s'en fait une chaque jour — n'ouvre pas l'application.

LES ESSAIS. Apres cinq mots de passe faux, chaque essai doit attendre :
une seconde, puis deux, quatre... jusqu'a une minute. Le compteur est
commun a tous — l'adresse d'origine ne distingue rien derriere le proxy
inverse — ce qui permet a un importun de faire patienter le proprietaire
une minute, jamais de deviner un mot de passe de dix caracteres.

LE RECOURS, quand le courriel ne part pas : depuis le NAS,

    docker exec veille_immo python -m app.metier.acces

imprime un lien a usage unique. Avoir la main sur le conteneur, c'est
deja etre le proprietaire.
"""

import datetime
import hashlib
import hmac
import html
import ipaddress
import logging
import math
import re
import secrets
import threading
import time
import urllib.parse

from app import config
from app.base import reglages
from app.base.connexion import connexion, transaction
from app.sources import courriel

logger = logging.getLogger(__name__)

COOKIE = "veille_session"
LONGUEUR_MIN = 10
LONGUEUR_MAX = 256
DUREE_LIEN = datetime.timedelta(minutes=30)
# Une session tombe apres trente jours SANS VENIR ; chaque visite la
# prolonge. Le cookie, lui, vit un an : c'est le serveur qui decide.
DUREE_SESSION = datetime.timedelta(days=30)
DUREE_COOKIE = 365 * 24 * 3600
# On ne reecrit pas la session a chaque requete : la carte en lance des
# dizaines, et une ecriture par heure suffit a la prolonger.
PROLONGER_APRES = datetime.timedelta(hours=1)

INTERVALLE_LIENS = datetime.timedelta(seconds=60)
LIENS_PAR_HEURE = 5
ESSAIS_LIBRES = 5
ATTENTE_MAX = 60

# scrypt : n = 2^14, r = 8 — 16 Mo et une fraction de seconde sur le NAS.
SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1}

# Les adresses de confiance qu'on garde, et la forme qu'elles doivent avoir.
ORIGINES_GARDEES = 20
FORME_ORIGINE = re.compile(r"https?://[A-Za-z0-9.\-_\[\]:]{1,200}")
# Ce qui ne se resout que sur un reseau local : un tiers exterieur ne peut
# pas y installer sa page.
SUFFIXES_LOCAUX = (".local", ".lan", ".home", ".home.arpa", ".internal", ".localdomain")

_verrou = threading.Lock()
_echecs = {"nombre": 0, "prochain": 0.0}
# Les origines deja retenues par ce processus : evite une ecriture en base
# a chaque requete.
_origines_vues = set()


class RefusAcces(Exception):
    """Une demande refusee, avec le code HTTP qui la dit et un message affichable."""

    def __init__(self, statut, message, attente=None):
        super().__init__(message)
        self.statut = statut
        self.attente = attente


# ---------------------------------------------------------------------
#  Outils
# ---------------------------------------------------------------------

def _maintenant():
    return datetime.datetime.now().replace(microsecond=0)


def _iso(moment):
    return moment.isoformat(timespec="seconds")


def _empreinte(jeton):
    return hashlib.sha256(jeton.encode("utf-8")).hexdigest()


def deriver(motdepasse, sel=None):
    """L'empreinte scrypt d'un mot de passe, parametres et sel compris."""
    sel = sel or secrets.token_bytes(16)
    cle = hashlib.scrypt(motdepasse.encode("utf-8"), salt=sel, dklen=32,
                         maxmem=64 * 1024 * 1024, **SCRYPT)
    return f"scrypt${SCRYPT['n']}${SCRYPT['r']}${SCRYPT['p']}${sel.hex()}${cle.hex()}"


def _conforme(motdepasse, empreinte):
    try:
        _nom, n, r, p, sel, attendu = empreinte.split("$")
        cle = hashlib.scrypt(motdepasse.encode("utf-8"), salt=bytes.fromhex(sel),
                             n=int(n), r=int(r), p=int(p), dklen=len(attendu) // 2,
                             maxmem=64 * 1024 * 1024)
    except (ValueError, TypeError):
        logger.error("empreinte du mot de passe illisible en base")
        return False
    return hmac.compare_digest(cle.hex(), attendu)


def _valider(motdepasse):
    if not isinstance(motdepasse, str) or len(motdepasse) < LONGUEUR_MIN:
        raise RefusAcces(400, f"Le mot de passe doit compter au moins {LONGUEUR_MIN} caractères.")
    if len(motdepasse) > LONGUEUR_MAX:
        raise RefusAcces(400, f"Le mot de passe ne doit pas dépasser {LONGUEUR_MAX} caractères.")


def masquer(adresse):
    """« m•••••••@gmail.com » : de quoi reconnaitre son adresse, pas de quoi la lire."""
    nom, _, domaine = (adresse or "").partition("@")
    if not nom or not domaine:
        return ""
    return nom[0] + "•" * max(len(nom) - 1, 3) + "@" + domaine


def destinataire():
    """L'adresse ou part le lien : celle du conteneur, sinon celle des alertes."""
    return config.COURRIEL_ACCES or str(reglages.lire("alerte_destinataire") or "").strip()


def initialise():
    with connexion() as conn:
        return conn.execute("SELECT 1 FROM acces WHERE id = 1").fetchone() is not None


# ---------------------------------------------------------------------
#  Les adresses de confiance
# ---------------------------------------------------------------------

def _origine(valeur):
    """« https://hote:port », ou None si la valeur n'a pas cette forme."""
    valeur = str(valeur or "").strip().rstrip("/")
    return valeur if FORME_ORIGINE.fullmatch(valeur) else None


def est_locale(origine):
    """Cette adresse ne peut-elle se trouver que sur le reseau local ?"""
    try:
        hote = (urllib.parse.urlsplit(origine).hostname or "").lower().rstrip(".")
    except ValueError:
        return False
    if not hote:
        return False
    try:
        return not ipaddress.ip_address(hote).is_global
    except ValueError:
        pass
    # Un nom sans point (« nas », « localhost ») ou d'un domaine reserve
    # aux reseaux prives : rien de cela ne s'achete ni ne se resout dehors.
    return "." not in hote or hote.endswith(SUFFIXES_LOCAUX)


def deja_retenue(origine):
    """Ce processus a-t-il deja note cette adresse ? Sans toucher a la base."""
    return origine in _origines_vues


def retenir_origine(origine, toujours=False):
    """
    Note une adresse d'ou le proprietaire vient de se servir de
    l'application. A n'appeler que pour une requete AUTHENTIFIEE : c'est
    ce qui fait de cette adresse une adresse de confiance.
    """
    origine = _origine(origine)
    if origine is None or (origine in _origines_vues and not toujours):
        return
    with transaction() as conn:
        conn.execute(
            "INSERT INTO acces_origine (origine, vue_le) VALUES (?, ?)"
            " ON CONFLICT(origine) DO UPDATE SET vue_le = excluded.vue_le",
            (origine, _iso(_maintenant())))
        conn.execute(
            "DELETE FROM acces_origine WHERE origine NOT IN ("
            " SELECT origine FROM acces_origine ORDER BY vue_le DESC LIMIT ?)",
            (ORIGINES_GARDEES,))
    _origines_vues.add(origine)


def origines_de_confiance():
    """Les adresses retenues, la plus recemment vue d'abord."""
    with connexion() as conn:
        return [ligne["origine"] for ligne in conn.execute(
            "SELECT origine FROM acces_origine ORDER BY vue_le DESC, origine")]


def adresse_du_lien(demandee):
    """
    L'adresse ou le lien menera, ou None si aucune n'est sure.

    `demandee` est celle qu'annonce la requete : on ne la suit que si elle
    est deja de confiance, ou locale. Sinon le lien mene a la derniere
    adresse d'ou le proprietaire s'est connecte.
    """
    if config.URL_PUBLIQUE:
        return config.URL_PUBLIQUE
    demandee = _origine(demandee)
    connues = origines_de_confiance()
    if demandee and (demandee in connues or est_locale(demandee)):
        return demandee
    return connues[0] if connues else None


# ---------------------------------------------------------------------
#  Les sessions
# ---------------------------------------------------------------------

def _ouvrir_session(conn, appareil):
    jeton = secrets.token_urlsafe(32)
    maintenant = _maintenant()
    conn.execute("DELETE FROM acces_session WHERE expire_le < ?", (_iso(maintenant),))
    conn.execute(
        "INSERT INTO acces_session (empreinte, cree_le, vu_le, expire_le, appareil)"
        " VALUES (?, ?, ?, ?, ?)",
        (_empreinte(jeton), _iso(maintenant), _iso(maintenant),
         _iso(maintenant + DUREE_SESSION), (appareil or "")[:200]))
    return jeton


def session_valide(jeton):
    """Ce jeton ouvre-t-il l'application ? Le prolonge au passage."""
    if not jeton:
        return False
    empreinte = _empreinte(jeton)
    maintenant = _maintenant()
    with connexion() as conn:
        ligne = conn.execute(
            "SELECT vu_le, expire_le FROM acces_session WHERE empreinte = ?",
            (empreinte,)).fetchone()
        if ligne is None or ligne["expire_le"] < _iso(maintenant):
            return False
        if ligne["vu_le"] < _iso(maintenant - PROLONGER_APRES):
            conn.execute(
                "UPDATE acces_session SET vu_le = ?, expire_le = ? WHERE empreinte = ?",
                (_iso(maintenant), _iso(maintenant + DUREE_SESSION), empreinte))
    return True


def deconnecter(jeton, partout=False):
    """Ferme cette session, ou toutes quand elle est encore valide."""
    if not jeton:
        return
    partout = partout and session_valide(jeton)
    with transaction() as conn:
        if partout:
            conn.execute("DELETE FROM acces_session")
            logger.info("acces : tous les appareils deconnectes")
        else:
            conn.execute("DELETE FROM acces_session WHERE empreinte = ?", (_empreinte(jeton),))


def etat(jeton=None):
    """Ce que l'ecran de connexion doit savoir. Ne revele que l'adresse masquee."""
    adresse = destinataire()
    serveur = reglages.smtp()
    return {
        "initialise": initialise(),
        "connecte": session_valide(jeton),
        "destinataire": masquer(adresse),
        "envoi_possible": bool(adresse and serveur["hote"] and serveur["expediteur"]),
        "longueur_min": LONGUEUR_MIN,
    }


# ---------------------------------------------------------------------
#  Le lien
# ---------------------------------------------------------------------

def emettre_jeton(verifier_rythme=True):
    """Un jeton neuf, a usage unique. Refuse d'en emettre trop, trop vite."""
    maintenant = _maintenant()
    with transaction() as conn:
        conn.execute("DELETE FROM acces_jeton WHERE expire_le < ?",
                     (_iso(maintenant - datetime.timedelta(days=1)),))
        if verifier_rythme:
            lignes = conn.execute(
                "SELECT cree_le, utilise_le FROM acces_jeton WHERE cree_le >= ?"
                " ORDER BY cree_le DESC",
                (_iso(maintenant - datetime.timedelta(hours=1)),)).fetchall()
            recents = [ligne["cree_le"] for ligne in lignes]
            # Seul un lien encore valable attend dans la boite : celui qui
            # a deja servi ne justifie pas de faire patienter.
            en_attente = [ligne["cree_le"] for ligne in lignes if ligne["utilise_le"] is None]
            if en_attente and en_attente[0] >= _iso(maintenant - INTERVALLE_LIENS):
                raise RefusAcces(429, "Un lien vient de partir : vérifiez votre boîte, "
                                      "ou patientez une minute avant d'en demander un autre.",
                                 attente=int(INTERVALLE_LIENS.total_seconds()))
            if len(recents) >= LIENS_PAR_HEURE:
                raise RefusAcces(429, f"{LIENS_PAR_HEURE} liens demandés en une heure : "
                                      "réessayez plus tard.", attente=3600)
        jeton = secrets.token_urlsafe(32)
        conn.execute("INSERT INTO acces_jeton (empreinte, cree_le, expire_le) VALUES (?, ?, ?)",
                     (_empreinte(jeton), _iso(maintenant), _iso(maintenant + DUREE_LIEN)))
    return jeton


def _oublier_jeton(jeton):
    with transaction() as conn:
        conn.execute("DELETE FROM acces_jeton WHERE empreinte = ?", (_empreinte(jeton),))


def envoyer_lien(adresse_demandee):
    """
    Envoie le lien qui choisit — ou remplace — le mot de passe.

    `adresse_demandee` est celle qu'annonce la requete ; le lien ne la suit
    que si elle est de confiance (voir `adresse_du_lien`).
    """
    adresse = destinataire()
    if not adresse:
        raise RefusAcces(503, "Aucune adresse où envoyer le lien : ni VEILLE_ACCES_COURRIEL "
                              "dans le conteneur, ni destinataire des alertes enregistré.")
    serveur = reglages.smtp()
    if not (serveur["hote"] and serveur["expediteur"]):
        raise RefusAcces(503, "Le serveur d'envoi n'est pas configuré : le lien ne peut pas "
                              "partir. Voir le recours depuis le NAS dans la documentation.")

    adresse_application = adresse_du_lien(adresse_demandee)
    if adresse_application is None:
        raise RefusAcces(409, "Le lien ne peut pas partir depuis cette adresse : "
                              "l'application ne s'y est jamais connectée, et rien ne prouve "
                              "que ce soit la sienne. Demandez-le depuis le réseau local "
                              "(http://<nas>:8020), ou indiquez l'adresse de l'application "
                              "dans le conteneur (VEILLE_URL), ou utilisez le recours du NAS.")

    deja = initialise()
    jeton = emettre_jeton()
    lien = f"{adresse_application}/#acces={jeton}"
    action = "changer" if deja else "choisir"
    minutes = int(DUREE_LIEN.total_seconds() // 60)
    texte = (
        f"Pour {action} le mot de passe de la Veille immobilière, ouvrez ce lien :\n\n"
        f"{lien}\n\n"
        f"Il est valable {minutes} minutes et ne sert qu'une fois. Il ouvre "
        f"l'application à l'adresse {adresse_application}.\n\n"
        "Vous n'avez rien demandé ? Ignorez ce message : tant que le lien "
        "n'est pas ouvert, rien ne change.")
    corps_html = f"""<html><body style="font-family:system-ui,sans-serif">
  <p>Pour {action} le mot de passe de la Veille immobilière&nbsp;:</p>
  <p><a href="{html.escape(lien)}" style="display:inline-block;padding:10px 16px;
     background:#2E5B4C;color:#fff;text-decoration:none;border-radius:3px">
     {action.capitalize()} le mot de passe</a></p>
  <p style="color:#555;font-size:13px">Valable {minutes} minutes, une seule fois.
  Le lien ouvre l'application à l'adresse {html.escape(adresse_application)}.</p>
  <p style="color:#555;font-size:13px">Vous n'avez rien demandé&nbsp;? Ignorez ce
  message&nbsp;: tant que le lien n'est pas ouvert, rien ne change.</p>
</body></html>"""
    try:
        courriel.envoyer(adresse, f"Veille immobilière — {action} le mot de passe",
                         texte, corps_html)
    except courriel.ErreurCourriel as erreur:
        # Un lien qui n'est pas parti ne doit ni servir, ni compter dans
        # le rythme : on pourrait ne plus en redemander de l'heure.
        _oublier_jeton(jeton)
        raise RefusAcces(502, f"Le courriel n'est pas parti : {erreur}") from erreur
    logger.info("acces : lien envoye a %s", masquer(adresse))
    return {"envoye": True, "destinataire": masquer(adresse), "valable_minutes": minutes,
            # L'ecran dit quand le lien menera ailleurs que la ou on se
            # trouve — sans dire ou : celui qui demande n'est pas connecte.
            "meme_adresse": adresse_application == _origine(adresse_demandee)}


def definir(jeton, motdepasse, appareil=""):
    """
    Pose le mot de passe avec le jeton d'un lien. Deconnecte tous les
    appareils, et connecte celui-ci. Rend le jeton de sa session.
    """
    _valider(motdepasse)
    if not isinstance(jeton, str) or not jeton:
        raise RefusAcces(400, "Lien incomplet : ouvrez celui du courriel tel quel.")
    empreinte = deriver(motdepasse)
    maintenant = _iso(_maintenant())
    with transaction() as conn:
        ligne = conn.execute(
            "SELECT 1 FROM acces_jeton WHERE empreinte = ? AND utilise_le IS NULL"
            " AND expire_le >= ?", (_empreinte(jeton), maintenant)).fetchone()
        if ligne is None:
            raise RefusAcces(400, "Ce lien n'est plus valable : il a déjà servi, ou ses "
                                  "30 minutes sont passées. Demandez-en un nouveau.")
        deja = conn.execute("SELECT 1 FROM acces WHERE id = 1").fetchone() is not None
        # Les autres liens en circulation tombent avec : un seul sert.
        conn.execute("UPDATE acces_jeton SET utilise_le = ? WHERE utilise_le IS NULL",
                     (maintenant,))
        conn.execute(
            "INSERT INTO acces (id, empreinte, defini_le) VALUES (1, ?, ?)"
            " ON CONFLICT(id) DO UPDATE SET empreinte = excluded.empreinte,"
            "                               defini_le = excluded.defini_le",
            (empreinte, maintenant))
        conn.execute("DELETE FROM acces_session")
        session = _ouvrir_session(conn, appareil)
    logger.info("acces : mot de passe %s", "remplace" if deja else "choisi")
    _prevenir("changé" if deja else "choisi")
    return session


def _prevenir(quoi):
    """Dit au proprietaire que le mot de passe a change — utile si ce n'est pas lui."""
    adresse = destinataire()
    if not adresse:
        return
    quand = _maintenant().strftime("%d/%m/%Y à %H:%M")
    texte = (f"Le mot de passe de la Veille immobilière vient d'être {quoi}, le {quand}. "
             "Les autres appareils ont été déconnectés.\n\n"
             "Si ce n'est pas vous, demandez un lien depuis l'écran de connexion : "
             "il arrive à cette adresse, et lui seul permet de reprendre la main.")
    try:
        courriel.envoyer(adresse, f"Veille immobilière — mot de passe {quoi}", texte)
    except courriel.ErreurCourriel as erreur:
        logger.warning("acces : avis de changement non envoye : %s", erreur)


# ---------------------------------------------------------------------
#  La connexion
# ---------------------------------------------------------------------

def _attente():
    with _verrou:
        return max(0, math.ceil(_echecs["prochain"] - time.monotonic()))


def _noter_echec():
    with _verrou:
        _echecs["nombre"] += 1
        exces = _echecs["nombre"] - ESSAIS_LIBRES
        delai = 0 if exces < 0 else min(2 ** exces, ATTENTE_MAX)
        _echecs["prochain"] = time.monotonic() + delai


def _oublier_echecs():
    with _verrou:
        _echecs.update(nombre=0, prochain=0.0)


def _verifier(motdepasse):
    """Le mot de passe est-il le bon ? Leve s'il faut patienter, ou s'il n'y en a pas."""
    attente = _attente()
    if attente:
        raise RefusAcces(429, f"Trop d'essais : réessayez dans {attente} s.", attente=attente)
    with connexion() as conn:
        ligne = conn.execute("SELECT empreinte FROM acces WHERE id = 1").fetchone()
    if ligne is None:
        raise RefusAcces(409, "Aucun mot de passe n'est encore choisi : demandez le lien.")
    if not isinstance(motdepasse, str) or not motdepasse \
            or len(motdepasse) > LONGUEUR_MAX or not _conforme(motdepasse, ligne["empreinte"]):
        _noter_echec()
        logger.warning("acces : mot de passe incorrect")
        raise RefusAcces(401, "Mot de passe incorrect.")
    _oublier_echecs()


def connecter(motdepasse, appareil=""):
    """Ouvre une session si le mot de passe est le bon. Rend son jeton."""
    _verifier(motdepasse)
    with transaction() as conn:
        session = _ouvrir_session(conn, appareil)
    return session


def changer(actuel, nouveau, appareil=""):
    """Remplace le mot de passe, l'actuel en main. Deconnecte les autres appareils."""
    _valider(nouveau)
    _verifier(actuel)
    # Derive AVANT de prendre le verrou d'ecriture : scrypt prend son temps.
    empreinte = deriver(nouveau)
    with transaction() as conn:
        conn.execute("UPDATE acces SET empreinte = ?, defini_le = ? WHERE id = 1",
                     (empreinte, _iso(_maintenant())))
        conn.execute("DELETE FROM acces_session")
        session = _ouvrir_session(conn, appareil)
    logger.info("acces : mot de passe change")
    _prevenir("changé")
    return session


if __name__ == "__main__":
    # Le recours depuis le NAS. Pas de rythme a respecter : qui tape cette
    # commande a deja la main sur le conteneur.
    from app.base import migrations
    migrations.appliquer()
    jeton = emettre_jeton(verifier_rythme=False)
    minutes = int(DUREE_LIEN.total_seconds() // 60)
    print("Lien a usage unique, valable", minutes, "minutes. Ouvrir, a l'adresse")
    print("habituelle de l'application (http://<nas>:8020 par exemple) :")
    print()
    print(f"    /#acces={jeton}")
