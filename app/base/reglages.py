# -*- coding: utf-8 -*-
"""
reglages.py — Les reglages metier, stockes en base.

Communes surveillees, points de reference bourg/plage, filtres par defaut :
tout se modifie depuis l'ecran Reglages. Rien de tout cela n'est ecrit en
dur dans le code, sinon la moindre commune ajoutee imposerait de
reconstruire l'image Docker.

Les valeurs ci-dessous reprennent celles des scripts d'origine : elles
servent de point de depart a la premiere ouverture.
"""

import datetime
import json
import logging
import re

from app.base.connexion import connexion, transaction

logger = logging.getLogger(__name__)

DEFAUTS = {
    # Mimizan-Plage n'est pas une commune distincte : meme code postal et
    # meme code INSEE que le bourg. On rattache donc chaque logement au
    # point de reference le plus proche (CDC F1).
    "zones": {
        "bourg": [44.2011, -1.2286],
        "plage": [44.2044, -1.2914],
    },

    # Le decoupage bourg / plage est INTERNE a une commune : il n'a de sens
    # que la ou les points de reference ont ete places. Sans cette
    # restriction, un logement d'Aureilhan se verrait etiqueter « bourg »
    # parce que c'est le point le plus proche — a 2 km. Et aucun seuil de
    # distance ne separe proprement les deux : Mimizan s'etend jusqu'a
    # 4 083 m de ses reperes, Aureilhan commence a 2 076 m.
    # Vide = appliquer les secteurs a toutes les communes.
    "zones_code_insee": "40184",      # Mimizan

    # Filtres par defaut de l'ecran Veille.
    "fenetre_jours": 120,
    "type_batiment": "maison",     # "maison", "appartement", ou "" pour tout
    "surface_min": 80,
    "surface_max": 400,

    # Bases ADEME interrogees (CDC 4). La chronologie F4 les veut toutes.
    "jeux_de_donnees": ["existant", "neuf", "ancien"],

    # Tolerances de l'identification F2 : de combien la base peut s'ecarter
    # des chiffres lus sur l'annonce. Les surfaces d'annonce sont souvent
    # arrondies, d'ou une marge un peu large.
    "tolerances": {
        "surface": 3.0,      # m2
        "conso": 5.0,        # kWh/m2.an
        "ges": 1.5,          # kg CO2/m2.an
    },

    # Rafraichissement paresseux : au lancement d'une recherche, si la
    # derniere moisson reussie remonte a plus de ce nombre d'heures, un
    # import part en tache de fond. 0 desactive completement.
    #
    # Le CDC 4 interdit tout appel externe declenche par le simple affichage
    # d'une page. La regle est respectee : le declencheur est l'action de
    # recherche, pas l'ouverture de l'ecran, et l'import tourne derriere
    # sans bloquer l'affichage des donnees deja en cache.
    "rafraichir_apres_heures": 24,

    # Le cadastre bouge lentement — un decoupage parcellaire ne change pas
    # toutes les semaines. Le CDC 8 prevoit un rafraichissement mensuel.
    "cadastre_apres_jours": 30,

    # Purge (CDC 9), sur `revu_le` — la derniere fois que l'ADEME a servi la
    # ligne — et non sur la date du diagnostic. Purger sur la date du
    # diagnostic rendrait le lot 2 impossible : la chronologie F4 remonte a
    # 2013, et une annonce peut citer un DPE de 2022.
    #
    # Zero veut dire « ne jamais purger », et c'est le defaut retenu :
    # l'exigence exprimee est de garder le maximum d'historique. C'est un
    # ecart assume au CDC 9, qui demande une purge a 24 mois. Il porte sur
    # une seule chose : un DPE que l'ADEME retire de sa base cesse d'etre
    # revu, et notre cache en devient l'unique trace — c'est precisement
    # celle que la chronologie F4 exploite. La purge la detruirait.
    #
    # Toute valeur positive retablit une purge en mois ; le reglage se
    # change dans l'ecran Reglages, sans redeploiement.
    "purge_mois": 0,

    # --- Alerte courriel (F6) ----------------------------------------
    # Ecart assume au CDC 9 (« aucun envoi automatique de courrier »), qui
    # prevoyait un webhook Home Assistant : le courriel a ete demande
    # explicitement. Il reste desactive par defaut — rien ne part tant
    # qu'on ne l'a pas voulu, ni sans destinataire.
    #
    "alerte_active": False,
    "alerte_destinataire": "",
    # Sur quoi porte l'alerte. Vides, elle porte sur TOUT le registre —
    # chaque commune exploree s'y ajouterait. On choisit donc une commune,
    # et au besoin un de ses secteurs.
    "alerte_code_insee": "",
    "alerte_zone": "",

    # --- Serveur d'envoi ---------------------------------------------
    # Ici plutot que dans l'environnement, pour que changer d'adresse ne
    # demande pas une session SSH sur le NAS et un redemarrage.
    #
    # Le mot de passe est donc le SEUL secret que porte cette table, et
    # elle est servie par l'API des Reglages. Il est pour cette raison
    # inscrit dans SECRETS, et `tous()` le masque par defaut : seul
    # `lire()` en rend la valeur, et seul l'envoi s'en sert.
    #
    "smtp_hote": "",
    "smtp_port": 587,
    "smtp_ssl": False,
    "smtp_expediteur": "",
    "smtp_utilisateur": "",
    "smtp_motdepasse": "",
}

