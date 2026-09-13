# -*- coding: utf-8 -*-
"""
F3 — recherche cadastrale et recoupement avec les DPE.

Aucun appel reseau : les parcelles sont injectees directement.
"""

import json
import math

import pytest

from app.base.connexion import connexion, transaction
from app.metier import parcelles
from app.sources import ademe
from tests.conftest import inserer_dpe

LAT, LON = 43.6600, 1.4400            # Launaguet
COTE = 0.0009                          # ~100 m


def carre(indice):
    """
    Un carre de ~100 m, decale de `indice` cases vers l'est.

    Le pas vaut deux cotes : les parcelles du fixture sont donc separees
    par ~72 m de vide, et aucune n'est mitoyenne d'une autre. Un demi-pas
    (indice=1.5) colle en revanche une parcelle contre le bord est de la
    precedente.
    """
    x = LON + indice * COTE * 2
    return [[x, LAT], [x + COTE, LAT], [x + COTE, LAT + COTE], [x, LAT + COTE], [x, LAT]]


def inserer_parcelle(identifiant, indice=0, code_insee="31282", contenance=800.0,
                     emprise=120.0, batiments=1):
    anneau = carre(indice)
    longitude = sum(p[0] for p in anneau[:-1]) / 4
    latitude = sum(p[1] for p in anneau[:-1]) / 4
    with transaction() as conn:
        conn.execute(
            "INSERT INTO parcelle (id, code_insee, section, numero, contenance_m2, "
            "  emprise_batie_m2, nb_batiments, latitude, longitude, "
            "  lat_min, lat_max, lon_min, lon_max, geometrie_json, importe_le) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (identifiant, code_insee, "AA", identifiant[-3:], contenance, emprise,
             batiments, latitude, longitude, LAT, LAT + COTE,
             anneau[0][0], anneau[1][0],
             json.dumps({"type": "Polygon", "coordinates": [anneau]}),
             "2026-08-20T10:00:00"))
    return {"id": identifiant, "centre": (longitude, latitude)}


@pytest.fixture()
def cadastre(base):
    """Trois parcelles : une petite, une au gabarit, une trop grande."""
    inserer_parcelle("P-PETITE", indice=0, contenance=250.0, emprise=90.0)
    inserer_parcelle("P-BONNE", indice=1, contenance=800.0, emprise=120.0)
    inserer_parcelle("P-GRANDE", indice=2, contenance=50_000.0, emprise=0.0, batiments=0)






# ---------------------------------------------------------------------
#  Recoupement avec les DPE (CDC F3)
# ---------------------------------------------------------------------

def test_recoupement_dpe_parcelle(cadastre):
    """
    « Une adresse presente dans deux modules est un candidat quasi
    certain » (CDC F3) : la parcelle porte le compte de ses DPE et la date
    du plus recent.

    L'invariant portait sur la recherche par filtres, retiree avec l'ecran
    « Chercher par le terrain ». Il vaut toujours, et se verifie sur le
    chemin qui subsiste : celui de la carte.
    """
    inserer_dpe(n_dpe="D1", adresse="1 rue", code_insee="31282",
                date_etablissement="2026-08-01")
    inserer_dpe(n_dpe="D2", adresse="2 rue", code_insee="31282",
                date_etablissement="2026-05-01")
    with transaction() as conn:
        conn.execute("UPDATE dpe SET parcelle_id = 'P-BONNE' WHERE n_dpe IN ('D1','D2')")

    cadre = (LON - 0.01, LAT - 0.01, LON + 0.02, LAT + 0.01)
    par_id = {p["id"]: p for p in parcelles.pour_carte("31282", cadre)["parcelles"]}
    assert par_id["P-BONNE"]["dpe"] == 2
    assert par_id["P-BONNE"]["dpe_dernier"] == "2026-08-01"
    # La voisine ne recupere rien — et comme elle ne porte rien, la carte
    # ne la rend meme pas.
    assert "P-PETITE" not in par_id

def test_rattachement_par_la_geometrie(cadastre):
    """
    Un DPE tombe dans la parcelle qui le contient, pas dans sa voisine —
    c'est l'index spatial qui tranche.
    """
    centre_bonne = (LON + COTE * 2 + COTE / 2, LAT + COTE / 2)
    inserer_dpe(n_dpe="DEDANS", adresse="1 rue", code_insee="31282",
                longitude=centre_bonne[0], latitude=centre_bonne[1])
    inserer_dpe(n_dpe="AILLEURS", adresse="2 rue", code_insee="31282",
                longitude=LON + 0.5, latitude=LAT + 0.5)

    assert parcelles.rattacher_dpe("31282") == 1

    from app.base.connexion import connexion
    with connexion() as conn:
        lignes = dict(conn.execute(
            "SELECT n_dpe, parcelle_id FROM dpe").fetchall())
    assert lignes["DEDANS"] == "P-BONNE"
    assert lignes["AILLEURS"] is None


