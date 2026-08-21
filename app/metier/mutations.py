# -*- coding: utf-8 -*-
"""
mutations.py — L'historique des ventes d'un bien (DVF).

Le rattachement passe par la parcelle, jamais par l'adresse : DVF et le
cadastre partagent `id_parcelle`, et les DPE y sont deja rattaches. Mesure
sur Mimizan : 95 % des parcelles citees par DVF se retrouvent au cadastre,
et 35 % des parcelles portant un DPE ont une vente connue sur cinq ans.

Le regroupement par mutation est la piece essentielle. Le fichier source
repete `valeur_fonciere` sur chaque ligne d'une meme vente — une par
parcelle et par local. Additionner ces lignes multiplie le prix : une vente
a 400 000 EUR sur quatre lignes en annoncerait 1 600 000. Sur Mimizan, 1 118
mutations sur 2 054 tiennent sur plusieurs lignes.
"""

import collections
import datetime
import json
import logging

from app.base.connexion import connexion, transaction
from app.sources import dvf
from app.sources.client_http import ErreurSource

logger = logging.getLogger(__name__)

# Un local sans surface ni type n'apporte rien a la fiche : c'est une ligne
# de terrain nu, deja comptee par la parcelle.
TYPES_UTILES = ("Maison", "Appartement")


def _nombre(valeur):
    try:
        return float(valeur)
    except (TypeError, ValueError):
        return None


def _regrouper(lignes):
    """
    Une entree par mutation, avec ses parcelles et ses locaux.

    C'est ici que se joue la justesse du prix affiche : `valeur_fonciere`
    est lue UNE fois par mutation, jamais additionnee entre les lignes.
    """
    par_mutation = collections.defaultdict(list)
    for ligne in lignes:
        identifiant = (ligne.get("id_mutation") or "").strip()
        if identifiant:
            par_mutation[identifiant].append(ligne)

    mutations = []
    for identifiant, groupe in par_mutation.items():
        tete = groupe[0]
        parcelles = {l["id_parcelle"].strip() for l in groupe
                     if (l.get("id_parcelle") or "").strip()}
        if not parcelles:
            continue        # sans parcelle, on ne saurait la rattacher

        locaux = [l for l in groupe if (l.get("type_local") or "").strip()]
        # Les surfaces, elles, s'additionnent : chaque ligne de local
        # decrit un bien distinct de la vente.
        surface_bati = sum(_nombre(l.get("surface_reelle_bati")) or 0 for l in locaux)
        # Le terrain se compte par parcelle, pas par ligne : une parcelle
        # portant deux locaux apparait deux fois.
        terrains = {}
        for ligne in groupe:
            cle = (ligne.get("id_parcelle") or "").strip()
            if cle:
                terrains[cle] = _nombre(ligne.get("surface_terrain")) or 0

        mutations.append({
            "id": identifiant,
            "code_insee": (tete.get("code_commune") or "").strip(),
            "date_mutation": (tete.get("date_mutation") or "").strip(),
            "nature": (tete.get("nature_mutation") or "").strip(),
            "valeur_fonciere": _nombre(tete.get("valeur_fonciere")),
            "parcelles": sorted(parcelles),
            "nb_locaux": len(locaux),
            "surface_bati_m2": surface_bati or None,
            "surface_terrain_m2": sum(terrains.values()) or None,
            "types_locaux": sorted({(l.get("type_local") or "").strip()
                                    for l in locaux}),
        })
    return mutations


