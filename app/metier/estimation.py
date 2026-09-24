# -*- coding: utf-8 -*-
"""
estimation.py — Estimer la valeur d'un bien, et dire avec quelle precision.

La methode a ete choisie sur preuve, par une etude sur les ventes 2021-2025
de seize departements (Nouvelle-Aquitaine, Paris, Rhone) : apprendre sur le
passe, predire l'annee suivante, deux fois. Ce qui en est retenu :

  - PLUSIEURS METHODES CROISEES valent mieux qu'une. La moyenne
    geometrique des comparables, de la regression hedonique, de la methode
    sol + construction (pour une maison) et du gradient boosting bat
    chacune prise seule, partout : maisons de Mimizan 14,6 et 18,9 %
    d'erreur mediane selon l'annee, contre 21,8 et 25,9 % pour le prix au
    m2 de la commune ;
  - L'HISTORIQUE DU BIEN, quand il a deja ete vendu, est le signal le plus
    precis (13,7 % pour une maison) : l'ancien prix contient deja l'etat,
    la vue, la piscine. Il pese les deux tiers pour une maison, la moitie
    pour un appartement, et l'erreur tombe a 11-12 % ;
  - le departement est la bonne echelle : un modele regional ne fait
    jamais mieux, meme en Creuse ;
  - le DPE n'ameliore PAS la precision (16,0 % sans, 16,2 % avec) : il
    n'entre donc pas dans le calcul — son annee de construction, si, pour
    la vetuste ;
  - l'ETAT DU BATI, que rien ne mesure dans les donnees, est ce qui reste
    d'erreur. Il est saisi, sur l'echelle officielle du coefficient
    d'entretien (CGI, annexe III, art. 324 Q).

L'APPLICATION MESURE SA PROPRE PRECISION. A chaque apprentissage, elle
refait tout le calcul sur les ventes d'avant la derniere annee et le
confronte aux prix de cette derniere annee. La fourchette affichee et le
niveau de fiabilite viennent de LA — les erreurs reelles de ce departement,
pour ce type de bien — et non d'un chiffre national : une maison de Gironde
s'estime a 18 % pres, une maison de Creuse a 32 %.

Tout est calcule sur le serveur, a partir de sources publiques. Rien du
bien estime ne sort.
"""

import datetime
import json
import logging
import math
import threading

import numpy as np

from app.base.connexion import connexion, transaction
from app.metier import boosting, references
from app.metier.voisinage import Voisinage
from app.sources import insee, loyers
from app.sources.client_http import ErreurSource

logger = logging.getLogger(__name__)

TYPES = ("maison", "appartement")
# 2 : le gradient boosting rejoint le croisement. Un modele d'une version
# anterieure est re-appris au prochain passage du planificateur.
VERSION_MODELE = 2
K_COMPARABLES = 12
K_TERRAINS = 10
RETRAIT_COMMUNE = 10.0        # « poids » de la moyenne departementale pour une commune
MIN_VENTES = 150              # en dessous, un type de bien n'est pas modelise
ECHANTILLON_TEST = 1500       # ventes de la derniere annee pour l'auto-evaluation

# Sol + construction. Le cout a neuf vient de l'enquete EPTB 2024 (Landes :
# 193 500 EUR de construction pour un projet moyen, soit ~1 700 EUR/m2) et
# des observatoires (1 739 a 1 817 EUR/m2 en Nouvelle-Aquitaine). Il fixe
# le PARTAGE terrain / bati ; le niveau d'ensemble, lui, est cale sur les
# ventes par le coefficient de marche.
COUT_CONSTRUCTION_M2 = 1700.0
VETUSTE_PAR_AN = 0.012        # l'usage des tables d'expert
VETUSTE_MAX = 0.60
# Age median des maisons vendues, 21 ans (833 maisons du Born reliees a leur
# DPE) : vetuste mediane 25 %, moyenne 32 %. On retient 30 % quand l'annee de
# construction est inconnue.
VETUSTE_TYPIQUE = 0.30
# Doubler la surface d'un terrain ne multiplie son prix que par 1,30
# (elasticite 0,38, 7 256 terrains a batir des Landes). Re-mesuree par
# departement quand il y a assez de ventes.
ELASTICITE_TERRAIN = 0.38

# Le coefficient d'entretien du Code general des impots. On le recentre sur
# « assez bon », l'etat typique d'un bien vendu : l'estimation represente
# un bien moyen de son secteur, donc un bien en etat d'usage courant.
ETATS = {
    "bon":       (1.20, "Bon — aucune réparation à prévoir"),
    "assez_bon": (1.10, "Assez bon — petites réparations (état d'usage courant)"),
    "passable":  (1.00, "Passable — défauts d'usure, sans nuire à l'habitabilité"),
    "mediocre":  (0.90, "Médiocre — réparations importantes mais localisées"),
    "mauvais":   (0.80, "Mauvais — grosses réparations dans toutes les parties"),
}
ETAT_DE_REFERENCE = "assez_bon"

LIBELLES_METHODES = {
    "comparables": "Ventes comparables",
    "hedonique": "Régression hédonique",
    "sol_construction": "Sol + construction",
    "boosting": "Gradient boosting",           # phase 2 : voir metier/boosting.py
}

ZONES_INDICE = {
    "PR": "province", "FM": "France métropolitaine", "FR-D976": "France hors Mayotte",
    "R11": "Île-de-France", "R32": "Hauts-de-France", "R84": "Auvergne-Rhône-Alpes",
    "R93": "Provence-Alpes-Côte d'Azur", "D75": "Paris", "D77": "Seine-et-Marne",
    "D78": "Yvelines", "D91": "Essonne", "D92": "Hauts-de-Seine",
    "D93": "Seine-Saint-Denis", "D94": "Val-de-Marne", "D95": "Val-d'Oise",
}


class PasPret(Exception):
    """Le departement n'a pas encore ses ventes de reference ou son modele."""


# =====================================================================
#  Outils de calcul
# =====================================================================
def _codes(valeurs):
    uniques, inverse = np.unique(np.asarray(valeurs).astype(str), return_inverse=True)
    return uniques, inverse


def _absorber(matrice, groupes):
    """Retire a chaque colonne sa moyenne par groupe (effet fixe absorbe).

    Une colonne par commune coutait des gigaoctets sur un departement ; ici,
    quelques colonnes suffisent, et le resultat est le meme (Frisch-Waugh)."""
    effectifs = np.bincount(groupes).astype(float)
    effectifs[effectifs == 0] = 1.0
    sortie = np.empty_like(matrice)
    for j in range(matrice.shape[1]):
        moyennes = np.bincount(groupes, weights=matrice[:, j]) / effectifs
        sortie[:, j] = matrice[:, j] - moyennes[groupes]
    return sortie


def _mediane_ponderee(valeurs, poids):
    ordre = np.argsort(valeurs)
    cumul = np.cumsum(poids[ordre])
    return float(valeurs[ordre][np.searchsorted(cumul, cumul[-1] / 2.0)])


def _geo(valeurs):
    valeurs = [v for v in valeurs if v and v > 0 and math.isfinite(v)]
    return math.exp(sum(math.log(v) for v in valeurs) / len(valeurs)) if valeurs else None


def _variables(v, sel, avec_terrain):
    colonnes = [np.log(v["surface"][sel]), v["pieces"][sel], v["dependances"][sel], v["vefa"][sel]]
    noms = ["log_surface", "pieces", "dependances", "vefa"]
    if avec_terrain:
        colonnes.insert(1, np.log1p(np.maximum(v["terrain_m2"][sel], 0)))
        noms.insert(1, "log_terrain")
    return np.column_stack(colonnes), noms


_CARACTERISTIQUES = ("surface", "terrain_m2", "pieces", "dependances", "vefa", "latitude", "longitude")


def _vecteur(bien, noms):
    table = {"log_surface": math.log(max(bien["surface"], 1.0)),
             "log_terrain": math.log1p(max(bien.get("terrain_m2") or 0.0, 0.0)),
             "pieces": float(bien.get("pieces") or 0), "dependances": float(bien.get("dependances") or 0),
             "vefa": 1.0 if bien.get("neuf") else 0.0}
    return np.array([table[n] for n in noms])