def test_le_rattachement_ne_refait_pas_le_travail(cadastre):
    centre_bonne = (LON + COTE * 2 + COTE / 2, LAT + COTE / 2)
    inserer_dpe(n_dpe="D1", adresse="1 rue", code_insee="31282",
                longitude=centre_bonne[0], latitude=centre_bonne[1])
    assert parcelles.rattacher_dpe("31282") == 1
    assert parcelles.rattacher_dpe("31282") == 0        # deja rattache
    assert parcelles.rattacher_dpe("31282", tous=True) == 1


def test_parcelle_d_un_dpe_pour_la_fiche(cadastre):
    inserer_dpe(n_dpe="D1", adresse="1 rue", code_insee="31282")
    with transaction() as conn:
        conn.execute("UPDATE dpe SET parcelle_id = 'P-BONNE' WHERE n_dpe = 'D1'")

    parcelle = parcelles.parcelle_de("D1")
    assert parcelle["id"] == "P-BONNE"
    assert parcelle["geometrie"]["type"] == "Polygon"
    assert parcelles.parcelle_de("INCONNU") is None




# ---------------------------------------------------------------------
#  Extrait cadastral : parcelle, voisines et bati
# ---------------------------------------------------------------------

def inserer_batiment(identifiant, indice, parcelle_id=None, type_bati="01",
                     surface=100.0, code_insee="31282"):
    anneau = carre(indice)
    with transaction() as conn:
        conn.execute(
            "INSERT INTO batiment (code_insee, parcelle_id, type, surface_m2, "
            "  lat_min, lat_max, lon_min, lon_max, geometrie_json, importe_le) "
            "VALUES (?,?,?,?,?,?,?,?,?,'2026-08-20T10:00:00')",
            (code_insee, parcelle_id, type_bati, surface,
             LAT, LAT + COTE, anneau[0][0], anneau[1][0],
             json.dumps({"type": "Polygon", "coordinates": [anneau]})))


def test_extrait_ramene_le_voisinage(cadastre):
    """
    Une parcelle seule ne se lit pas : c'est le voisinage qui donne
    l'echelle, et le bati qui montre ce qui est construit.
    """
    inserer_parcelle("P-MITOYENNE", indice=1.5)      # colle au bord est
    inserer_dpe(n_dpe="D1", adresse="1 rue", code_insee="31282")
    with transaction() as conn:
        conn.execute("UPDATE dpe SET parcelle_id = 'P-BONNE' WHERE n_dpe = 'D1'")
    inserer_batiment("B1", indice=1, parcelle_id="P-BONNE")
    inserer_batiment("B2", indice=1.5, parcelle_id="P-MITOYENNE",
                     type_bati="02", surface=9.0)

    resultat = parcelles.extrait("D1")
    assert resultat["parcelle"]["id"] == "P-BONNE"

    # La mitoyenne est la, la parcelle elle-meme n'y est pas, et les
    # lointaines (72 m de vide, pour 35 m de marge) restent dehors.
    voisines = {v["id"] for v in resultat["voisines"]}
    assert "P-MITOYENNE" in voisines
    assert "P-BONNE" not in voisines
    assert voisines.isdisjoint({"P-PETITE", "P-GRANDE"})

    par_parcelle = {b["parcelle_id"]: b for b in resultat["batiments"]}
    assert par_parcelle["P-BONNE"]["sur_la_parcelle"] is True
    assert par_parcelle["P-MITOYENNE"]["sur_la_parcelle"] is False
    # Le type distingue le bati dur du bati leger : a Launaguet, 10 m2 de
    # mediane pour le leger contre 129 pour le dur.
    assert par_parcelle["P-MITOYENNE"]["type"] == "02"


def test_extrait_sans_parcelle(base):
    inserer_dpe(n_dpe="D1", adresse="1 rue", code_insee="31282")
    assert parcelles.extrait("D1") is None


def test_le_cadre_deborde_la_parcelle(cadastre):
    """Sans marge, la parcelle toucherait les bords et le voisinage
    disparaitrait."""
    inserer_dpe(n_dpe="D1", adresse="1 rue", code_insee="31282")
    with transaction() as conn:
        conn.execute("UPDATE dpe SET parcelle_id = 'P-BONNE' WHERE n_dpe = 'D1'")

    resultat = parcelles.extrait("D1")
    cadre, parcelle = resultat["cadre"], resultat["parcelle"]
    assert cadre["lat_min"] < parcelle["lat_min"]
    assert cadre["lat_max"] > parcelle["lat_max"]
    assert cadre["lon_min"] < parcelle["lon_min"]
    assert cadre["lon_max"] > parcelle["lon_max"]


