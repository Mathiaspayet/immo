#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ouvrir_liens.py — Ouvrir une liste de liens dans le navigateur, par lots.

Fonctionne avec :
  - le fichier parcelles_filtrees.csv produit par parcelles.py
  - ou n'importe quel fichier texte contenant un lien par ligne

Le script ouvre les liens par paquets et attend ta validation entre chaque,
pour ne pas saturer le navigateur. Tu peux t'arreter et reprendre plus tard
au numero ou tu en etais.

Usage :  py ouvrir_liens.py
"""

import csv
import os
import sys
import time
import webbrowser

# =====================================================================
#  CONFIGURATION
# =====================================================================

FICHIER = "parcelles_filtrees.csv"

# Quelle colonne ouvrir (ignore si le fichier n'est pas un CSV) :
#   "street_view"   -> vue depuis la rue
#   "vue_aerienne"  -> vue satellite Google
#   "geoportail"    -> orthophoto IGN
COLONNE = "street_view"

TAILLE_LOT = 12       # nombre d'onglets ouverts d'un coup
DEPART = 1            # numero de la ligne a laquelle commencer (pour reprendre)
PAUSE = 0.4           # secondes entre deux ouvertures, laisse respirer le navigateur

# =====================================================================

DOSSIER = os.path.dirname(os.path.abspath(__file__))
CHEMIN = os.path.join(DOSSIER, FICHIER)


def lire_liens(chemin):
    """Extrait la liste des liens, que le fichier soit un CSV ou un simple texte."""
    if not os.path.exists(chemin):
        sys.exit(f"Fichier introuvable : {chemin}")

    if chemin.lower().endswith(".csv"):
        with open(chemin, "r", encoding="utf-8-sig", newline="") as fichier:
            lecteur = csv.DictReader(fichier, delimiter=";")
            colonnes = lecteur.fieldnames or []
            if COLONNE not in colonnes:
                sys.exit(f"Colonne '{COLONNE}' absente.\n"
                         f"Colonnes disponibles : {', '.join(colonnes)}")
            return [(ligne.get("id_parcelle", "?"), ligne[COLONNE])
                    for ligne in lecteur if ligne.get(COLONNE)]

    # Sinon : un lien par ligne, on ignore le reste
    liens = []
    with open(chemin, "r", encoding="utf-8") as fichier:
        for numero, ligne in enumerate(fichier, 1):
            ligne = ligne.strip()
            if ligne.startswith("http"):
                liens.append((str(numero), ligne))
    return liens


def main():
    liens = lire_liens(CHEMIN)
    total = len(liens)
    if total == 0:
        sys.exit("Aucun lien trouve dans le fichier.")

    print(f"\n{total} liens trouves dans {FICHIER}")
    if DEPART > 1:
        print(f"Reprise a partir du numero {DEPART}")
    print(f"Ouverture par lots de {TAILLE_LOT}.\n")

    position = DEPART - 1
    while position < total:
        lot = liens[position:position + TAILLE_LOT]
        print(f"--- Liens {position + 1} a {position + len(lot)} sur {total} ---")
        for identifiant, lien in lot:
            print(f"    {identifiant}")
            webbrowser.open_new_tab(lien)
            time.sleep(PAUSE)

        position += len(lot)
        if position >= total:
            break

        print(f"\n    Reste {total - position} liens.")
        reponse = input("    Entree = lot suivant, 'q' = arreter : ").strip().lower()
        if reponse == "q":
            print(f"\n  Arret. Pour reprendre plus tard, mets DEPART = {position + 1}")
            print("  en haut de ce fichier.\n")
            return
        print()

    print("\nTous les liens ont ete ouverts.\n")


if __name__ == "__main__":
    main()
    input("Appuie sur Entree pour fermer.")