# =====================================================================
#  Indice local, tire de DVF
# =====================================================================
def indice(v, sel):
    """
    L'evolution des prix a qualite et lieu constants, trimestre par trimestre.

    Regression du log du prix sur les caracteristiques du bien et le
    trimestre, commune absorbee. Mesure sur la Nouvelle-Aquitaine, cet
    indice suit l'indice Notaires-Insee des maisons de province a un ou
    deux points pres sur cinq ans — mais s'en ecarte localement : les Landes
    ont monte jusqu'a 122,4 quand la province plafonnait a 115,7. C'est
    pourquoi il est calcule par departement.

    Le NIVEAU DE REFERENCE est la moyenne des deux derniers trimestres : un
    seul trimestre, dans un petit departement, bouge de plusieurs points
    d'une fois a l'autre, et tout le calcul s'y ramene.
    """
    trimestres = sorted(set(v["trimestre"][sel].tolist()))
    if sel.sum() < MIN_VENTES or len(trimestres) < 3:
        return {"trimestres": trimestres, "effets": [0.0] * len(trimestres), "reference": 0.0}
    rang = {q: i for i, q in enumerate(trimestres)}
    idx_q = np.array([rang[q] for q in v["trimestre"][sel]])
    muettes = np.zeros((int(sel.sum()), len(trimestres) - 1))
    lignes = np.where(idx_q > 0)[0]
    muettes[lignes, idx_q[lignes] - 1] = 1.0
    x, _ = _variables(v, sel, avec_terrain=True)
    matrice = np.column_stack([np.log(v["prix"][sel]), x, muettes])
    _, communes = _codes(v["code_insee"][sel])
    absorbee = _absorber(matrice, communes)
    beta, *_ = np.linalg.lstsq(absorbee[:, 1:], absorbee[:, 0], rcond=None)
    effets = [0.0] + beta[x.shape[1]:].tolist()
    return {"trimestres": trimestres, "effets": effets,
            "reference": float(np.mean(effets[-2:]))}


def _decalage(ind, trimestres):
    """Ce qu'il faut ajouter au log du prix pour le ramener au niveau de reference."""
    table = dict(zip(ind["trimestres"], ind["effets"]))
    return np.array([ind["reference"] - table.get(q, ind["reference"]) for q in trimestres])


# =====================================================================
#  Le moteur : les memes calculs pour estimer et pour s'auto-evaluer
# =====================================================================
class Moteur:
    """
    Tout ce qu'il faut pour estimer, a partir de ventes de reference.

    Construit sur TOUTES les ventes, il estime les biens. Construit sur les
    ventes d'avant la derniere annee, il mesure sa precision sur celles de
    cette annee-la. C'est le MEME code : la fiabilite affichee est celle du
    calcul qui tourne vraiment.
    """

    def __init__(self, v, t, sel, indices, parametres=None, boosters=None,
                 apprendre_boosting=False):
        self.v, self.t, self.indices = v, t, indices
        self.parametres = parametres or {}
        self.types = {}
        for type_bien in TYPES:
            masque = sel & (v["type"] == type_bien)
            if masque.sum() < MIN_VENTES:
                continue
            log_d = np.log(v["prix"][masque]) + _decalage(indices[type_bien], v["trimestre"][masque])
            entree = {
                "rangs": np.where(masque)[0],
                "log_d": log_d,
                "pm2_d": np.exp(log_d) / v["surface"][masque],
                "voisinage": Voisinage(v["latitude"][masque], v["longitude"][masque]),
            }
            modele = self.parametres.get("hedonique", {}).get(type_bien)
            if modele is None:
                modele = self._apprendre_hedonique(masque, log_d, type_bien == "maison")
            entree["hedonique"] = modele
            self.types[type_bien] = entree

        # Les terrains a batir, ramenes au niveau de reference par l'indice des
        # maisons : il n'y a pas assez de ventes de terrains pour leur propre indice.
        self.terrains = None
        if t.get("n", 0) >= 30 and "maison" in indices:
            log_t = np.log(t["prix"]) + _decalage(indices["maison"], t["trimestre"])
            self.terrains = {"prix_d": np.exp(log_t), "surface": t["terrain_m2"],
                             "voisinage": Voisinage(t["latitude"], t["longitude"])}
        self.pieces = {}
        for type_bien in self.types:
            rangs = self.types[type_bien]["rangs"]
            rangs = rangs[v["pieces"][rangs] > 0]
            if len(rangs) >= 30:
                a = np.column_stack([np.ones(len(rangs)), np.log(v["surface"][rangs])])
                self.pieces[type_bien] = np.linalg.lstsq(a, v["pieces"][rangs], rcond=None)[0].tolist()
        self.elasticite = self.parametres.get("elasticite_terrain")
        if self.elasticite is None:
            self.elasticite = self._mesurer_elasticite()
        self.coefficient_marche = self.parametres.get("coefficient_marche")
        if self.coefficient_marche is None and "maison" in self.types:
            self.coefficient_marche = self._mesurer_coefficient_marche()
        # Le boosting s'apprend a l'entrainement (quelques secondes par type),
        # et se relit ensuite de la base : jamais au moment d'estimer.
        self.boosters = {tb: m for tb, m in (boosters or {}).items() if tb in self.types}
        if apprendre_boosting and boosting.disponible():
            for type_bien in self.types:
                self.boosters[type_bien] = self._apprendre_boosting(type_bien)

    # --- apprentissage ------------------------------------------------
    def _apprendre_hedonique(self, masque, log_d, avec_terrain):
        """
        log(prix) = effet de la commune + b . caracteristiques.

        L'effet d'une commune qui a peu de ventes est TIRE vers la moyenne du
        departement, au poids n / (n + 10) : trois ventes a Uza ne font pas
        un prix de marche, et c'est ce qui rend la methode utilisable dans le
        rural, ou les communes sont nombreuses et minces.
        """
        x, noms = _variables(self.v, masque, avec_terrain)
        uniques, communes = _codes(self.v["code_insee"][masque])
        absorbee = _absorber(np.column_stack([log_d, x]), communes)
        beta, *_ = np.linalg.lstsq(absorbee[:, 1:], absorbee[:, 0], rcond=None)
        residus = log_d - x @ beta
        effectifs = np.bincount(communes).astype(float)
        moyennes = np.bincount(communes, weights=residus) / effectifs
        general = float(residus.mean())
        effets = (effectifs * moyennes + RETRAIT_COMMUNE * general) / (effectifs + RETRAIT_COMMUNE)
        variance = float(np.var(residus - effets[communes]))
        return {"variables": noms, "beta": beta.tolist(), "general": general,
                "variance": variance,
                "effets": {c: float(e) for c, e in zip(uniques.tolist(), effets.tolist())}}

    def _mesurer_elasticite(self):
        t = self.t
        if self.terrains is None or t["n"] < 200:
            return ELASTICITE_TERRAIN
        _, communes = _codes(t["code_insee"])
        m = _absorber(np.column_stack([np.log(self.terrains["prix_d"]), np.log(t["terrain_m2"])]), communes)
        denominateur = float((m[:, 1] ** 2).sum())
        if denominateur <= 0:
            return ELASTICITE_TERRAIN
        return float(min(max((m[:, 0] * m[:, 1]).sum() / denominateur, 0.15), 0.8))

    def _mesurer_coefficient_marche(self):
        """Ce qui relie la valeur technique (terrain + bati) au prix de marche.

        Il ne se devine pas : on le mesure, en mediane, sur des maisons vendues
        du departement — a vetuste typique, puisque DVF ne dit pas leur age."""
        if self.terrains is None:
            return None
        e = self.types["maison"]
        rangs = e["rangs"][self.v["terrain_m2"][e["rangs"]] > 0]
        if len(rangs) < 50:
            return None
        graine = np.random.default_rng(7)
        if len(rangs) > 3000:
            rangs = graine.choice(rangs, 3000, replace=False)
        rapports = []
        position = {r: i for i, r in enumerate(e["rangs"].tolist())}
        for r in rangs.tolist():
            terrain = self.valeur_terrain(self.v["latitude"][r], self.v["longitude"][r],
                                          self.v["terrain_m2"][r])
            if terrain is None:
                continue
            bati = COUT_CONSTRUCTION_M2 * self.v["surface"][r] * (1 - VETUSTE_TYPIQUE)
            rapports.append(math.exp(e["log_d"][position[r]]) / (terrain[0] + bati))
        return float(np.median(rapports)) if len(rapports) >= 50 else None

    def _apprendre_boosting(self, type_bien):
        """Le modele d'un type de bien, appris sur toutes ses ventes de reference.

        Les voisines d'une vente d'apprentissage l'EXCLUENT : on en demande une
        de plus, et on retire la vente elle-meme — ou, si des ventes au meme
        point la masquent, la plus lointaine."""
        v, e = self.v, self.types[type_bien]
        rangs = e["rangs"]
        k = boosting.K_VOISINS
        locaux, distances = e["voisinage"].plus_proches_lot(v["latitude"][rangs],
                                                            v["longitude"][rangs], k + 1)
        garde = locaux != np.arange(len(rangs))[:, None]
        garde[garde.all(axis=1), -1] = False
        locaux = locaux[garde].reshape(len(rangs), k)
        distances = distances[garde].reshape(len(rangs), k)
        pm2 = boosting.prix_voisins(e["pm2_d"][locaux], distances, v["surface"][rangs][locaux],
                                    v["surface"][rangs])
        x = boosting.traits(type_bien, {c: v[c][rangs] for c in _CARACTERISTIQUES}, pm2, distances)
        return boosting.apprendre(x, e["log_d"])

    def pieces_typiques(self, type_bien, surface):
        """Le nombre de pieces le plus courant pour cette surface, quand il n'est pas saisi.

        Le laisser a zero ferait mentir la regression : un appartement de trois
        pieces compte pres de 9 % de plus qu'un « zero piece » de meme surface."""
        coefficients = self.pieces.get(type_bien)
        if not coefficients:
            return max(1, round(surface / 25))
        return int(min(max(round(coefficients[0] + coefficients[1] * math.log(surface)), 1), 15))

    def terrain_typique(self, latitude, longitude, k=K_COMPARABLES):
        """Le terrain median des maisons vendues autour, quand celui du bien n'est pas connu."""
        e = self.types.get("maison")
        if e is None:
            return 0.0
        indices, _ = e["voisinage"].plus_proches(latitude, longitude, k)
        if not len(indices):
            return 0.0
        return float(np.median(self.v["terrain_m2"][e["rangs"][indices]]))

    def parametres_appris(self):
        return {"hedonique": {t: e["hedonique"] for t, e in self.types.items()},
                "elasticite_terrain": self.elasticite,
                "coefficient_marche": self.coefficient_marche}

    # --- les methodes ---------------------------------------------------
    def voisines(self, bien, k=K_COMPARABLES):
        """Les k ventes du meme type les plus proches : (indices locaux, distances)."""
        e = self.types.get(bien["type"])
        if e is None:
            return np.array([], dtype=np.int64), np.array([])
        return e["voisinage"].plus_proches(bien["latitude"], bien["longitude"], k)

    def comparables(self, bien, locaux, distances):
        e = self.types.get(bien["type"])
        if e is None or len(locaux) < 3:
            return None
        surfaces = self.v["surface"][e["rangs"][locaux]]
        poids = 1.0 / (1.0 + distances / 300.0) * np.exp(-np.abs(np.log(surfaces / bien["surface"])))
        return _mediane_ponderee(e["pm2_d"][locaux], poids) * bien["surface"]

    def gradient_boosting(self, bien, locaux, distances):
        modele = self.boosters.get(bien["type"])
        e = self.types.get(bien["type"])
        if modele is None or e is None or len(locaux) < boosting.K_VOISINS:
            return None
        pm2 = boosting.prix_voisins(e["pm2_d"][locaux][None, :], distances[None, :],
                                    self.v["surface"][e["rangs"][locaux]][None, :],
                                    np.array([bien["surface"]]))
        caracteristiques = {
            "surface": bien["surface"], "terrain_m2": bien.get("terrain_m2") or 0.0,
            "pieces": float(bien.get("pieces") or 0), "dependances": float(bien.get("dependances") or 0),
            "vefa": 1.0 if bien.get("neuf") else 0.0,
            "latitude": bien["latitude"], "longitude": bien["longitude"]}
        x = boosting.traits(bien["type"], {c: np.array([float(val)]) for c, val in caracteristiques.items()},
                            pm2, distances[None, :])
        return float(np.exp(boosting.predire(modele, x)[0]))

    def hedonique(self, bien):
        e = self.types.get(bien["type"])
        if e is None:
            return None
        m = e["hedonique"]
        effet = m["effets"].get(str(bien.get("code_insee")), m["general"])
        return math.exp(effet + float(_vecteur(bien, m["variables"]) @ np.array(m["beta"]))
                        + m["variance"] / 2)

    def valeur_terrain(self, latitude, longitude, surface_terrain, k=K_TERRAINS):
        """(valeur du terrain nu, distance mediane des terrains voisins)."""
        if self.terrains is None or not surface_terrain or surface_terrain <= 0:
            return None
        indices, distances = self.terrains["voisinage"].plus_proches(latitude, longitude, k)
        if len(indices) < 3:
            return None
        cible = max(float(surface_terrain), 100.0)
        valeurs = self.terrains["prix_d"][indices] * (cible / self.terrains["surface"][indices]) ** self.elasticite
        return float(np.median(valeurs)), float(np.median(distances))

    def sol_construction(self, bien):
        """(valeur, detail) — seulement pour une maison avec terrain."""
        if bien["type"] != "maison" or not self.coefficient_marche:
            return None, None
        terrain = self.valeur_terrain(bien["latitude"], bien["longitude"], bien.get("terrain_m2"))
        if terrain is None:
            return None, None
        annee = bien.get("annee_construction")
        if annee:
            age = max(0, datetime.date.today().year - int(annee))
            vetuste, source = min(age * VETUSTE_PAR_AN, VETUSTE_MAX), "annee"
        else:
            vetuste, source = VETUSTE_TYPIQUE, "typique"
        bati = COUT_CONSTRUCTION_M2 * bien["surface"] * (1 - vetuste)
        valeur = self.coefficient_marche * (terrain[0] + bati)
        return valeur, {"terrain": self.coefficient_marche * terrain[0],
                        "bati": self.coefficient_marche * bati,
                        "vetuste": vetuste, "vetuste_source": source,
                        "cout_m2": COUT_CONSTRUCTION_M2,
                        "coefficient_marche": self.coefficient_marche,
                        "distance_terrains_m": terrain[1]}

    def estimer_brut(self, bien):
        """Les methodes disponibles pour ce bien, et leur croisement.

        Rend aussi les ventes comparables (rangs dans les ventes de reference)
        et leurs distances, pour les montrer."""
        valeurs = {}
        locaux, distances = self.voisines(bien)
        comp = self.comparables(bien, locaux, distances)
        if comp:
            valeurs["comparables"] = comp
        hed = self.hedonique(bien)
        if hed:
            valeurs["hedonique"] = hed
        sc, detail = self.sol_construction(bien)
        if sc:
            valeurs["sol_construction"] = sc
        gb = self.gradient_boosting(bien, locaux, distances)
        if gb:
            valeurs["boosting"] = gb
        e = self.types.get(bien["type"])
        rangs = e["rangs"][locaux] if e is not None and len(locaux) >= 3 else []
        if not len(rangs):
            distances = []
        return valeurs, _geo(list(valeurs.values())), rangs, distances, detail


