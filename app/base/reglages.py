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

    # Purge (CDC 9) : rien n'est conserve indefiniment.
    #
    # Elle porte sur `revu_le`, la derniere fois que l'ADEME a servi la
    # ligne — pas sur la date du diagnostic. Purger sur la date du
    # diagnostic rendrait le lot 2 impossible : la chronologie F4 remonte a
    # 2013, et une annonce peut citer un DPE de 2022. Sur `revu_le`, la
    # regle garde son sens — on ne conserve pas une donnee qu'on ne
    # rafraichit plus — et elle rend meme un service a F4 : un DPE remplace
    # disparait de la base active de l'ADEME, notre cache en garde la trace
    # 24 mois de plus.
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
                            ("purge_mois", 1, 600),
                            ("rafraichir_apres_heures", 0, 8760)]:
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

    if "zones_code_insee" in valeurs:
        code = str(valeurs["zones_code_insee"] or "").strip()
        if code and not (code.isalnum() and len(code) == 5):
            raise ValueError(
                f"Code INSEE invalide : {code!r} (cinq caracteres attendus, "
                "ou vide pour appliquer les secteurs partout).")

    if "type_batiment" in valeurs:
        if str(valeurs["type_batiment"]).lower() not in ("", "maison", "appartement"):
            raise ValueError("type_batiment : \"maison\", \"appartement\", ou vide.")
