# -*- coding: utf-8 -*-
"""
test_estimation.py — Estimer la valeur d'un bien.

Aucun reseau : les ventes d'un departement FICTIF (« 99 ») sont fabriquees
avec des prix connus d'avance — un prix au m2 par commune, une tendance,
un bruit. Le moteur doit retrouver ce qu'on y a mis, et mesurer une
precision coherente avec le bruit : c'est ce qui garantit que la
fourchette affichee dit vrai.
"""

import datetime
import json
import math

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.base.connexion import connexion, transaction
from app.main import application
from app.metier import boosting, criteres, estimation, references
from app.metier.voisinage import Voisinage
from app.sources import insee, loyers
from app.sources.client_http import ErreurSource
from tests.conftest import inserer_dpe

# =====================================================================
#  Un departement fictif, aux prix connus
# =====================================================================
DEP = "99"
LAT0, LON0 = 44.0, -1.0
PRIX_M2 = 2500.0
TENDANCE = 0.015                         # par trimestre
BRUIT = 0.12
EFFETS_COMMUNES = {f"99{n:03d}": e for n, e in
                   zip(range(1, 9), (-0.30, -0.20, -0.10, 0.0, 0.05, 0.10, 0.20, 0.30))}


def _centre(code):
    rang = int(code[-3:]) - 1
    return LAT0 + (rang // 4) * 0.08, LON0 + (rang % 4) * 0.08


def _trimestre(date):
    return f"{date.year}-Q{(date.month - 1) // 3 + 1}"


def _rang_trimestre(date):
    return (date.year - 2023) * 4 + (date.month - 1) // 3


def _valeur_attendue(code, type_bien, surface, terrain, date):
    """Le prix « vrai », sans bruit, que le moteur doit retrouver."""
    log = (math.log(PRIX_M2 * surface) + EFFETS_COMMUNES[code]
           + TENDANCE * _rang_trimestre(date))
    if type_bien == "maison":
        log += 0.2 * math.log(max(terrain, 50) / 700.0)
    else:
        log += 0.15
    return math.exp(log)


def _fabriquer(n=2400, graine=3, reventes=0.12):
    rng = np.random.default_rng(graine)
    debut = datetime.date(2023, 1, 1)
    communes = list(EFFETS_COMMUNES)
    ventes, terrains = [], []
    for i in range(n):
        code = communes[i % len(communes)]
        lat, lon = _centre(code)
        lat += rng.normal(0, 0.01)
        lon += rng.normal(0, 0.01)
        date = debut + datetime.timedelta(days=int(rng.integers(0, 3 * 365)))
        type_bien = "maison" if rng.random() < 0.7 else "appartement"
        if type_bien == "maison":
            surface = float(np.clip(rng.lognormal(math.log(100), 0.25), 40, 250))
            terrain = float(np.clip(rng.lognormal(math.log(700), 0.5), 100, 5000))
        else:
            surface = float(np.clip(rng.lognormal(math.log(55), 0.3), 18, 140))
            terrain = 0.0
        prix = _valeur_attendue(code, type_bien, surface, terrain, date) * math.exp(rng.normal(0, BRUIT))
        parcelle = f"{code}000AB{i:04d}"
        ventes.append((DEP, f"M{i}", code, date.isoformat(), _trimestre(date), type_bien, round(prix),
                       surface, max(1, round(surface / 25)), terrain, 0, 0, lat, lon, parcelle,
                       f"{i} rue de l'Essai"))
        # Une part des biens est revendue plus tard, un peu plus cher que le marche.
        if type_bien == "maison" and rng.random() < reventes and date < datetime.date(2025, 3, 1):
            date2 = date + datetime.timedelta(days=int(rng.integers(300, 900)))
            if date2 <= datetime.date(2025, 12, 31):
                prix2 = (_valeur_attendue(code, type_bien, surface, terrain, date2) * 1.06
                         * math.exp(rng.normal(0, BRUIT / 2)))
                ventes.append((DEP, f"R{i}", code, date2.isoformat(), _trimestre(date2), type_bien,
                               round(prix2), surface, max(1, round(surface / 25)), terrain, 0, 0,
                               lat, lon, parcelle, f"{i} rue de l'Essai"))
    for i in range(400):
        code = communes[i % len(communes)]
        lat, lon = _centre(code)
        date = debut + datetime.timedelta(days=int(rng.integers(0, 3 * 365)))
        surface = float(np.clip(rng.lognormal(math.log(700), 0.5), 150, 5000))
        prix = (80 * 700 * (surface / 700) ** 0.38 * math.exp(EFFETS_COMMUNES[code])
                * math.exp(TENDANCE * _rang_trimestre(date) + rng.normal(0, 0.15)))
        terrains.append((DEP, f"T{i}", code, date.isoformat(), _trimestre(date), round(prix),
                         surface, lat + rng.normal(0, 0.01), lon + rng.normal(0, 0.01)))
    with transaction() as conn:
        conn.executemany("INSERT INTO vente_reference VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", ventes)
        conn.executemany("INSERT INTO terrain_reference VALUES (?,?,?,?,?,?,?,?,?)", terrains)
        conn.execute("INSERT INTO departement_reference VALUES (?,?,?,?,?,?,?)",
                     (DEP, "2026-09-01T10:00:00", "{}", len(ventes), len(terrains),
                      "2023-01-01", "2025-12-31"))
    return ventes, terrains


@pytest.fixture()
def sans_reseau(monkeypatch):
    """Toute tentative de sortie echoue : le moteur doit s'en passer."""
    def refuse(*args, **kwargs):
        raise ErreurSource("reseau coupe pour les tests")
    monkeypatch.setattr(insee, "telecharger", refuse)
    monkeypatch.setattr(loyers, "telecharger", refuse)


@pytest.fixture()
def departement(base, sans_reseau, monkeypatch):
    # Moins d'arbres qu'en production : les tests verifient le comportement,
    # pas la precision du boosting, et restent rapides.
    monkeypatch.setattr(boosting, "TOURS", 120)
    estimation._cache.clear()
    ventes, terrains = _fabriquer()
    modele = estimation.entrainer(DEP)
    yield {"ventes": ventes, "terrains": terrains, "modele": modele}
    estimation._cache.clear()


# Le boosting vient avec LightGBM, installe dans l'image : sans lui, le
# croisement se fait sans, et les tests le verifient aussi.
BOOSTING = {"boosting"} if boosting.disponible() else set()


def _bien(code="99004", type_bien="maison", surface=100.0, terrain=700.0, **autres):
    lat, lon = _centre(code)
    return {"type": type_bien, "surface": surface, "terrain_m2": terrain, "latitude": lat,
            "longitude": lon, "code_insee": code, "pieces": 4, **autres}


# =====================================================================
#  Le nettoyage des ventes DVF
# =====================================================================
def _ligne(mutation, **champs):
    ligne = {"id_mutation": mutation, "date_mutation": "2025-03-14", "nature_mutation": "Vente",
             "valeur_fonciere": "250000", "code_commune": "40184", "id_parcelle": "40184000AB0001",
             "code_nature_culture": "S", "surface_terrain": "", "type_local": "",
             "surface_reelle_bati": "", "nombre_pieces_principales": "", "lot1_numero": "",
             "latitude": "44.2", "longitude": "-1.23", "adresse_numero": "12",
             "adresse_suffixe": "", "adresse_nom_voie": "RUE DES PINS"}
    ligne.update(champs)
    return ligne


def test_une_maison_avec_sa_dependance_et_deux_parcelles():
    """Le terrain se somme sur les parcelles DISTINCTES : la ligne de la
    dependance repete la surface de la parcelle de la maison."""
    lignes = [
        _ligne("A", type_local="Maison", surface_reelle_bati="110", nombre_pieces_principales="5",
               surface_terrain="600"),
        _ligne("A", type_local="Dépendance", surface_terrain="600"),
        _ligne("A", id_parcelle="40184000AB0002", surface_terrain="150"),
    ]
    logements, terrains = references.nettoyer(lignes, "40")
    assert terrains == []
    (vente,) = logements
    assert vente[5] == "maison" and vente[6] == 250000 and vente[7] == 110
    assert vente[8] == 5
    assert vente[9] == 750            # 600 + 150, pas 1 350
    assert vente[10] == 1             # une dependance
    assert vente[15] == "12 RUE DES PINS"


def test_une_vente_de_deux_maisons_est_ecartee():
    """Un prix global pour deux maisons ne se repartit pas."""
    lignes = [_ligne("B", type_local="Maison", surface_reelle_bati="90"),
              _ligne("B", type_local="Maison", surface_reelle_bati="70", id_parcelle="40184000AB0009")]
    assert references.nettoyer(lignes, "40") == ([], [])


def test_un_local_d_activite_ecarte_la_vente():
    lignes = [_ligne("C", type_local="Maison", surface_reelle_bati="90"),
              _ligne("C", type_local="Local industriel. commercial ou assimilé", surface_reelle_bati="40")]
    assert references.nettoyer(lignes, "40") == ([], [])


def test_les_prix_impossibles_sont_ecartes():
    lignes = [_ligne("D", valeur_fonciere="1", type_local="Maison", surface_reelle_bati="90"),
              _ligne("E", valeur_fonciere="9000000", type_local="Appartement", surface_reelle_bati="30"),
              _ligne("F", type_local="Maison", surface_reelle_bati="90", surface_terrain="80000")]
    assert references.nettoyer(lignes, "40") == ([], [])


def test_une_vefa_est_marquee_et_un_terrain_a_batir_mis_a_part():
    lignes = [
        _ligne("G", nature_mutation="Vente en l'état futur d'achèvement", type_local="Appartement",
               surface_reelle_bati="45", valeur_fonciere="210000"),
        _ligne("H", nature_mutation="Vente terrain à bâtir", code_nature_culture="AB",
               surface_terrain="800", valeur_fonciere="72000"),
        _ligne("I", nature_mutation="Echange", type_local="Maison", surface_reelle_bati="90"),
    ]
    logements, terrains = references.nettoyer(lignes, "40")
    assert [(l[1], l[5], l[11]) for l in logements] == [("G", "appartement", 1)]
    assert [(t[1], t[5], t[6]) for t in terrains] == [("H", 72000, 800)]


def test_une_vente_sans_position_est_ignoree():
    lignes = [_ligne("J", type_local="Maison", surface_reelle_bati="90", latitude="", longitude="")]
    assert references.nettoyer(lignes, "40") == ([], [])


# =====================================================================
#  Les plus proches voisins
# =====================================================================
@pytest.mark.parametrize("methode", ["grille", "auto"])
def test_les_voisins_sont_exacts(methode):
    """La grille n'est pas une approximation : memes voisins que la force brute."""
    rng = np.random.default_rng(5)
    lat = 44 + rng.random(3000) * 0.4
    lon = -1.2 + rng.random(3000) * 0.4
    index = Voisinage(lat, lon, methode=methode)
    for _ in range(60):
        qlat, qlon = 43.9 + rng.random() * 0.6, -1.3 + rng.random() * 0.6   # parfois hors du nuage
        indices, distances = index.plus_proches(qlat, qlon, 12)
        brute = np.hypot((lon - qlon) * index.kx, (lat - qlat) * 110574.0)
        attendu = np.sort(brute)[:12]
        assert np.allclose(distances, attendu)
        assert np.allclose(brute[indices], distances)


def test_le_compte_dans_un_rayon():
    rng = np.random.default_rng(6)
    lat = 44 + rng.random(2000) * 0.1
    lon = -1 + rng.random(2000) * 0.1
    index = Voisinage(lat, lon, methode="grille")
    brute = np.hypot((lon + 0.95) * index.kx, (lat - 44.05) * 110574.0)
    assert index.dans_le_rayon(44.05, -0.95, 1500) == int((brute <= 1500).sum())


def test_un_nuage_vide_ne_fait_pas_tomber():
    index = Voisinage([], [], methode="grille")
    indices, distances = index.plus_proches(44, -1, 5)
    assert len(indices) == 0 and len(distances) == 0


# =====================================================================
#  L'apprentissage
# =====================================================================
def test_l_indice_retrouve_la_tendance(departement):
    """+1,5 % par trimestre sur trois ans : l'indice doit le retrouver."""
    effets = departement["modele"]["indices"]["maison"]["effets"]
    pente = (effets[-1] - effets[0]) / (len(effets) - 1)
    assert pente == pytest.approx(TENDANCE, abs=0.004)


def test_la_precision_mesuree_est_celle_du_bruit(departement):
    """Avec 12 % de bruit, l'erreur mediane attendue est de l'ordre de 8 %.
    Le moteur doit la mesurer lui-meme, sans biais notable."""
    precision = departement["modele"]["precision"]["maison"]
    assert 5 < precision["erreur_mediane"] < 14
    assert abs(precision["biais"]) < 4
    # La fourchette encadre 80 % des prix : P10 negatif, P90 positif.
    assert precision["bas"] < 0 < precision["haut"]
    assert set(precision["methodes"]) >= {"comparables", "hedonique", "sol_construction"}


def test_le_modele_est_garde_en_base(departement):
    m = estimation.modele(DEP)
    assert m["departement"] == DEP and m["entraine_le"]
    assert m["ventes"]["maison"] > 1000
    assert estimation.etat_departement(DEP)["pret"] is True


def test_la_plus_value_des_reventes_est_mesuree(departement):
    """Les reventes fabriquees gagnent 6 % sur le marche."""
    reventes = departement["modele"]["reventes"]["maison"]
    assert reventes["reventes"] >= 50
    assert reventes["plus_value"] == pytest.approx(0.06, abs=0.04)


# =====================================================================
#  L'estimation d'un bien
# =====================================================================
def test_une_maison_s_estime_pres_de_sa_valeur(departement):
    resultat = estimation.estimer(_bien(), {})
    attendu = _valeur_attendue("99004", "maison", 100, 700, datetime.date(2025, 10, 1))
    assert resultat["valeur"] == pytest.approx(attendu, rel=0.15)
    assert resultat["bas"] < resultat["valeur"] < resultat["haut"]
    assert {m["cle"] for m in resultat["methodes"]} == {"comparables", "hedonique", "sol_construction"} | BOOSTING
    assert resultat["decomposition"]["terrain"] > 0 and resultat["decomposition"]["bati"] > 0
    assert len(resultat["comparables"]) == estimation.K_COMPARABLES
    json.dumps(resultat)              # tout doit passer en JSON


def test_la_commune_chere_s_estime_plus_cher(departement):
    """L'effet commune : de -30 % a +30 % entre les deux extremes."""
    chere = estimation.estimer(_bien("99008"), {})["valeur"]
    modeste = estimation.estimer(_bien("99001"), {})["valeur"]
    assert chere / modeste == pytest.approx(math.exp(0.6), rel=0.2)


def test_un_appartement_n_a_pas_de_sol_construction(departement):
    resultat = estimation.estimer(_bien(type_bien="appartement", surface=55, terrain=300), {})
    assert {m["cle"] for m in resultat["methodes"]} == {"comparables", "hedonique"} | BOOSTING
    assert resultat["bien"]["terrain_m2"] == 0
    assert resultat["decomposition"] is None


def test_l_etat_du_bati_suit_l_echelle(departement):
    reference = estimation.estimer(_bien(), {"etat": "assez_bon"})["valeur"]
    mauvais = estimation.estimer(_bien(), {"etat": "mauvais"})["valeur"]
    bon = estimation.estimer(_bien(), {"etat": "bon"})["valeur"]
    assert mauvais / reference == pytest.approx(0.8 / 1.1, rel=0.002)
    assert bon / reference == pytest.approx(1.2 / 1.1, rel=0.002)


def test_les_travaux_remplacent_l_etat(departement):
    reference = estimation.estimer(_bien(), {})
    avec_travaux = estimation.estimer(_bien(), {"etat": "mauvais", "travaux": 40000})
    assert avec_travaux["valeur"] == pytest.approx(reference["valeur"] - 40000, abs=2)
    assert avec_travaux["saisie"]["etat"] is None
    assert any(a.get("montant") == -40000 for a in avec_travaux["ajustements"])


def test_l_ajustement_personnel_est_borne(departement):
    reference = estimation.estimer(_bien(), {})["valeur"]
    excessif = estimation.estimer(_bien(), {"ajustement": 80, "raison": "vue"})
    assert excessif["valeur"] == pytest.approx(reference * 1.3, rel=0.002)
    assert "vue" in excessif["ajustements"][-1]["libelle"]


def test_un_bien_deja_vendu_prend_son_historique(departement):
    """La revente la plus recente d'une parcelle entre dans le calcul, et la
    precision affichee devient celle des biens deja vendus."""
    revente = next(v for v in departement["ventes"] if v[1].startswith("R"))
    bien = _bien(revente[2], surface=revente[7], terrain=revente[9], parcelle_id=revente[14])
    bien["latitude"], bien["longitude"] = revente[12], revente[13]
    resultat = estimation.estimer(bien, {})
    assert resultat["historique"]["date"] == revente[3]
    assert resultat["historique"]["poids"] == pytest.approx(2 / 3)
    sans = estimation.estimer({**bien, "parcelle_id": None}, {})
    assert sans["historique"] is None
    precision = departement["modele"]["precision"]["maison"]
    if precision.get("avec_historique"):
        assert resultat["precision"] == precision["avec_historique"]


def test_les_pieces_et_le_terrain_inconnus_sont_estimes(departement):
    """Laisses vides, ils prennent la valeur courante — pas zero."""
    resultat = estimation.estimer({**_bien(), "pieces": None, "terrain_m2": None}, {})
    assert resultat["bien"]["pieces_estimees"] and resultat["bien"]["pieces"] >= 3
    assert resultat["bien"]["terrain_estime"] and resultat["bien"]["terrain_m2"] > 300
    assert any("terrain" in phrase for phrase in resultat["ne_sait_pas"])


@pytest.mark.parametrize("bien, message", [
    ({"type": "chateau"}, "maison ou appartement"),
    ({"surface": 5}, "Surface"),
    ({"latitude": None}, "Position"),
    ({"code_insee": "67482"}, "Alsace-Moselle"),
])
def test_les_demandes_impossibles_disent_pourquoi(departement, bien, message):
    with pytest.raises(ValueError, match=message):
        estimation.estimer({**_bien(), **bien}, {})


def test_un_departement_non_prepare_est_signale(base, sans_reseau):
    with pytest.raises(estimation.PasPret):
        estimation.estimer(_bien(code="64445"), {})


def test_sans_reseau_l_estimation_se_fait_quand_meme(departement):
    """Ni indice Insee ni loyers : l'estimation sort, et le dit."""
    resultat = estimation.estimer(_bien(), {})
    assert resultat["projection"] is None and resultat["rendement"] is None
    assert any("indice officiel" in phrase for phrase in resultat["ne_sait_pas"])


# =====================================================================
#  L'indice Notaires-Insee et les loyers
# =====================================================================
SDMX = b"""<?xml version="1.0" encoding="UTF-8"?>
<message:StructureSpecificData xmlns:message="http://www.sdmx.org/resources/sdmxml/schemas/v2_1/message">
<message:DataSet>
<Series INDICATEUR="IPLA_M" CORRECTION="BRUT" REF_AREA="PR">
  <Obs TIME_PERIOD="2025-Q3" OBS_VALUE="130.0"/>
  <Obs TIME_PERIOD="2025-Q4" OBS_VALUE="130.6"/>
  <Obs TIME_PERIOD="2026-Q1" OBS_VALUE="129.4"/>
  <Obs TIME_PERIOD="2026-Q2" OBS_VALUE="127.7"/>
</Series>
<Series INDICATEUR="IPLA_M" CORRECTION="CVS" REF_AREA="PR">
  <Obs TIME_PERIOD="2026-Q2" OBS_VALUE="999"/>
</Series>
<Series INDICATEUR="IPLA_A" CORRECTION="BRUT" REF_AREA="D75">
  <Obs TIME_PERIOD="2026-Q2" OBS_VALUE="101.2"/>
</Series>
</message:DataSet>
</message:StructureSpecificData>"""


def test_l_indice_ne_garde_que_les_series_brutes():
    observations = insee.lire(SDMX)
    assert ("PR", "maison", "2026-Q2", 127.7) in observations
    assert ("D75", "appartement", "2026-Q2", 101.2) in observations
    assert all(valeur != 999 for *_, valeur in observations)


def test_la_zone_de_l_indice_la_plus_fine():
    assert insee.zones_candidates("75")[0] == "D75"
    assert insee.zones_candidates("69")[0] == "R84"
    assert insee.zones_candidates("40") == ["PR", "FM"]
    assert insee.zones_candidates("974") == ["FR-D976"]


def test_la_projection_part_du_niveau_de_reference(base):
    """Le calcul est ramene a la moyenne des deux derniers trimestres DVF :
    la projection part de la meme moyenne."""
    with transaction() as conn:
        conn.executemany("INSERT INTO indice_officiel VALUES (?,?,?,?)", insee.lire(SDMX))
    projection = estimation.projection("40", "maison", ["2025-Q3", "2025-Q4"])
    assert projection["zone"] == "PR" and projection["jusqu_a"] == "2026-Q2"
    assert projection["facteur"] == pytest.approx(127.7 / ((130.0 + 130.6) / 2))
    # Rien pour les appartements de province dans cet extrait : pas de projection.
    assert estimation.projection("40", "appartement", ["2025-Q3", "2025-Q4"]) is None


def test_l_indice_se_relit_au_plus_une_fois_par_mois(base, monkeypatch):
    appels = []
    monkeypatch.setattr(insee, "telecharger", lambda: appels.append(1) or insee.lire(SDMX))
    assert estimation.rafraichir_indice_officiel() is True
    assert estimation.rafraichir_indice_officiel() is False
    assert len(appels) == 1


def test_apres_un_echec_on_ne_retente_pas_aussitot(base, monkeypatch):
    """Sans Internet, chaque estimation attendrait sinon la fin du delai de
    connexion : un echec suspend les tentatives quelques heures."""
    appels = []

    def injoignable():
        appels.append(1)
        raise ErreurSource("Insee injoignable (URLError)")
    monkeypatch.setattr(insee, "telecharger", injoignable)
    assert estimation.rafraichir_indice_officiel() is False
    assert estimation.rafraichir_indice_officiel() is False
    assert len(appels) == 1


LOYERS = ('"id_zone";"INSEE_C";"LIBGEO";"EPCI";"DEP";"REG";"loypredm2";"lwr.IPm2";"upr.IPm2";'
          '"TYPPRED";"nbobs_com";"nbobs_mail";"R2_adj"\n'
          '"1";"40184";"Mimizan";"244000865";"40";"75";10,77;8,03;14,44;"commune";54;494;0,75\n'
          '"1";"37264";"Vallères";"200072650";"37";"24";8,96;6,95;11,55;"maille";39;494;0,75\n'
          ).encode("latin-1")


def test_la_carte_des_loyers_se_lit():
    lignes = loyers.lire_csv(LOYERS, "maison", "2025")
    assert lignes[0] == ("40184", "maison", 10.77, 8.03, 14.44, "2025")
    assert len(lignes) == 2


def test_le_rendement_brut_est_calcule(departement):
    with transaction() as conn:
        conn.execute("INSERT INTO loyer_commune VALUES ('99004', 'maison', 10.0, 8.0, 12.0, '2025')")
    resultat = estimation.estimer(_bien(), {})
    rendement = resultat["rendement"]
    assert rendement["brut"] == pytest.approx(10.0 * 12 * 100 / resultat["valeur"], rel=0.01)


# =====================================================================
#  Pre-remplissage, memoire, entretien
# =====================================================================
def test_le_formulaire_se_pre_remplit_depuis_le_diagnostic(base):
    inserer_dpe(n_dpe="DPE-E", code_insee="40184", surface_habitable=92.5,
                type_batiment="maison", annee_construction=1978)
    bien = estimation.bien_depuis(n_dpe="DPE-E")
    assert (bien["type"], bien["surface"], bien["annee_construction"]) == ("maison", 92.5, 1978)
    assert bien["code_insee"] == "40184" and bien["latitude"] is not None
    assert bien["sources"] == ["diagnostic"]


def test_une_parcelle_sans_diagnostic_donne_son_terrain(base):
    with transaction() as conn:
        conn.execute(
            "INSERT INTO parcelle (id, code_insee, contenance_m2, latitude, longitude, importe_le)"
            " VALUES ('40184000AB0001', '40184', 812, 44.2, -1.23, '2026-09-01')")
        conn.execute(
            "INSERT INTO vente_reference VALUES ('40', 'M1', '40184', '2024-05-02', '2024-Q2',"
            " 'maison', 280000, 104, 5, 790, 1, 0, 44.2, -1.23, '40184000AB0001', '3 rue X')")
    bien = estimation.bien_depuis(parcelle_id="40184000AB0001")
    assert (bien["type"], bien["surface"], bien["pieces"]) == ("maison", 104, 5)
    assert bien["terrain_m2"] == 790            # celui de la vente, plutot que la contenance
    assert bien["dependances"] == 1 and bien["derniere_vente"] == "2024-05-02"


def test_un_bien_inconnu_est_signale(base):
    with pytest.raises(LookupError):
        estimation.bien_depuis(n_dpe="INCONNU")
    with pytest.raises(LookupError):
        estimation.bien_depuis(parcelle_id="INCONNUE")


def test_une_estimation_se_garde_et_se_relit(departement):
    resultat = estimation.estimer(_bien(adresse="4 rue de l'Essai"), {"etat": "passable"})
    ident = estimation.enregistrer(resultat)
    (ligne,) = estimation.enregistrees()
    assert ligne["id"] == ident and ligne["valeur"] == resultat["valeur"]
    relue = estimation.enregistree(ident)
    assert relue["saisie"]["etat"] == "passable"
    assert relue["resultat"]["valeur"] == resultat["valeur"]
    assert estimation.supprimer(ident) is True
    assert estimation.enregistrees() == []


def test_l_entretien_ne_reprend_que_ce_qui_a_change(departement, monkeypatch):
    repris = []
    monkeypatch.setattr(estimation, "preparer", lambda dep, forcer=False: repris.append(dep))
    monkeypatch.setattr(references, "a_rafraichir", lambda dep: False)
    estimation.entretenir()
    assert repris == []
    monkeypatch.setattr(references, "a_rafraichir", lambda dep: True)
    estimation.entretenir()
    assert repris == [DEP]
    assert estimation.etat_preparation()["en_cours"] is False


# =====================================================================
#  Les atouts et defauts
# =====================================================================
def test_un_atout_s_applique_a_son_coefficient(departement):
    reference = estimation.estimer(_bien(), {})["valeur"]
    avec_vue = estimation.estimer(_bien(), {"criteres": ["vue_mer"]})
    assert avec_vue["valeur"] / reference == pytest.approx(1.20, rel=0.002)
    assert avec_vue["saisie"]["criteres"] == ["vue_mer"]
    assert {"libelle": "Vue mer dégagée", "facteur": 1.2, "critere": "vue_mer"} in avec_vue["ajustements"]
    bruit = estimation.estimer(_bien(), {"criteres": ["rue_passante", "vis_a_vis"]})["valeur"]
    assert bruit / reference == pytest.approx(0.92 * 0.92, rel=0.002)


def test_le_cumul_des_atouts_est_borne(departement):
    reference = estimation.estimer(_bien(), {})["valeur"]
    tout = ["vue_mer", "standing", "architecture", "piscine", "sans_vis_a_vis", "lumineux", "calme"]
    resultat = estimation.estimer(_bien(), {"criteres": tout})
    assert resultat["valeur"] / reference == pytest.approx(criteres.PLAFOND, rel=0.002)
    assert any("bornés" in a["libelle"] for a in resultat["ajustements"])
    defauts = ["nuisance_forte", "vis_a_vis", "sombre", "voisinage", "risque", "passoire",
               "prestations_modestes", "mitoyenne"]
    assert (estimation.estimer(_bien(), {"criteres": defauts})["valeur"] / reference
            == pytest.approx(criteres.PLANCHER, rel=0.002))


@pytest.mark.parametrize("coches, message", [
    (["inconnu"], "inconnu"),
    (["rdc"], "ne s'applique pas à une maison"),
    (["vue_mer", "vue_mer_partielle"], "s'excluent"),
    (["calme", "rue_passante"], "s'excluent"),
])
def test_les_atouts_incoherents_sont_refuses(departement, coches, message):
    with pytest.raises(ValueError, match=message):
        estimation.estimer(_bien(), {"criteres": coches})


def test_un_atout_d_appartement_s_applique_a_un_appartement(departement):
    appartement = _bien(type_bien="appartement", surface=55, terrain=0)
    reference = estimation.estimer(appartement, {})["valeur"]
    rdc = estimation.estimer(appartement, {"criteres": ["rdc", "grande_terrasse"]})["valeur"]
    assert rdc / reference == pytest.approx(0.90 * 1.10, rel=0.002)
    with pytest.raises(ValueError, match="ne s'applique pas à un appartement"):
        estimation.estimer(appartement, {"criteres": ["piscine"]})


def test_un_bien_deja_vendu_garde_ses_atouts_dans_son_ancien_prix(departement):
    """Une vue mer, le bien l'avait deja a sa vente precedente : l'atout ne
    porte que sur la part « bien type » du calcul."""
    revente = next(v for v in departement["ventes"] if v[1].startswith("R"))
    bien = _bien(revente[2], surface=revente[7], terrain=revente[9], parcelle_id=revente[14])
    bien["latitude"], bien["longitude"] = revente[12], revente[13]
    reference = estimation.estimer(bien, {})["valeur"]
    avec_vue = estimation.estimer(bien, {"criteres": ["vue_mer"]})
    assert avec_vue["valeur"] / reference == pytest.approx(1.20 ** (1 / 3), rel=0.002)
    assert "ancien prix" in avec_vue["ajustements"][0]["libelle"]


def test_le_bilan_se_lit_aussi_par_critere(departement):
    resultat = estimation.estimer(_bien(parcelle_id="99004000ZZ0003"), {"criteres": ["piscine"]})
    estimation.enregistrer(resultat)
    _vente_apres("99004000ZZ0003", datetime.date.today().isoformat(),
                 round(resultat["valeur"] * 0.95), 100, ident="VENTE-PISCINE")
    assert estimation.rapprocher(DEP) == 1
    par_critere = estimation.bilan()["par_critere"]
    assert par_critere["piscine"]["libelle"] == "Piscine"
    assert par_critere["piscine"]["ecart_median"] == pytest.approx(-5, abs=0.1)


def test_les_coefficients_dates():
    assert criteres.effet_en("passoire", 2021) == -0.07
    assert criteres.effet_en("passoire", 2025) == -0.12          # celui du catalogue
    assert criteres.effet_en("vue_mer", 2021) == 0.20            # non date : constant
    assert criteres.facteur_en(["climatisation"], 2022) == 1.0
    assert set(criteres.dates()) <= {c["cle"] for c in criteres.liste()}


def test_le_catalogue_est_coherent():
    catalogue = criteres.liste()
    assert len({c["cle"] for c in catalogue}) == len(catalogue)
    for c in catalogue:
        assert c["theme"] in criteres.THEMES and c["repere"]
        assert -20 <= c["effet"] <= 20 and c["effet"] != 0
        assert set(c["types"]) <= {"maison", "appartement"}
    # Un groupe exclusif reunit des criteres du meme type de bien.
    groupes = {}
    for c in catalogue:
        if c["groupe"]:
            groupes.setdefault(c["groupe"], set()).add(tuple(c["types"]))
    assert all(len(types) == 1 for types in groupes.values())


# =====================================================================
#  La valeur dans le temps
# =====================================================================
def test_la_courbe_part_de_l_estimation_et_suit_l_indice(departement):
    resultat = estimation.estimer(_bien(), {})
    courbe = resultat["evolution"]
    points = {p["trimestre"]: p for p in courbe["points"]}
    assert courbe["ancre"] == resultat["trimestre_de_reference"] == "2025-Q4"
    # Au trimestre de reference, la courbe donne l'estimation elle-meme.
    assert points["2025-Q4"]["valeur"] == pytest.approx(resultat["valeur"], abs=1)
    assert points["2025-Q4"]["bas"] == pytest.approx(resultat["bas"], abs=1)
    # Trois ans a +1,5 % par trimestre : la courbe remonte le temps d'autant.
    assert points["2023-Q1"]["valeur"] / points["2025-Q4"]["valeur"] == pytest.approx(
        math.exp(-11 * TENDANCE), rel=0.05)
    assert courbe["variations"]["un_an"] == pytest.approx(math.exp(4 * TENDANCE) - 1, abs=0.03)
    assert all(p["bas"] <= p["valeur"] <= p["haut"] for p in courbe["points"])


def test_l_indice_officiel_prolonge_la_courbe(departement):
    observations = [("PR", "maison", q, i) for q, i in
                    (("2025-Q3", 130.0), ("2025-Q4", 130.6), ("2026-Q1", 129.4), ("2026-Q2", 127.7))]
    with transaction() as conn:
        conn.executemany("INSERT INTO indice_officiel VALUES (?,?,?,?)", observations)
        conn.execute("INSERT INTO source_maj VALUES ('insee', ?, 'essai')",
                     (datetime.datetime.now().isoformat(timespec="seconds"),))
    resultat = estimation.estimer(_bien("99004"), {})
    courbe = resultat["evolution"]
    assert courbe["points"][-1]["trimestre"] == "2026-Q2" == courbe["ancre"]
    assert courbe["points"][-1]["source"] == "insee"
    assert courbe["points"][-1]["valeur"] == pytest.approx(resultat["valeur"], abs=1)


def test_un_critere_date_change_la_forme_de_la_courbe(departement, monkeypatch):
    """Une passoire perdait moins autrefois qu'aujourd'hui : sa valeur passee,
    rapportee a aujourd'hui, est plus haute que celle d'un bien ordinaire.
    Le departement fictif commence en 2023 : on y date l'effet."""
    monkeypatch.setitem(criteres.PROFILS, "passoire", {2023: -0.07})
    ordinaire = estimation.estimer(_bien(), {})["evolution"]["points"]
    passoire = estimation.estimer(_bien(), {"criteres": ["passoire"]})["evolution"]["points"]
    rapport = lambda points: points[0]["valeur"] / points[-1]["valeur"]
    assert rapport(passoire) / rapport(ordinaire) == pytest.approx(0.93 / 0.88, rel=0.01)


def test_la_courbe_porte_les_ventes_et_les_estimations_du_bien(departement):
    revente = next(v for v in departement["ventes"] if v[1].startswith("R"))
    bien = _bien(revente[2], surface=revente[7], terrain=revente[9], parcelle_id=revente[14])
    premiere = estimation.estimer(bien, {})
    ident = estimation.enregistrer(premiere)
    ventes = premiere["evolution"]["ventes"]
    assert [v["date"] for v in ventes][-1] == revente[3] and len(ventes) == 2
    relue = estimation.enregistree(ident)
    courbe = relue["resultat"]["evolution"]
    assert [e["id"] for e in courbe["estimations"]] == [ident]
    assert courbe["estimations"][0]["trimestre"] == premiere["trimestre_de_reference"]


def test_une_estimation_ancienne_retrouve_son_trimestre(departement):
    """Enregistree avant que le trimestre de reference ne soit garde : on le
    deduit de la projection, ou de la fin des donnees."""
    resultat = estimation.estimer(_bien(), {})
    del resultat["trimestre_de_reference"]
    assert estimation._ancre(resultat) == "2025-Q4"
    resultat["projection"] = {"jusqu_a": "2026-Q1"}
    assert estimation._ancre(resultat) == "2026-Q1"


# =====================================================================
#  Le gradient boosting
# =====================================================================
@pytest.mark.parametrize("methode", ["grille", "auto"])
def test_les_voisins_d_un_lot_sont_ceux_de_chaque_point(methode):
    rng = np.random.default_rng(8)
    lat, lon = 44 + rng.random(800) * 0.2, -1 + rng.random(800) * 0.2
    index = Voisinage(lat, lon, methode=methode)
    qlat, qlon = 44 + rng.random(25) * 0.2, -1 + rng.random(25) * 0.2
    indices, distances = index.plus_proches_lot(qlat, qlon, 7)
    assert indices.shape == distances.shape == (25, 7)
    for rang in range(25):
        _, attendues = index.plus_proches(qlat[rang], qlon[rang], 7)
        assert np.allclose(distances[rang], attendues)


def test_le_prix_des_voisines_est_la_mediane_ponderee_des_comparables():
    """Le trait principal du boosting est exactement le calcul des comparables."""
    rng = np.random.default_rng(9)
    pm2 = rng.uniform(1500, 4000, (30, 12))
    distances = rng.uniform(0, 2000, (30, 12))
    surfaces_v = rng.uniform(40, 200, (30, 12))
    surfaces = rng.uniform(40, 200, 30)
    lot = boosting.prix_voisins(pm2, distances, surfaces_v, surfaces)
    for rang in range(30):
        poids = (1 / (1 + distances[rang] / 300)
                 * np.exp(-np.abs(np.log(surfaces_v[rang] / surfaces[rang]))))
        assert lot[rang] == pytest.approx(estimation._mediane_ponderee(pm2[rang], poids))


@pytest.mark.skipif(not boosting.disponible(), reason="LightGBM absent")
def test_le_boosting_est_appris_garde_et_relu(departement):
    assert departement["modele"]["boosting"] == ["appartement", "maison"]
    assert "boosting" in departement["modele"]["precision"]["maison"]["methodes"]
    with connexion() as conn:
        assert conn.execute("SELECT count(*) FROM modele_boosting WHERE departement = ?",
                            (DEP,)).fetchone()[0] == 2
    # Relu de la base, sans re-apprentissage, il predit la meme chose.
    premiere = estimation.estimer(_bien(), {})
    estimation._cache.clear()
    seconde = estimation.estimer(_bien(), {})
    valeur = {m["cle"]: m["valeur"] for m in premiere["methodes"]}["boosting"]
    assert valeur == {m["cle"]: m["valeur"] for m in seconde["methodes"]}["boosting"]
    assert valeur == pytest.approx(
        _valeur_attendue("99004", "maison", 100, 700, datetime.date(2025, 10, 1)), rel=0.25)
    assert estimation.a_reapprendre(DEP) is False


def test_sans_lightgbm_le_croisement_se_fait_sans_lui(departement, monkeypatch):
    monkeypatch.setattr(boosting, "lightgbm", None)
    estimation._cache.clear()
    resultat = estimation.estimer(_bien(), {})
    assert "boosting" not in {m["cle"] for m in resultat["methodes"]}
    assert resultat["valeur"] > 0


def test_un_modele_d_une_version_anterieure_est_re_appris(departement):
    with transaction() as conn:
        ligne = conn.execute("SELECT modele_json FROM modele_estimation WHERE departement = ?",
                             (DEP,)).fetchone()
        ancien = json.loads(ligne["modele_json"])
        ancien["version"] = 1
        conn.execute("UPDATE modele_estimation SET modele_json = ? WHERE departement = ?",
                     (json.dumps(ancien), DEP))
    assert estimation.a_reapprendre(DEP) is True


# =====================================================================
#  Le bilan : les estimations face aux ventes reelles
# =====================================================================
def _vente_apres(parcelle, date, prix, surface, type_bien="maison", ident="VENTE-APRES"):
    with transaction() as conn:
        conn.execute("INSERT INTO vente_reference VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (DEP, ident, "99004", date, "2026-Q4", type_bien, prix, surface, 4, 700, 0, 0,
                      LAT0, LON0, parcelle, "4 rue de l'Essai"))


