# -*- coding: utf-8 -*-
"""
ademe.py — Acces aux bases DPE de l'ADEME (plateforme data-fair).

Ce module porte trois correctifs obtenus par essais successifs dans
`scripts_existants/dpe_recherche.py` et `dpe_recents.py`. Ils ne sont pas
evidents a la lecture, mais chacun corrige un probleme reel :

1. DECOUVERTE DES NOMS DE COLONNES. L'ADEME renomme ses colonnes d'une
   version a l'autre. Les ecrire en dur, c'est casser l'application a la
   prochaine mise a jour. On lit donc le schema publie par l'API et on
   retrouve chaque champ par mots-cles.

2. CORRESPONDANCE EXACTE QUAND IL LE FAUT. `date_derniere_modification_dpe`
   contient litteralement la sequence `n_dpe` : une recherche par
   sous-chaine prendrait cette date pour le numero de DPE. Les mots-cles
   prefixes par « = » imposent l'egalite de la cle.

3. CASCADE DE SYNTAXES DE REQUETE. Selon la configuration du serveur, le
   filtrage passe par `_eq`, `_in`, `qs` ou la recherche plein texte. On
   les essaie dans l'ordre jusqu'a ce que l'une reponde.
"""

import logging
import time

from app.sources.client_http import ErreurSource, appeler, construire_url

logger = logging.getLogger(__name__)

RACINE = "https://data.ademe.fr/data-fair/api/v1/datasets"

# Les trois generations de bases (CDC 4). Le lot 1 n'exploite que la
# premiere ; les deux autres seront branchees au lot 2 pour l'historique.
JEUX = {
    "existant": "dpe03existant",   # DPE logements existants, depuis juillet 2021
    "neuf": "dpe02neuf",           # DPE logements neufs
    "ancien": "dpe-france",        # avant juillet 2021, schema different
}

TAILLE_PAGE = 1000
MAX_PAGES = 60          # garde-fou : 60 000 lignes par code postal
PAUSE_PAGE = 0.2        # on ne martele pas le serveur de l'ADEME

# ---------------------------------------------------------------------
#  Concepts -> mots-cles permettant de retrouver la colonne reelle
# ---------------------------------------------------------------------
# Un mot prefixe par « = » impose l'egalite exacte de la cle (voir le
# correctif 2 en tete de fichier). Les listes sont essayees dans l'ordre :
# la premiere qui trouve gagne.
CONCEPTS = {
    "numero_dpe":     [["=numero_dpe"], ["=n_dpe"]],
    "n_dpe_remplace": [["=numero_dpe_remplace"], ["=n_dpe_remplace"], ["dpe", "remplace"]],
    "date":           [["=date_etablissement_dpe"], ["date", "etablissement"], ["date", "visite"]],
    "adresse":        [["=adresse_ban"], ["adresse", "ban"], ["adresse", "brute"], ["adresse"]],
    "commune":        [["=nom_commune_ban"], ["nom", "commune", "ban"], ["commune"]],
    "code_postal":    [["=code_postal_ban"], ["code", "postal", "ban"], ["code", "postal"]],
    "code_insee":     [["=code_insee_ban"], ["code", "insee", "ban"], ["code", "insee"]],
    "surface":        [["=surface_habitable_logement"], ["surface", "habitable", "logement"],
                       ["surface", "habitable"]],
    "type_batiment":  [["=type_batiment"], ["type", "batiment"]],
    "etiquette_dpe":  [["=etiquette_dpe"], ["etiquette", "dpe"], ["classe", "dpe"]],
    "etiquette_ges":  [["=etiquette_ges"], ["etiquette", "ges"], ["classe", "ges"]],
    # L'ADEME note "ep" pour energie primaire et "ef" pour energie finale —
    # jamais « primaire » ni « finale ».
    "conso_primaire": [["=conso_5_usages_par_m2_ep"], ["conso", "5_usages", "par_m2", "ep"],
                       ["conso", "par_m2", "ep"], ["conso", "5_usages", "ep"],
                       ["conso", "primaire"]],
    "conso_finale":   [["=conso_5_usages_par_m2_ef"], ["conso", "5_usages", "par_m2", "ef"],
                       ["conso", "par_m2", "ef"], ["conso", "5_usages", "ef"],
                       ["conso", "finale"]],
    # Attention : `emission_ges_5_usages` est un total annuel, a ne pas
    # confondre avec `emission_ges_5_usages_par_m2` qui est ce qu'on veut.
    "ges_m2":         [["=emission_ges_5_usages_par_m2"], ["emission", "ges", "5_usages", "par_m2"],
                       ["emission", "ges", "par_m2"], ["emission", "ges", "m2"]],
    # `cout_total_5_usages_energie_n1` est le cout d'UNE energie du logement,
    # pas le total : sans le nom exact, la recherche par sous-chaine tombait
    # dessus et affichait un cout annuel trop bas.
    "cout_annuel":    [["=cout_total_5_usages"], ["cout", "total", "5_usages"], ["cout", "total"]],
    "annee":          [["=annee_construction"], ["annee", "construction"]],
    # Coordonnees : soit un point deja projete par data-fair, soit du
    # Lambert-93 en metres qu'il faudra convertir (voir metier/coordonnees.py).
    "geopoint":       [["=_geopoint"]],
    "x_lambert":      [["=coordonnee_cartographique_x_ban"], ["coordonnee", "cartographique", "x"]],
    "y_lambert":      [["=coordonnee_cartographique_y_ban"], ["coordonnee", "cartographique", "y"]],
}

