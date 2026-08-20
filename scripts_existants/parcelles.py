#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
parcelles.py — Filtrer les parcelles cadastrales d'une commune française.

Ce script :
  1. retrouve le code INSEE d'une commune à partir de son nom,
  2. télécharge le cadastre (parcelles + bâtiments) depuis les données ouvertes,
  3. calcule pour chaque parcelle : la surface du terrain et l'emprise bâtie,
  4. garde uniquement celles qui correspondent à tes critères,
  5. écrit un fichier CSV avec des liens cliquables (vue aérienne, Street View).

Aucune bibliothèque à installer : uniquement la bibliothèque standard de Python.

Usage :
    python3 parcelles.py
(les réglages se font dans la section CONFIGURATION juste en dessous)
"""

import csv
import gzip
import json
import math
import os
import ssl
import sys
import time
import urllib.parse
import urllib.request

# =====================================================================
#  CONFIGURATION — c'est la SEULE partie que tu as besoin de modifier
# =====================================================================

COMMUNE = "Mimizan"          # nom de la commune
CODE_DEPARTEMENT = "40"      # département, pour lever les homonymes

# Surface du TERRAIN recherchée, en m² (la "contenance" cadastrale)
TERRAIN_MIN = 400
TERRAIN_MAX = 2000

# EMPRISE BÂTIE au sol recherchée, en m²
# Repère : une maison de 120 m² habitables de plain-pied ≈ 120 m² d'emprise ;
# la même sur 2 niveaux ≈ 60-70 m² d'emprise.
BATI_MIN = 60
BATI_MAX = 250

# Chercher aussi l'adresse approximative de chaque parcelle ?
# (une requête réseau par parcelle : laisse False si tu as des milliers de résultats)
CHERCHER_ADRESSES = True
MAX_ADRESSES = 300           # sécurité : au-delà, on n'interroge pas

# Les fichiers produits sont écrits À CÔTÉ de ce script, quel que soit le dossier
# depuis lequel tu le lances (sinon ils atterrissent dans le "dossier courant"
# du terminal, ce qui réserve de mauvaises surprises).
DOSSIER_DU_SCRIPT = os.path.dirname(os.path.abspath(__file__))

FICHIER_SORTIE = os.path.join(DOSSIER_DU_SCRIPT, "parcelles_filtrees.csv")
DOSSIER_CACHE = os.path.join(DOSSIER_DU_SCRIPT, "cache_cadastre")

# Vérification des certificats HTTPS.
# Laisse True. Ne passe à False QUE si le script refuse de se connecter avec une
# erreur "CERTIFICATE_VERIFY_FAILED" et que tu as épuisé les autres pistes.
VERIFIER_CERTIFICATS = True

# =====================================================================
#  ÉTAPE 0 — Préparer la connexion sécurisée (HTTPS)
# =====================================================================
# Pour vérifier qu'un site est bien celui qu'il prétend être, Python a besoin
# d'une liste d'autorités de certification de confiance. Sous Windows, il
# utilise celle de Windows, qui est parfois périmée ou incomplète.
# On préfère donc, si elle est disponible, la liste maintenue par le paquet
# "certifi" (celle de Mozilla, toujours à jour).

def creer_contexte_ssl():
    if not VERIFIER_CERTIFICATS:
        print("  [!] ATTENTION : vérification des certificats DÉSACTIVÉE")
        contexte = ssl.create_default_context()
        contexte.check_hostname = False
        contexte.verify_mode = ssl.CERT_NONE
        return contexte
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


CONTEXTE_SSL = creer_contexte_ssl()


def expliquer_erreur_ssl():
    """Message d'aide affiché si la connexion sécurisée échoue."""
    print("""
  ------------------------------------------------------------------
  ÉCHEC DE LA CONNEXION SÉCURISÉE (certificat refusé)

  Le serveur est en cause dans moins de 1 % des cas. Essaie dans l'ordre :

  1. VÉRIFIE LA DATE ET L'HEURE DE TON PC.
     Une horloge décalée fait apparaître tous les certificats comme
     expirés. Windows : Paramètres > Heure et langue > Date et heure,
     puis clique sur "Synchroniser maintenant".

  2. INSTALLE LA LISTE DE CERTIFICATS À JOUR.
     Dans un terminal :   pip install certifi
     Puis relance ce script : il l'utilisera automatiquement.

  3. ANTIVIRUS. Si tu utilises Kaspersky, ESET, Avast ou Bitdefender,
     désactive l'option d'analyse du trafic HTTPS (elle s'interpose
     dans les connexions) et réessaie.

  4. EN DERNIER RECOURS, mets VERIFIER_CERTIFICATS = False en haut de
     ce fichier. Les données téléchargées sont publiques, le risque est
     faible, mais ce n'est pas une bonne habitude à prendre.
  ------------------------------------------------------------------
""")