# =====================================================================
#  Apprentissage d'un departement
# =====================================================================
MEME_SURFACE = 0.03           # deux ventes d'une parcelle a 3 % de surface pres : le meme bien
MIN_REVENTES = 50            # en dessous, la mediane des plus-values est trop instable
# Le poids de l'ancien prix face au croisement des methodes, quand le bien a
# deja ete vendu. Mesure sur trois departements (Landes, Gironde, Creuse) :
# une maison revendue vaut en moyenne 9 a 12 % de plus que la maison type
# de son secteur — travaux, ou bien au-dessus du lot des l'origine — et le
# croisement, qui estime la maison type, la sous-evalue. Donner les deux
# tiers du poids a l'ancien prix ramene l'erreur mediane de 11,8 a 11,2 %
# dans les Landes, de 12,6 a 12,1 % en Gironde, de 19,8 a 16,3 % en Creuse.
# Pour un appartement, moitie-moitie reste le meilleur choix.
POIDS_HISTORIQUE = {"maison": 2 / 3, "appartement": 0.5}


def _ventes_par_bien(v, rangs):
    """{(parcelle, type): [rangs...]} — pour retrouver les ventes d'un meme bien."""
    table = {}
    for i in rangs.tolist():
        if v["parcelle_id"][i]:
            table.setdefault((v["parcelle_id"][i], v["type"][i]), []).append(i)
    return table


def _vente_anterieure(v, candidats, surface):
    """La plus recente des `candidats` qui soit le meme bien (meme surface a 3 % pres)."""
    retenus = [i for i in candidats if abs(math.log(v["surface"][i] / surface)) < MEME_SURFACE]
    return max(retenus, key=lambda r: v["date_vente"][r]) if retenus else None


