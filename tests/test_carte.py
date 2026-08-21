# -*- coding: utf-8 -*-
"""
test_carte.py — La carte d'exploration.

Deux invariants la gouvernent :

  - elle ne renvoie QUE le cadre demande. Les 11 444 parcelles de Mimizan
    pesent 3,8 Mo ; les envoyer d'un bloc rendrait la carte inutilisable ;
  - les quatre etats se lisent du croisement DPE x vente, et c'est ce
    croisement qui informe.
"""

import json

import pytest

from app.base.connexion import transaction
from app.metier import parcelles
from tests.conftest import inserer_dpe

LAT, LON, COTE = 44.20, -1.23, 0.0009


@pytest.fixture()
def client_carte(base):
    from fastapi.testclient import TestClient

    from app.main import application
    with TestClient(application) as c:
        yield c


def _parcelle(identifiant, indice=0, code_insee="40184"):
    """Une parcelle carree, decalee de `indice` cases vers l'est."""
    x = LON + indice * COTE * 2
    anneau = [[x, LAT], [x + COTE, LAT], [x + COTE, LAT + COTE],
              [x, LAT + COTE], [x, LAT]]
    with transaction() as conn:
        conn.execute(
            "INSERT INTO parcelle (id, code_insee, section, numero, contenance_m2,"
            "  emprise_batie_m2, nb_batiments, latitude, longitude,"
            "  lat_min, lat_max, lon_min, lon_max, geometrie_json, importe_le)"
            " VALUES (?,?,?,?,800,120,1,?,?,?,?,?,?,?,'2026-08-21T10:00:00')",
            (identifiant, code_insee, "AT", identifiant[-3:],
             LAT + COTE / 2, x + COTE / 2, LAT, LAT + COTE, x, x + COTE,
             json.dumps({"type": "Polygon", "coordinates": [anneau]})))
    return x


def _vente(identifiant, parcelle_id, code_insee="40184"):
    with transaction() as conn:
        conn.execute(
            "INSERT INTO mutation (id, code_insee, date_mutation, nature,"
            "  valeur_fonciere, nb_parcelles, nb_locaux, importe_le)"
            " VALUES (?,?,'2024-11-04','Vente',261030,1,1,'2026-08-21T10:00:00')",
            (identifiant, code_insee))
        conn.execute("INSERT INTO mutation_parcelle (mutation_id, parcelle_id)"
                     " VALUES (?,?)", (identifiant, parcelle_id))


def _dpe(n_dpe, parcelle_id):
    inserer_dpe(n_dpe=n_dpe, adresse=f"{n_dpe} rue", code_insee="40184")
    with transaction() as conn:
        conn.execute("UPDATE dpe SET parcelle_id = ? WHERE n_dpe = ?",
                     (parcelle_id, n_dpe))


@pytest.fixture()
def quatre_etats(base):
    """Une parcelle par etat, alignees d'ouest en est."""
    _parcelle("P-DEUX", 0)
    _parcelle("P-DPE", 1)
    _parcelle("P-VENTE", 2)
    _parcelle("P-RIEN", 3)
    _dpe("D1", "P-DEUX")
    _vente("M1", "P-DEUX")
    _dpe("D2", "P-DPE")
    _vente("M2", "P-VENTE")


def test_les_quatre_etats_se_distinguent(quatre_etats):
    cadre = (LON - 0.01, LAT - 0.01, LON + 0.01, LAT + 0.01)
    par_id = {p["id"]: p for p in parcelles.pour_carte("40184", cadre)["parcelles"]}

    assert (par_id["P-DEUX"]["dpe"], par_id["P-DEUX"]["ventes"]) == (1, 1)
    assert (par_id["P-DPE"]["dpe"], par_id["P-DPE"]["ventes"]) == (1, 0)
    assert (par_id["P-VENTE"]["dpe"], par_id["P-VENTE"]["ventes"]) == (0, 1)
    assert (par_id["P-RIEN"]["dpe"], par_id["P-RIEN"]["ventes"]) == (0, 0)
    # De quoi ouvrir la fiche depuis la carte.
    assert par_id["P-DEUX"]["n_dpe"] == "D1"
    assert par_id["P-RIEN"]["n_dpe"] is None


def test_seul_le_cadre_demande_est_renvoye(quatre_etats):
    """
    L'invariant qui rend la carte utilisable. Un cadre serre sur la
    premiere parcelle ne doit pas ramener les trois autres.
    """
    cadre = (LON - 0.0002, LAT - 0.0002, LON + COTE + 0.0002, LAT + COTE + 0.0002)
    resultat = parcelles.pour_carte("40184", cadre)
    assert {p["id"] for p in resultat["parcelles"]} == {"P-DEUX"}
    assert resultat["tronque"] is False


def test_une_parcelle_a_cheval_sur_le_bord_est_incluse(quatre_etats):
    """Sinon les parcelles disparaitraient au bord de l'ecran."""
    # Un cadre qui ne mord que sur la moitie ouest de P-DPE.
    x = LON + COTE * 2
    cadre = (x + COTE / 2, LAT, x + COTE * 3, LAT + COTE)
    trouvees = {p["id"] for p in parcelles.pour_carte("40184", cadre)["parcelles"]}
    assert "P-DPE" in trouvees


def test_le_trop_plein_est_annonce(quatre_etats):
    """Mieux vaut demander de zoomer que rendre une bouillie de polygones."""
    cadre = (LON - 0.01, LAT - 0.01, LON + 0.01, LAT + 0.01)
    resultat = parcelles.pour_carte("40184", cadre, limite=2)
    assert len(resultat["parcelles"]) == 2
    assert resultat["tronque"] is True
    # Les parcelles renseignees passent d'abord : tronquer ne doit pas
    # faire disparaitre celles qui portent l'information.
    assert "P-RIEN" not in {p["id"] for p in resultat["parcelles"]}