# =====================================================================
#  ÉTAPE 1 — Retrouver le code INSEE de la commune
# =====================================================================

def telecharger_json(url):
    """Télécharge une URL et renvoie le contenu interprété comme du JSON."""
    requete = urllib.request.Request(url, headers={"User-Agent": "parcelles.py"})
    with urllib.request.urlopen(requete, timeout=60, context=CONTEXTE_SSL) as reponse:
        return json.loads(reponse.read().decode("utf-8"))


def trouver_code_insee(nom_commune, code_departement):
    """Interroge l'API Découpage administratif (geo.api.gouv.fr)."""
    url = ("https://geo.api.gouv.fr/communes?nom="
           + urllib.parse.quote(nom_commune)
           + "&codeDepartement=" + code_departement
           + "&fields=nom,code&format=json")
    resultats = telecharger_json(url)
    if not resultats:
        sys.exit(f"Aucune commune '{nom_commune}' trouvée dans le {code_departement}.")
    # L'API classe par pertinence : le premier résultat est le bon dans 99 % des cas.
    print(f"  Commune retenue : {resultats[0]['nom']} (INSEE {resultats[0]['code']})")
    if len(resultats) > 1:
        autres = ", ".join(f"{r['nom']} ({r['code']})" for r in resultats[1:4])
        print(f"  (autres correspondances possibles : {autres})")
    return resultats[0]["code"]

# =====================================================================
#  ÉTAPE 2 — Télécharger les couches cadastrales
# =====================================================================

def telecharger_couche(code_insee, couche):
    """
    Récupère une couche GeoJSON du cadastre Etalab pour une commune.
    couche vaut 'parcelles' ou 'batiments'.
    Le fichier est mis en cache sur le disque pour ne pas le retélécharger.
    """
    os.makedirs(DOSSIER_CACHE, exist_ok=True)
    chemin_local = os.path.join(DOSSIER_CACHE, f"{code_insee}-{couche}.json")

    if os.path.exists(chemin_local):
        print(f"  {couche} : déjà en cache")
    else:
        departement = code_insee[:2]
        url = ("https://cadastre.data.gouv.fr/data/etalab-cadastre/latest/geojson/"
               f"communes/{departement}/{code_insee}/cadastre-{code_insee}-{couche}.json.gz")
        print(f"  {couche} : téléchargement...")
        requete = urllib.request.Request(url, headers={"User-Agent": "parcelles.py"})
        with urllib.request.urlopen(requete, timeout=300, context=CONTEXTE_SSL) as reponse:
            donnees_compressees = reponse.read()
        # Le fichier arrive compressé en .gz : on le décompresse avant de l'écrire.
        with open(chemin_local, "wb") as fichier:
            fichier.write(gzip.decompress(donnees_compressees))

    with open(chemin_local, "r", encoding="utf-8") as fichier:
        geojson = json.load(fichier)
    print(f"  {couche} : {len(geojson['features'])} objets chargés")
    return geojson["features"]

# =====================================================================
#  ÉTAPE 3 — Un peu de géométrie
# =====================================================================
# Le GeoJSON donne des coordonnées en degrés (longitude, latitude).
# Pour calculer des surfaces en m², on les convertit d'abord en mètres
# avec une approximation locale (largement suffisante à l'échelle d'une commune).

METRES_PAR_DEGRE_LAT = 110540.0


def anneaux_exterieurs(geometrie):
    """
    Renvoie la liste des contours extérieurs d'une géométrie.
    Un Polygon a un contour ; un MultiPolygon en a plusieurs.
    """
    if geometrie is None:
        return []
    if geometrie["type"] == "Polygon":
        return [geometrie["coordinates"][0]]
    if geometrie["type"] == "MultiPolygon":
        return [polygone[0] for polygone in geometrie["coordinates"]]
    return []