def test_cadastre_sans_batiments_est_a_refaire(cadastre):
    """
    Les cadastres importes avant que les contours ne soient conserves n'ont
    que des parcelles : la fiche ne peut rien dessiner dessus.
    """
    assert parcelles.batiments_manquants("31282") is True
    inserer_batiment("B1", indice=1, parcelle_id="P-BONNE")
    assert parcelles.batiments_manquants("31282") is False


def test_une_commune_sans_cadastre_n_est_pas_incomplete(base):
    assert parcelles.batiments_manquants("31282") is False


def test_une_commune_sans_bati_n_est_pas_incomplete(base):
    """
    Foret et labours : aucun batiment n'est attendu. La signaler
    « incomplete » la ferait retelecharger a chaque recherche, sans fin.
    """
    inserer_parcelle("BOIS", indice=0, batiments=0, emprise=0.0)
    inserer_parcelle("CHAMP", indice=1, batiments=0, emprise=0.0)
    assert parcelles.batiments_manquants("31282") is False


def test_extrait_signale_un_import_sans_bati(cadastre):
    """
    Le piege du cadastre incomplet : parcelles et voisines se dessinent,
    l'extrait parait donc complet, mais aucun bati ne s'affiche.

    Sans ce drapeau la fiche n'a aucun moyen de distinguer ce cas d'une
    commune sans construction, et ne peut donc pas proposer de le
    completer : le bati manque en silence, sans issue.
    """
    inserer_dpe(n_dpe="D1", adresse="1 rue", code_insee="31282")
    with transaction() as conn:
        conn.execute("UPDATE dpe SET parcelle_id = 'P-BONNE' WHERE n_dpe = 'D1'")

    resultat = parcelles.extrait("D1")
    assert resultat["batiments"] == []
    assert resultat["batiments_manquants"] is True

    # Une fois les contours repris, l'extrait ne reclame plus rien.
    inserer_batiment("B1", indice=1, parcelle_id="P-BONNE")
    assert parcelles.extrait("D1")["batiments_manquants"] is False


def _parcelle_a(identifiant, latitude, longitude, cote=COTE, code_insee="40184"):
    """Une parcelle carree centree sur un point precis, pour eprouver le
    rattachement d'un DPE dont on connait les coordonnees reelles."""
    lat0, lon0 = latitude - cote / 2, longitude - cote / 2
    anneau = [[lon0, lat0], [lon0 + cote, lat0], [lon0 + cote, lat0 + cote],
              [lon0, lat0 + cote], [lon0, lat0]]
    with transaction() as conn:
        conn.execute(
            "INSERT INTO parcelle (id, code_insee, section, numero, contenance_m2,"
            "  emprise_batie_m2, nb_batiments, latitude, longitude,"
            "  lat_min, lat_max, lon_min, lon_max, geometrie_json, importe_le)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (identifiant, code_insee, "ZZ", identifiant[-4:], 800.0, 120.0, 1,
             latitude, longitude, lat0, lat0 + cote, lon0, lon0 + cote,
             json.dumps({"type": "Polygon", "coordinates": [anneau]}),
             "2026-09-01T10:00:00"))
    return identifiant


def test_un_dpe_arrive_apres_le_cadastre_est_rattache(base, monkeypatch):
    """
    Le defaut le plus sournois rencontre : un DPE arrive apres le dernier
    import du cadastre restait ORPHELIN — `parcelle_id` a NULL.

    Rien n'echouait. La ligne etait bien en base, visible dans la liste et
    sur la carte de la veille, qui travaillent sur ses coordonnees. Mais
    elle disparaissait de la carte d'exploration, qui joint les DPE aux
    parcelles par cette clef, et sa fiche perdait son historique de
    ventes, qui passe par la meme parcelle.

    Constate sur Mimizan le 10/09/2026 : le DPE le plus recent rattache a
    une parcelle datait du 30 juin — deux mois et demi de moisson
    quotidienne restee sans lien.
    """
    from app.metier import import_dpe, parcelles as metier_parcelles

    parcelle = _parcelle_a("40184000ZZ0001", 44.2177, -1.2968)

    correspondances = {c: c for c in ademe.CONCEPTS}
    monkeypatch.setattr("app.sources.ademe.preparer",
                        lambda jeu="existant": (correspondances, []))
    monkeypatch.setattr("app.sources.ademe.orphelins", lambda *a, **k: [])
    monkeypatch.setattr(
        "app.sources.ademe.telecharger",
        lambda code_insee, corr, jeu="existant", progression=None, champs=None:
            [{"numero_dpe": "NEUF-1", "code_insee": "40184",
              "date": "2026-09-02", "adresse": "25 Avenue de la Côte d'Argent",
              "commune": "Mimizan", "surface": 286.5, "type_batiment": "maison",
              "etiquette_dpe": "E", "geopoint": "44.2177,-1.2968"}]
            if jeu == "existant" else [])

    import_dpe.importer_commune("40184", declencheur="test", avec_cadastre=False)

    with connexion() as conn:
        ligne = conn.execute(
            "SELECT parcelle_id, latitude FROM dpe WHERE n_dpe = 'NEUF-1'").fetchone()
    assert ligne is not None, "le DPE n'est pas entre en base"
    assert ligne["latitude"] is not None
    assert ligne["parcelle_id"] == "40184000ZZ0001", (
        "le DPE est orphelin : il manquera a la carte d'exploration et son "
        "historique de ventes sera vide")