def _plus_value_des_reventes(v, indices, sel=None):
    """
    Ce que les biens revendus gagnent en moyenne AU-DELA du marche.

    Mesure sur les Landes : +7,6 % en mediane, la signature des travaux faits
    entre deux ventes. On le re-mesure ici, departement par departement, et
    on ne l'applique que s'il repose sur assez de reventes.
    """
    resultat = {}
    for type_bien in TYPES:
        masque = v["type"] == type_bien
        if sel is not None:
            masque &= sel
        rangs = np.where(masque)[0]
        if type_bien not in indices or len(rangs) < MIN_VENTES:
            continue
        ecarts = []
        for ventes in _ventes_par_bien(v, rangs).values():
            if len(ventes) < 2:
                continue
            ventes.sort(key=lambda r: v["date_vente"][r])
            for i1, i2 in zip(ventes, ventes[1:]):
                if v["vefa"][i1] or abs(math.log(v["surface"][i2] / v["surface"][i1])) >= MEME_SURFACE:
                    continue
                d1 = datetime.date.fromisoformat(v["date_vente"][i1])
                d2 = datetime.date.fromisoformat(v["date_vente"][i2])
                if (d2 - d1).days < 180:
                    continue
                c1, c2 = _decalage(indices[type_bien], [v["trimestre"][i1], v["trimestre"][i2]])
                ecarts.append((math.log(v["prix"][i2]) + c2) - (math.log(v["prix"][i1]) + c1))
        if len(ecarts) >= MIN_REVENTES:
            resultat[type_bien] = {"plus_value": float(min(max(math.exp(np.median(ecarts)) - 1, 0.0), 0.15)),
                                   "reventes": len(ecarts)}
    return resultat


def _avec_historique(croise, historique, type_bien):
    """Le croisement des methodes et l'ancien prix du bien, en moyenne geometrique ponderee."""
    poids = POIDS_HISTORIQUE[type_bien]
    return croise ** (1 - poids) * historique ** poids


def _valeur_historique(v, i, indice_type, plus_value):
    """Le prix de la vente `i`, ramene au niveau de reference, plus-value des reventes comprise."""
    decal = float(_decalage(indice_type, [v["trimestre"][i]])[0])
    return float(v["prix"][i] * math.exp(decal) * (1 + plus_value))


def _mesurer(reels, estimes):
    reels, estimes = np.asarray(reels, float), np.asarray(estimes, float)
    ok = np.isfinite(estimes) & (estimes > 0)
    if ok.sum() < 20:
        return None
    ecart = estimes[ok] / reels[ok] - 1
    rapport = reels[ok] / estimes[ok] - 1
    return {"n": int(ok.sum()), "erreur_mediane": float(np.median(np.abs(ecart)) * 100),
            "a10": float((np.abs(ecart) <= 0.10).mean() * 100),
            "a20": float((np.abs(ecart) <= 0.20).mean() * 100),
            "biais": float(np.median(ecart) * 100),
            "bas": float(np.quantile(rapport, 0.10)), "haut": float(np.quantile(rapport, 0.90))}


def _bien_de_la_vente(v, i):
    """Une vente de reference, decrite comme un bien a estimer."""
    return {"type": v["type"][i], "surface": v["surface"][i], "pieces": v["pieces"][i],
            "terrain_m2": v["terrain_m2"][i], "dependances": v["dependances"][i],
            "neuf": bool(v["vefa"][i]), "latitude": v["latitude"][i],
            "longitude": v["longitude"][i], "code_insee": v["code_insee"][i]}


def _auto_evaluation(v, t, indices):
    """
    Refait tout le calcul sur les ventes d'avant la derniere annee, et le
    confronte aux prix de cette derniere annee.

    Les prix de l'annee testee sont ramenes au niveau de reference par
    l'indice : on mesure ainsi la precision de la METHODE, la derive du
    marche etant traitee a part (par l'indice, puis la projection Insee).

    Deux mesures par type de bien : sur un echantillon de toutes les ventes
    de l'annee, et sur celles d'un bien DEJA VENDU auparavant — ou l'ancien
    prix entre dans le calcul, et qui s'estiment nettement mieux. Chaque
    estimation affiche la precision du cas ou elle se trouve.
    """
    dates = v["date_vente"].astype(str)
    fin = datetime.date.fromisoformat(max(dates))
    coupure = (fin - datetime.timedelta(days=365)).isoformat()
    avant = dates < coupure
    moteur = Moteur(v, t, avant, indices, apprendre_boosting=True)
    reventes = _plus_value_des_reventes(v, indices, avant)
    anterieures = _ventes_par_bien(v, np.where(avant)[0])
    graine = np.random.default_rng(11)
    mesures = {}
    for type_bien in TYPES:
        if type_bien not in moteur.types:
            continue
        tous = np.where(~avant & (v["type"] == type_bien))[0]
        if len(tous) < 30:
            continue
        test = tous
        if len(test) > ECHANTILLON_TEST:
            test = graine.choice(test, ECHANTILLON_TEST, replace=False)
        reels = np.exp(np.log(v["prix"][test]) + _decalage(indices[type_bien], v["trimestre"][test]))
        par_methode = {m: [] for m in LIBELLES_METHODES}
        croisements = []
        for i in test.tolist():
            valeurs, croise, *_ = moteur.estimer_brut(_bien_de_la_vente(v, i))
            for m in par_methode:
                par_methode[m].append(valeurs.get(m, np.nan))
            croisements.append(croise if croise else np.nan)
        mesure = _mesurer(reels, croisements)
        if mesure is None:
            continue
        mesure["methodes"] = {m: _mesurer(reels, vals) for m, vals in par_methode.items()
                              if _mesurer(reels, vals)}
        mesure["periode"] = [coupure, fin.isoformat()]

        # Les biens deja vendus avant la coupure : l'historique entre en jeu.
        plus_value = reventes.get(type_bien, {}).get("plus_value", 0.0)
        reels_h, estimes_h = [], []
        for i in graine.permutation(tous).tolist():
            if len(reels_h) >= ECHANTILLON_TEST:
                break
            precedente = _vente_anterieure(
                v, anterieures.get((v["parcelle_id"][i], type_bien), ()), v["surface"][i])
            if precedente is None:
                continue
            _, croise, *_ = moteur.estimer_brut(_bien_de_la_vente(v, i))
            if not croise:
                continue
            historique = _valeur_historique(v, precedente, indices[type_bien], plus_value)
            reels_h.append(float(np.exp(np.log(v["prix"][i])
                                        + _decalage(indices[type_bien], [v["trimestre"][i]])[0])))
            estimes_h.append(_avec_historique(croise, historique, type_bien))
        avec_historique = _mesurer(reels_h, estimes_h)
        if avec_historique:
            mesure["avec_historique"] = avec_historique
        mesures[type_bien] = mesure
    return mesures


def entrainer(departement, progression=None):
    """Apprend le modele d'un departement a partir de ses ventes de reference."""
    departement = str(departement)
    if progression:
        progression(f"Apprentissage sur les ventes du département {departement}")
    v = references.charger_ventes(departement)
    t = references.charger_terrains(departement)
    if v.get("n", 0) < MIN_VENTES:
        raise ErreurSource(f"Trop peu de ventes dans le département {departement} pour estimer.")
    tout = np.ones(v["n"], dtype=bool)
    indices = {tb: indice(v, v["type"] == tb) for tb in TYPES if (v["type"] == tb).sum() >= MIN_VENTES}
    if progression:
        progression("Mesure de la précision sur la dernière année")
    mesures = _auto_evaluation(v, t, indices)
    if progression:
        progression("Apprentissage du modèle final")
    moteur = Moteur(v, t, tout, indices, apprendre_boosting=True)
    boosters = {tb: boosting.vers_octets(m) for tb, m in moteur.boosters.items() if m is not None}
    modele = {
        "departement": departement,
        "indices": indices,
        "parametres": moteur.parametres_appris(),
        "reventes": _plus_value_des_reventes(v, indices),
        "precision": mesures,
        "ventes": {tb: int((v["type"] == tb).sum()) for tb in TYPES},
        "terrains": int(t.get("n", 0)),
        "periode": [str(min(v["date_vente"])), str(max(v["date_vente"]))],
        "cout_construction_m2": COUT_CONSTRUCTION_M2,
        "boosting": sorted(boosters),
        "version": VERSION_MODELE,
    }
    maintenant = datetime.datetime.now().isoformat(timespec="seconds")
    with transaction() as conn:
        conn.execute("INSERT INTO modele_estimation (departement, entraine_le, modele_json)"
                     " VALUES (?,?,?) ON CONFLICT(departement) DO UPDATE SET"
                     " entraine_le = excluded.entraine_le, modele_json = excluded.modele_json",
                     (departement, maintenant, json.dumps(modele)))
        conn.execute("DELETE FROM modele_boosting WHERE departement = ?", (departement,))
        conn.executemany("INSERT INTO modele_boosting (departement, type, modele) VALUES (?,?,?)",
                         [(departement, tb, octets) for tb, octets in boosters.items()])
    with _verrou_cache:
        _cache.pop(departement, None)
    logger.info("modele %s appris : %s", departement,
                {tb: round(m["erreur_mediane"], 1) for tb, m in mesures.items()})
    return modele


def modele(departement):
    with connexion() as conn:
        ligne = conn.execute("SELECT entraine_le, modele_json FROM modele_estimation"
                             " WHERE departement = ?", (str(departement),)).fetchone()
    if ligne is None:
        return None
    m = json.loads(ligne["modele_json"])
    m["entraine_le"] = ligne["entraine_le"]
    return m


