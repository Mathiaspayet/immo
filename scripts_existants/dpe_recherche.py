#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dpe_recherche.py — Retrouver une adresse a partir des donnees DPE d'une annonce.

Principe : toute maison mise en vente a un DPE, et la base des DPE de l'ADEME
est en open data AVEC l'adresse. On telecharge tous les DPE de la commune,
puis on classe les logements par ressemblance avec les chiffres de l'annonce.

Usage :
    1. MODE_EXPLORATION = True  -> affiche les champs disponibles (diagnostic)
    2. MODE_EXPLORATION = False -> lance la recherche

Aucune bibliotheque a installer.
"""

import csv
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# =====================================================================
#  CE QUE TU LIS SUR L'ANNONCE
# =====================================================================

CODE_POSTAL = "40200"        # Mimizan

SURFACE_HABITABLE = 144.0    # m²
CONSO_PRIMAIRE = 216.0       # kWh/m².an, energie primaire
CONSO_FINALE = 158.0         # kWh/m².an, energie finale
EMISSION_GES = 7.0           # kg CO2/m².an
ETIQUETTE_DPE = "D"
ETIQUETTE_GES = "B"

# Tolerances : de combien la base peut s'ecarter de l'annonce.
# Les surfaces d'annonce sont souvent arrondies, d'ou une marge un peu large.
TOLERANCE_SURFACE = 3.0      # m²
TOLERANCE_CONSO = 5.0        # kWh/m².an
TOLERANCE_GES = 1.5          # kg CO2/m².an

MODE_EXPLORATION = False     # True = affiche juste la structure de la base

FICHIER_SORTIE = "dpe_candidats.csv"

# =====================================================================
#  Reglages techniques
# =====================================================================

DATASET = "dpe03existant"    # DPE logements existants, depuis juillet 2021
BASE = f"https://data.ademe.fr/data-fair/api/v1/datasets/{DATASET}"
TAILLE_PAGE = 1000
MAX_PAGES = 40               # securite : 40 000 lignes maximum

DOSSIER = os.path.dirname(os.path.abspath(__file__))


def creer_contexte_ssl():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


CONTEXTE = creer_contexte_ssl()


# Certains pare-feux applicatifs rejettent les requetes dont l'identifiant de
# navigateur est inhabituel. On se presente donc comme un navigateur classique.
ENTETES = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/126.0.0.0 Safari/537.36"),
    "Accept": "application/json",
}


def appeler(url, silencieux=False):
    """Appelle une URL, renvoie le JSON ou None."""
    try:
        requete = urllib.request.Request(url, headers=ENTETES)
        with urllib.request.urlopen(requete, timeout=90, context=CONTEXTE) as reponse:
            return json.loads(reponse.read().decode("utf-8"))
    except urllib.error.HTTPError as erreur:
        if not silencieux:
            corps = erreur.read().decode("utf-8", "ignore")[:200]
            print(f"    HTTP {erreur.code} : {corps.strip()[:120]}")
    except Exception as erreur:
        if not silencieux:
            print(f"    {type(erreur).__name__} : {erreur}")
    return None

# =====================================================================
#  Decouverte automatique des noms de champs
# =====================================================================
# Les noms de colonnes de la base ADEME changent d'une version a l'autre.
# Plutot que de les ecrire en dur (et de tout casser a la prochaine mise a
# jour), on lit le schema publie par l'API et on retrouve chaque champ a
# partir de mots-cles.

CONCEPTS = {
    "surface":        [["surface", "habitable", "logement"], ["surface", "habitable"]],
    # L'ADEME note "ep" pour energie primaire et "ef" pour energie finale.
    "conso_primaire": [["conso", "5_usages", "par_m2", "ep"], ["conso", "par_m2", "ep"],
                       ["conso", "5_usages", "ep"], ["conso", "primaire"]],
    "conso_finale":   [["conso", "5_usages", "par_m2", "ef"], ["conso", "par_m2", "ef"],
                       ["conso", "5_usages", "ef"], ["conso", "finale"]],
    "ges_m2":         [["emission", "ges", "5_usages", "par_m2"],
                       ["emission", "ges", "par_m2"], ["emission", "ges", "m2"]],
    "etiquette_dpe":  [["etiquette", "dpe"], ["classe", "dpe"]],
    "etiquette_ges":  [["etiquette", "ges"], ["classe", "ges"]],
    "code_postal":    [["code", "postal", "ban"], ["code", "postal"]],
    "adresse":        [["adresse", "ban"], ["adresse", "brute"], ["adresse"]],
    "commune":        [["nom", "commune", "ban"], ["commune"]],
    "date":           [["date", "etablissement"], ["date", "visite"]],
    "annee":          [["annee", "construction"]],
    "type_batiment":  [["type", "batiment"]],
    "numero_dpe":     [["=n_dpe"], ["=numero_dpe"]],
}

# Si la detection automatique se trompe, force le nom exact ici. Exemple :
#   CHAMPS_FORCES = {"conso_primaire": "conso_5_usages_par_m2_ep"}
CHAMPS_FORCES = {}

# Mots servant a proposer des pistes quand un champ n'est pas trouve
INDICES = {"conso_primaire": "conso", "conso_finale": "conso",
           "ges_m2": "emission", "surface": "surface"}


def sans_accents(texte):
    """Version simplifiee du texte, pour comparer sans se soucier des accents."""
    remplacements = {"é": "e", "è": "e", "ê": "e", "à": "a", "â": "a",
                     "î": "i", "ï": "i", "ô": "o", "û": "u", "ù": "u",
                     "ç": "c", "°": "", "²": "2", " ": "_", "-": "_", "'": "_"}
    texte = texte.lower()
    for ancien, nouveau in remplacements.items():
        texte = texte.replace(ancien, nouveau)
    return texte


def lire_schema():
    """Recupere la liste des champs du jeu de donnees."""
    print("  lecture du schema...")
    schema = appeler(f"{BASE}/schema")
    if not schema:
        sys.exit("Impossible de lire le schema de la base ADEME.")
    champs = []
    for champ in schema:
        cle = champ.get("key", "")
        libelle = champ.get("x-originalName", cle)
        champs.append((cle, libelle, sans_accents(f"{cle} {libelle}")))
    print(f"  {len(champs)} champs disponibles")
    return champs


def associer_champs(champs):
    """
    Associe chaque concept au nom de champ reel de la base.
    Un mot prefixe par « = » impose une egalite exacte de la cle : sans ca,
    « date_derniere_modification_dpe » contient « n_dpe » et serait pris a
    tort pour le numero de DPE.
    """
    correspondances = {}
    for concept, listes_mots in CONCEPTS.items():
        trouve = None
        for mots in listes_mots:
            for cle, libelle, normalise in champs:
                if all((cle == mot[1:]) if mot.startswith("=") else (mot in normalise)
                       for mot in mots):
                    trouve = cle
                    break
            if trouve:
                break
        correspondances[concept] = trouve
    return correspondances

# =====================================================================
#  Telechargement des DPE de la commune
# =====================================================================

def telecharger_dpe(champ_code_postal, champs_utiles):
    """
    Recupere tous les DPE du code postal.
    Le filtrage peut s'ecrire de plusieurs facons selon la configuration du
    serveur ; on les essaie l'une apres l'autre jusqu'a ce que ca passe.
    """
    selection = ",".join(champs_utiles)
    strategies = []

    if champ_code_postal:
        strategies.append(("filtre direct",
                           {f"{champ_code_postal}_eq": CODE_POSTAL,
                            "size": TAILLE_PAGE, "select": selection}))
        strategies.append(("filtre in",
                           {f"{champ_code_postal}_in": CODE_POSTAL,
                            "size": TAILLE_PAGE, "select": selection}))
        strategies.append(("recherche qs",
                           {"qs": f"{champ_code_postal}:{CODE_POSTAL}",
                            "size": TAILLE_PAGE, "select": selection}))
    strategies.append(("recherche plein texte",
                       {"q": CODE_POSTAL, "size": TAILLE_PAGE, "select": selection}))
    strategies.append(("sans selection de champs",
                       {"q": CODE_POSTAL, "size": 200}))

    premiere_page = None
    for libelle, parametres in strategies:
        url = f"{BASE}/lines?" + urllib.parse.urlencode(parametres)
        print(f"    essai « {libelle} »...")
        reponse = appeler(url, silencieux=True)
        if reponse and reponse.get("results"):
            print(f"      -> ca fonctionne ({reponse.get('total', '?')} lignes annoncees)")
            premiere_page = (reponse, url)
            break
        print("      -> refuse ou vide")
        time.sleep(0.5)

    if premiere_page is None:
        print("\n    Aucune requete n'a abouti. Le serveur de l'ADEME bloque")
        print("    peut-etre temporairement, ou le code postal est absent.")
        return []

    reponse, _ = premiere_page
    lignes = list(reponse.get("results", []))
    url_suivante = reponse.get("next")

    for page in range(1, MAX_PAGES):
        if not url_suivante:
            break
        reponse = appeler(url_suivante)
        if not reponse:
            break
        resultats = reponse.get("results", [])
        if not resultats:
            break
        lignes.extend(resultats)
        print(f"    page {page + 1} : {len(lignes)} lignes")
        url_suivante = reponse.get("next")
        time.sleep(0.2)

    return lignes

# =====================================================================
#  Notation des candidats
# =====================================================================

def nombre(valeur):
    """Convertit en nombre, ou None si impossible."""
    try:
        return float(str(valeur).replace(",", "."))
    except (TypeError, ValueError):
        return None


def criteres_actifs(champs):
    """Liste des criteres numeriques exploitables : (concept, attendu, tolerance, unite)."""
    tous = [
        ("surface",        SURFACE_HABITABLE, TOLERANCE_SURFACE, "m²"),
        ("conso_primaire", CONSO_PRIMAIRE,    TOLERANCE_CONSO,   "kWh/m² ep"),
        ("conso_finale",   CONSO_FINALE,      TOLERANCE_CONSO,   "kWh/m² ef"),
        ("ges_m2",         EMISSION_GES,      TOLERANCE_GES,     "kgCO2/m²"),
    ]
    return [c for c in tous if champs.get(c[0]) and c[1]]


def ecart_relatif(ligne, champs, concept, attendu, tolerance):
    """Ecart d'une ligne sur un critere, exprime en nombre de tolerances.
       None si la valeur est absente de la base."""
    valeur = nombre(ligne.get(champs[concept]))
    if valeur is None:
        return None
    return abs(valeur - attendu) / tolerance


def analyser(lignes, champs):
    """
    Au lieu d'eliminer, on NOTE tout le monde et on classe.
    On mesure aussi, critere par critere, combien de logements tombent dans
    la tolerance : ca montre immediatement quel chiffre pose probleme.
    """
    criteres = criteres_actifs(champs)

    # --- Entonnoir : combien de logements passent chaque critere, seul ---
    print("\n  Chaque critere pris isolement :")
    survivants_cumules = list(lignes)
    for concept, attendu, tolerance, unite in criteres:
        seuls = [l for l in lignes
                 if (e := ecart_relatif(l, champs, concept, attendu, tolerance)) is not None
                 and e <= 1]
        survivants_cumules = [l for l in survivants_cumules
                              if (e := ecart_relatif(l, champs, concept, attendu, tolerance)) is not None
                              and e <= 1]
        print(f"    {concept:16s} {attendu:>7} {unite:12s} "
              f"seul : {len(seuls):5d}   cumule : {len(survivants_cumules):5d}")

    for concept, attendu in [("etiquette_dpe", ETIQUETTE_DPE),
                             ("etiquette_ges", ETIQUETTE_GES)]:
        if champs.get(concept) and attendu:
            seuls = [l for l in lignes
                     if str(l.get(champs[concept]) or "").strip().upper() == attendu.upper()]
            print(f"    {concept:16s} {attendu:>7} {'':12s} seul : {len(seuls):5d}")

    # --- Classement general, sans elimination ---
    notes = []
    for ligne in lignes:
        ecarts = {}
        total = 0.0
        renseignes = 0
        for concept, attendu, tolerance, _ in criteres:
            e = ecart_relatif(ligne, champs, concept, attendu, tolerance)
            ecarts[concept] = e
            if e is not None:
                total += e
                renseignes += 1
        if renseignes == 0:
            continue
        notes.append((total / renseignes, ecarts, ligne))

    notes.sort(key=lambda n: n[0])
    return notes, criteres


def afficher(notes, criteres, champs, combien=12):
    """Affiche les meilleurs candidats avec le detail de chaque ecart."""
    if not notes:
        print("\n  Aucune ligne exploitable.")
        return

    print(f"\n  Les {min(combien, len(notes))} logements les plus proches :\n")
    for rang, (score, ecarts, ligne) in enumerate(notes[:combien], 1):
        adresse = ligne.get(champs["adresse"]) if champs.get("adresse") else None
        print(f"  {rang}. {adresse or '(adresse absente)'}")

        details = []
        for concept, attendu, tolerance, unite in criteres:
            valeur = nombre(ligne.get(champs[concept]))
            if valeur is None:
                details.append(f"{concept}=?")
            else:
                marque = "ok" if abs(valeur - attendu) <= tolerance else "!!"
                details.append(f"{concept} {valeur:g} (vise {attendu:g}) {marque}")
        print("     " + " | ".join(details))

        etiquettes = []
        for concept, attendu in [("etiquette_dpe", ETIQUETTE_DPE),
                                 ("etiquette_ges", ETIQUETTE_GES)]:
            if champs.get(concept):
                etiquettes.append(f"{concept}={ligne.get(champs[concept])} (vise {attendu})")
        if etiquettes:
            print("     " + " | ".join(etiquettes))
        print(f"     ecart moyen : {score:.2f} tolerance(s)\n")

# =====================================================================
#  Programme principal
# =====================================================================

def main():
    print(f"\n=== Recherche DPE — code postal {CODE_POSTAL} ===\n")

    print("[1/4] Structure de la base")
    champs_bruts = lire_schema()
    champs = associer_champs(champs_bruts)
    champs.update({k: v for k, v in CHAMPS_FORCES.items() if v})

    for concept, cle in champs.items():
        etat = cle if cle else "NON TROUVE"
        print(f"    {concept:16s} -> {etat}")

    # Pour tout champ introuvable, on affiche les colonnes qui pourraient
    # convenir : ca permet de le forcer dans CHAMPS_FORCES en un coup d'oeil.
    manquants = [c for c, v in champs.items() if not v and c in INDICES]
    if manquants:
        print("\n    Champs introuvables — colonnes ressemblantes dans la base :")
        for concept in manquants:
            indice = INDICES[concept]
            pistes = [cle for cle, _, norme in champs_bruts if indice in norme][:25]
            print(f"\n    « {concept} » (contiennent « {indice} ») :")
            for piste in pistes:
                print(f"        {piste}")

    if MODE_EXPLORATION:
        print("\n  --- Tous les champs de la base ---")
        for cle, libelle, _ in champs_bruts:
            print(f"    {cle}   ({libelle})")
        print("\nMode exploration : arret ici.")
        print("Passe MODE_EXPLORATION a False pour lancer la recherche.\n")
        return

    if not champs["surface"]:
        sys.exit("\nLe champ 'surface habitable' est introuvable : relance en "
                 "MODE_EXPLORATION = True et envoie-moi la liste des champs.")

    champs_utiles = [cle for cle in champs.values() if cle]

    print("\n[2/4] Telechargement des DPE de la commune")
    lignes = telecharger_dpe(champs["code_postal"], champs_utiles)
    if not lignes:
        sys.exit("Aucun DPE recupere. Verifie le code postal.")
    print(f"  {len(lignes)} DPE recuperes")

    print("\n[3/4] Comparaison avec l'annonce")
    notes, criteres = analyser(lignes, champs)

    print("\n[4/4] Resultats")
    afficher(notes, criteres, champs)

    if notes:
        sortie = os.path.join(DOSSIER, FICHIER_SORTIE)
        meilleurs = [dict(ligne, _ecart_moyen=round(score, 3))
                     for score, _, ligne in notes[:200]]
        colonnes = sorted({cle for ligne in meilleurs for cle in ligne})
        with open(sortie, "w", newline="", encoding="utf-8-sig") as fichier:
            redacteur = csv.DictWriter(fichier, fieldnames=colonnes, delimiter=";")
            redacteur.writeheader()
            redacteur.writerows(meilleurs)
        print(f"  Les 200 plus proches sont detailles dans :\n    {sortie}\n")


if __name__ == "__main__":
    main()
    input("Appuie sur Entree pour fermer.")
