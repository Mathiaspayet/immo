# -*- coding: utf-8 -*-
"""
boosting.py — Le gradient boosting, quatrieme methode du croisement.

Un modele par departement et par type de bien, appris sur ses ventes
(LightGBM : des centaines de petits arbres de decision, chacun corrigeant
l'erreur des precedents). Il voit ce que la regression lineaire ne voit
pas : un effet de la surface qui s'emousse, un terrain qui ne compte plus
au-dela d'une certaine taille, une position qui vaut plus pres d'un lac.

CE QU'IL APPREND : le prix ramene au niveau actuel du marche (comme les
autres methodes), a partir de la surface, du terrain, des pieces, des
dependances, de la VEFA, de la position, et du PRIX AU M2 DES VENTES
VOISINES avec leur eloignement. Ce dernier trait est celui qui porte le
plus : il donne au modele le marche local, qu'un arbre ne reconstituerait
pas a partir des seules coordonnees. Pour une vente d'apprentissage, ses
voisines excluent la vente elle-meme — sinon le modele apprendrait a
recopier son propre prix.

CE QU'IL APPORTE, mesure sur la derniere annee (erreur mediane du
croisement, sans puis avec lui) : maisons des Landes 18,3 -> 17,8 %, de
Gironde 17,6 -> 17,2 %, de Creuse 31,6 -> 31,0 % ; appartements des Landes
12,0 -> 11,6 %, de Gironde 12,1 -> 11,3 %, de Creuse 18,7 -> 17,8 %. Seul
il vaut les meilleures methodes ; c'est croise qu'il sert.

Il reste FACULTATIF : sans LightGBM installe, le croisement se fait sans
lui, et l'application le dit.

Rien ne sort : l'apprentissage se fait sur le NAS, en quelques secondes
par departement.
"""

import logging
import os
import zlib

import numpy as np

try:
    import lightgbm
except ImportError:                              # pragma: no cover - depend de l'image
    lightgbm = None

logger = logging.getLogger(__name__)

K_VOISINS = 12
TOURS = 900
# Ceux de l'etude, ou ils ont ete eprouves sur seize departements. Deux
# fils d'execution : le NAS a autre chose a faire pendant l'apprentissage.
PARAMETRES = {
    "objective": "regression",
    "learning_rate": 0.03,
    "num_leaves": 31,
    "min_data_in_leaf": 30,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "feature_fraction": 0.8,
    "seed": 0,
    "deterministic": True,
    "force_row_wise": True,
    "num_threads": max(1, min(2, os.cpu_count() or 1)),
    "verbose": -1,
}


def disponible():
    return lightgbm is not None


def noms_des_traits(type_bien):
    noms = ["log_surface", "pieces", "dependances", "vefa", "latitude", "longitude",
            "log_prix_m2_voisins", "log_distance_voisins"]
    if type_bien == "maison":
        noms.insert(1, "log_terrain")
    return noms


def prix_voisins(pm2, distances, surfaces_voisines, surfaces):
    """
    Le prix au m2 des ventes voisines, en mediane ponderee : plus de poids
    aux plus proches et a celles de surface voisine — le meme calcul que la
    methode des comparables, fait pour un lot entier.
    """
    poids = (1.0 / (1.0 + distances / 300.0)
             * np.exp(-np.abs(np.log(surfaces_voisines / surfaces[:, None]))))
    ordre = np.argsort(pm2, axis=1)
    pm2 = np.take_along_axis(pm2, ordre, axis=1)
    poids = np.take_along_axis(poids, ordre, axis=1)
    cumul = np.cumsum(poids, axis=1) / poids.sum(axis=1, keepdims=True)
    return pm2[np.arange(len(pm2)), (cumul < 0.5).sum(axis=1)]


def traits(type_bien, caracteristiques, pm2_voisins, distances):
    """La matrice des traits, dans l'ordre de `noms_des_traits`."""
    c = caracteristiques
    colonnes = {
        "log_surface": np.log(c["surface"]),
        "log_terrain": np.log1p(np.maximum(c["terrain_m2"], 0)),
        "pieces": c["pieces"], "dependances": c["dependances"], "vefa": c["vefa"],
        "latitude": c["latitude"], "longitude": c["longitude"],
        "log_prix_m2_voisins": np.log(pm2_voisins),
        "log_distance_voisins": np.log1p(np.median(distances, axis=1)),
    }
    return np.column_stack([colonnes[nom] for nom in noms_des_traits(type_bien)])


def apprendre(x, y):
    """Un modele appris, ou None si LightGBM manque."""
    if lightgbm is None:
        return None
    jeu = lightgbm.Dataset(x, label=y, free_raw_data=True)
    return lightgbm.train(PARAMETRES, jeu, num_boost_round=TOURS)


def predire(modele, x):
    return modele.predict(np.atleast_2d(x), num_threads=1)


def vers_octets(modele):
    """Le modele, compresse : 2 a 3 Mo de texte, quatre fois moins en base."""
    return zlib.compress(modele.model_to_string().encode("utf-8"), 6)


def depuis_octets(octets):
    if lightgbm is None or not octets:
        return None
    return lightgbm.Booster(model_str=zlib.decompress(octets).decode("utf-8"))