# Le moteur d'un departement est reconstruit depuis la base au premier
# usage, puis garde en memoire tant que le modele ne change pas : cent mille
# ventes a relire a chaque estimation seraient une seconde perdue a chaque fois.
_cache = {}
_verrou_cache = threading.Lock()


def _boosters(departement):
    """Les modeles de boosting appris pour ce departement, prets a predire."""
    with connexion() as conn:
        lignes = conn.execute("SELECT type, modele FROM modele_boosting WHERE departement = ?",
                              (str(departement),)).fetchall()
    boosters = {}
    for ligne in lignes:
        try:
            modele_type = boosting.depuis_octets(ligne["modele"])
        except Exception as erreur:                  # noqa: BLE001
            logger.warning("boosting %s/%s illisible : %s", departement, ligne["type"], erreur)
            continue
        if modele_type is not None:
            boosters[ligne["type"]] = modele_type
    return boosters


def _moteur(departement):
    m = modele(departement)
    if m is None:
        raise PasPret(departement)
    with _verrou_cache:
        connu = _cache.get(departement)
        if connu and connu[0] == m["entraine_le"]:
            return m, connu[1]
    v = references.charger_ventes(departement)
    t = references.charger_terrains(departement)
    if v.get("n", 0) == 0:
        raise PasPret(departement)
    moteur = Moteur(v, t, np.ones(v["n"], dtype=bool), m["indices"], m["parametres"],
                    boosters=_boosters(departement))
    with _verrou_cache:
        _cache[departement] = (m["entraine_le"], moteur)
    return m, moteur


# =====================================================================
#  Preparation en tache de fond
# =====================================================================
_verrou = threading.Lock()
_etat = {"en_cours": False, "departement": None, "etape": "", "erreur": None, "fini_le": None}


def etat_preparation():
    with _verrou:
        return dict(_etat)


def _publier(**champs):
    with _verrou:
        _etat.update(champs)


def preparer(departement, forcer=False):
    """Importe les ventes si besoin, puis apprend. Synchrone."""
    departement = str(departement)
    progression = lambda message: _publier(etape=message)
    if forcer or references.etat(departement) is None or references.a_rafraichir(departement):
        references.importer(departement, progression=progression)
        entrainer(departement, progression=progression)
    elif a_reapprendre(departement):
        entrainer(departement, progression=progression)
    rapprocher(departement)
    # L'indice et les loyers servent a toutes les estimations : on les lit
    # ici, pendant qu'on attend deja, plutot qu'au moment d'estimer.
    progression("Indice Notaires-Insee et carte des loyers")
    for rafraichir in (rafraichir_indice_officiel, rafraichir_loyers):
        try:
            rafraichir()
        except Exception as erreur:                  # noqa: BLE001
            logger.warning("source annexe de l'estimation indisponible : %s", erreur)
    return modele(departement)


def a_reapprendre(departement):
    """Pas de modele, ou un modele d'une version anterieure — sans boosting,
    alors qu'il est disponible."""
    m = modele(departement)
    if m is None or m.get("version", 1) < VERSION_MODELE:
        return True
    return boosting.disponible() and not m.get("boosting")


def lancer_preparation(departement, forcer=False):
    with _verrou:
        if _etat["en_cours"]:
            raise RuntimeError("Une preparation est deja en cours.")
        _etat.update(en_cours=True, departement=str(departement), etape="Démarrage",
                     erreur=None, fini_le=None)

    def travail():
        try:
            preparer(departement, forcer=forcer)
            _publier(etape="Prêt")
        except Exception as erreur:                  # noqa: BLE001
            logger.exception("preparation de l'estimation %s en echec", departement)
            _publier(erreur=str(erreur))
        finally:
            _publier(en_cours=False, fini_le=datetime.datetime.now().isoformat(timespec="seconds"))

    fil = threading.Thread(target=travail, name="estimation", daemon=True)
    fil.start()
    return fil


# =====================================================================
#  Sources annexes : indice Notaires-Insee, loyers
# =====================================================================
# Apres un echec, on ne retente pas avant quelques heures : sans Internet,
# chaque estimation attendrait sinon la fin du delai de connexion.
RETENTE_APRES_ECHEC_JOURS = 0.25


def _age_source(source):
    """Age en jours (fractionnaires) de la derniere lecture reussie, ou None."""
    with connexion() as conn:
        ligne = conn.execute("SELECT maj_le FROM source_maj WHERE source = ?", (source,)).fetchone()
    if ligne is None:
        return None
    ecart = datetime.datetime.now() - datetime.datetime.fromisoformat(ligne["maj_le"])
    return ecart.total_seconds() / 86400


def _noter_source(conn, source, detail):
    conn.execute("INSERT INTO source_maj (source, maj_le, detail) VALUES (?,?,?)"
                 " ON CONFLICT(source) DO UPDATE SET maj_le = excluded.maj_le, detail = excluded.detail",
                 (source, datetime.datetime.now().isoformat(timespec="seconds"), detail))


def _echec_recent(source):
    age = _age_source(source + "_echec")
    return age is not None and age < RETENTE_APRES_ECHEC_JOURS


def _noter_echec(source, erreur):
    logger.warning("%s indisponible : %s", source, erreur)
    with transaction() as conn:
        _noter_source(conn, source + "_echec", str(erreur)[:200])


def rafraichir_indice_officiel(jours=30):
    """L'indice paraît chaque trimestre : on le relit au plus une fois par mois."""
    age = _age_source("insee")
    if (age is not None and age < jours) or _echec_recent("insee"):
        return False
    try:
        observations = insee.telecharger()
    except ErreurSource as erreur:
        _noter_echec("insee", erreur)
        return False
    with transaction() as conn:
        conn.execute("DELETE FROM indice_officiel")
        conn.executemany("INSERT OR REPLACE INTO indice_officiel (zone, type, trimestre, indice)"
                         " VALUES (?,?,?,?)", observations)
        _noter_source(conn, "insee", f"{len(observations)} observations")
    return True


def rafraichir_loyers(jours=180):
    """Une carte par an : on la relit au plus deux fois l'an."""
    age = _age_source("loyers")
    if (age is not None and age < jours) or _echec_recent("loyers"):
        return False
    try:
        lignes = loyers.telecharger()
    except ErreurSource as erreur:
        _noter_echec("loyers", erreur)
        return False
    with transaction() as conn:
        conn.execute("DELETE FROM loyer_commune")
        conn.executemany("INSERT OR REPLACE INTO loyer_commune (code_insee, type, loyer_m2, bas_m2,"
                         " haut_m2, millesime) VALUES (?,?,?,?,?,?)", lignes)
        _noter_source(conn, "loyers", f"millesime {lignes[0][5]}, {len(lignes)} lignes")
    return True


def projection(departement, type_bien, trimestres_reference):
    """
    Combien le marche a bouge depuis la fin des donnees DVF, d'apres l'indice
    Notaires-Insee de la zone officielle la plus proche.

    Le point de depart est celui du calcul : la moyenne des deux derniers
    trimestres DVF, niveau auquel toutes les ventes ont ete ramenees.

    Mesure sur la Nouvelle-Aquitaine : pendant la hausse de 2022, cette
    correction ramene le biais des maisons de -4,7 % a -3,0 %. L'erreur
    typique, elle, ne bouge presque pas — c'est une mise a jour du niveau,
    pas un gain de precision.
    """
    trimestres_reference = list(trimestres_reference or [])
    if not trimestres_reference:
        return None
    with connexion() as conn:
        for zone in insee.zones_candidates(departement):
            serie = conn.execute("SELECT trimestre, indice FROM indice_officiel WHERE zone = ?"
                                 " AND type = ? ORDER BY trimestre", (zone, type_bien)).fetchall()
            table = {l["trimestre"]: l["indice"] for l in serie}
            if not all(q in table for q in trimestres_reference):
                continue
            depart = sum(table[q] for q in trimestres_reference) / len(trimestres_reference)
            dernier_officiel = serie[-1]["trimestre"]
            return {"zone": zone, "zone_libelle": ZONES_INDICE.get(zone, zone),
                    "depuis": trimestres_reference[-1], "jusqu_a": dernier_officiel,
                    "facteur": table[dernier_officiel] / depart}
    return None


def loyer(code_insee, type_bien):
    with connexion() as conn:
        ligne = conn.execute("SELECT loyer_m2, bas_m2, haut_m2, millesime FROM loyer_commune"
                             " WHERE code_insee = ? AND type = ?", (str(code_insee), type_bien)).fetchone()
    return dict(ligne) if ligne else None