def importer(code_insee, progression=None):
    """Telecharge et enregistre les ventes d'une commune."""
    code_insee = str(code_insee).strip()
    lignes = dvf.telecharger(code_insee, progression=progression)
    mutations = _regrouper(lignes)
    maintenant = datetime.datetime.now().isoformat(timespec="seconds")

    with transaction() as conn:
        # Remplacement en bloc : DVF republie la commune entiere a chaque
        # millesime, et corrige parfois des mutations passees.
        anciennes = [l[0] for l in conn.execute(
            "SELECT id FROM mutation WHERE code_insee = ?", (code_insee,))]
        if anciennes:
            marques = ", ".join("?" * len(anciennes))
            conn.execute(
                f"DELETE FROM mutation_parcelle WHERE mutation_id IN ({marques})",
                anciennes)
            conn.execute("DELETE FROM mutation WHERE code_insee = ?", (code_insee,))

        conn.executemany(
            "INSERT INTO mutation (id, code_insee, date_mutation, nature,"
            " valeur_fonciere, nb_parcelles, nb_locaux, surface_bati_m2,"
            " surface_terrain_m2, types_locaux_json, importe_le)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [(m["id"], m["code_insee"] or code_insee, m["date_mutation"],
              m["nature"], m["valeur_fonciere"], len(m["parcelles"]),
              m["nb_locaux"], m["surface_bati_m2"], m["surface_terrain_m2"],
              json.dumps(m["types_locaux"], ensure_ascii=False), maintenant)
             for m in mutations])
        conn.executemany(
            "INSERT OR IGNORE INTO mutation_parcelle (mutation_id, parcelle_id)"
            " VALUES (?,?)",
            [(m["id"], p) for m in mutations for p in m["parcelles"]])

        rattachees = conn.execute(
            "SELECT count(DISTINCT mp.parcelle_id) FROM mutation_parcelle mp"
            " JOIN parcelle p ON p.id = mp.parcelle_id"
            " WHERE p.code_insee = ?", (code_insee,)).fetchone()[0]

    logger.info("dvf %s : %d mutations, %d parcelles rattachees au cadastre",
                code_insee, len(mutations), rattachees)
    return {
        "mutations": len(mutations),
        "lignes": len(lignes),
        "parcelles_rattachees": rattachees,
        "message": f"{len(mutations)} vente(s) sur {len(lignes)} lignes",
    }


def _decorer(ligne):
    entree = dict(ligne)
    entree["types_locaux"] = json.loads(entree.pop("types_locaux_json") or "[]")

    # Le prix au metre carre n'a de sens que si la vente porte sur UN seul
    # local bati, sur une seule parcelle. Sinon on rapporterait le prix
    # d'une maison, d'un garage et d'un terrain a la seule surface de la
    # maison — un chiffre faux, et flatteur.
    entree["prix_m2"] = None
    entree["prix_m2_incertain"] = True
    if (entree["nb_locaux"] == 1 and entree["nb_parcelles"] == 1
            and entree.get("surface_bati_m2") and entree.get("valeur_fonciere")):
        entree["prix_m2"] = round(
            entree["valeur_fonciere"] / entree["surface_bati_m2"])
        entree["prix_m2_incertain"] = False
    return entree


def pour_parcelle(parcelle_id):
    """Les ventes connues pour une parcelle, de la plus recente a la plus ancienne."""
    if not parcelle_id:
        return []
    with connexion() as conn:
        lignes = conn.execute(
            "SELECT m.* FROM mutation m"
            " JOIN mutation_parcelle mp ON mp.mutation_id = m.id"
            " WHERE mp.parcelle_id = ?"
            " ORDER BY m.date_mutation DESC", (str(parcelle_id),)).fetchall()
    return [_decorer(l) for l in lignes]


def pour_dpe(n_dpe):
    """Les ventes de la parcelle qui porte ce DPE."""
    with connexion() as conn:
        ligne = conn.execute(
            "SELECT parcelle_id FROM dpe WHERE n_dpe = ?", (str(n_dpe),)).fetchone()
    if ligne is None or not ligne["parcelle_id"]:
        return []
    return pour_parcelle(ligne["parcelle_id"])


def manquantes(code_insee):
    """
    Cette commune a-t-elle un cadastre mais aucune vente enregistree ?

    Sert au meme usage que `batiments_manquants` : une base montee avant
    l'arrivee de DVF a des parcelles et rien d'autre, et la fiche resterait
    muette sans que rien ne l'explique.
    """
    code_insee = str(code_insee)
    with connexion() as conn:
        parcelles = conn.execute(
            "SELECT count(*) FROM parcelle WHERE code_insee = ?",
            (code_insee,)).fetchone()[0]
        ventes = conn.execute(
            "SELECT count(*) FROM mutation WHERE code_insee = ?",
            (code_insee,)).fetchone()[0]
    return bool(parcelles) and not ventes