def test_la_carte_d_exploration_montre_le_dpe_du_jour(base, monkeypatch):
    """Le symptome tel que l'utilisateur le voit : la parcelle doit
    s'allumer sur la carte d'exploration."""
    from app.metier import import_dpe, parcelles as metier_parcelles

    _parcelle_a("40184000ZZ0002", 44.2177, -1.2968)
    correspondances = {c: c for c in ademe.CONCEPTS}
    monkeypatch.setattr("app.sources.ademe.preparer",
                        lambda jeu="existant": (correspondances, []))
    monkeypatch.setattr("app.sources.ademe.orphelins", lambda *a, **k: [])
    monkeypatch.setattr(
        "app.sources.ademe.telecharger",
        lambda code_insee, corr, jeu="existant", progression=None, champs=None:
            [{"numero_dpe": "NEUF-2", "code_insee": "40184",
              "date": "2026-09-02", "adresse": "25 Avenue de la Côte d'Argent",
              "commune": "Mimizan", "surface": 286.5, "type_batiment": "maison",
              "etiquette_dpe": "E", "geopoint": "44.2177,-1.2968"}]
            if jeu == "existant" else [])

    import_dpe.importer_commune("40184", declencheur="test", avec_cadastre=False)

    carte = metier_parcelles.pour_carte(
        "40184", (-1.2988, 44.2157, -1.2948, 44.2197))
    visees = [p for p in carte["parcelles"] if p["id"] == "40184000ZZ0002"]
    assert visees, "la parcelle n'est pas dans le cadre"
    assert visees[0]["dpe"] >= 1, (
        "la parcelle reste eteinte sur la carte d'exploration")


# ---------------------------------------------------------------------
#  Le plan de requete de la carte
# ---------------------------------------------------------------------

def test_la_carte_garde_ses_index(base):
    """
    Une coloration instantanee tient a DEUX index : celui du cadre, et
    celui des diagnostics par parcelle. Ecrire le calcul en clair dans la
    jointure — `coalesce(d.parcelle_id, d.parcelle_approchee) = p.id` —
    rend le predicat non indexable, et SQLite abandonne alors les deux :

        SEARCH p USING INDEX idx_parcelle_cadre      ->  SCAN p
        SEARCH d USING INDEX idx_dpe_parcelle        ->  SCAN d

    soit 11 444 parcelles x 4 382 diagnostics pour un rafraichissement.
    Mesure : 8 ms avant, 266 ms apres, 8 ms une fois la colonne generee
    `parcelle_carte` indexee en place.

    Rien n'echoue quand cela se reproduit — c'est seulement lent, et la
    lenteur ne fait pas rougir une suite de tests. D'ou ce garde, qui lit
    le plan lui-meme.
    """
    from app.base.connexion import connexion

    sql = ("SELECT p.id, count(DISTINCT d.n_dpe)"
           "  FROM parcelle p"
           "  LEFT JOIN dpe d ON d.parcelle_carte = p.id"
           "  LEFT JOIN mutation_parcelle mp ON mp.parcelle_id = p.id"
           " WHERE p.code_insee = ?"
           "   AND p.lat_max >= ? AND p.lat_min <= ?"
           "   AND p.lon_max >= ? AND p.lon_min <= ?"
           " GROUP BY p.id")
    with connexion() as conn:
        plan = [ligne[-1] for ligne in conn.execute(
            "EXPLAIN QUERY PLAN " + sql, ("40184", 0, 90, -10, 10))]

    lisible = "\n".join(plan)
    assert any("idx_parcelle_cadre" in etape for etape in plan), (
        "le cadre de la carte doit passer par son index :\n" + lisible)
    assert any("idx_dpe_parcelle_carte" in etape for etape in plan), (
        "les diagnostics doivent passer par l'index de parcelle_carte :\n" + lisible)
    assert not any(etape.startswith("SCAN d") for etape in plan), (
        "la table des diagnostics est parcourue en entier :\n" + lisible)