def test_une_autre_commune_ne_deborde_pas(quatre_etats):
    _parcelle("AILLEURS", 0, code_insee="31282")
    cadre = (LON - 0.01, LAT - 0.01, LON + 0.01, LAT + 0.01)
    trouvees = {p["id"] for p in parcelles.pour_carte("40184", cadre)["parcelles"]}
    assert "AILLEURS" not in trouvees


# ---------------------------------------------------------------------
#  Recherche : une adresse, ou une reference cadastrale
# ---------------------------------------------------------------------

def test_la_recherche_accepte_les_deux_ecritures_du_numero(base):
    """
    La colonne garde le numero sans zeros (« 148 ») quand l'identifiant
    les porte (« AT0148 ») — et c'est l'identifiant que la fiche affiche.
    Les deux doivent mener au meme endroit.
    """
    with transaction() as conn:
        conn.execute(
            "INSERT INTO parcelle (id, code_insee, section, numero, contenance_m2,"
            "  emprise_batie_m2, nb_batiments, latitude, longitude, importe_le)"
            " VALUES ('40184000AT0148','40184','AT','148',800,120,1,44.2,-1.23,"
            "         '2026-08-21T10:00:00')")

    for saisie in ("AT148", "AT0148", "at 148", "40184000AT0148"):
        resultats = parcelles.chercher_sur_carte("40184", saisie)
        assert resultats, f"{saisie!r} devrait trouver la parcelle"
        assert resultats[0]["parcelle_id"] == "40184000AT0148"


def test_la_recherche_trouve_une_adresse(base):
    inserer_dpe(n_dpe="D1", adresse="53 Chemin des Roseaux 40200 Mimizan",
                code_insee="40184", latitude=44.205, longitude=-1.232)
    resultats = parcelles.chercher_sur_carte("40184", "roseaux")
    assert len(resultats) == 1
    assert resultats[0]["type"] == "adresse"
    assert resultats[0]["latitude"] == pytest.approx(44.205)


def test_une_recherche_trop_courte_ne_renvoie_rien(base):
    assert parcelles.chercher_sur_carte("40184", "a") == []
    assert parcelles.chercher_sur_carte("40184", "") == []


def test_une_adresse_sans_position_est_ecartee(base):
    """Sans coordonnees, on ne saurait ou aller."""
    inserer_dpe(n_dpe="D1", adresse="53 Chemin des Roseaux", code_insee="40184",
                latitude=None, longitude=None)
    assert parcelles.chercher_sur_carte("40184", "roseaux") == []


# ---------------------------------------------------------------------
#  Ouvrir une parcelle depuis la carte
# ---------------------------------------------------------------------

def test_l_extrait_s_ouvre_par_la_parcelle(quatre_etats):
    """
    Le chemin de la carte. La plupart des parcelles ne portent aucun DPE —
    468 sur 550 dans une vue courante de Mimizan — et cliquer dessus doit
    mener quelque part.
    """
    # Les parcelles du fixture sont espacees de ~100 m, au-dela de la marge
    # de l'extrait : on en colle une contre P-RIEN pour que le voisinage
    # ait de quoi se peupler.
    _parcelle("P-MITOYENNE", 3.5)

    extrait = parcelles.extrait_parcelle("P-RIEN")
    assert extrait is not None
    assert extrait["parcelle"]["id"] == "P-RIEN"
    # Le voisinage est ce qui donne l'echelle : il doit etre la aussi.
    voisines = {v["id"] for v in extrait["voisines"]}
    assert "P-MITOYENNE" in voisines
    assert "P-RIEN" not in voisines


def test_les_deux_chemins_donnent_le_meme_extrait(quatre_etats):
    """Par le DPE ou par la parcelle, c'est le meme terrain."""
    par_dpe = parcelles.extrait("D1")
    par_parcelle = parcelles.extrait_parcelle("P-DEUX")
    assert par_dpe["parcelle"]["id"] == par_parcelle["parcelle"]["id"]
    assert par_dpe["cadre"] == par_parcelle["cadre"]


def test_une_parcelle_inconnue_ne_fait_pas_tomber(base):
    assert parcelles.parcelle("N-EXISTE-PAS") is None
    assert parcelles.extrait_parcelle("N-EXISTE-PAS") is None


def test_la_fiche_d_une_parcelle_rassemble_tout(client_carte, quatre_etats):
    """Contour, voisinage, bati et ventes en une seule reponse."""
    corps = client_carte.get("/api/parcelles/fiche-parcelle",
                             params={"parcelle_id": "P-VENTE"}).json()
    assert corps["parcelle"]["id"] == "P-VENTE"
    assert corps["extrait"]["parcelle"]["id"] == "P-VENTE"
    assert len(corps["ventes"]) == 1
    assert corps["ventes"][0]["valeur_fonciere"] == 261030

    # Une parcelle nue repond aussi : c'est la carte d'identite du terrain.
    nue = client_carte.get("/api/parcelles/fiche-parcelle",
                           params={"parcelle_id": "P-RIEN"}).json()
    assert nue["ventes"] == []
    assert nue["extrait"] is not None

    manquante = client_carte.get("/api/parcelles/fiche-parcelle",
                                 params={"parcelle_id": "AUCUNE"})
    assert manquante.status_code == 404