# =====================================================================
#  Estimer un bien
# =====================================================================
def _niveau_fiabilite(precision, distances, type_bien, deja_vendu=False):
    raisons = []
    if not precision:
        return {"niveau": "faible", "raisons": ["Précision non mesurable : trop peu de ventes récentes."]}
    erreur = precision["erreur_mediane"]
    niveau = 0 if erreur <= 12 else 1 if erreur <= 20 else 2
    cas = ("déjà vendue" if type_bien == "maison" else "déjà vendu") if deja_vendu else ""
    raisons.append(f"Dans ce département, pour un{'e maison' if type_bien == 'maison' else ' appartement'}"
                   f"{' ' + cas if cas else ''}, l'erreur médiane mesurée sur la dernière année "
                   f"est de {erreur:.0f} %.")
    seuil = 3000 if type_bien == "maison" else 1500
    if len(distances) and float(np.median(distances)) > seuil:
        niveau = min(niveau + 1, 2)
        raisons.append(f"Les ventes comparables sont éloignées (distance médiane "
                       f"{float(np.median(distances)) / 1000:.1f} km) : le secteur est peu vendu.")
    return {"niveau": ("bonne", "moyenne", "faible")[niveau], "raisons": raisons}


def _historique(moteur, m, bien):
    """La vente precedente du MEME bien, ramenee au niveau actuel du marche."""
    parcelle = bien.get("parcelle_id")
    if not parcelle:
        return None
    v = moteur.v
    candidats = np.where((v["parcelle_id"] == parcelle) & (v["type"] == bien["type"]))[0]
    i = _vente_anterieure(v, candidats.tolist(), bien["surface"])
    if i is None:
        return None
    indice_type = m["indices"][bien["type"]]
    plus_value = m.get("reventes", {}).get(bien["type"], {}).get("plus_value", 0.0)
    return {"date": v["date_vente"][i], "prix": float(v["prix"][i]),
            "surface": float(v["surface"][i]),
            "reindexe": _valeur_historique(v, i, indice_type, 0.0),
            "plus_value": plus_value,
            "valeur": _valeur_historique(v, i, indice_type, plus_value)}


def _surface(valeur):
    try:
        return float(valeur or 0)
    except (TypeError, ValueError):
        return 0.0


def estimer(bien, saisie=None):
    """
    Estime un bien. `bien` : type, surface, latitude, longitude, code_insee,
    et si connus pieces, terrain_m2, dependances, neuf, annee_construction,
    parcelle_id. `saisie` : etat OU travaux, ajustement (en %) et sa raison.

    Leve ValueError quand la demande ne peut pas aboutir (le message dit
    pourquoi), PasPret quand le departement n'est pas encore prepare.
    """
    saisie = dict(saisie or {})
    type_bien = bien.get("type")
    if type_bien not in TYPES:
        raise ValueError("Type de bien attendu : maison ou appartement.")
    surface = _surface(bien.get("surface"))
    if surface < 9:
        raise ValueError("Surface habitable manquante ou trop petite (9 m² au moins).")
    if surface > 2000:
        raise ValueError("Surface habitable invraisemblable pour un logement.")
    if bien.get("latitude") is None or bien.get("longitude") is None:
        raise ValueError("Position du bien inconnue : impossible de trouver des ventes comparables.")
    code_insee = str(bien.get("code_insee") or "").strip()
    if not code_insee:
        raise ValueError("Commune du bien inconnue.")
    raison = references.dvf.indisponible(code_insee)
    if raison:
        raise ValueError(raison + " Aucune estimation n'est donc possible ici.")
    terrain_saisi = bien.get("terrain_m2")
    bien = {**bien, "code_insee": code_insee, "surface": surface,
            "terrain_m2": _surface(bien.get("terrain_m2")) if type_bien == "maison" else 0.0,
            "latitude": float(bien["latitude"]), "longitude": float(bien["longitude"]),
            "dependances": int(bien.get("dependances") or 0), "neuf": bool(bien.get("neuf"))}
    departement = references.departement_de(code_insee)

    m, moteur = _moteur(departement)
    if type_bien not in moteur.types:
        raise ValueError(f"Trop peu de ventes de ce type dans le département {departement} pour estimer.")
    pieces_estimees = not bien.get("pieces")
    if pieces_estimees:
        bien["pieces"] = moteur.pieces_typiques(type_bien, surface)
    # Un terrain VIDE n'est pas un terrain nul : laisse a zero, il ferait
    # estimer une maison sans jardin, un quart moins chere.
    terrain_estime = type_bien == "maison" and terrain_saisi in (None, "")
    if terrain_estime:
        bien["terrain_m2"] = moteur.terrain_typique(bien["latitude"], bien["longitude"])

    valeurs, croise, rangs, distances, detail_sc = moteur.estimer_brut(bien)
    if not croise:
        raise ValueError("Aucune méthode n'a pu estimer ce bien.")
    precision_type = m["precision"].get(type_bien) or {}
    methodes = [{"cle": k, "libelle": LIBELLES_METHODES[k], "valeur": round(val),
                 "erreur_mediane": (precision_type.get("methodes", {}).get(k) or {}).get("erreur_mediane")}
                for k, val in valeurs.items()]

    # L'historique pese autant, ou plus, que tout le reste reuni : c'est le
    # signal le plus precis, et la precision affichee devient alors celle des
    # biens deja vendus.
    historique = _historique(moteur, m, bien)
    if historique:
        historique["poids"] = POIDS_HISTORIQUE[type_bien]
    marche = croise if historique is None else _avec_historique(croise, historique["valeur"], type_bien)
    precision = precision_type or None
    if historique and precision_type.get("avec_historique"):
        precision = precision_type["avec_historique"]

    ind = m["indices"][type_bien]
    rafraichir_indice_officiel()
    proj = projection(departement, type_bien, ind["trimestres"][-2:])
    facteur_marche = proj["facteur"] if proj else 1.0

    ajustements = []
    travaux = max(_surface(saisie.get("travaux")), 0.0)
    etat = saisie.get("etat") or ETAT_DE_REFERENCE
    if etat not in ETATS:
        raise ValueError("État du bâti inconnu.")
    facteur_etat = 1.0 if travaux else ETATS[etat][0] / ETATS[ETAT_DE_REFERENCE][0]
    if facteur_etat != 1.0:
        libelle = f"État : {ETATS[etat][1]}"
        if historique:
            # L'ancien prix contient deja l'etat du bien a cette date : l'etat
            # ne s'applique qu'a la part du calcul qui estime un bien type.
            facteur_etat = facteur_etat ** (1 - historique["poids"])
            libelle += " — effet réduit : l'ancien prix du bien le reflète déjà en partie"
        ajustements.append({"libelle": libelle, "facteur": facteur_etat})
    try:
        perso = float(saisie.get("ajustement") or 0)
    except (TypeError, ValueError):
        raise ValueError("Ajustement personnel : un pourcentage est attendu.") from None
    perso = min(max(perso, -30.0), 30.0)
    if perso:
        ajustements.append({"libelle": f"Ajustement personnel : {saisie.get('raison') or 'sans motif'}",
                            "facteur": 1 + perso / 100})

    centre = marche * facteur_marche * facteur_etat * (1 + perso / 100)
    bas_r, haut_r = (precision["bas"], precision["haut"]) if precision else (-0.4, 0.35)
    if travaux:
        ajustements.append({"libelle": "Travaux à prévoir", "montant": -travaux})
    valeur = max(centre - travaux, 0.0)

    comparables = []
    v = moteur.v
    for r, d in zip(list(rangs), list(distances)):
        comparables.append({"date": v["date_vente"][r], "adresse": v["adresse"][r],
                            "code_insee": v["code_insee"][r], "surface": float(v["surface"][r]),
                            "terrain_m2": float(v["terrain_m2"][r]), "pieces": int(v["pieces"][r]),
                            "prix": float(v["prix"][r]),
                            "prix_actuel": _valeur_historique(v, r, ind, 0.0),
                            "distance_m": float(d)})

    location = loyer(code_insee, type_bien)
    rendement = None
    if location and valeur > 0:
        rendement = {"loyer_m2": location["loyer_m2"], "millesime": location["millesime"],
                     "loyer_annuel": location["loyer_m2"] * 12 * surface,
                     "brut": location["loyer_m2"] * 12 * surface / valeur}

    ne_sait_pas = [
        "L'état intérieur, les finitions, la vue, une piscine : aucune base publique ne les connaît.",
        "Une vente hors marché (viager, vente entre proches) parmi les comparables fausse leur médiane.",
    ]
    if pieces_estimees:
        ne_sait_pas.append("Le nombre de pièces n'a pas été saisi : on a pris le plus courant pour cette surface.")
    if terrain_estime:
        ne_sait_pas.append(f"La surface du terrain n'a pas été saisie : on a pris celle des maisons "
                           f"vendues autour, {bien['terrain_m2']:.0f} m² en médiane.")
    if proj is None:
        ne_sait_pas.append("Le marché depuis la fin des données DVF : aucun indice officiel n'a pu être lu.")

    return {
        "departement": departement,
        "modele_du": m["entraine_le"],
        "donnees": {"periode": m["periode"], "ventes": m["ventes"].get(type_bien)},
        "bien": {**bien, "pieces_estimees": pieces_estimees, "terrain_estime": terrain_estime},
        "saisie": {"etat": None if travaux else etat, "travaux": travaux, "ajustement": perso,
                   "raison": saisie.get("raison") or ""},
        "methodes": methodes,
        "croisement": round(croise),
        "historique": historique,
        "marche": round(marche),
        "projection": proj,
        "ajustements": ajustements,
        "valeur": round(valeur),
        "bas": round(max(centre * (1 + bas_r) - travaux, 0)),
        "haut": round(max(centre * (1 + haut_r) - travaux, 0)),
        "fiabilite": _niveau_fiabilite(precision, distances, type_bien, deja_vendu=bool(historique)),
        "precision": precision,
        "precision_generale": precision_type or None,
        "comparables": comparables,
        "decomposition": detail_sc,
        "rendement": rendement,
        "ne_sait_pas": ne_sait_pas,
    }


