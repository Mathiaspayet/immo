# -*- coding: utf-8 -*-
"""
valeurs.py — Conversions defensives.

Les donnees de l'ADEME arrivent en texte, parfois vides, parfois avec une
virgule decimale. Ces trois fonctions renvoient None plutot que de lever une
exception : une ligne mal formee ne doit pas interrompre un import de
plusieurs milliers de lignes.
"""

import datetime


def nombre(valeur):
    """Convertit en nombre, ou None si ce n'en est pas un."""
    try:
        return float(str(valeur).replace(",", "."))
    except (TypeError, ValueError):
        return None


def entier(valeur):
    """Convertit en entier, ou None. Utile pour l'annee de construction."""
    n = nombre(valeur)
    return int(n) if n is not None else None


def texte(valeur):
    """Chaine nettoyee, ou None si vide."""
    if valeur is None:
        return None
    resultat = str(valeur).strip()
    return resultat or None


def en_date(valeur):
    """Convertit une date de la base en objet date, ou None."""
    brut = str(valeur or "")[:10]
    try:
        return datetime.date.fromisoformat(brut)
    except ValueError:
        return None


ACCENTS = {"é": "e", "è": "e", "ê": "e", "ë": "e", "à": "a", "â": "a", "ä": "a",
           "î": "i", "ï": "i", "ô": "o", "ö": "o", "û": "u", "ù": "u", "ü": "u",
           "ç": "c", "°": "", "²": "2"}


def normaliser_adresse(valeur):
    """
    Reduit une adresse a des mots comparables.

    L'orthographe varie d'une base ADEME a l'autre — accents, tirets,
    majuscules, ponctuation. Sans normalisation, « 8bis Cite des Tilleuls »
    et « 8BIS CITE DES TILLEULS » seraient deux adresses distinctes et la
    chronologie F4 se couperait en deux.
    """
    texte_brut = str(valeur or "").lower()
    for ancien, nouveau in ACCENTS.items():
        texte_brut = texte_brut.replace(ancien, nouveau)
    garde = [caractere if caractere.isalnum() else " " for caractere in texte_brut]
    return " ".join("".join(garde).split())


# Les types de voie tels que DVF les abrege, ramenes au mot entier de la
# Base Adresse Nationale — celle des diagnostics : « PL DE L'OCEAN » et
# « Place de l'Ocean » sont la meme adresse.
TYPES_DE_VOIE = {
    "r": "rue", "av": "avenue", "ave": "avenue", "bd": "boulevard", "bld": "boulevard",
    "che": "chemin", "chem": "chemin", "rte": "route", "pl": "place", "all": "allee",
    "imp": "impasse", "lot": "lotissement", "res": "residence", "sq": "square",
    "crs": "cours", "qua": "quai", "fg": "faubourg", "pass": "passage", "sen": "sentier",
    "tra": "traverse", "trav": "traverse", "rpt": "rond point", "cite": "cite", "lieu": "lieu",
    "ld": "lieu dit", "hle": "halle", "esp": "esplanade", "prom": "promenade",
}
SUFFIXES = {"b": "bis", "t": "ter", "q": "quater"}


def _numero_et_voie(adresse):
    """(numero, voie) d'une adresse normalisee, la commune et le code postal ecartes."""
    mots = normaliser_adresse(adresse).split()
    for i, mot in enumerate(mots):
        if len(mot) == 5 and mot.isdigit():       # code postal : la suite est la commune
            mots = mots[:i]
            break
    if not mots or not mots[0][:1].isdigit():
        return None, " ".join(mots)
    numero = mots.pop(0)
    # « 8bis », « 8 bis », « 8 B » : un seul numero.
    if mots and (mots[0] in SUFFIXES or mots[0] in SUFFIXES.values()):
        suffixe = mots.pop(0)
        numero += SUFFIXES.get(suffixe, suffixe)
    elif numero[-1:].isalpha():
        chiffres = numero.rstrip("abcdefghijklmnopqrstuvwxyz")
        numero = chiffres + SUFFIXES.get(numero[len(chiffres):], numero[len(chiffres):])
    if mots and mots[0] in TYPES_DE_VOIE:
        mots[0] = TYPES_DE_VOIE[mots[0]]
    return numero, " ".join(mots)


def meme_adresse(une, autre):
    """
    Deux adresses designent-elles le meme numero de la meme voie ?

    True ou False quand on peut en juger, None sinon — une adresse absente,
    ou sans numero (un lieu-dit, une residence) : la parcelle seule decide
    alors. Sert a confirmer une vente rattachee par une position APPROCHEE.
    """
    if not une or not autre:
        return None
    numero_un, voie_un = _numero_et_voie(une)
    numero_autre, voie_autre = _numero_et_voie(autre)
    if not numero_un or not numero_autre or not voie_un or not voie_autre:
        return None
    return numero_un == numero_autre and voie_un == voie_autre