def test_la_parcelle_de_carte_prefere_l_exacte(base):
    """La colonne generee : l'appartenance d'abord, l'approche a defaut."""
    from app.base.connexion import connexion, transaction

    inserer_dpe(n_dpe="EXACT", adresse="1 rue")
    inserer_dpe(n_dpe="APPROCHE", adresse="2 rue")
    inserer_dpe(n_dpe="AUCUNE", adresse="3 rue")
    with transaction() as conn:
        conn.execute("UPDATE dpe SET parcelle_id = 'P1', parcelle_approchee = 'P9'"
                     " WHERE n_dpe = 'EXACT'")
        conn.execute("UPDATE dpe SET parcelle_approchee = 'P2' WHERE n_dpe = 'APPROCHE'")

    with connexion() as conn:
        carte = dict(conn.execute(
            "SELECT n_dpe, parcelle_carte FROM dpe").fetchall())
    assert carte == {"EXACT": "P1", "APPROCHE": "P2", "AUCUNE": None}


def test_les_coordonnees_partent_arrondies(base):
    """
    `json.dumps` ecrit un flottant avec seize chiffres significatifs —
    « -1.2426787850467291 ». Six decimales valent ~11 cm, bien au-dela de
    ce qu'un contour affiche a l'ecran peut rendre : le reste etait 28 %
    du poids de la reponse envoye en decimales invisibles.

    Mesure sur un cadre de quartier : 357 Ko avant, 268 Ko apres.
    """
    import json
    from app.base.connexion import transaction
    from app.metier import parcelles as metier_parcelles

    contour = [[-1.2426787850467291, 44.19587560747664],
               [-1.2416787850467291, 44.19587560747664],
               [-1.2416787850467291, 44.19687560747664],
               [-1.2426787850467291, 44.19587560747664]]
    with transaction() as conn:
        conn.execute(
            "INSERT INTO parcelle (id, code_insee, section, numero, latitude,"
            " longitude, lat_min, lat_max, lon_min, lon_max, geometrie_json,"
            " importe_le) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            ("40184AB0001", "40184", "AB", "1", 44.1963, -1.2421,
             44.1958, 44.1969, -1.2427, -1.2416,
             json.dumps({"type": "Polygon", "coordinates": [contour]}),
             "2026-09-11T08:00:00"))
    # La carte ne rend que les parcelles renseignees : sans diagnostic,
    # celle-ci n'y figurerait pas et il n'y aurait aucun contour a mesurer.
    inserer_dpe(n_dpe="A", adresse="1 rue", code_insee="40184")
    with transaction() as conn:
        conn.execute("UPDATE dpe SET parcelle_id = '40184AB0001' WHERE n_dpe = 'A'")

    reponse = metier_parcelles.pour_carte("40184", (-1.25, 44.19, -1.23, 44.20))
    sommets = reponse["parcelles"][0]["geometrie"]["coordinates"][0]
    assert sommets[0] == [-1.242679, 44.195876]
    for longitude, latitude in sommets:
        assert len(str(longitude).split(".")[-1]) <= 6, longitude
        assert len(str(latitude).split(".")[-1]) <= 6, latitude


def _poser_parcelle(conn, numero, lat, lon):
    import json
    cote = 0.0002
    anneau = [[lon, lat], [lon + cote, lat], [lon + cote, lat + cote],
              [lon, lat + cote], [lon, lat]]
    conn.execute(
        "INSERT INTO parcelle (id, code_insee, section, numero, latitude,"
        " longitude, lat_min, lat_max, lon_min, lon_max, geometrie_json,"
        " importe_le) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (f"40184AB{numero:04d}", "40184", "AB", str(numero), lat, lon,
         lat, lat + cote, lon, lon + cote,
         json.dumps({"type": "Polygon", "coordinates": [anneau]}),
         "2026-09-11T08:00:00"))


