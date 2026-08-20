#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dpe_recents.py — Reperer les logements dont le DPE vient d'etre etabli.

Un DPE est obligatoire AVANT la mise en vente ou en location. Un diagnostic
tout frais est donc un signal avance : le bien n'est souvent pas encore en
ligne. C'est la seule facon simple d'avoir une longueur d'avance sur les
annonces.

A lire avant de s'emballer : un DPE recent ne signifie pas forcement une
vente. Il peut s'agir d'une mise en location, d'un audit energetique avant
travaux, ou d'un dossier MaPrimeRenov'. Compte une proportion importante de
faux positifs.

Aucune bibliotheque a installer.
"""

import csv
import datetime
import json
import math
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

# =====================================================================
#  CONFIGURATION
# =====================================================================

# Codes postaux a surveiller. Ajoute les communes voisines si tu elargis.
CODES_POSTAUX = ["40200"]

# Le code postal 40200 couvre plusieurs communes. Laisse vide pour tout garder.
COMMUNE = "Mimizan"

# Mimizan-Plage n'est pas une commune distincte : meme code postal et meme
# code INSEE que le bourg. On separe donc les deux par la geographie, en
# rattachant chaque logement au point de reference le plus proche.
ZONES = {
    "bourg": (44.2011, -1.2286),     # centre-bourg, mairie
    "plage": (44.2044, -1.2914),     # Mimizan-Plage
}

# "" = les deux, sinon "bourg" ou "plage"
ZONE = ""

JOURS = 120                  # fenetre : diagnostics des N derniers jours

TYPE_RECHERCHE = "maison"    # "maison", "appartement", ou "" pour tout
SURFACE_MINIMUM = 80         # m², pour ecarter les petits logements locatifs
SURFACE_MAXIMUM = 400

FICHIER_SORTIE = "dpe_recents.csv"

# =====================================================================

DATASET = "dpe03existant"
RACINE = "https://data.ademe.fr/data-fair/api/v1/datasets"
TAILLE_PAGE = 1000
MAX_PAGES = 15

ENTETES = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/126.0.0.0 Safari/537.36"),
    "Accept": "application/json",
}

DOSSIER = os.path.dirname(os.path.abspath(__file__))

CHAMPS = ["n_dpe", "date_etablissement_dpe", "adresse_ban", "nom_commune_ban",
          "code_postal_ban", "surface_habitable_logement", "type_batiment",
          "etiquette_dpe", "etiquette_ges", "annee_construction",
          "conso_5_usages_par_m2_ep", "cout_total_5_usages", "n_dpe_remplace",
          "_geopoint", "coordonnee_cartographique_x_ban",
          "coordonnee_cartographique_y_ban"]


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


def champs_disponibles():
    """Ne demande que les colonnes qui existent reellement dans la base."""
    schema = appeler(f"{RACINE}/{DATASET}/schema")
    if not schema:
        return CHAMPS
    cles = {champ.get("key", "") for champ in schema}
    return [c for c in CHAMPS if c in cles]

# =====================================================================
#  Telechargement
# =====================================================================

def telecharger(code_postal, selection):
    strategies = [
        {"code_postal_ban_eq": code_postal, "size": TAILLE_PAGE, "select": selection},
        {"code_postal_ban_in": code_postal, "size": TAILLE_PAGE, "select": selection},
        {"q": code_postal, "size": TAILLE_PAGE, "select": selection},
    ]

    depart = None
    for parametres in strategies:
        url = f"{RACINE}/{DATASET}/lines?" + urllib.parse.urlencode(parametres)
        reponse = appeler(url)
        if reponse and reponse.get("results"):
            depart = reponse
            break
        time.sleep(0.3)

    if depart is None:
        return []

    lignes = list(depart.get("results", []))
    suivante = depart.get("next")
    for _ in range(MAX_PAGES):
        if not suivante:
            break
        reponse = appeler(suivante)
        if not reponse or not reponse.get("results"):
            break
        lignes.extend(reponse["results"])
        print(f"      {len(lignes)} lignes", flush=True)
        suivante = reponse.get("next")
        time.sleep(0.2)
    return lignes

# =====================================================================
#  Filtrage
# =====================================================================

def en_date(valeur):
    """Convertit une date de la base en objet date, ou None."""
    texte = str(valeur or "")[:10]
    try:
        return datetime.date.fromisoformat(texte)
    except ValueError:
        return None


def nombre(valeur):
    try:
        return float(str(valeur).replace(",", "."))
    except (TypeError, ValueError):
        return None

# =====================================================================
#  Coordonnees et rattachement geographique
# =====================================================================
# La base fournit selon les cas un point deja en latitude/longitude, ou
# des coordonnees Lambert-93 en metres (la projection officielle francaise).
# La conversion ci-dessous a ete verifiee au centimetre pres contre pyproj.

E_GRS80 = 0.0818191910428158
N_L93 = 0.725607765053267
C_L93 = 11754255.426096
XS_L93, YS_L93 = 700000.0, 12655612.049876
LON0_L93 = math.radians(3.0)


def lambert93_vers_wgs84(x, y):
    """Convertit des coordonnees Lambert-93 (metres) en (latitude, longitude)."""
    dx, dy = x - XS_L93, y - YS_L93
    rayon = math.hypot(dx, dy)
    if rayon == 0:
        return None
    gamma = math.atan2(dx, -dy)
    longitude = LON0_L93 + gamma / N_L93
    latiso = -math.log(abs(rayon / C_L93)) / N_L93

    phi = 2 * math.atan(math.exp(latiso)) - math.pi / 2
    for _ in range(30):
        sinus = E_GRS80 * math.sin(phi)
        phi = 2 * math.atan(((1 + sinus) / (1 - sinus)) ** (E_GRS80 / 2)
                            * math.exp(latiso)) - math.pi / 2
    return math.degrees(phi), math.degrees(longitude)


def coordonnees(ligne):
    """Extrait (latitude, longitude) d'une ligne, quel que soit le format."""
    point = ligne.get("_geopoint")
    if point and "," in str(point):
        morceaux = str(point).split(",")
        lat, lon = nombre(morceaux[0]), nombre(morceaux[1])
        if lat is not None and lon is not None:
            return lat, lon

    x = nombre(ligne.get("coordonnee_cartographique_x_ban"))
    y = nombre(ligne.get("coordonnee_cartographique_y_ban"))
    if x and y and x > 1000:          # ecarte les zeros et valeurs aberrantes
        return lambert93_vers_wgs84(x, y)
    return None


