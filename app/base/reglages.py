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

from app.base.connexion import connexion, transaction

logger = logging.getLogger(__name__)

DEFAUTS = {
    # Codes postaux surveilles. Le 40200 couvre plusieurs communes, d'ou le
    # filtre `commune` qui restreint au seul Mimizan.
    "communes": [{"code_postal": "40200", "commune": "Mimizan"}],

    # Mimizan-Plage n'est pas une commune distincte : meme code postal et
    # meme code INSEE que le bourg. On rattache donc chaque logement au
    # point de reference le plus proche (CDC F1).
    "zones": {
        "bourg": [44.2011, -1.2286],
        "plage": [44.2044, -1.2914],
    },

    # Filtres par defaut de l'ecran Veille.
    "fenetre_jours": 120,
    "type_batiment": "maison",     # "maison", "appartement", ou "" pour tout
    "surface_min": 80,
    "surface_max": 400,

    # Purge : le CDC 9 impose de ne pas conserver la veille au-dela de
    # 24 mois. A savoir avant le lot 2 : ce reglage supprime aussi les DPE
    # anciens du cache, dont la fonction F2 (identifier un bien depuis une
    # annonce) aura besoin — une annonce peut citer un DPE de 2022. Il
    # faudra alors le porter a 60 mois, soit toute la profondeur de la
    # base dpe03existant, qui demarre en juillet 2021.
    "purge_mois": 24,
}


def _decoder(texte, defaut):
    try:
        return json.loads(texte)
    except (TypeError, ValueError):
        logger.warning("reglage illisible en base, valeur par defaut retenue")
        return defaut


def tous():
    """Renvoie tous les reglages : les valeurs enregistrees, completees par
    les valeurs par defaut pour les cles jamais modifiees."""
    valeurs = dict(DEFAUTS)
    with connexion() as conn:
        for ligne in conn.execute("SELECT cle, valeur_json FROM reglage"):
            if ligne["cle"] in DEFAUTS:
                valeurs[ligne["cle"]] = _decoder(ligne["valeur_json"], DEFAUTS[ligne["cle"]])
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
    """Enregistre un lot de reglages, apres validation."""
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

    if "communes" in valeurs:
        communes = valeurs["communes"]
        if not isinstance(communes, list) or not communes:
            raise ValueError("Il faut au moins une commune surveillee.")
        for entree in communes:
            if not isinstance(entree, dict) or not str(entree.get("code_postal", "")).strip():
                raise ValueError("Chaque commune doit porter un code postal.")
            code = str(entree["code_postal"]).strip()
            if not (code.isdigit() and len(code) == 5):
                raise ValueError(f"Code postal invalide : {code!r} (cinq chiffres attendus).")

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

    for cle, mini, maxi in [("fenetre_jours", 1, 3650),
                            ("surface_min", 0, 10000),
                            ("surface_max", 0, 10000),
                            ("purge_mois", 1, 600)]:
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

    if "type_batiment" in valeurs:
        if str(valeurs["type_batiment"]).lower() not in ("", "maison", "appartement"):
            raise ValueError("type_batiment : \"maison\", \"appartement\", ou vide.")