# Cles dont la valeur ne doit jamais sortir par l'API. `tous()` les masque,
# et il faut la demander explicitement pour l'obtenir. Le defaut est donc
# le silence : ajouter un secret plus tard le protege sans y penser.
SECRETS = {"smtp_motdepasse"}

MASQUE = "\u2022" * 8


def smtp():
    """
    La configuration d'envoi, telle qu'elle est reglee dans l'ecran.

    Une seule source : cette table. Rien a poser dans le conteneur, rien a
    redemarrer pour changer d'adresse — et aucune ambiguite sur l'origine
    d'un reglage qui ne prend pas effet.
    """
    valeurs = tous(avec_secrets=True)
    hote = str(valeurs.get("smtp_hote") or "").strip()
    return {
        "hote": hote,
        "port": int(valeurs["smtp_port"] or 587),
        "ssl": bool(valeurs["smtp_ssl"]),
        "expediteur": str(valeurs["smtp_expediteur"] or "").strip(),
        "utilisateur": str(valeurs["smtp_utilisateur"] or "").strip(),
        "motdepasse": str(valeurs["smtp_motdepasse"] or ""),
        "source": "reglages" if hote else "aucune",
    }


def _decoder(texte, defaut):
    try:
        return json.loads(texte)
    except (TypeError, ValueError):
        logger.warning("reglage illisible en base, valeur par defaut retenue")
        return defaut


def tous(avec_secrets=False):
    """
    Renvoie tous les reglages : les valeurs enregistrees, completees par
    les valeurs par defaut pour les cles jamais modifiees.

    Les cles de SECRETS sont MASQUEES par defaut. C'est ce qui rend
    acceptable de garder un mot de passe SMTP dans cette table : l'API des
    Reglages sert le resultat de cette fonction tel quel, et ne peut donc
    pas le divulguer par inadvertance. Il faut demander `avec_secrets` pour
    l'obtenir — seul l'envoi le fait.

    Le masque n'est pas la chaine vide : un champ vide voudrait dire
    « aucun mot de passe », et l'ecran proposerait d'en saisir un alors
    qu'il en existe deja.
    """
    valeurs = dict(DEFAUTS)
    with connexion() as conn:
        for ligne in conn.execute("SELECT cle, valeur_json FROM reglage"):
            if ligne["cle"] in DEFAUTS:
                valeurs[ligne["cle"]] = _decoder(ligne["valeur_json"], DEFAUTS[ligne["cle"]])

    if not avec_secrets:
        for cle in SECRETS:
            # Le drapeau dit qu'un secret existe sans rien en reveler :
            # l'ecran a besoin de la distinction, pas de la valeur.
            valeurs[f"{cle}_defini"] = bool(valeurs.get(cle))
            valeurs[cle] = MASQUE if valeurs.get(cle) else ""
    return valeurs