# Concepts sans lesquels un import n'a aucun sens.
INDISPENSABLES = ["numero_dpe", "date", "adresse"]

# Mots servant a proposer des pistes quand un champ reste introuvable.
INDICES = {"conso_primaire": "conso", "conso_finale": "conso",
           "ges_m2": "emission", "surface": "surface", "cout_annuel": "cout"}


def sans_accents(texte):
    """Version simplifiee du texte, pour comparer sans se soucier des accents."""
    remplacements = {"é": "e", "è": "e", "ê": "e", "à": "a", "â": "a",
                     "î": "i", "ï": "i", "ô": "o", "û": "u", "ù": "u",
                     "ç": "c", "°": "", "²": "2", " ": "_", "-": "_", "'": "_"}
    texte = texte.lower()
    for ancien, nouveau in remplacements.items():
        texte = texte.replace(ancien, nouveau)
    return texte


def lire_schema(jeu="existant"):
    """Liste des champs du jeu de donnees : [(cle, libelle, forme_normalisee)]."""
    dataset = JEUX[jeu]
    schema = appeler(f"{RACINE}/{dataset}/schema")
    if not schema:
        raise ErreurSource(f"schema vide pour {dataset}")

    champs = []
    for champ in schema:
        cle = champ.get("key", "")
        libelle = champ.get("x-originalName", cle)
        champs.append((cle, libelle, sans_accents(f"{cle} {libelle}")))
    logger.info("%s : %d champs disponibles", dataset, len(champs))
    return champs


def associer_champs(champs):
    """
    Associe chaque concept au nom de colonne reel de la base.

    Deux niveaux, dans cet ordre :
      1. le nom exact tel qu'il existe aujourd'hui (prefixe « = ») ;
      2. la recherche par mots-cles, qui survivra a un renommage.

    Quand plusieurs colonnes satisfont les memes mots-cles, on retient la
    cle la PLUS COURTE. C'est ce qui distingue `cout_total_5_usages` (le
    total cherche) de `cout_total_5_usages_energie_n1` (le cout d'une seule
    energie) : sans ce departage, l'ordre du schema decidait a notre place.
    """
    correspondances = {}
    for concept, listes_mots in CONCEPTS.items():
        trouve = None
        for mots in listes_mots:
            candidats = [
                cle for cle, _libelle, normalise in champs
                if all((cle == mot[1:]) if mot.startswith("=") else (mot in normalise)
                       for mot in mots)
            ]
            if candidats:
                trouve = min(candidats, key=lambda cle: (len(cle), cle))
                break
        correspondances[concept] = trouve
    return correspondances


def pistes(champs, concept):
    """Colonnes ressemblantes, a afficher quand un concept reste introuvable."""
    indice = INDICES.get(concept)
    if not indice:
        return []
    return [cle for cle, _l, normalise in champs if indice in normalise][:15]


