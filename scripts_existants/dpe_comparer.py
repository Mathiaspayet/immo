#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dpe_comparer.py — Recuperer un ou plusieurs DPE par leur numero et les comparer.

Utile quand un diagnostic en remplace un autre : le script affiche les
valeurs cles de chacun, puis la LISTE DES CHAMPS QUI DIFFERENT, ce qui
montre exactement ce qui a ete corrige.

Le script suit aussi la chaine des remplacements : si un DPE en remplace
un autre, il va chercher le precedent, et ainsi de suite.

Aucune bibliotheque a installer.
"""

import csv
import json
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

# =====================================================================
#  CONFIGURATION
# =====================================================================

# Numeros de DPE a recuperer. Attention aux caracteres ambigus :
# le O final est la lettre O, pas le chiffre zero.
NUMEROS = [
    "2540E2017709X",
    "2540E2017570O",
]

SUIVRE_LA_CHAINE = True      # aller chercher les DPE remplaces plus anciens
FICHIER_SORTIE = "dpe_comparaison.csv"

# =====================================================================

JEUX_DE_DONNEES = ["dpe03existant", "dpe02neuf"]
RACINE = "https://data.ademe.fr/data-fair/api/v1/datasets"

ENTETES = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/126.0.0.0 Safari/537.36"),
    "Accept": "application/json",
}

DOSSIER = os.path.dirname(os.path.abspath(__file__))


def creer_contexte_ssl():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


CONTEXTE = creer_contexte_ssl()


def appeler(url):
    try:
        requete = urllib.request.Request(url, headers=ENTETES)
        with urllib.request.urlopen(requete, timeout=90, context=CONTEXTE) as reponse:
            return json.loads(reponse.read().decode("utf-8"))
    except urllib.error.HTTPError:
        return None
    except Exception as erreur:
        print(f"      {type(erreur).__name__} : {erreur}")
        return None

# =====================================================================
#  Recuperation d'un DPE par son numero
# =====================================================================

def trouver_champ_numero(dataset):
    """
    Repere le nom exact du champ contenant le numero de DPE.
    On ne le devine pas : on lit le schema publie par l'API.
    """
    schema = appeler(f"{RACINE}/{dataset}/schema")
    if not schema:
        return "n_dpe"
    cles = [champ.get("key", "") for champ in schema]
    for candidat in ("n_dpe", "numero_dpe", "ndpe", "n__dpe"):
        if candidat in cles:
            return candidat
    return "n_dpe"


def chercher_dpe(numero):
    """
    Cherche un numero de DPE. Deux niveaux de confiance :

    - un filtre portant explicitement sur le champ du numero est fiable par
      construction : si le serveur renvoie une seule ligne, c'est la bonne,
      meme si le champ n'est pas visible dans la reponse ;
    - une recherche plein texte, elle, ramene aussi les DPE qui CITENT ce
      numero (dans leur champ « remplace le DPE »). Elle n'est acceptee que
      si on peut verifier l'egalite du numero.

    Renvoie (jeu, ligne, methode) ou (None, None, None).
    """
    for dataset in JEUX_DE_DONNEES:
        champ = trouver_champ_numero(dataset)
        selection = f"{champ},n_dpe_remplace"

        strategies = [
            ("filtre exact", {f"{champ}_eq": numero, "size": 5}, True),
            ("filtre in",    {f"{champ}_in": numero, "size": 5}, True),
            ("recherche qs", {"qs": f"{champ}:{numero}", "size": 5}, True),
            ("plein texte",  {"q": numero, "size": 10}, False),
        ]

        for libelle, parametres, cible_le_champ in strategies:
            url = f"{RACINE}/{dataset}/lines?" + urllib.parse.urlencode(parametres)
            reponse = appeler(url)
            resultats = (reponse or {}).get("results", [])
            if not resultats:
                time.sleep(0.2)
                continue

            print(f"      {libelle} : {len(resultats)} resultat(s)")

            # Cas ideal : le numero est visible et correspond
            exacts = [l for l in resultats
                      if str(l.get(champ, "")).strip() == numero]
            if exacts:
                return dataset, exacts[0], libelle

            # Filtre cible + un seul resultat : fiable meme sans verification
            if cible_le_champ and len(resultats) == 1:
                return dataset, resultats[0], libelle + " (non verifie)"

            time.sleep(0.2)

    return None, None, None

# =====================================================================
#  Affichage
# =====================================================================

# Champs mis en avant, dans cet ordre. On les cherche par nom exact ;
# ceux qui n'existent pas dans la base sont simplement ignores.
CHAMPS_CLES = [
    ("n_dpe", "N° DPE"),
    ("date_etablissement_dpe", "Date d'etablissement"),
    ("date_visite_diagnostiqueur", "Date de visite"),
    ("date_derniere_modification_dpe", "Derniere modification"),
    ("adresse_ban", "Adresse"),
    ("surface_habitable_logement", "Surface habitable"),
    ("annee_construction", "Annee de construction"),
    ("type_batiment", "Type de batiment"),
    ("etiquette_dpe", "Etiquette DPE"),
    ("etiquette_ges", "Etiquette GES"),
    ("conso_5_usages_par_m2_ep", "Conso primaire /m2"),
    ("conso_5_usages_par_m2_ef", "Conso finale /m2"),
    ("conso_5_usages_ep", "Conso primaire totale"),
    ("emission_ges_5_usages_par_m2", "Emissions /m2"),
    ("cout_total_5_usages", "Cout annuel estime"),
    ("type_energie_principale_chauffage", "Energie de chauffage"),
    ("type_installation_chauffage", "Installation de chauffage"),
    ("n_dpe_remplace", "Remplace le DPE"),
]


def afficher_dpe(numero, dataset, ligne):
    print(f"\n{'=' * 62}")
    print(f"  DPE {numero}   [{dataset}]")
    print("=" * 62)
    for cle, libelle in CHAMPS_CLES:
        if cle in ligne and ligne[cle] not in (None, ""):
            print(f"    {libelle:26s} : {ligne[cle]}")


def comparer(dpe_a, dpe_b, nom_a, nom_b):
    """Affiche uniquement les champs dont la valeur differe."""
    print(f"\n{'=' * 62}")
    print(f"  CE QUI A CHANGE entre {nom_b} et {nom_a}")
    print("=" * 62)

    cles = sorted(set(dpe_a) | set(dpe_b))
    differences = []
    for cle in cles:
        # Les champs commencant par « _ » sont ajoutes par le moteur de
        # recherche (score de pertinence, identifiant interne) et ne font
        # pas partie du diagnostic.
        if cle.startswith("_"):
            continue
        valeur_a = dpe_a.get(cle)
        valeur_b = dpe_b.get(cle)
        if str(valeur_a) != str(valeur_b):
            differences.append((cle, valeur_b, valeur_a))

    if not differences:
        print("\n    Les deux enregistrements sont identiques.")
        return differences

    # On evite le bruit des identifiants et dates techniques
    bruit = ("_id", "date_derniere_modification", "date_reception",
             "n_dpe", "identifiant")
    utiles = [d for d in differences if not any(m in d[0] for m in bruit)]
    autres = [d for d in differences if d not in utiles]

    print(f"\n  {len(differences)} champs different"
          f" ({len(utiles)} hors identifiants techniques)\n")

    for cle, avant, apres in utiles:
        print(f"    {cle}")
        print(f"        avant : {avant}")
        print(f"        apres : {apres}")

    if autres:
        print(f"\n    (+ {len(autres)} champs techniques : identifiants, dates de saisie)")

    return differences

# =====================================================================
#  Programme principal
# =====================================================================

def main():
    print("\n=== Comparaison de DPE ===")

    a_traiter = list(NUMEROS)
    recuperes = {}          # numero -> (dataset, ligne)
    ordre = []

    while a_traiter:
        numero = a_traiter.pop(0)
        if numero in recuperes:
            continue
        print(f"\n  recherche de {numero}...")
        dataset, ligne, methode = chercher_dpe(numero)
        if ligne is None:
            print("    INTROUVABLE.")
            print("    L'ADEME ne conserve dans ce jeu de donnees que les DPE")
            print("    en vigueur : un diagnostic remplace en est retire.")
            print("    Ses valeurs ne sont donc pas accessibles par l'API.")
            continue
        print(f"    trouve dans {dataset} (via {methode})")
        recuperes[numero] = (dataset, ligne)
        ordre.append(numero)

        if SUIVRE_LA_CHAINE:
            precedent = str(ligne.get("n_dpe_remplace") or "").strip()
            if precedent and precedent not in recuperes:
                print(f"    -> il remplace {precedent}, on remonte la chaine")
                a_traiter.append(precedent)

    if not recuperes:
        print("\nAucun DPE recupere.\n")
        return

    for numero in ordre:
        dataset, ligne = recuperes[numero]
        afficher_dpe(numero, dataset, ligne)

    if len(ordre) >= 2:
        recent, ancien = ordre[0], ordre[1]
        comparer(recuperes[recent][1], recuperes[ancien][1], recent, ancien)

    # --- Export complet ---
    sortie = os.path.join(DOSSIER, FICHIER_SORTIE)
    lignes = []
    for numero in ordre:
        dataset, ligne = recuperes[numero]
        lignes.append(dict(ligne, _jeu_de_donnees=dataset))
    colonnes = sorted({cle for ligne in lignes for cle in ligne})
    with open(sortie, "w", newline="", encoding="utf-8-sig") as fichier:
        redacteur = csv.DictWriter(fichier, fieldnames=colonnes, delimiter=";")
        redacteur.writeheader()
        redacteur.writerows(lignes)
    print(f"\n  Tous les champs (il y en a {len(colonnes)}) sont dans :")
    print(f"    {sortie}\n")


if __name__ == "__main__":
    main()
    input("Appuie sur Entree pour fermer.")