def test_la_vente_d_un_bien_estime_est_retrouvee(departement):
    resultat = estimation.estimer(_bien(parcelle_id="99004000ZZ0001"), {"etat": "mediocre"})
    ident = estimation.enregistrer(resultat)
    assert estimation.rapprocher(DEP) == 0             # rien de paru encore
    prix = round(resultat["valeur"] * 1.08)
    _vente_apres("99004000ZZ0001", datetime.date.today().isoformat(), prix, 104)
    assert estimation.rapprocher(DEP) == 1
    relue = estimation.enregistree(ident)
    assert relue["vente_prix"] == prix
    assert estimation.rapprocher(DEP) == 0             # deja rapprochee
    bilan = estimation.bilan()
    assert (bilan["estimations"], bilan["vendues"]) == (1, 1)
    assert bilan["erreur_mediane"] == pytest.approx(8, abs=0.1)
    assert bilan["par_etat"]["mediocre"]["ecart_median"] == pytest.approx(8, abs=0.1)
    assert bilan["dans_la_fourchette"] == 100


def test_une_vente_ancienne_ou_d_un_autre_lot_n_est_pas_retenue(departement):
    resultat = estimation.estimer(_bien(type_bien="appartement", surface=50, terrain=0,
                                        parcelle_id="99004000ZZ0002"), {})
    estimation.enregistrer(resultat)
    # Six mois avant l'estimation : c'etait la vente precedente, pas celle-ci.
    ancienne = (datetime.date.today() - datetime.timedelta(days=180)).isoformat()
    _vente_apres("99004000ZZ0002", ancienne, 150000, 50, "appartement", "ANCIENNE")
    # Apres, mais un autre lot de l'immeuble : 70 m² au lieu de 50.
    _vente_apres("99004000ZZ0002", datetime.date.today().isoformat(), 210000, 70, "appartement", "AUTRE")
    assert estimation.rapprocher(DEP) == 0
    assert estimation.bilan()["vendues"] == 0


