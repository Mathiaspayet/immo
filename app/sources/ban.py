# -*- coding: utf-8 -*-
"""
ban.py — Geocodage par la Base Adresse Nationale.

Pourquoi ce module existe : environ 5 % des DPE d'une commune n'ont PAS de
code INSEE. Le geocodage de l'ADEME a echoue sur eux, et comme
l'application interroge par code INSEE, ils lui sont invisibles. Mesure sur
Mimizan le 24/08/2026 : 102 manquants pour 2 023 vus, dont 48 maisons — et
46 de ces maisons datent de 2025 ou 2026.

Ils ne sont pourtant pas douteux. Leur adresse brute est bien renseignee ;
c'est son bavardage qui a noye le geocodeur :

    « 5 rue Bremontier - Residence Cap Ocean - Apt 317 »

Coupe apres le nom de voie, la BAN la retrouve sans peine. Verifie sur les
cinq adresses distinctes d'un echantillon : cinq sur cinq placees a
Mimizan, scores de 0,70 a 0,96.

Le code INSEE que rend la BAN sert de GARDE-FOU. Un code postal couvre
plusieurs communes — le 40200 en couvre cinq — et on ne retient que les
adresses que la BAN place dans la commune visee. Sans cela, reparer les
orphelins de Mimizan y ferait entrer ceux d'Aureilhan.

L'API est celle du CDC section 4, deja declaree. Rien ne sort d'autre que
l'adresse a geocoder : ni numero de DPE, ni valeur energetique.
"""

import csv
import io
import logging
import re
import urllib.error
import urllib.request
import uuid

from app.sources.client_http import CONTEXTE, ENTETES, ErreurSource

logger = logging.getLogger(__name__)

BASE = "https://api-adresse.data.gouv.fr/search/csv/"
DELAI = 180

# En deca, la reponse de la BAN est une devinette. Mesure sur Mimizan : les
# bonnes correspondances tombent entre 0,70 et 0,96, et une rue seule sans
# numero sort a 0,40. On accepte donc la rue mais pas le hasard.
SCORE_MINIMUM = 0.55

# La BAN accepte de gros fichiers ; on decoupe tout de meme, pour qu'un
# echec ne coute pas tout et pour ne pas tenir 50 Mo en memoire.
PAQUET = 500


def nettoyer(adresse):
    """
    Coupe ce qui suit le nom de voie.

    « 5 rue Bremontier - Residence Cap Ocean - Apt 317 » devient
    « 5 rue Bremontier ». C'est exactement ce qui manquait au geocodeur de
    l'ADEME : le complement de residence et le numero d'appartement ne
    figurent dans aucun referentiel d'adresses.
    """
    texte = " ".join(str(adresse or "").split())
    if not texte:
        return ""
    # Le tiret entoure d'espaces separe l'adresse de son complement ; un
    # tiret colle appartient au nom (« Saint-Julien », « 5-7 »).
    texte = re.split(r"\s+[-–—]\s+", texte)[0]
    # Puis les mots qui n'appartiennent jamais a une voie.
    texte = re.split(r"(?i)\b(?:r[ée]s(?:idence)?|appt?|apt|b[âa]t(?:iment)?|"
                     r"lot|etage|[ée]tage|esc(?:alier)?)\b", texte)[0]
    texte = re.sub(r"(?i)\bn°\s*\w+", "", texte)
    return " ".join(texte.split())


def _multipart(csv_texte, champs):
    """Construit un corps multipart. La BAN n'accepte que ce format."""
    frontiere = "----veille" + uuid.uuid4().hex
    morceaux = []
    for nom, valeur in champs:
        morceaux.append(f"--{frontiere}\r\n"
                        f'Content-Disposition: form-data; name="{nom}"\r\n\r\n'
                        f"{valeur}\r\n")
    morceaux.append(f"--{frontiere}\r\n"
                    'Content-Disposition: form-data; name="data";'
                    ' filename="adresses.csv"\r\n'
                    "Content-Type: text/csv\r\n\r\n"
                    f"{csv_texte}\r\n")
    morceaux.append(f"--{frontiere}--\r\n")
    return "".join(morceaux).encode("utf-8"), frontiere


def _lot(adresses, code_postal):
    """Geocode un paquet d'adresses. Renvoie [{...}] alignes sur l'entree."""
    tampon = io.StringIO()
    graveur = csv.writer(tampon)
    graveur.writerow(["adresse", "cp"])
    for adresse in adresses:
        graveur.writerow([adresse, code_postal or ""])

    corps, frontiere = _multipart(tampon.getvalue(), [
        ("columns", "adresse"),
        # `postcode` restreint la recherche : sans lui, « rue de la Poste »
        # renverrait la premiere de France.
        ("postcode", "cp"),
        ("result_columns", "result_score"),
        ("result_columns", "result_citycode"),
        ("result_columns", "result_label"),
        ("result_columns", "latitude"),
        ("result_columns", "longitude"),
    ])
    requete = urllib.request.Request(
        BASE, data=corps, method="POST",
        headers={**ENTETES,
                 "Content-Type": f"multipart/form-data; boundary={frontiere}"})
    with urllib.request.urlopen(requete, timeout=DELAI, context=CONTEXTE) as reponse:
        rendu = reponse.read().decode("utf-8", "replace")
    return list(csv.DictReader(io.StringIO(rendu)))


def geocoder(adresses, code_postal, code_insee_attendu=None):
    """
    Geocode une liste d'adresses brutes.

    Renvoie {adresse_brute: {latitude, longitude, label, score, code_insee}}
    pour les seules adresses reconnues. Une adresse que la BAN place dans
    une AUTRE commune que celle attendue est ecartee : c'est ce qui empeche
    la reparation des orphelins de Mimizan d'y faire entrer ceux
    d'Aureilhan, le code postal 40200 en couvrant cinq.
    """
    propres = {}
    for brute in adresses:
        propre = nettoyer(brute)
        if propre:
            propres.setdefault(propre, []).append(brute)
    if not propres:
        return {}

    trouvees, liste = {}, list(propres)
    for debut in range(0, len(liste), PAQUET):
        paquet = liste[debut:debut + PAQUET]
        try:
            resultats = _lot(paquet, code_postal)
        except urllib.error.HTTPError as erreur:
            raise ErreurSource(f"BAN : HTTP {erreur.code}") from erreur
        except Exception as erreur:                  # noqa: BLE001
            raise ErreurSource(
                f"BAN injoignable ({type(erreur).__name__})") from erreur

        for ligne in resultats:
            propre = (ligne.get("adresse") or "").strip()
            try:
                score = float(ligne.get("result_score") or 0)
                latitude = float(ligne.get("latitude"))
                longitude = float(ligne.get("longitude"))
            except (TypeError, ValueError):
                continue
            code_insee = (ligne.get("result_citycode") or "").strip()
            if score < SCORE_MINIMUM:
                continue
            if code_insee_attendu and code_insee != str(code_insee_attendu):
                continue
            for brute in propres.get(propre, []):
                trouvees[brute] = {
                    "latitude": latitude, "longitude": longitude,
                    "label": (ligne.get("result_label") or "").strip(),
                    "score": score, "code_insee": code_insee,
                }

    logger.info("ban : %d adresse(s) sur %d placee(s) dans %s",
                len(trouvees), len(adresses), code_insee_attendu or "la zone")
    return trouvees