def surface_m2(anneau):
    """
    Surface d'un contour fermé, par la formule dite "des lacets" (shoelace).
    On projette localement les degrés en mètres avant de calculer.
    """
    if len(anneau) < 3:
        return 0.0
    latitude_moyenne = sum(point[1] for point in anneau) / len(anneau)
    metres_par_degre_lon = METRES_PAR_DEGRE_LAT * math.cos(math.radians(latitude_moyenne))

    total = 0.0
    for i in range(len(anneau)):
        x1, y1 = anneau[i][0] * metres_par_degre_lon, anneau[i][1] * METRES_PAR_DEGRE_LAT
        x2, y2 = anneau[i - 1][0] * metres_par_degre_lon, anneau[i - 1][1] * METRES_PAR_DEGRE_LAT
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def centre(anneau):
    """Point moyen d'un contour : suffisant pour situer un bâtiment."""
    longitude = sum(point[0] for point in anneau) / len(anneau)
    latitude = sum(point[1] for point in anneau) / len(anneau)
    return longitude, latitude


def point_dans_anneau(longitude, latitude, anneau):
    """
    Teste si un point est à l'intérieur d'un contour (algorithme du lancer de rayon) :
    on trace une demi-droite horizontale depuis le point et on compte les
    intersections avec le contour. Nombre impair => le point est dedans.
    """
    dedans = False
    j = len(anneau) - 1
    for i in range(len(anneau)):
        xi, yi = anneau[i]
        xj, yj = anneau[j]
        if (yi > latitude) != (yj > latitude):
            x_intersection = (xj - xi) * (latitude - yi) / (yj - yi) + xi
            if longitude < x_intersection:
                dedans = not dedans
        j = i
    return dedans


def boite_englobante(anneaux):
    """Rectangle minimal contenant la géométrie : (lon_min, lat_min, lon_max, lat_max)."""
    longitudes = [p[0] for anneau in anneaux for p in anneau]
    latitudes = [p[1] for anneau in anneaux for p in anneau]
    return min(longitudes), min(latitudes), max(longitudes), max(latitudes)

# =====================================================================
#  ÉTAPE 4 — Associer chaque bâtiment à sa parcelle
# =====================================================================
# Comparer chaque bâtiment à chaque parcelle serait beaucoup trop lent
# (10 000 x 20 000 = 200 millions de comparaisons).
# Astuce : on découpe la commune en cases d'environ 100 m de côté et on note,
# pour chaque case, quelles parcelles la touchent. Pour un bâtiment donné,
# on ne teste alors qu'une poignée de parcelles.

TAILLE_CASE = 0.001   # en degrés, soit ~110 m


def cases_couvertes(lon_min, lat_min, lon_max, lat_max):
    """Liste des cases de la grille recouvertes par un rectangle."""
    resultat = []
    for ix in range(int(lon_min / TAILLE_CASE), int(lon_max / TAILLE_CASE) + 1):
        for iy in range(int(lat_min / TAILLE_CASE), int(lat_max / TAILLE_CASE) + 1):
            resultat.append((ix, iy))
    return resultat


def associer_batiments(parcelles, batiments):
    """
    Renvoie deux dictionnaires indexés par identifiant de parcelle :
    l'emprise bâtie totale (m²) et le nombre de bâtiments.
    """
    # -- Construction de la grille --
    grille = {}
    geometries = {}
    for parcelle in parcelles:
        identifiant = parcelle["properties"]["id"]
        anneaux = anneaux_exterieurs(parcelle["geometry"])
        if not anneaux:
            continue
        geometries[identifiant] = anneaux
        for case in cases_couvertes(*boite_englobante(anneaux)):
            grille.setdefault(case, []).append(identifiant)

    emprise = {}
    nombre = {}
    for batiment in batiments:
        for anneau in anneaux_exterieurs(batiment["geometry"]):
            longitude, latitude = centre(anneau)
            case = (int(longitude / TAILLE_CASE), int(latitude / TAILLE_CASE))
            for identifiant in grille.get(case, []):
                if any(point_dans_anneau(longitude, latitude, a)
                       for a in geometries[identifiant]):
                    emprise[identifiant] = emprise.get(identifiant, 0.0) + surface_m2(anneau)
                    nombre[identifiant] = nombre.get(identifiant, 0) + 1
                    break   # un bâtiment n'appartient qu'à une parcelle
    return emprise, nombre