def test_tronquer_c_est_desormais_toujours_cacher(base):
    """
    Il n'y a plus qu'une seule sorte de troncature.

    Tant que le voile des parcelles sans information existait, le plafond
    mordait presque toujours sur LUI — 1 549 parcelles pour un plafond de
    1 600 sur un ecran large — et il fallait distinguer ce manque anodin
    d'un vrai, faute de quoi la carte redemandait deux fois a chaque
    geste et perdait tout son cache.

    Maintenant que seules les parcelles renseignees sont rendues, le
    drapeau `tronque` se suffit : s'il est leve, de l'information manque
    sous les yeux.
    """
    from app.base.connexion import transaction
    from app.metier import parcelles as metier_parcelles

    with transaction() as conn:
        for numero in range(8):
            _poser_parcelle(conn, numero, 44.2010 + numero * 0.0003, -1.2286)
        conn.execute("UPDATE dpe SET parcelle_id = NULL")
    inserer_dpe(n_dpe="A", adresse="1 rue", code_insee="40184")
    inserer_dpe(n_dpe="B", adresse="2 rue", code_insee="40184")
    with transaction() as conn:
        conn.execute("UPDATE dpe SET parcelle_id = '40184AB0000' WHERE n_dpe = 'A'")
        conn.execute("UPDATE dpe SET parcelle_id = '40184AB0001' WHERE n_dpe = 'B'")

    cadre = (-1.30, 44.19, -1.20, 44.21)

    # Plafond de 4 pour huit parcelles : il ne mord pas, car six d'entre
    # elles ne sont plus envoyees du tout.
    serre = metier_parcelles.pour_carte("40184", cadre, limite=4)
    assert serre["tronque"] is False
    assert {p["id"] for p in serre["parcelles"]} == {"40184AB0000", "40184AB0001"}
    # Le drapeau a deux visages a disparu avec le voile qui le justifiait.
    assert "tronque_utile" not in serre

    # Plafond de 1 : cette fois on coupe dans le vif, et il faut le dire.
    minuscule = metier_parcelles.pour_carte("40184", cadre, limite=1)
    assert minuscule["tronque"] is True
    assert len(minuscule["parcelles"]) == 1


def test_une_parcelle_sans_information_n_est_jamais_rendue(base):
    """
    Le voile blanc n'existe plus.

    Il couvrait 80 % des parcelles de Mimizan — 9 205 sur 11 444 — pour
    ne rien dire, et pesait les trois quarts de la reponse : 710 Ko sur
    942, mesure sur un cadre de quartier en grand ecran.

    Rien n'est perdu a l'oeil : le contour des parcelles muettes reste
    trace par la couche parcellaire de l'IGN, qui est une tuile et ne
    transite pas par nous.

    UNE VENTE SUFFIT a rendre une parcelle, comme un diagnostic : ce sont
    les deux choses que la carte sait montrer, et aucune n'est
    subordonnee a l'autre.
    """
    from app.base.connexion import transaction
    from app.metier import parcelles as metier_parcelles

    with transaction() as conn:
        for numero in range(5):
            _poser_parcelle(conn, numero, 44.2010 + numero * 0.0003, -1.2286)
    inserer_dpe(n_dpe="A", adresse="1 rue", code_insee="40184")
    with transaction() as conn:
        conn.execute("UPDATE dpe SET parcelle_id = '40184AB0000' WHERE n_dpe = 'A'")
        conn.execute(
            "INSERT INTO mutation (id, code_insee, date_mutation, nature,"
            "  valeur_fonciere, nb_parcelles, nb_locaux, importe_le)"
            " VALUES ('M1','40184','2024-11-04','Vente',261030,1,1,"
            "         '2026-09-11T08:00:00')")
        conn.execute("INSERT INTO mutation_parcelle (mutation_id, parcelle_id)"
                     " VALUES ('M1','40184AB0002')")

    cadre = (-1.30, 44.19, -1.20, 44.21)
    rendues = metier_parcelles.pour_carte("40184", cadre)["parcelles"]
    assert {p["id"] for p in rendues} == {"40184AB0000", "40184AB0002"}
    # Les trois muettes sont bien en base : c'est la carte qui les tait.
    with connexion() as conn:
        assert conn.execute("SELECT count(*) FROM parcelle").fetchone()[0] == 5


def test_une_parcelle_montre_TOUS_ses_diagnostics(base):
    """
    Cliquer une parcelle qui en portait plusieurs n'en ouvrait qu'UN —
    celui dont le numero vient le premier par ordre alphabetique — et rien
    ne disait que les autres existaient.

    Ce n'est pas un cas rare : beaucoup d'adresses de l'ADEME n'ont pas de
    numero de rue et sont geocodees au centre de la voie. Sur Mimizan,
    2 420 diagnostics partagent leur position avec un autre, et un seul
    point en porte 180.
    """
    from app.base.connexion import transaction
    from app.metier import parcelles as metier_parcelles

    with transaction() as conn:
        _poser_parcelle(conn, 1, 44.2010, -1.2286)

    for numero, quand in [("ZED", "2026-01-10"), ("ABC", "2026-08-01"),
                          ("MID", "2025-03-03")]:
        inserer_dpe(n_dpe=numero, adresse=f"{numero} rue", code_insee="40184",
                    date_etablissement=quand)
    with transaction() as conn:
        conn.execute("UPDATE dpe SET parcelle_id = '40184AB0001'"
                     " WHERE n_dpe IN ('ZED', 'ABC')")
        # Le troisieme n'y est rattache que par APPROCHE : il compte aussi,
        # c'est la meme clef que la carte.
        conn.execute("UPDATE dpe SET parcelle_approchee = '40184AB0001'"
                     " WHERE n_dpe = 'MID'")

    portes = metier_parcelles.diagnostics_de("40184AB0001")
    assert [d["n_dpe"] for d in portes] == ["ABC", "ZED", "MID"], (
        "du plus recent au plus ancien")
    approchees = {d["n_dpe"] for d in portes if d["position_approchee"]}
    assert approchees == {"MID"}, "la position approchee doit se signaler"