def distance_m(lat1, lon1, lat2, lon2):
    d_lat = (lat2 - lat1) * 110540.0
    d_lon = (lon2 - lon1) * 110540.0 * math.cos(math.radians(lat1))
    return math.hypot(d_lat, d_lon)


def zone_de(ligne):
    """Rattache un logement a la zone de reference la plus proche."""
    point = coordonnees(ligne)
    if point is None:
        return None, None
    latitude, longitude = point
    meilleure, distance_min = None, None
    for nom, (lat_ref, lon_ref) in ZONES.items():
        d = distance_m(latitude, longitude, lat_ref, lon_ref)
        if distance_min is None or d < distance_min:
            meilleure, distance_min = nom, d
    return meilleure, round(distance_min)


def filtrer(lignes, limite):
    retenus = []
    sans_coordonnees = 0

    for ligne in lignes:
        date = en_date(ligne.get("date_etablissement_dpe"))
        if date is None or date < limite:
            continue

        if COMMUNE:
            commune = str(ligne.get("nom_commune_ban") or "").lower()
            if COMMUNE.lower() not in commune:
                continue

        if TYPE_RECHERCHE:
            type_bat = str(ligne.get("type_batiment") or "").lower()
            if TYPE_RECHERCHE.lower() not in type_bat:
                continue

        surface = nombre(ligne.get("surface_habitable_logement"))
        if surface is None or not (SURFACE_MINIMUM <= surface <= SURFACE_MAXIMUM):
            continue

        nom_zone, distance = zone_de(ligne)
        if nom_zone is None:
            sans_coordonnees += 1
        if ZONE and nom_zone != ZONE:
            continue

        ligne["_date"] = date
        ligne["_zone"] = nom_zone or "?"
        ligne["_distance_m"] = distance
        retenus.append(ligne)

    if sans_coordonnees:
        print(f"  ({sans_coordonnees} logement(s) sans coordonnees exploitables)")

    # Une adresse peut avoir plusieurs DPE : on ne garde que le plus recent
    par_adresse = {}
    for ligne in retenus:
        cle = str(ligne.get("adresse_ban") or ligne.get("n_dpe"))
        if cle not in par_adresse or ligne["_date"] > par_adresse[cle]["_date"]:
            par_adresse[cle] = ligne

    resultats = list(par_adresse.values())
    resultats.sort(key=lambda l: l["_date"], reverse=True)
    return resultats