def etats():
    """L'echelle d'etat, pour l'ecran."""
    reference = ETATS[ETAT_DE_REFERENCE][0]
    return [{"cle": cle, "libelle": libelle, "coefficient": coef,
             "effet": round((coef / reference - 1) * 100)} for cle, (coef, libelle) in ETATS.items()]


# =====================================================================
#  Ce qu'on sait deja du bien : de quoi pre-remplir le formulaire
# =====================================================================
TYPES_DPE = {"maison": "maison", "appartement": "appartement"}


def bien_depuis(n_dpe=None, parcelle_id=None):
    """
    Ce que la base sait deja d'un bien, a partir de son diagnostic ou de sa
    parcelle : type, surface, terrain, annee, position. L'utilisateur
    corrige ensuite ce qui ne va pas — rien n'est fige.

    Le diagnostic donne la surface habitable et l'annee de construction ;
    la derniere vente du bien (DVF) le nombre de pieces et le terrain
    vendu avec ; la parcelle, a defaut, sa contenance. Leve LookupError si
    ni l'un ni l'autre n'existe.
    """
    bien = {"n_dpe": None, "parcelle_id": None, "type": None, "surface": None, "pieces": None,
            "terrain_m2": None, "dependances": 0, "annee_construction": None,
            "etiquette_dpe": None, "latitude": None, "longitude": None,
            "code_insee": None, "adresse": None, "commune": None, "sources": []}
    with connexion() as conn:
        dpe = None
        if n_dpe:
            dpe = conn.execute(
                "SELECT n_dpe, code_insee, commune, adresse, latitude, longitude, surface_habitable,"
                " type_batiment, annee_construction, etiquette_dpe, parcelle_carte"
                " FROM dpe WHERE n_dpe = ?", (str(n_dpe),)).fetchone()
            if dpe is None:
                raise LookupError(f"Diagnostic {n_dpe} inconnu.")
            parcelle_id = parcelle_id or dpe["parcelle_carte"]
        parcelle = None
        if parcelle_id:
            parcelle = conn.execute(
                "SELECT id, code_insee, contenance_m2, latitude, longitude FROM parcelle WHERE id = ?",
                (str(parcelle_id),)).fetchone()
            if parcelle is None and dpe is None:
                raise LookupError(f"Parcelle {parcelle_id} inconnue.")
            if dpe is None:
                # Le diagnostic le plus recent de la parcelle, s'il y en a un.
                dpe = conn.execute(
                    "SELECT n_dpe, code_insee, commune, adresse, latitude, longitude,"
                    " surface_habitable, type_batiment, annee_construction, etiquette_dpe,"
                    " parcelle_carte FROM dpe WHERE parcelle_carte = ?"
                    " ORDER BY date_etablissement DESC, n_dpe DESC LIMIT 1",
                    (str(parcelle_id),)).fetchone()
        if dpe is None and parcelle is None:
            raise LookupError("Indiquez un diagnostic ou une parcelle.")

        vente = None
        if parcelle_id:
            vente = conn.execute(
                "SELECT type, surface, pieces, terrain_m2, dependances, date_vente, prix, adresse"
                " FROM vente_reference WHERE parcelle_id = ? ORDER BY date_vente DESC LIMIT 1",
                (str(parcelle_id),)).fetchone()
            if vente is None:
                # Le departement n'est pas encore charge : la vente de la
                # fiche, si elle porte sur un seul logement, dit deja l'essentiel.
                brute = conn.execute(
                    "SELECT m.surface_bati_m2, m.surface_terrain_m2, m.types_locaux_json,"
                    " m.date_mutation FROM mutation m"
                    " JOIN mutation_parcelle mp ON mp.mutation_id = m.id"
                    " WHERE mp.parcelle_id = ? AND m.nb_locaux = 1"
                    " ORDER BY m.date_mutation DESC LIMIT 1", (str(parcelle_id),)).fetchone()
                if brute is not None:
                    types = json.loads(brute["types_locaux_json"] or "[]")
                    genre = ("maison" if "Maison" in types
                             else "appartement" if "Appartement" in types else None)
                    if genre and brute["surface_bati_m2"]:
                        vente = {"type": genre, "surface": brute["surface_bati_m2"], "pieces": None,
                                 "terrain_m2": brute["surface_terrain_m2"], "dependances": 0,
                                 "date_vente": brute["date_mutation"], "adresse": None}
        commune = None
        code = (dpe["code_insee"] if dpe is not None and dpe["code_insee"] else
                parcelle["code_insee"] if parcelle is not None else None)
        if code:
            ligne = conn.execute("SELECT nom FROM commune WHERE code_insee = ?", (code,)).fetchone()
            commune = ligne["nom"] if ligne else None

    bien["parcelle_id"] = parcelle["id"] if parcelle is not None else parcelle_id
    bien["code_insee"] = code
    bien["commune"] = commune or (dpe["commune"] if dpe is not None else None)
    if dpe is not None:
        bien["n_dpe"] = dpe["n_dpe"]
        bien["adresse"] = dpe["adresse"]
        bien["type"] = TYPES_DPE.get((dpe["type_batiment"] or "").lower())
        bien["surface"] = dpe["surface_habitable"]
        bien["annee_construction"] = dpe["annee_construction"]
        bien["etiquette_dpe"] = dpe["etiquette_dpe"]
        bien["latitude"], bien["longitude"] = dpe["latitude"], dpe["longitude"]
        bien["sources"].append("diagnostic")
    if vente is not None:
        vente = dict(vente)
        bien["type"] = bien["type"] or vente["type"]
        if bien["type"] == vente["type"]:
            bien["surface"] = bien["surface"] or vente["surface"]
            bien["pieces"] = vente["pieces"] or None
            bien["dependances"] = vente["dependances"] or 0
            if vente["type"] == "maison" and vente["terrain_m2"]:
                bien["terrain_m2"] = vente["terrain_m2"]
        bien["adresse"] = bien["adresse"] or vente.get("adresse")
        bien["derniere_vente"] = vente["date_vente"]
        bien["sources"].append("vente")
    if parcelle is not None:
        if bien["latitude"] is None:
            bien["latitude"], bien["longitude"] = parcelle["latitude"], parcelle["longitude"]
        if bien["type"] != "appartement" and not bien["terrain_m2"] and parcelle["contenance_m2"]:
            bien["terrain_m2"] = parcelle["contenance_m2"]
        bien["sources"].append("parcelle")
    if bien["type"] == "appartement":
        bien["terrain_m2"] = None
    return bien


def etat_departement(departement):
    """Ou en est un departement : ventes chargees, modele appris, precision."""
    departement = str(departement)
    raison = references.dvf.indisponible(departement + "000")
    ref = references.etat(departement)
    m = modele(departement)
    precision = {}
    if m:
        for type_bien, p in m["precision"].items():
            precision[type_bien] = {"erreur_mediane": p["erreur_mediane"], "a10": p["a10"],
                                    "a20": p["a20"], "n": p["n"],
                                    "avec_historique": (p.get("avec_historique") or {}).get("erreur_mediane")}
    return {"departement": departement, "indisponible": raison,
            "ventes_chargees": ref is not None, "ventes": ref["ventes"] if ref else None,
            "importe_le": ref["importe_le"] if ref else None,
            "pret": m is not None, "entraine_le": m["entraine_le"] if m else None,
            "periode": m["periode"] if m else None, "precision": precision}