def lire(cle):
    """Valeur d'un reglage, ou sa valeur par defaut."""
    if cle not in DEFAUTS:
        raise KeyError(f"reglage inconnu : {cle}")
    with connexion() as conn:
        ligne = conn.execute(
            "SELECT valeur_json FROM reglage WHERE cle = ?", (cle,)
        ).fetchone()
    if ligne is None:
        return DEFAUTS[cle]
    return _decoder(ligne["valeur_json"], DEFAUTS[cle])


def ecrire(valeurs):
    """
    Enregistre un lot de reglages, apres validation.

    Un secret renvoye MASQUE est ignore. L'ecran ne peut pas afficher le
    mot de passe enregistre : il affiche le masque, et le renvoie tel quel
    quand on enregistre autre chose sur la meme page. Le prendre au pied de
    la lettre remplacerait le mot de passe par huit puces, et l'alerte
    cesserait de partir sans que rien ne l'explique.

    La chaine vide, elle, EFFACE : c'est le seul moyen de retirer un mot de
    passe une fois pose.
    """
    valeurs = dict(valeurs)
    for cle in SECRETS:
        if cle in valeurs and str(valeurs[cle]) == MASQUE:
            del valeurs[cle]
    if not valeurs:
        return tous()

    valider(valeurs)
    maintenant = datetime.datetime.now().isoformat(timespec="seconds")
    with transaction() as conn:
        for cle, valeur in valeurs.items():
            conn.execute(
                "INSERT INTO reglage (cle, valeur_json, maj_le) VALUES (?, ?, ?) "
                "ON CONFLICT(cle) DO UPDATE SET valeur_json = excluded.valeur_json, "
                "                               maj_le = excluded.maj_le",
                (cle, json.dumps(valeur, ensure_ascii=False), maintenant),
            )
    logger.info("reglages mis a jour : %s", ", ".join(sorted(valeurs)))
    return tous()


# ---------------------------------------------------------------------
#  Validation
# ---------------------------------------------------------------------
# Un reglage aberrant (surface maximale inferieure a la minimale, latitude
# a 300 degres) ne doit pas pouvoir entrer en base : il produirait un ecran
# Veille vide sans que rien n'explique pourquoi.