# =====================================================================
#  Programme principal
# =====================================================================

def main():
    aujourdhui = datetime.date.today()
    limite = aujourdhui - datetime.timedelta(days=JOURS)

    print(f"\n=== DPE etablis depuis le {limite:%d/%m/%Y} ===")
    print(f"    codes postaux : {', '.join(CODES_POSTAUX)}")
    print(f"    commune : {COMMUNE or 'toutes'} · secteur : {ZONE or 'tous'}")
    print(f"    type : {TYPE_RECHERCHE or 'tous'} · "
          f"surface {SURFACE_MINIMUM} a {SURFACE_MAXIMUM} m²\n")

    selection = ",".join(champs_disponibles())

    toutes = []
    for code_postal in CODES_POSTAUX:
        print(f"  [{code_postal}] telechargement...")
        lignes = telecharger(code_postal, selection)
        print(f"      {len(lignes)} DPE au total")
        toutes.extend(lignes)

    resultats = filtrer(toutes, limite)
    print(f"\n  {len(resultats)} logement(s) correspondant aux criteres\n")

    if not resultats:
        print("  Aucun resultat. Elargis JOURS, ou verifie que la base est")
        print("  a jour : la transmission des DPE prend quelques semaines.\n")
        return

    print("=" * 66)
    for rang, ligne in enumerate(resultats, 1):
        anciennete = (aujourdhui - ligne["_date"]).days
        adresse = ligne.get("adresse_ban", "(adresse absente)")
        zone = ligne.get("_zone", "?")
        print(f"\n  {rang}. {ligne['_date']:%d/%m/%Y}  (il y a {anciennete} jours)"
              f"   [{zone}]")
        print(f"     {adresse}")

        details = []
        for libelle, cle in [("surface", "surface_habitable_logement"),
                             ("classe", "etiquette_dpe"),
                             ("construit en", "annee_construction"),
                             ("cout annuel", "cout_total_5_usages")]:
            valeur = ligne.get(cle)
            if valeur not in (None, ""):
                details.append(f"{libelle} {valeur}")
        if details:
            print("     " + " · ".join(details))

        requete = urllib.parse.quote(str(adresse))
        print(f"     https://www.google.com/maps/search/?api=1&query={requete}")

    print("\n" + "=" * 66)

    comptes = {}
    for ligne in resultats:
        comptes[ligne.get("_zone", "?")] = comptes.get(ligne.get("_zone", "?"), 0) + 1
    print("\n  Repartition : "
          + " · ".join(f"{nom} : {n}" for nom, n in sorted(comptes.items())))

    sortie = os.path.join(DOSSIER, FICHIER_SORTIE)
    for ligne in resultats:
        ligne["_date"] = str(ligne["_date"])
    colonnes = sorted({cle for ligne in resultats for cle in ligne})
    with open(sortie, "w", newline="", encoding="utf-8-sig") as fichier:
        redacteur = csv.DictWriter(fichier, fieldnames=colonnes, delimiter=";")
        redacteur.writeheader()
        redacteur.writerows(resultats)
    print(f"\n  Detail : {sortie}")
    print("\n  Rappel : un DPE recent peut aussi correspondre a une mise en")
    print("  location ou a un projet de travaux. Recoupe avant de conclure.\n")


if __name__ == "__main__":
    main()
    input("Appuie sur Entree pour fermer.")