# =====================================================================
#  Les estimations enregistrees
# =====================================================================
def enregistrer(resultat, n_dpe=None, adresse=None):
    """Garde une estimation, avec ce qui a ete saisi : c'est ce qui permettra
    de la comparer au prix reel le jour ou la vente parait dans DVF."""
    b = resultat["bien"]
    with transaction() as conn:
        curseur = conn.execute(
            "INSERT INTO estimation (cree_le, departement, code_insee, parcelle_id, n_dpe, adresse,"
            " type, surface, terrain_m2, latitude, longitude, saisie_json, valeur, bas, haut,"
            " resultat_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (datetime.datetime.now().isoformat(timespec="seconds"), resultat["departement"],
             b.get("code_insee"), b.get("parcelle_id"), n_dpe or b.get("n_dpe"),
             adresse or b.get("adresse"), b["type"], b["surface"], b.get("terrain_m2"),
             b["latitude"], b["longitude"], json.dumps(resultat["saisie"]),
             resultat["valeur"], resultat["bas"], resultat["haut"], json.dumps(resultat)))
        return curseur.lastrowid


COLONNES_LISTE = ("e.id, e.cree_le, e.departement, e.code_insee, e.parcelle_id, e.n_dpe, e.adresse,"
                  " e.type, e.surface, e.terrain_m2, e.valeur, e.bas, e.haut, e.vente_date,"
                  " e.vente_prix, c.nom AS commune")


def enregistrees():
    with connexion() as conn:
        return [dict(l) for l in conn.execute(
            f"SELECT {COLONNES_LISTE} FROM estimation e"
            " LEFT JOIN commune c ON c.code_insee = e.code_insee ORDER BY e.cree_le DESC, e.id DESC")]


def enregistree(ident):
    with connexion() as conn:
        ligne = conn.execute(
            f"SELECT {COLONNES_LISTE}, e.saisie_json, e.resultat_json FROM estimation e"
            " LEFT JOIN commune c ON c.code_insee = e.code_insee WHERE e.id = ?",
            (int(ident),)).fetchone()
    if ligne is None:
        return None
    resultat = dict(ligne)
    resultat["saisie"] = json.loads(resultat.pop("saisie_json"))
    resultat["resultat"] = json.loads(resultat.pop("resultat_json"))
    return resultat


def supprimer(ident):
    with transaction() as conn:
        return conn.execute("DELETE FROM estimation WHERE id = ?", (int(ident),)).rowcount > 0


# =====================================================================
#  Le bilan : les estimations confrontees aux ventes reelles
# =====================================================================
# Une vente parue au plus trois mois AVANT l'estimation compte encore : DVF
# a six mois de retard, et l'on estime parfois un bien deja vendu sans le
# savoir. Au-dela, c'est une vente precedente, que l'historique connaissait.
RAPPROCHEMENT_JOURS_AVANT = 90
# La surface saisie vient souvent du diagnostic (habitable), celle de DVF du
# fisc (reelle batie) : elles different couramment de 10 %. Pour une maison
# la parcelle suffit presque a designer le bien ; pour un appartement, la
# surface doit trancher entre les lots d'un meme immeuble.
RAPPROCHEMENT_ECART_SURFACE = {"maison": 0.25, "appartement": 0.10}


def rapprocher(departement=None):
    """
    Retrouve, dans les ventes de reference, la vente des biens estimes.

    Meme parcelle, meme type, surface proche, vendue apres l'estimation (ou
    juste avant). Rend le nombre d'estimations nouvellement rapprochees.
    """
    requete = ("SELECT id, cree_le, parcelle_id, type, surface FROM estimation"
               " WHERE vente_id_mutation IS NULL AND parcelle_id IS NOT NULL")
    parametres = ()
    if departement:
        requete += " AND departement = ?"
        parametres = (str(departement),)
    trouvees = []
    with connexion() as conn:
        for e in conn.execute(requete, parametres).fetchall():
            depuis = (datetime.date.fromisoformat(e["cree_le"][:10])
                      - datetime.timedelta(days=RAPPROCHEMENT_JOURS_AVANT)).isoformat()
            ecart = RAPPROCHEMENT_ECART_SURFACE.get(e["type"], 0.1)
            for vente in conn.execute(
                    "SELECT id_mutation, date_vente, prix, surface FROM vente_reference"
                    " WHERE parcelle_id = ? AND type = ? AND date_vente >= ?"
                    " ORDER BY date_vente", (e["parcelle_id"], e["type"], depuis)):
                if abs(math.log(vente["surface"] / e["surface"])) <= ecart:
                    trouvees.append((vente["id_mutation"], vente["date_vente"], vente["prix"], e["id"]))
                    break
    if trouvees:
        maintenant = datetime.datetime.now().isoformat(timespec="seconds")
        with transaction() as conn:
            conn.executemany("UPDATE estimation SET vente_id_mutation = ?, vente_date = ?,"
                             " vente_prix = ?, rapproche_le = ? WHERE id = ?",
                             [(ident, date, prix, maintenant, e) for ident, date, prix, e in trouvees])
        logger.info("estimation : %d vente(s) retrouvee(s)", len(trouvees))
    return len(trouvees)


def bilan():
    """
    Ce que valaient vos estimations, face aux prix reellement payes.

    C'est la seule facon de verifier sur SES biens ce que rien d'autre ne
    calibre : l'echelle d'etat et l'ajustement personnel. Si les biens juges
    « mediocres » se vendent systematiquement plus cher qu'estime, c'est que
    l'on est trop severe — l'ecart par niveau d'etat le montre.
    """
    with connexion() as conn:
        total = conn.execute("SELECT count(*) FROM estimation").fetchone()[0]
        lignes = conn.execute("SELECT valeur, bas, haut, vente_prix, saisie_json FROM estimation"
                              " WHERE vente_prix IS NOT NULL AND valeur > 0").fetchall()
    resultat = {"estimations": total, "vendues": len(lignes)}
    if not lignes:
        return resultat
    ecarts = np.array([l["vente_prix"] / l["valeur"] - 1 for l in lignes])
    dedans = [l["bas"] <= l["vente_prix"] <= l["haut"] for l in lignes if l["bas"] and l["haut"]]
    resultat.update({
        "erreur_mediane": float(np.median(np.abs(ecarts)) * 100),
        "ecart_median": float(np.median(ecarts) * 100),
        "dans_la_fourchette": float(np.mean(dedans) * 100) if dedans else None,
    })
    par_etat = {}
    for ligne, ecart in zip(lignes, ecarts.tolist()):
        saisie = json.loads(ligne["saisie_json"] or "{}")
        cle = "travaux" if saisie.get("travaux") else (saisie.get("etat") or ETAT_DE_REFERENCE)
        par_etat.setdefault(cle, []).append(ecart)
    resultat["par_etat"] = {cle: {"n": len(valeurs), "ecart_median": float(np.median(valeurs) * 100)}
                            for cle, valeurs in par_etat.items()}
    return resultat


# =====================================================================
#  Entretien quotidien
# =====================================================================
def entretenir():
    """
    Le passage du planificateur : reprendre les departements dont DVF a
    publie un nouveau millesime (ou dont le modele date d'une version
    anterieure), relire l'indice et les loyers s'ils ont vieilli, puis
    chercher la vente des biens estimes. Quelques requetes HEAD les jours
    ou rien n'a change.

    Ne leve jamais : une source injoignable ne doit pas faire echouer la
    tache quotidienne, qui a d'autres choses a faire.
    """
    for departement in references.departements_importes():
        with _verrou:
            if _etat["en_cours"]:
                logger.info("estimation : preparation en cours, entretien reporte")
                return
            _etat.update(en_cours=True, departement=departement, etape="Vérification des millésimes DVF",
                         erreur=None, fini_le=None)
        try:
            if references.a_rafraichir(departement):
                logger.info("estimation %s : nouveau millesime DVF, reprise", departement)
                preparer(departement, forcer=True)
            elif a_reapprendre(departement):
                logger.info("estimation %s : modele d'une version anterieure, re-apprentissage",
                            departement)
                entrainer(departement)
        except Exception as erreur:                  # noqa: BLE001
            logger.error("entretien de l'estimation %s en echec : %s", departement, erreur)
            _publier(erreur=str(erreur))
        finally:
            _publier(en_cours=False, etape="Prêt",
                     fini_le=datetime.datetime.now().isoformat(timespec="seconds"))
    if references.departements_importes():
        for rafraichir in (rafraichir_indice_officiel, rafraichir_loyers):
            try:
                rafraichir()
            except Exception as erreur:              # noqa: BLE001
                logger.error("source annexe de l'estimation en echec : %s", erreur)
        try:
            rapprocher()
        except Exception as erreur:                  # noqa: BLE001
            logger.error("rapprochement des estimations en echec : %s", erreur)
