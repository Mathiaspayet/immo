# -*- coding: utf-8 -*-
"""
voisinage.py — Les ventes les plus proches d'un point, vite et exactement.

C'est le coeur de la methode par comparables : « les douze ventes les plus
proches, du meme type ». Il faut le faire pour le bien estime, mais aussi
des milliers de fois quand l'application mesure sa propre precision sur
l'annee ecoulee.

Une GRILLE suffit : on range les ventes par case de 400 m, et on explore
les cases en anneaux autour du point jusqu'a ce que le k-ieme voisin soit
plus proche que tout ce qui reste a explorer. Le resultat est EXACT, pas
approche — la condition d'arret le garantit. On evite ainsi d'embarquer
scipy pour un seul arbre de recherche ; s'il est deja la (il vient avec
le boosting), on s'en sert, et le resultat est le meme.

Les distances sont calculees dans un plan local (equirectangulaire) : a
l'echelle d'un departement, l'ecart avec la vraie distance sur la sphere
est de l'ordre du pour mille.
"""

import math

import numpy as np

try:                                     # present avec le boosting (phase 2)
    from scipy.spatial import cKDTree
except ImportError:                      # pragma: no cover - depend de l'image
    cKDTree = None

METRES_PAR_DEGRE_LAT = 110574.0
METRES_PAR_DEGRE_LON_EQUATEUR = 111320.0


class Voisinage:
    """Index des k plus proches voisins d'un nuage de points (lat, lon)."""

    def __init__(self, latitude, longitude, cote_m=400.0, methode="auto"):
        lat = np.asarray(latitude, dtype=float)
        lon = np.asarray(longitude, dtype=float)
        self.n = len(lat)
        self.lat0 = float(np.median(lat)) if self.n else 46.0
        self.kx = METRES_PAR_DEGRE_LON_EQUATEUR * math.cos(math.radians(self.lat0))
        self.x = lon * self.kx
        self.y = lat * METRES_PAR_DEGRE_LAT
        self.cote = float(cote_m)
        self.arbre = None
        if methode != "grille" and cKDTree is not None and self.n:
            self.arbre = cKDTree(np.column_stack([self.x, self.y]))
            return
        self.cases = {}
        self._bornes = (0, 0, 0, 0)
        if not self.n:
            return
        cx = np.floor(self.x / self.cote).astype(np.int64)
        cy = np.floor(self.y / self.cote).astype(np.int64)
        # Une clef entiere par case, triee une fois : les points d'une meme
        # case deviennent contigus, et chaque case est une tranche.
        largeur = int(cy.max() - cy.min() + 1)
        cle = (cx - cx.min()) * largeur + (cy - cy.min())
        ordre = np.argsort(cle, kind="stable")
        uniques, debuts = np.unique(cle[ordre], return_index=True)
        fins = np.append(debuts[1:], self.n)
        for u, d, f in zip(uniques.tolist(), debuts.tolist(), fins.tolist()):
            self.cases[(u // largeur + int(cx.min()), u % largeur + int(cy.min()))] = ordre[d:f]
        self._bornes = (int(cx.min()), int(cx.max()), int(cy.min()), int(cy.max()))

    def plus_proches(self, latitude, longitude, k):
        """(indices, distances en metres) des k plus proches, du plus pres au plus loin."""
        k = min(int(k), self.n)
        if k <= 0:
            return np.array([], dtype=np.int64), np.array([])
        xq = float(longitude) * self.kx
        yq = float(latitude) * METRES_PAR_DEGRE_LAT
        if self.arbre is not None:
            d, i = self.arbre.query([xq, yq], k=k)
            return np.atleast_1d(i).astype(np.int64), np.atleast_1d(d)
        cx0, cy0 = int(math.floor(xq / self.cote)), int(math.floor(yq / self.cote))
        xmin, xmax, ymin, ymax = self._bornes
        rayon_max = int(max(abs(cx0 - xmin), abs(cx0 - xmax), abs(cy0 - ymin), abs(cy0 - ymax))) + 1
        morceaux = []
        compte = 0
        for r in range(0, rayon_max + 1):
            for cle in _anneau(cx0, cy0, r):
                indices = self.cases.get(cle)
                if indices is not None:
                    morceaux.append(indices)
                    compte += len(indices)
            if compte >= k:
                candidats = np.concatenate(morceaux)
                d = np.hypot(self.x[candidats] - xq, self.y[candidats] - yq)
                ordre = np.argpartition(d, k - 1)[:k]
                ordre = ordre[np.argsort(d[ordre])]
                # Tout point hors des anneaux explores est a plus de r cases :
                # si le k-ieme est plus proche que cela, le resultat est exact.
                if d[ordre[-1]] <= r * self.cote:
                    return candidats[ordre], d[ordre]
        candidats = np.concatenate(morceaux) if morceaux else np.array([], dtype=np.int64)
        d = np.hypot(self.x[candidats] - xq, self.y[candidats] - yq)
        ordre = np.argsort(d)[:k]
        return candidats[ordre], d[ordre]

    def plus_proches_lot(self, latitudes, longitudes, k):
        """
        Les k plus proches de CHAQUE point d'un lot : (indices, distances),
        deux tableaux n x k. Sert au boosting, qui a besoin du voisinage de
        dizaines de milliers de ventes a la fois ; l'arbre les traite d'un
        seul appel, la grille point par point.
        """
        latitudes = np.asarray(latitudes, dtype=float)
        longitudes = np.asarray(longitudes, dtype=float)
        k = min(int(k), self.n)
        if self.arbre is not None and k > 0:
            d, i = self.arbre.query(np.column_stack([longitudes * self.kx,
                                                     latitudes * METRES_PAR_DEGRE_LAT]), k=k)
            return i.reshape(len(latitudes), k).astype(np.int64), d.reshape(len(latitudes), k)
        indices = np.zeros((len(latitudes), max(k, 0)), dtype=np.int64)
        distances = np.zeros((len(latitudes), max(k, 0)))
        for rang, (lat, lon) in enumerate(zip(latitudes.tolist(), longitudes.tolist())):
            indices[rang], distances[rang] = self.plus_proches(lat, lon, k)
        return indices, distances

    def dans_le_rayon(self, latitude, longitude, rayon_m):
        """Combien de points a moins de `rayon_m` — pour juger la densite locale."""
        if self.n == 0:
            return 0
        xq = float(longitude) * self.kx
        yq = float(latitude) * METRES_PAR_DEGRE_LAT
        if self.arbre is not None:
            return len(self.arbre.query_ball_point([xq, yq], r=rayon_m))
        r_cases = int(math.ceil(rayon_m / self.cote)) + 1
        cx0, cy0 = int(math.floor(xq / self.cote)), int(math.floor(yq / self.cote))
        total = 0
        for dx in range(-r_cases, r_cases + 1):
            for dy in range(-r_cases, r_cases + 1):
                indices = self.cases.get((cx0 + dx, cy0 + dy))
                if indices is not None:
                    total += int((np.hypot(self.x[indices] - xq, self.y[indices] - yq) <= rayon_m).sum())
        return total


def _anneau(cx, cy, r):
    """Les cases a exactement r cases (distance de Tchebychev) de (cx, cy)."""
    if r == 0:
        yield (cx, cy)
        return
    for dx in range(-r, r + 1):
        yield (cx + dx, cy - r)
        yield (cx + dx, cy + r)
    for dy in range(-r + 1, r):
        yield (cx - r, cy + dy)
        yield (cx + r, cy + dy)