# =====================================================================
#  ÉTAPE 5 — Adresse approximative (Base Adresse Nationale)
# =====================================================================

def adresse_la_plus_proche(longitude, latitude):
    """Géocodage inverse via l'API Adresse de l'État. Renvoie '' en cas d'échec."""
    url = f"https://api-adresse.data.gouv.fr/reverse/?lon={longitude:.6f}&lat={latitude:.6f}"
    try:
        reponse = telecharger_json(url)
        entites = reponse.get("features", [])
        return entites[0]["properties"]["label"] if entites else ""
    except Exception:
        return ""

# =====================================================================
#  PROGRAMME PRINCIPAL
# =====================================================================

def main():
    print("\n[1/5] Recherche de la commune")
    try:
        code_insee = trouver_code_insee(COMMUNE, CODE_DEPARTEMENT)
    except Exception as erreur:
        if "CERTIFICATE_VERIFY_FAILED" in str(erreur):
            expliquer_erreur_ssl()
            sys.exit(1)
        raise

    print("\n[2/5] Téléchargement du cadastre")
    parcelles = telecharger_couche(code_insee, "parcelles")
    batiments = telecharger_couche(code_insee, "batiments")

    print("\n[3/5] Association des bâtiments aux parcelles (peut prendre 10-60 s)")
    debut = time.time()
    emprise_batie, nombre_batiments = associer_batiments(parcelles, batiments)
    print(f"  terminé en {time.time() - debut:.0f} s "
          f"— {len(emprise_batie)} parcelles bâties")

    print("\n[4/5] Filtrage")
    retenues = []
    for parcelle in parcelles:
        proprietes = parcelle["properties"]
        identifiant = proprietes["id"]

        terrain = int(proprietes.get("contenance") or 0)   # m², donné par le cadastre
        bati = emprise_batie.get(identifiant, 0.0)

        if not (TERRAIN_MIN <= terrain <= TERRAIN_MAX):
            continue
        if not (BATI_MIN <= bati <= BATI_MAX):
            continue

        anneaux = anneaux_exterieurs(parcelle["geometry"])
        if not anneaux:
            continue
        longitude, latitude = centre(anneaux[0])

        retenues.append({
            "id_parcelle": identifiant,
            "section": proprietes.get("section", ""),
            "numero": proprietes.get("numero", ""),
            "terrain_m2": terrain,
            "emprise_batie_m2": round(bati),
            "nb_batiments": nombre_batiments.get(identifiant, 0),
            "latitude": round(latitude, 6),
            "longitude": round(longitude, 6),
            "adresse_approx": "",
            "vue_aerienne": f"https://www.google.com/maps/search/?api=1&query={latitude:.6f},{longitude:.6f}",
            "street_view": f"https://www.google.com/maps/@?api=1&map_action=pano&viewpoint={latitude:.6f},{longitude:.6f}",
            "geoportail": f"https://www.geoportail.gouv.fr/carte?c={longitude:.6f},{latitude:.6f}&z=19&l0=ORTHOIMAGERY.ORTHOPHOTOS",
        })
    print(f"  {len(retenues)} parcelles retenues sur {len(parcelles)}")

    print("\n[5/5] Adresses et écriture du fichier")
    if CHERCHER_ADRESSES and 0 < len(retenues) <= MAX_ADRESSES:
        for i, ligne in enumerate(retenues, 1):
            ligne["adresse_approx"] = adresse_la_plus_proche(ligne["longitude"], ligne["latitude"])
            if i % 25 == 0:
                print(f"  {i}/{len(retenues)} adresses")
            time.sleep(0.05)   # on reste poli avec l'API publique
    elif CHERCHER_ADRESSES:
        print(f"  adresses ignorées (plus de {MAX_ADRESSES} résultats — resserre tes critères)")

    if not retenues:
        print("\nAucun résultat : élargis les fourchettes en haut du fichier.")
        return

    retenues.sort(key=lambda l: l["terrain_m2"], reverse=True)
    with open(FICHIER_SORTIE, "w", newline="", encoding="utf-8-sig") as fichier:
        redacteur = csv.DictWriter(fichier, fieldnames=list(retenues[0].keys()), delimiter=";")
        redacteur.writeheader()
        redacteur.writerows(retenues)

    print(f"\nTerminé : {len(retenues)} lignes écrites dans")
    print(f"  {FICHIER_SORTIE}")


if __name__ == "__main__":
    main()
