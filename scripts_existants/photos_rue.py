#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
photos_rue.py — Chercher des photos de rue libres pour chaque parcelle.

Interroge Panoramax (open data, sans compte) et, en option, Mapillary,
puis fabrique une PLANCHE CONTACT : une page HTML unique montrant toutes
les vignettes cote a cote. Bien plus rapide a parcourir que des onglets.

Usage :
    1. mets MODE_TEST = True et lance -> verifie que l'API repond
    2. passe MODE_TEST a False -> traite tout ton CSV

Aucune bibliotheque a installer (certifi est utilise s'il est present).
"""

import csv
import json
import math
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

MODE_TEST = True          # True = teste 3 points connus et s'arrete la

FICHIER_ENTREE = "parcelles_filtrees.csv"
FICHIER_SORTIE = "planche_contact.html"

RAYON_M = 70              # rayon de recherche autour du centre de la parcelle
MAX_PARCELLES = 150       # securite : on n'interroge pas plus que ca
PAUSE = 0.15              # secondes entre deux requetes (on reste poli)

# Instance Panoramax interrogee.
#   https://api.panoramax.xyz/api      -> meta-catalogue (toutes les instances)
#   https://panoramax.ign.fr/api       -> instance IGN, France
#   https://panoramax.openstreetmap.fr/api -> instance OSM France
INSTANCE = "https://api.panoramax.xyz/api"

# Mapillary : optionnel, necessite un jeton gratuit.
# Cree un compte sur mapillary.com, puis Developers > Register application.
# Le jeton commence par MLY|
MAPILLARY_TOKEN = ""

# =====================================================================
#  Connexion securisee (reprend le correctif certifi)
# =====================================================================

def creer_contexte_ssl():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


CONTEXTE = creer_contexte_ssl()
DOSSIER = os.path.dirname(os.path.abspath(__file__))


def appeler(url):
    """Appelle une URL et renvoie le JSON, ou None si ca echoue."""
    try:
        requete = urllib.request.Request(url, headers={"User-Agent": "photos_rue.py"})
        with urllib.request.urlopen(requete, timeout=30, context=CONTEXTE) as reponse:
            return json.loads(reponse.read().decode("utf-8"))
    except urllib.error.HTTPError as erreur:
        print(f"    HTTP {erreur.code} sur {url[:90]}")
    except Exception as erreur:
        print(f"    {type(erreur).__name__}: {erreur}")
    return None

# =====================================================================
#  Geometrie : construire un rectangle autour d'un point
# =====================================================================

def bbox_autour(latitude, longitude, rayon_metres):
    """
    Renvoie (lon_min, lat_min, lon_max, lat_max), le format attendu par
    les API cartographiques. Un degre de latitude vaut ~110 540 m ;
    un degre de longitude vaut la meme chose multipliee par cos(latitude).
    """
    d_lat = rayon_metres / 110540.0
    d_lon = rayon_metres / (110540.0 * math.cos(math.radians(latitude)))
    return (longitude - d_lon, latitude - d_lat,
            longitude + d_lon, latitude + d_lat)


def distance_m(lat1, lon1, lat2, lon2):
    """Distance approximative entre deux points, en metres."""
    d_lat = (lat2 - lat1) * 110540.0
    d_lon = (lon2 - lon1) * 110540.0 * math.cos(math.radians(lat1))
    return math.hypot(d_lat, d_lon)

# =====================================================================
#  Panoramax
# =====================================================================

def chercher_panoramax(latitude, longitude, rayon=RAYON_M):
    """
    Cherche la photo Panoramax la plus proche d'un point.
    L'API suit le standard STAC : /api/search avec un parametre bbox.
    Renvoie un dictionnaire, ou None si aucune photo.
    """
    lon_min, lat_min, lon_max, lat_max = bbox_autour(latitude, longitude, rayon)
    url = (f"{INSTANCE}/search?"
           + urllib.parse.urlencode({
               "bbox": f"{lon_min:.6f},{lat_min:.6f},{lon_max:.6f},{lat_max:.6f}",
               "limit": 30,
           }))

    reponse = appeler(url)
    if not reponse:
        return None

    meilleures = None
    for photo in reponse.get("features", []):
        coordonnees = (photo.get("geometry") or {}).get("coordinates")
        if not coordonnees:
            continue
        d = distance_m(latitude, longitude, coordonnees[1], coordonnees[0])
        if meilleures is None or d < meilleures["distance_m"]:
            assets = photo.get("assets", {})
            identifiant = photo.get("id", "")
            racine = INSTANCE.rsplit("/api", 1)[0]
            meilleures = {
                "source": "Panoramax",
                "id": identifiant,
                "distance_m": round(d),
                "date": (photo.get("properties") or {}).get("datetime", "")[:10],
                "vignette": (assets.get("thumb") or {}).get("href")
                            or f"{INSTANCE}/pictures/{identifiant}/thumb.jpg",
                "visionneuse": f"{racine}/#focus=pic&pic={identifiant}",
            }
    return meilleures

# =====================================================================
#  Mapillary (optionnel)
# =====================================================================

def chercher_mapillary(latitude, longitude, rayon=RAYON_M):
    """Equivalent chez Mapillary. Necessite MAPILLARY_TOKEN."""
    if not MAPILLARY_TOKEN:
        return None

    lon_min, lat_min, lon_max, lat_max = bbox_autour(latitude, longitude, rayon)
    url = ("https://graph.mapillary.com/images?"
           + urllib.parse.urlencode({
               "access_token": MAPILLARY_TOKEN,
               "fields": "id,computed_geometry,captured_at,thumb_1024_url",
               "bbox": f"{lon_min:.6f},{lat_min:.6f},{lon_max:.6f},{lat_max:.6f}",
               "limit": 20,
           }))

    reponse = appeler(url)
    if not reponse:
        return None

    meilleures = None
    for photo in reponse.get("data", []):
        coordonnees = (photo.get("computed_geometry") or {}).get("coordinates")
        if not coordonnees:
            continue
        d = distance_m(latitude, longitude, coordonnees[1], coordonnees[0])
        if meilleures is None or d < meilleures["distance_m"]:
            meilleures = {
                "source": "Mapillary",
                "id": photo.get("id", ""),
                "distance_m": round(d),
                "date": "",
                "vignette": photo.get("thumb_1024_url", ""),
                "visionneuse": f"https://www.mapillary.com/app/?pKey={photo.get('id','')}&focus=photo",
            }
    return meilleures

# =====================================================================
#  Mode test
# =====================================================================

def lancer_test():
    print("\n=== MODE TEST ===\n")
    print(f"Instance interrogee : {INSTANCE}\n")

    points = [
        ("Paris, place de la Bastille", 48.8532, 2.3692),
        ("Bordeaux, place de la Bourse", 44.8412, -0.5697),
        ("Mimizan, centre-bourg", 44.2011, -1.2286),
        ("Mimizan-Plage", 44.2044, -1.2914),
    ]

    for libelle, latitude, longitude in points:
        print(f"  {libelle}")
        resultat = chercher_panoramax(latitude, longitude, rayon=200)
        if resultat:
            print(f"    -> photo a {resultat['distance_m']} m, prise le {resultat['date']}")
            print(f"       {resultat['visionneuse']}")
        else:
            print("    -> aucune photo dans un rayon de 200 m")
        if MAPILLARY_TOKEN:
            resultat = chercher_mapillary(latitude, longitude, rayon=200)
            print(f"    Mapillary -> {'trouve' if resultat else 'rien'}")
        print()
        time.sleep(PAUSE)

    print("Si Paris et Bordeaux repondent mais pas Mimizan, l'API fonctionne :")
    print("c'est simplement que Mimizan n'est pas couverte.")
    print("Si RIEN ne repond, c'est l'API ou le reseau qu'il faut regarder.\n")

# =====================================================================
#  Traitement du CSV et planche contact
# =====================================================================

MODELE_HTML = """<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8">
<title>Planche contact — {nombre} parcelles</title>
<style>
 body {{ font-family: system-ui, sans-serif; margin: 24px; background: #f5f5f4; }}
 h1 {{ font-size: 20px; }}
 .grille {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; }}
 .fiche {{ background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 4px rgba(0,0,0,.12); }}
 .fiche img {{ width: 100%; height: 190px; object-fit: cover; display: block; background: #ddd; }}
 .infos {{ padding: 10px 12px; font-size: 13px; line-height: 1.5; }}
 .ref {{ font-weight: 600; }}
 .meta {{ color: #666; }}
 .liens a {{ margin-right: 10px; }}
 .vide {{ opacity: .45; }}
</style></head><body>
<h1>Planche contact — {nombre} parcelles ({avec} avec photo)</h1>
<p class="meta">Photos sous licence CC-BY-SA, via Panoramax / Mapillary.</p>
<div class="grille">
{fiches}
</div></body></html>
"""

MODELE_FICHE = """<div class="fiche{classe}">
  <img src="{vignette}" alt="" loading="lazy">
  <div class="infos">
    <div class="ref">{reference}</div>
    <div class="meta">{terrain} m² de terrain · {bati} m² bâtis<br>{adresse}</div>
    <div class="meta">{source}</div>
    <div class="liens"><a href="{visionneuse}" target="_blank">Photo</a>
      <a href="{satellite}" target="_blank">Satellite</a>
      <a href="{streetview}" target="_blank">Street View</a></div>
  </div>
</div>"""


def traiter_csv():
    chemin = os.path.join(DOSSIER, FICHIER_ENTREE)
    if not os.path.exists(chemin):
        sys.exit(f"Fichier introuvable : {chemin}")

    with open(chemin, "r", encoding="utf-8-sig", newline="") as fichier:
        lignes = list(csv.DictReader(fichier, delimiter=";"))

    if len(lignes) > MAX_PARCELLES:
        print(f"{len(lignes)} parcelles : on se limite aux {MAX_PARCELLES} premieres.")
        lignes = lignes[:MAX_PARCELLES]

    print(f"\nInterrogation de {len(lignes)} parcelles...\n")
    fiches = []
    avec_photo = 0

    for numero, ligne in enumerate(lignes, 1):
        latitude = float(ligne["latitude"])
        longitude = float(ligne["longitude"])

        photo = chercher_panoramax(latitude, longitude)
        if photo is None:
            photo = chercher_mapillary(latitude, longitude)

        if photo:
            avec_photo += 1
            source = f"{photo['source']} · {photo['distance_m']} m · {photo['date']}"
            vignette, visionneuse, classe = photo["vignette"], photo["visionneuse"], ""
        else:
            source, vignette, visionneuse, classe = "aucune photo libre", "", "#", " vide"

        fiches.append(MODELE_FICHE.format(
            classe=classe,
            vignette=vignette,
            reference=ligne.get("id_parcelle", ""),
            terrain=ligne.get("terrain_m2", "?"),
            bati=ligne.get("emprise_batie_m2", "?"),
            adresse=ligne.get("adresse_approx", "") or "&nbsp;",
            source=source,
            visionneuse=visionneuse,
            satellite=ligne.get("vue_aerienne", "#"),
            streetview=ligne.get("street_view", "#"),
        ))

        if numero % 20 == 0:
            print(f"  {numero}/{len(lignes)} — {avec_photo} avec photo")
        time.sleep(PAUSE)

    sortie = os.path.join(DOSSIER, FICHIER_SORTIE)
    with open(sortie, "w", encoding="utf-8") as fichier:
        fichier.write(MODELE_HTML.format(
            nombre=len(lignes), avec=avec_photo, fiches="\n".join(fiches)))

    print(f"\n{avec_photo} photos trouvees sur {len(lignes)} parcelles")
    print(f"Planche contact :\n  {sortie}")
    print("Ouvre ce fichier avec ton navigateur.\n")


if __name__ == "__main__":
    if MODE_TEST:
        lancer_test()
    else:
        traiter_csv()
    input("Appuie sur Entree pour fermer.")