def valider(valeurs):
    inconnues = set(valeurs) - set(DEFAUTS)
    if inconnues:
        raise ValueError(f"reglage(s) inconnu(s) : {', '.join(sorted(inconnues))}")

    if "zones" in valeurs:
        zones = valeurs["zones"]
        if not isinstance(zones, dict) or not zones:
            raise ValueError("Il faut au moins un point de reference de secteur.")
        for nom, point in zones.items():
            if (not isinstance(point, (list, tuple)) or len(point) != 2):
                raise ValueError(f"Secteur {nom!r} : latitude et longitude attendues.")
            try:
                lat, lon = float(point[0]), float(point[1])
            except (TypeError, ValueError):
                raise ValueError(f"Secteur {nom!r} : coordonnees non numeriques.")
            if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
                raise ValueError(f"Secteur {nom!r} : coordonnees hors des bornes terrestres.")

    if "jeux_de_donnees" in valeurs:
        jeux = valeurs["jeux_de_donnees"]
        connus = {"existant", "neuf", "ancien"}
        if not isinstance(jeux, list) or not jeux:
            raise ValueError("Il faut au moins une base ADEME.")
        inconnus = set(jeux) - connus
        if inconnus:
            raise ValueError(
                f"Base(s) ADEME inconnue(s) : {', '.join(sorted(inconnus))}. "
                f"Valeurs possibles : {', '.join(sorted(connus))}.")

    if "tolerances" in valeurs:
        tolerances = valeurs["tolerances"]
        if not isinstance(tolerances, dict):
            raise ValueError("Les tolerances doivent former un ensemble cle/valeur.")
        for cle in ("surface", "conso", "ges"):
            if cle not in tolerances:
                raise ValueError(f"Tolerance manquante : {cle}.")
            try:
                marge = float(tolerances[cle])
            except (TypeError, ValueError):
                raise ValueError(f"Tolerance {cle} : un nombre est attendu.")
            # Une tolerance nulle n'ecarte pas seulement les arrondis : elle
            # exige une egalite au centieme, et ne remonte plus rien.
            if not (0 < marge <= 1000):
                raise ValueError(f"Tolerance {cle} : attendue entre 0 (exclu) et 1000.")

    for cle, mini, maxi in [("fenetre_jours", 1, 3650),
                            ("surface_min", 0, 10000),
                            ("surface_max", 0, 10000),
                            ("purge_mois", 0, 600),   # 0 = jamais
                            ("rafraichir_apres_heures", 0, 8760),
                            ("cadastre_apres_jours", 0, 3650)]:
        if cle in valeurs:
            try:
                nombre = float(valeurs[cle])
            except (TypeError, ValueError):
                raise ValueError(f"{cle} : un nombre est attendu.")
            if not (mini <= nombre <= maxi):
                raise ValueError(f"{cle} doit etre compris entre {mini} et {maxi}.")

    surface_min = valeurs.get("surface_min")
    surface_max = valeurs.get("surface_max")
    if surface_min is not None and surface_max is not None:
        if float(surface_min) > float(surface_max):
            raise ValueError("La surface minimale depasse la surface maximale.")

    if "smtp_port" in valeurs:
        try:
            port = int(valeurs["smtp_port"])
        except (TypeError, ValueError):
            raise ValueError("Port SMTP : un nombre entier est attendu.")
        if not (1 <= port <= 65535):
            raise ValueError("Port SMTP : attendu entre 1 et 65535.")

    for cle, etiquette in [("smtp_expediteur", "Adresse d'expedition")]:
        if cle in valeurs:
            adresse = str(valeurs[cle] or "").strip()
            if adresse and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", adresse):
                raise ValueError(f"{etiquette} invalide : {adresse!r}.")

    # Un hote sans expediteur ne peut rien envoyer : le serveur refuserait
    # a la premiere alerte, et on ne le saurait qu'a ce moment-la.
    if "smtp_hote" in valeurs or "smtp_expediteur" in valeurs:
        courant = tous(avec_secrets=True)
        hote = str(valeurs.get("smtp_hote", courant["smtp_hote"]) or "").strip()
        expediteur = str(valeurs.get("smtp_expediteur",
                                     courant["smtp_expediteur"]) or "").strip()
        if hote and not expediteur:
            raise ValueError(
                "Un serveur d'envoi demande une adresse d'expedition.")

    if "alerte_code_insee" in valeurs:
        code = str(valeurs["alerte_code_insee"] or "").strip()
        if code and not (code.isalnum() and len(code) == 5):
            raise ValueError(
                f"Code INSEE invalide pour l'alerte : {code!r} (cinq "
                "caracteres attendus, ou vide pour toutes les communes).")

    if "zones_code_insee" in valeurs:
        code = str(valeurs["zones_code_insee"] or "").strip()
        if code and not (code.isalnum() and len(code) == 5):
            raise ValueError(
                f"Code INSEE invalide : {code!r} (cinq caracteres attendus, "
                "ou vide pour appliquer les secteurs partout).")

    if "type_batiment" in valeurs:
        if str(valeurs["type_batiment"]).lower() not in ("", "maison", "appartement"):
            raise ValueError("type_batiment : \"maison\", \"appartement\", ou vide.")

    # Une adresse mal saisie ne se voit qu'au premier bien manque : le
    # serveur SMTP accepte, puis rejette en silence. On la controle ici.
    if "alerte_destinataire" in valeurs:
        adresse = str(valeurs["alerte_destinataire"] or "").strip()
        if adresse and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", adresse):
            raise ValueError(f"Adresse de courriel invalide : {adresse!r}.")

    # Activer l'alerte sans destinataire ne previendrait personne, et rien
    # ne le dirait avant le premier DPE manque.
    if valeurs.get("alerte_active"):
        adresse = str(valeurs.get("alerte_destinataire",
                                  lire("alerte_destinataire")) or "").strip()
        if not adresse:
            raise ValueError(
                "Activer l'alerte demande une adresse de destinataire.")