def test_une_vue_large_rend_des_positions_et_non_des_contours(base):
    """
    Au zoom 13, une commune entiere tient a l'ecran et un pixel vaut
    13,7 m : une parcelle en couvre deux ou trois. Son contour exact ne se
    VOIT pas, il se paie seulement.

    Mesure sur Mimizan entiere : 1 538 Ko avec les contours, 406 Ko sans —
    et sur un telephone bride six fois, le fil principal passe de 2 935 ms
    a 602 ms. Ce n'est pas un raffinement, c'est ce qui rend le zoom 13
    tenable.

    Ce qui reste doit suffire a POSER et a CLIQUER une marque : une
    position, les deux drapeaux, et de quoi ouvrir la fiche.
    """
    from app.base.connexion import transaction
    from app.metier import parcelles as metier_parcelles

    with transaction() as conn:
        _poser_parcelle(conn, 0, 44.2010, -1.2286)
    inserer_dpe(n_dpe="A", adresse="1 rue", code_insee="40184")
    with transaction() as conn:
        conn.execute("UPDATE dpe SET parcelle_id = '40184AB0000' WHERE n_dpe = 'A'")

    cadre = (-1.30, 44.19, -1.20, 44.21)
    legere = metier_parcelles.pour_carte("40184", cadre, avec_geometrie=False)
    marque = legere["parcelles"][0]

    assert "geometrie" not in marque
    assert marque["latitude"] is not None and marque["longitude"] is not None
    # De quoi colorer, et de quoi ouvrir.
    for clef in ("id", "dpe", "ventes", "dpe_approche", "n_dpe"):
        assert clef in marque, clef
    # Ce qui ne se lit pas a cette echelle ne part pas.
    for clef in ("contenance_m2", "emprise_batie_m2", "nb_batiments", "section"):
        assert clef not in marque, clef

    # Les diagnostics sans parcelle sont allegés de la meme facon : il y
    # en a mille, et aucune bulle ne s'ouvre a ce zoom.
    inserer_dpe(n_dpe="B", adresse="2 rue", code_insee="40184")
    legere = metier_parcelles.pour_carte("40184", cadre, avec_geometrie=False)
    point = legere["points"][0]
    assert set(point) == {"n_dpe", "latitude", "longitude", "nouveau"}

    # Et la vue rapprochee, elle, ne perd rien.
    lourde = metier_parcelles.pour_carte("40184", cadre)
    assert "geometrie" in lourde["parcelles"][0]
    assert "adresse" in lourde["points"][0]


