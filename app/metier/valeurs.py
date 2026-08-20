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