# =====================================================================
#  Les routes
# =====================================================================
@pytest.fixture()
def client(base):
    with TestClient(application) as c:
        yield c


def test_route_estimer(client, departement):
    corps = {"bien": _bien(), "saisie": {"etat": "bon"}, "enregistrer": True}
    reponse = client.post("/api/estimation", json=corps)
    assert reponse.status_code == 200
    resultat = reponse.json()
    assert resultat["id"] and resultat["valeur"] > 0
    corps_liste = client.get("/api/estimation/enregistrees").json()
    assert [e["id"] for e in corps_liste["estimations"]] == [resultat["id"]]
    assert corps_liste["bilan"] == {"estimations": 1, "vendues": 0}
    assert client.get(f"/api/estimation/enregistrees/{resultat['id']}").status_code == 200
    assert client.delete(f"/api/estimation/enregistrees/{resultat['id']}").status_code == 204
    assert client.get(f"/api/estimation/enregistrees/{resultat['id']}").status_code == 404


def test_route_estimer_refuse_proprement(client, departement):
    assert client.post("/api/estimation", json={"bien": _bien(surface=3)}).status_code == 400
    reponse = client.post("/api/estimation", json={"bien": _bien(code="64445")})
    assert reponse.status_code == 409
    assert "préparé" in reponse.json()["detail"]