def test_une_parcelle_trop_vaste_n_est_pas_peinte_en_plein(base):
    """
    Colorer une parcelle, c'est dire « ce terrain est diagnostique ».

    Sur les 900 m² d'une maison c'est vrai, et c'est meme plus juste que
    le point de l'ADEME, geocode a l'adresse donc sur la chaussee. Sur les
    18 hectares de 401840000K0051, un seul diagnostic peignait une foret
    entiere en vert.

    Le critere n'est PAS le nombre de batiments : le cadastre compte les
    garages et les abris, et un meme batiment peut porter plusieurs
    logements — 109 diagnostics pour 17 batiments sur une parcelle de
    Mimizan. C'est la surface revendiquee par diagnostic qui discrimine,
    et elle laisse tranquilles 754 des 762 parcelles diagnostiquees.

    La parcelle trop vaste porte alors la POSITION de ses diagnostics :
    c'est tout ce qu'on sait d'eux, et la carte le pose la plutot que de
    l'etaler sur un hectare.
    """
    import json as _json
    from app.base.connexion import transaction
    from app.metier import parcelles as metier_parcelles

    def _terrain(identifiant, lat, lon, cote, contenance):
        anneau = [[lon, lat], [lon + cote, lat], [lon + cote, lat + cote],
                  [lon, lat + cote], [lon, lat]]
        with transaction() as conn:
            conn.execute(
                "INSERT INTO parcelle (id, code_insee, section, numero,"
                " contenance_m2, latitude, longitude, lat_min, lat_max,"
                " lon_min, lon_max, geometrie_json, importe_le)"
                " VALUES (?,'40184','AB',?,?,?,?,?,?,?,?,?,'2026-09-13T08:00:00')",
                (identifiant, identifiant[-1], contenance, lat, lon,
                 lat, lat + cote, lon, lon + cote,
                 _json.dumps({"type": "Polygon", "coordinates": [anneau]})))

    # Une maison sur son terrain, et une foret avec un seul diagnostic.
    _terrain("40184AB0001", 44.2010, -1.2286, 0.0003, 900.0)
    _terrain("40184AB0002", 44.2030, -1.2286, 0.0300, 182275.0)
    inserer_dpe(n_dpe="MAISON", adresse="1 rue", code_insee="40184",
                latitude=44.2011, longitude=-1.2285)
    inserer_dpe(n_dpe="FORET", adresse="2 rue", code_insee="40184",
                latitude=44.2164, longitude=-1.2198)
    with transaction() as conn:
        conn.execute("UPDATE dpe SET parcelle_id='40184AB0001' WHERE n_dpe='MAISON'")
        conn.execute("UPDATE dpe SET parcelle_id='40184AB0002' WHERE n_dpe='FORET'")

    cadre = (-1.30, 44.19, -1.10, 44.25)
    par_id = {p["id"]: p for p in
              metier_parcelles.pour_carte("40184", cadre)["parcelles"]}

    maison = par_id["40184AB0001"]
    assert maison["trop_vaste"] is False
    # Rien de superflu sur celle qui n'en a pas besoin.
    assert "diagnostics" not in maison

    foret = par_id["40184AB0002"]
    assert foret["trop_vaste"] is True
    assert [d["n_dpe"] for d in foret["diagnostics"]] == ["FORET"]
    assert foret["diagnostics"][0]["latitude"] == 44.2164

    # Le meme terrain, dix fois plus diagnostique, redevient legitime.
    with transaction() as conn:
        for numero in range(60):
            conn.execute(
                "INSERT INTO dpe (n_dpe, code_insee, adresse, commune, code_postal,"
                " date_etablissement, jeu_de_donnees, importe_le, latitude, longitude,"
                " parcelle_id) VALUES (?,'40184',?,'Mimizan','40200','2026-08-01',"
                " 'existant','2026-08-01T10:00:00',44.2164,-1.2198,'40184AB0002')",
                (f"LOT-{numero}", f"{numero} rue du Lot"))
    par_id = {p["id"]: p for p in
              metier_parcelles.pour_carte("40184", cadre)["parcelles"]}
    assert par_id["40184AB0002"]["trop_vaste"] is False


def test_le_seuil_suit_les_criteres_de_l_ecran(base):
    """
    Le compte des diagnostics d'une parcelle depend des filtres poses.
    Le seuil doit suivre : une parcelle qui porte cinquante diagnostics
    mais un seul dans la fenetre demandee revendique bien, pour l'ecran
    affiche, toute sa surface pour ce seul diagnostic.
    """
    import json as _json
    from app.base.connexion import transaction
    from app.metier import parcelles as metier_parcelles

    anneau = [[-1.2286, 44.2030], [-1.1986, 44.2030],
              [-1.1986, 44.2330], [-1.2286, 44.2330], [-1.2286, 44.2030]]
    with transaction() as conn:
        conn.execute(
            "INSERT INTO parcelle (id, code_insee, section, numero, contenance_m2,"
            " latitude, longitude, lat_min, lat_max, lon_min, lon_max,"
            " geometrie_json, importe_le)"
            " VALUES ('40184AB0009','40184','AB','9',60000.0,44.21,-1.21,"
            "         44.2030,44.2330,-1.2286,-1.1986,?,'2026-09-13T08:00:00')",
            (_json.dumps({"type": "Polygon", "coordinates": [anneau]}),))
        for numero in range(40):
            conn.execute(
                "INSERT INTO dpe (n_dpe, code_insee, adresse, commune, code_postal,"
                " date_etablissement, jeu_de_donnees, importe_le, latitude, longitude,"
                " parcelle_id) VALUES (?,'40184',?,'Mimizan','40200',?,"
                " 'existant','2026-08-01T10:00:00',44.21,-1.21,'40184AB0009')",
                (f"V-{numero}", f"{numero} rue",
                 "2026-09-01" if numero == 0 else "2015-01-01"))

    cadre = (-1.30, 44.19, -1.10, 44.25)
    # Sans filtre : 40 diagnostics pour 60 000 m², soit 1 500 m² chacun.
    sans = metier_parcelles.pour_carte("40184", cadre)["parcelles"][0]
    assert sans["dpe"] == 40 and sans["trop_vaste"] is False

    # Fenetre courte : un seul reste, et il revendiquerait les 6 hectares.
    avec = metier_parcelles.pour_carte(
        "40184", cadre, filtres_dpe={"fenetre_jours": 30})["parcelles"][0]
    assert avec["dpe"] == 1 and avec["trop_vaste"] is True
    assert [d["n_dpe"] for d in avec["diagnostics"]] == ["V-0"]