def preparer(jeu="existant"):
    """
    Lit le schema et en deduit les colonnes a demander.

    Renvoie (correspondances, champs_bruts). Leve ErreurSource si un champ
    indispensable manque : mieux vaut un echec franc qu'un import silencieux
    qui remplirait la base de lignes inexploitables.
    """
    champs = lire_schema(jeu)
    correspondances = associer_champs(champs)

    manquants = [c for c in INDISPENSABLES if not correspondances.get(c)]
    if manquants:
        detail = []
        for concept in manquants:
            proches = pistes(champs, concept)
            detail.append(f"{concept}" + (f" (proches : {', '.join(proches[:5])})" if proches else ""))
        raise ErreurSource(
            "Le schema de l'ADEME a change, colonne(s) introuvable(s) : "
            + " ; ".join(detail)
        )

    absents = [c for c, v in correspondances.items() if not v]
    if absents:
        logger.warning("colonnes absentes du schema, ignorees : %s", ", ".join(sorted(absents)))
    return correspondances, champs


def _selection(correspondances):
    """Colonnes a demander a l'API, sans doublon et dans un ordre stable."""
    vues, retenues = set(), []
    for cle in correspondances.values():
        if cle and cle not in vues:
            vues.add(cle)
            retenues.append(cle)
    return ",".join(retenues)


def telecharger(code_postal, correspondances, jeu="existant", progression=None):
    """
    Recupere toutes les lignes d'un code postal.

    `progression` est appelee a chaque page avec (nombre_de_lignes, message) :
    un telechargement silencieux de plusieurs milliers de lignes est
    indiscernable d'un plantage (CDC 7).
    """
    dataset = JEUX[jeu]
    base = f"{RACINE}/{dataset}/lines"
    selection = _selection(correspondances)
    champ_cp = correspondances.get("code_postal")

    # --- Cascade de syntaxes (correctif 3) ---------------------------
    strategies = []
    if champ_cp:
        strategies += [
            ("filtre direct", {f"{champ_cp}_eq": code_postal,
                               "size": TAILLE_PAGE, "select": selection}),
            ("filtre in", {f"{champ_cp}_in": code_postal,
                           "size": TAILLE_PAGE, "select": selection}),
            ("requete qs", {"qs": f"{champ_cp}:{code_postal}",
                            "size": TAILLE_PAGE, "select": selection}),
        ]
    strategies += [
        ("plein texte", {"q": code_postal, "size": TAILLE_PAGE, "select": selection}),
        ("sans selection", {"q": code_postal, "size": 200}),
    ]

    premiere, echecs = None, []
    for libelle, parametres in strategies:
        url = construire_url(base, parametres)
        try:
            reponse = appeler(url, silencieux=True)
        except ErreurSource as erreur:
            echecs.append(f"{libelle} : {erreur}")
            time.sleep(0.5)
            continue
        if reponse and reponse.get("results"):
            logger.info("%s : strategie « %s » retenue (%s lignes annoncees)",
                        code_postal, libelle, reponse.get("total", "?"))
            premiere = reponse
            break
        echecs.append(f"{libelle} : reponse vide")
        time.sleep(0.5)

    if premiere is None:
        raise ErreurSource(
            f"Aucune requete n'a abouti pour le code postal {code_postal}. "
            "Le serveur de l'ADEME bloque peut-etre temporairement, ou ce code "
            "postal est absent de la base. Detail : " + " | ".join(echecs)
        )

    # --- Pagination ---------------------------------------------------
    lignes = list(premiere.get("results", []))
    suivante = premiere.get("next")
    if progression:
        progression(len(lignes), f"code postal {code_postal}")

    for page in range(1, MAX_PAGES):
        if not suivante:
            break
        reponse = appeler(suivante)
        resultats = (reponse or {}).get("results") or []
        if not resultats:
            break
        lignes.extend(resultats)
        if progression:
            progression(len(lignes), f"code postal {code_postal}, page {page + 1}")
        suivante = reponse.get("next")
        time.sleep(PAUSE_PAGE)
    else:
        if suivante:
            logger.warning("%s : garde-fou de %d pages atteint, resultats tronques",
                           code_postal, MAX_PAGES)

    return lignes
