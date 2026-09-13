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
def trois_etats(base):
    """
    Une parcelle par etat, alignees d'ouest en est.

    P-RIEN est le TEMOIN : elle ne porte ni diagnostic ni vente, et la
    carte ne doit jamais la rendre. Elle existe en base, comme les 9 205
    parcelles muettes de Mimizan ; c'est la reponse de la carte qui les
    tait, pas la moisson qui les oublie.
    """
    _parcelle("P-DEUX", 0)
    _parcelle("P-DPE", 1)
    _parcelle("P-VENTE", 2)
    _parcelle("P-RIEN", 3)
    _dpe("D1", "P-DEUX")
    _vente("M1", "P-DEUX")
    _dpe("D2", "P-DPE")
    _vente("M2", "P-VENTE")


def test_les_trois_etats_se_distinguent(trois_etats):
    """
    Trois etats, et un quatrieme cas qui n'en est pas un : ne rien
    savoir. La carte le traite par l'absence, pas par une couleur.
    """
    cadre = (LON - 0.01, LAT - 0.01, LON + 0.01, LAT + 0.01)
    par_id = {p["id"]: p for p in parcelles.pour_carte("40184", cadre)["parcelles"]}

    assert (par_id["P-DEUX"]["dpe"], par_id["P-DEUX"]["ventes"]) == (1, 1)
    assert (par_id["P-DPE"]["dpe"], par_id["P-DPE"]["ventes"]) == (1, 0)
    assert (par_id["P-VENTE"]["dpe"], par_id["P-VENTE"]["ventes"]) == (0, 1)
    # Le voile blanc n'existe plus : elle n'est pas envoyee du tout.
    assert "P-RIEN" not in par_id
    # De quoi ouvrir la fiche depuis la carte.
    assert par_id["P-DEUX"]["n_dpe"] == "D1"


def test_seul_le_cadre_demande_est_renvoye(trois_etats):
    """
    L'invariant qui rend la carte utilisable. Un cadre serre sur la
    premiere parcelle ne doit pas ramener les trois autres.
    """
    cadre = (LON - 0.0002, LAT - 0.0002, LON + COTE + 0.0002, LAT + COTE + 0.0002)
    resultat = parcelles.pour_carte("40184", cadre)
    assert {p["id"] for p in resultat["parcelles"]} == {"P-DEUX"}
    assert resultat["tronque"] is False


def test_une_parcelle_a_cheval_sur_le_bord_est_incluse(trois_etats):
    """Sinon les parcelles disparaitraient au bord de l'ecran."""
    # Un cadre qui ne mord que sur la moitie ouest de P-DPE.
    x = LON + COTE * 2
    cadre = (x + COTE / 2, LAT, x + COTE * 3, LAT + COTE)
    trouvees = {p["id"] for p in parcelles.pour_carte("40184", cadre)["parcelles"]}
    assert "P-DPE" in trouvees


def test_le_trop_plein_est_annonce(trois_etats):
    """Mieux vaut demander de zoomer que rendre une bouillie de polygones."""
    cadre = (LON - 0.01, LAT - 0.01, LON + 0.01, LAT + 0.01)
    resultat = parcelles.pour_carte("40184", cadre, limite=2)
    assert len(resultat["parcelles"]) == 2
    assert resultat["tronque"] is True
    # Si le plafond mord, il mord sur les ventes seules : un diagnostic
    # est ce qu'on vient chercher ici.
    assert {p["id"] for p in resultat["parcelles"]} == {"P-DEUX", "P-DPE"}


def test_une_autre_commune_ne_deborde_pas(trois_etats):
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

def test_l_extrait_s_ouvre_par_la_parcelle(trois_etats):
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


def test_les_deux_chemins_donnent_le_meme_extrait(trois_etats):
    """Par le DPE ou par la parcelle, c'est le meme terrain."""
    par_dpe = parcelles.extrait("D1")
    par_parcelle = parcelles.extrait_parcelle("P-DEUX")
    assert par_dpe["parcelle"]["id"] == par_parcelle["parcelle"]["id"]
    assert par_dpe["cadre"] == par_parcelle["cadre"]


def test_une_parcelle_inconnue_ne_fait_pas_tomber(base):
    assert parcelles.parcelle("N-EXISTE-PAS") is None
    assert parcelles.extrait_parcelle("N-EXISTE-PAS") is None


def test_la_fiche_d_une_parcelle_rassemble_tout(client_carte, trois_etats):
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


# ---------------------------------------------------------------------
#  Cliquer n'importe ou sur la carte
# ---------------------------------------------------------------------

def test_on_retrouve_la_parcelle_sous_un_point(trois_etats):
    """
    Toute parcelle doit rester consultable, meme celle dont on ne sait
    RIEN — c'est souvent la question qu'on se pose devant la carte :
    « qu'est-ce que c'est, ce terrain-la ? »

    Tant que les parcelles muettes etaient peintes en voile blanc, elles
    offraient une surface au clic. En cessant de les envoyer — 80 % de la
    carte pour ne rien dire — on leur a retire cette surface. C'est donc
    le serveur qui repond, au clic, et il repond pour TOUTES.
    """
    # P-RIEN ne porte ni diagnostic ni vente : la carte ne la dessine plus.
    cadre = (LON - 0.01, LAT - 0.01, LON + 0.01, LAT + 0.01)
    rendues = {p["id"] for p in parcelles.pour_carte("40184", cadre)["parcelles"]}
    assert "P-RIEN" not in rendues

    # Elle reste pourtant joignable par sa position.
    x = LON + 3 * COTE * 2                  # l'abscisse de P-RIEN (indice 3)
    trouvee = parcelles.a_la_position("40184", LAT + COTE / 2, x + COTE / 2)
    assert trouvee == "P-RIEN"

    # Et celles qui sont dessinees repondent aussi bien.
    assert parcelles.a_la_position(
        "40184", LAT + COTE / 2, LON + COTE / 2) == "P-DEUX"


def test_un_point_hors_de_toute_parcelle_ne_rend_rien(trois_etats):
    """Cliquer sur une route ou un lac n'est pas une erreur."""
    assert parcelles.a_la_position("40184", LAT + 5, LON + 5) is None
    # Une position illisible non plus.
    assert parcelles.a_la_position("40184", None, LON) is None


def test_une_autre_commune_ne_repond_pas_a_la_place(trois_etats):
    """Le code INSEE borne la recherche : deux communes se touchent."""
    _parcelle("AILLEURS", 0, code_insee="31282")
    assert parcelles.a_la_position("31282", LAT + COTE / 2, LON + COTE / 2) == "AILLEURS"
    assert parcelles.a_la_position("40184", LAT + COTE / 2, LON + COTE / 2) == "P-DEUX"


def test_la_route_http_repond_toujours(client_carte, trois_etats):
    """Ne rien trouver se dit par une reponse vide, pas par une erreur."""
    x = LON + 3 * COTE * 2
    reponse = client_carte.get("/api/parcelles/a-la-position", params={
        "code_insee": "40184", "latitude": LAT + COTE / 2, "longitude": x + COTE / 2})
    assert reponse.status_code == 200
    assert reponse.json()["parcelle_id"] == "P-RIEN"

    vide = client_carte.get("/api/parcelles/a-la-position", params={
        "code_insee": "40184", "latitude": LAT + 5, "longitude": LON + 5})
    assert vide.status_code == 200 and vide.json()["parcelle_id"] is None

    assert client_carte.get("/api/parcelles/a-la-position", params={
        "code_insee": "40184", "latitude": 91, "longitude": 0}).status_code == 422
