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
