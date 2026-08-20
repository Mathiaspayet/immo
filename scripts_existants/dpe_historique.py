#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dpe_historique.py — Retracer tous les DPE connus pour une adresse.

Interroge successivement les differents jeux de donnees de l'ADEME :
  - les DPE etablis depuis juillet 2021 (nouveau modele)
  - les DPE anterieurs a juillet 2021 (ancien modele, depuis 2013)
puis reconstitue une chronologie.

Ce que ca revele :
  - un DPE ancien = le bien a deja ete vendu ou loue a cette epoque
  - deux DPE rapproches = correction, ou travaux entre les deux
  - un champ « DPE remplace » rempli = le diagnostic en annule un precedent

Aucune bibliotheque a installer.
"""

import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# =====================================================================
#  CONFIGURATION
# =====================================================================

CODE_POSTAL = "40200"

# Fragment d'adresse a rechercher, tel qu'il apparait dans les resultats
# du script dpe_recherche.py. Mets peu de mots : le nom de la voie et le
# numero suffisent, la ponctuation et la casse sont ignorees.
ADRESSE = "rue des pins"

MODE_EXPLORATION = False     # True = liste les champs de chaque base

# =====================================================================

JEUX_DE_DONNEES = [
    ("dpe03existant", "Logements existants — depuis juillet 2021"),
    ("dpe02neuf",     "Logements neufs — depuis juillet 2021"),
    ("dpe-france",    "Logements — avant juillet 2021"),
    ("dpe-tertiaire", "Tertiaire — avant juillet 2021"),
]

RACINE = "https://data.ademe.fr/data-fair/api/v1/datasets"
TAILLE_PAGE = 1000
MAX_PAGES = 15               # 15 000 lignes maximum par jeu de donnees

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


def appeler(url, silencieux=False):
    try:
        requete = urllib.request.Request(url, headers=ENTETES)
        with urllib.request.urlopen(requete, timeout=90, context=CONTEXTE) as reponse:
            return json.loads(reponse.read().decode("utf-8"))
    except urllib.error.HTTPError as erreur:
        if not silencieux:
            print(f"      HTTP {erreur.code}")
    except Exception as erreur:
        if not silencieux:
            print(f"      {type(erreur).__name__} : {erreur}")
    return None


def sans_accents(texte):
    remplacements = {"é": "e", "è": "e", "ê": "e", "à": "a", "â": "a",
                     "î": "i", "ï": "i", "ô": "o", "û": "u", "ù": "u",
                     "ç": "c", "°": "", "²": "2", " ": "_", "-": "_", "'": "_"}
    texte = str(texte).lower()
    for ancien, nouveau in remplacements.items():
        texte = texte.replace(ancien, nouveau)
    return texte


def normaliser_adresse(texte):
    """Reduit une adresse a des mots comparables."""
    texte = sans_accents(texte).replace("_", " ")
    return " ".join(mot for mot in texte.split() if mot)

# =====================================================================
#  Reperage des champs, avec les noms des DEUX generations de bases
# =====================================================================

CONCEPTS = {
    "adresse":      [["adresse", "ban"], ["geo_adresse"], ["adresse", "brute"],
                     ["adresse"], ["nom_rue"]],
    "code_postal":  [["code", "postal", "ban"], ["code", "postal"],
                     ["code", "insee", "commune"]],
    "date":         [["date", "etablissement"], ["date", "visite"],
                     ["date", "reception"], ["date", "dpe"]],
    "date_modif":   [["date", "derniere", "modification"]],
    "etiquette":    [["etiquette", "dpe"], ["classe", "consommation", "energie"],
                     ["classe", "estimation", "ges"]],
    "conso":        [["conso", "5_usages", "par_m2", "ep"],
                     ["=consommation_energie"], ["conso", "par_m2", "ep"]],
    "surface":      [["surface", "habitable", "logement"], ["surface", "thermique"],
                     ["surface", "habitable"]],
    "numero_dpe":   [["=n_dpe"], ["=numero_dpe"], ["=id"]],
    "dpe_remplace": [["dpe", "remplace"], ["remplace"]],
    "annee":        [["annee", "construction"]],
    "type":         [["type", "batiment"], ["tr002_type_batiment_description"]],
}


def lire_schema(dataset):
    schema = appeler(f"{RACINE}/{dataset}/schema", silencieux=True)
    if not schema:
        return None
    return [(champ.get("key", ""),
             sans_accents(f"{champ.get('key','')} {champ.get('x-originalName','')}"))
            for champ in schema]


def associer(champs):
    resultat = {}
    for concept, listes in CONCEPTS.items():
        trouve = None
        for mots in listes:
            for cle, norme in champs:
                if all((cle == mot[1:]) if mot.startswith("=") else (mot in norme)
                       for mot in mots):
                    trouve = cle
                    break
            if trouve:
                break
        resultat[concept] = trouve
    return resultat

# =====================================================================
#  Telechargement
# =====================================================================

def telecharger(dataset, champs):
    """
    Recupere les lignes du code postal, en essayant plusieurs syntaxes.
    On ne demande QUE les colonnes utiles : sur une base a 230 champs,
    ca divise le volume transfere par vingt.
    """
    champ_cp = champs.get("code_postal")
    selection = ",".join(sorted({cle for cle in champs.values() if cle}))

    strategies = []
    if champ_cp:
        strategies.append({f"{champ_cp}_eq": CODE_POSTAL,
                           "size": TAILLE_PAGE, "select": selection})
        strategies.append({f"{champ_cp}_in": CODE_POSTAL,
                           "size": TAILLE_PAGE, "select": selection})
    strategies.append({"q": CODE_POSTAL, "size": TAILLE_PAGE, "select": selection})
    strategies.append({"q": CODE_POSTAL, "size": 500})

    depart = None
    for numero, parametres in enumerate(strategies, 1):
        url = f"{RACINE}/{dataset}/lines?" + urllib.parse.urlencode(parametres)
        print(f"    telechargement (essai {numero})...", flush=True)
        reponse = appeler(url, silencieux=True)
        if reponse and reponse.get("results"):
            depart = reponse
            break
        time.sleep(0.3)

    if depart is None:
        return []

    lignes = list(depart.get("results", []))
    total = depart.get("total")
    suivante = depart.get("next")

    for _ in range(MAX_PAGES):
        if not suivante:
            break
        reponse = appeler(suivante, silencieux=True)
        if not reponse or not reponse.get("results"):
            break
        lignes.extend(reponse["results"])
        print(f"      {len(lignes)}" + (f" / {total}" if total else "") + " lignes",
              flush=True)
        suivante = reponse.get("next")
        time.sleep(0.2)
    return lignes

# =====================================================================
#  Programme principal
# =====================================================================

def main():
    cible = normaliser_adresse(ADRESSE)
    print(f"\n=== Historique DPE — « {ADRESSE} », {CODE_POSTAL} ===\n")

    trouvailles = []

    for dataset, libelle in JEUX_DE_DONNEES:
        print(f"[{dataset}] {libelle}")

        champs_bruts = lire_schema(dataset)
        if not champs_bruts:
            print("    jeu de donnees indisponible sous ce nom — ignore\n")
            continue
        champs = associer(champs_bruts)
        print(f"    {len(champs_bruts)} champs · adresse -> {champs['adresse']}")

        if MODE_EXPLORATION:
            interessants = [cle for cle, norme in champs_bruts
                            if any(mot in norme for mot in
                                   ("date", "dpe", "adresse", "remplac"))]
            for cle in interessants[:40]:
                print(f"        {cle}")
            print()
            continue

        if not champs["adresse"]:
            print("    champ adresse introuvable — ignore\n")
            continue

        lignes = telecharger(dataset, champs)
        print(f"    {len(lignes)} lignes sur le code postal")

        correspondances = [
            ligne for ligne in lignes
            if cible in normaliser_adresse(ligne.get(champs["adresse"], ""))
        ]
        print(f"    {len(correspondances)} correspondance(s) sur l'adresse\n")

        for ligne in correspondances:
            trouvailles.append((libelle, champs, ligne))

    if MODE_EXPLORATION:
        print("Mode exploration : arret ici.\n")
        return

    # --- Chronologie ---
    print("=" * 62)
    if not trouvailles:
        print("\nAucun DPE trouve pour cette adresse.")
        print("Essaie un fragment plus court (juste le nom de la voie),")
        print("l'orthographe de la base differant parfois de l'annonce.\n")
        return

    def cle_tri(element):
        _, champs, ligne = element
        return str(ligne.get(champs["date"]) or "")

    trouvailles.sort(key=cle_tri)

    print(f"\n{len(trouvailles)} diagnostic(s), du plus ancien au plus recent :\n")
    for numero, (libelle, champs, ligne) in enumerate(trouvailles, 1):
        def valeur(concept):
            cle = champs.get(concept)
            return ligne.get(cle) if cle else None

        print(f"  {numero}. {str(valeur('date'))[:10] or 'date inconnue'}"
              f"   [{libelle}]")
        print(f"     {valeur('adresse')}")

        details = []
        for etiquette, concept in [("surface", "surface"), ("conso", "conso"),
                                   ("classe", "etiquette"), ("construit en", "annee")]:
            v = valeur(concept)
            if v not in (None, ""):
                details.append(f"{etiquette} : {v}")
        if details:
            print("     " + " · ".join(details))

        if valeur("numero_dpe"):
            print(f"     n° DPE {valeur('numero_dpe')}")
        if valeur("dpe_remplace"):
            print(f"     >>> remplace le DPE {valeur('dpe_remplace')}")
        if valeur("date_modif"):
            print(f"     derniere modification : {str(valeur('date_modif'))[:10]}")
        print()

    print("  Lecture :")
    print("   - plusieurs DPE espaces de quelques annees = le bien a deja")
    print("     ete propose a la vente ou a la location")
    print("   - deux DPE tres rapproches = correction du diagnostic")
    print("   - une classe qui s'ameliore = des travaux ont eu lieu entre les deux")
    print("   - un DPE est valable 10 ans ; ceux etablis avant juillet 2021")
    print("     ont toutefois ete invalides par la reforme\n")


if __name__ == "__main__":
    main()
    input("Appuie sur Entree pour fermer.")