def test_route_bien_et_departement(client, base, monkeypatch):
    """Ouvrir l'ecran ne declenche AUCUN appel exterieur (CDC 4)."""
    import urllib.request

    def interdit(*args, **kwargs):
        raise AssertionError("appel exterieur a l'ouverture de l'ecran")
    monkeypatch.setattr(urllib.request, "urlopen", interdit)
    inserer_dpe(n_dpe="DPE-R", code_insee="40184")
    reponse = client.get("/api/estimation/bien?n_dpe=DPE-R")
    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["departement"]["departement"] == "40" and corps["departement"]["pret"] is False
    assert [e["cle"] for e in corps["etats"]][:2] == ["bon", "assez_bon"]
    assert "vue_mer" in {c["cle"] for c in corps["criteres"]}
    assert client.get("/api/estimation/etats").json()["criteres"] == corps["criteres"]
    assert client.get("/api/estimation/bien").status_code == 400
    assert client.get("/api/estimation/bien?n_dpe=ABSENT").status_code == 404


def test_route_preparer(client, monkeypatch):
    lances = []
    monkeypatch.setattr(estimation, "lancer_preparation",
                        lambda dep, forcer=False: lances.append((dep, forcer)))
    assert client.post("/api/estimation/preparer?departement=40").status_code == 202
    assert lances == [("40", False)]
    # Alsace-Moselle : pas de DVF, donc rien a preparer.
    assert client.post("/api/estimation/preparer?departement=67").status_code == 400

    def occupe(dep, forcer=False):
        raise RuntimeError("Une preparation est deja en cours.")
    monkeypatch.setattr(estimation, "lancer_preparation", occupe)
    assert client.post("/api/estimation/preparer?departement=40").status_code == 409
