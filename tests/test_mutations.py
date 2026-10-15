# -*- coding: utf-8 -*-
"""
test_mutations.py — L'historique des ventes (DVF).

Le defaut a ne jamais laisser passer est arithmetique : le fichier source
repete `valeur_fonciere` sur chaque ligne d'une meme vente. Additionner ces
lignes multiplie le prix. Sur Mimizan, 1 118 mutations sur 2 054 tiennent
sur plusieurs lignes — le cas est majoritaire, pas marginal.
"""

import pytest

from app.base.connexion import connexion, transaction
from app.metier import mutations
from app.sources import dvf, dvf_archive
from app.sources.client_http import ErreurSource
from tests.conftest import inserer_dpe


def _ligne(id_mutation, parcelle, valeur, **champs):
    """Une ligne du CSV DVF, les champs non precises etant vides."""
    ligne = {
        "id_mutation": id_mutation, "date_mutation": "2024-11-04",
        "nature_mutation": "Vente", "valeur_fonciere": str(valeur),
        "code_commune": "40184", "id_parcelle": parcelle,
        "type_local": "", "surface_reelle_bati": "", "surface_terrain": "",
    }
    ligne.update(champs)
    return ligne


def _parcelle(identifiant, code_insee="40184"):
    with transaction() as conn:
        conn.execute(
            "INSERT INTO parcelle (id, code_insee, section, numero, contenance_m2,"
            "  emprise_batie_m2, nb_batiments, latitude, longitude, importe_le)"
            " VALUES (?,?,'AA','001',800,120,1,44.2,-1.2,'2026-08-20T10:00:00')",
            (identifiant, code_insee))


def test_une_vente_sur_plusieurs_lignes_garde_son_prix(base, monkeypatch):
    """
    Le coeur du sujet. Une vente a 400 000 EUR etalee sur quatre lignes —
    trois parcelles, deux locaux — doit rester a 400 000, pas monter a
    1 600 000.
    """
    lignes = [
        _ligne("M1", "40184000AA0265", 400000, surface_terrain="10"),
        _ligne("M1", "40184000AA0266", 400000, type_local="Maison",
               surface_reelle_bati="80", surface_terrain="296"),
        _ligne("M1", "40184000AA0266", 400000, type_local="Dépendance",
               surface_reelle_bati="30", surface_terrain="296"),
        _ligne("M1", "40184000AA0267", 400000, type_local="Dépendance",
               surface_reelle_bati="124", surface_terrain="153"),
    ]
    monkeypatch.setattr("app.sources.dvf.telecharger",
                        lambda code, progression=None: lignes)
    _parcelle("40184000AA0266")

    resume = mutations.importer("40184")
    assert resume["mutations"] == 1
    assert resume["lignes"] == 4

    ventes = mutations.pour_parcelle("40184000AA0266")
    assert len(ventes) == 1
    vente = ventes[0]
    assert vente["valeur_fonciere"] == 400000        # et non 1 600 000
    assert vente["nb_parcelles"] == 3
    assert vente["nb_locaux"] == 3
    # Les surfaces bâties, elles, s'additionnent : chaque local est distinct.
    assert vente["surface_bati_m2"] == 234
    # Le terrain se compte par parcelle : 296 ne doit pas etre compte deux fois.
    assert vente["surface_terrain_m2"] == 459


def test_le_prix_au_m2_se_tait_quand_il_serait_faux(base, monkeypatch):
    """
    Rapporter le prix d'une maison, d'un garage et d'un terrain a la seule
    surface batie donnerait un chiffre faux — et flatteur.
    """
    lignes = [
        _ligne("M1", "40184000AA0266", 400000, type_local="Maison",
               surface_reelle_bati="80"),
        _ligne("M1", "40184000AA0266", 400000, type_local="Dépendance",
               surface_reelle_bati="30"),
    ]
    monkeypatch.setattr("app.sources.dvf.telecharger",
                        lambda code, progression=None: lignes)
    _parcelle("40184000AA0266")
    mutations.importer("40184")

    vente = mutations.pour_parcelle("40184000AA0266")[0]
    assert vente["prix_m2"] is None
    assert vente["prix_m2_incertain"] is True


def test_le_prix_au_m2_s_affiche_quand_il_est_juste(base, monkeypatch):
    """Une maison seule, sur une parcelle seule : la division a un sens."""
    lignes = [_ligne("M1", "40184000AT0148", 261030, type_local="Maison",
                     surface_reelle_bati="62", surface_terrain="314")]
    monkeypatch.setattr("app.sources.dvf.telecharger",
                        lambda code, progression=None: lignes)
    _parcelle("40184000AT0148")
    mutations.importer("40184")

    vente = mutations.pour_parcelle("40184000AT0148")[0]
    assert vente["prix_m2"] == 4210            # 261030 / 62
    assert vente["prix_m2_incertain"] is False


def test_les_ventes_se_retrouvent_depuis_un_dpe(base, monkeypatch):
    """Le rattachement passe par la parcelle, jamais par l'adresse."""
    lignes = [_ligne("M1", "40184000AT0148", 261030, type_local="Maison",
                     surface_reelle_bati="62")]
    monkeypatch.setattr("app.sources.dvf.telecharger",
                        lambda code, progression=None: lignes)
    _parcelle("40184000AT0148")
    mutations.importer("40184")

    inserer_dpe(n_dpe="D1", adresse="53 Chemin des Roseaux")
    with transaction() as conn:
        conn.execute("UPDATE dpe SET parcelle_id = '40184000AT0148'"
                     " WHERE n_dpe = 'D1'")

    ventes = mutations.pour_dpe("D1")
    assert len(ventes) == 1
    assert ventes[0]["valeur_fonciere"] == 261030
    # Un DPE sans parcelle ne doit pas faire tomber la fiche.
    inserer_dpe(n_dpe="D2", adresse="ailleurs")
    assert mutations.pour_dpe("D2") == []
    assert mutations.pour_dpe("INEXISTANT") == []


def test_un_dpe_pose_devant_sa_parcelle_retrouve_sa_vente(base, monkeypatch):
    """
    Le cas reel du 13 rue des Ecoles, a Mimizan : l'ADEME a geocode le
    diagnostic sur la chaussee, a 1,8 m de la parcelle AB0180 — l'autre la
    plus proche est a 10,6 m. La carte les reunissait ; la fiche, qui ne
    lisait que la parcelle certaine, ne montrait pas la vente de 2022.
    """
    vente_2022 = dict(date_mutation="2022-06-23", type_local="Maison",
                      surface_reelle_bati="160", nombre_pieces_principales="6",
                      adresse_numero="13", adresse_nom_voie="RUE DES ECOLES")
    lignes = [
        # Les deux lignes reelles de DVF : la maison est repetee pour
        # chaque nature de culture de sa parcelle.
        _ligne("2022-685985", "40184000AB0180", 557142, code_nature_culture="S",
               surface_terrain="500", **vente_2022),
        _ligne("2022-685985", "40184000AB0180", 557142, code_nature_culture="AG",
               surface_terrain="590", **vente_2022),
        _ligne("2023-VOISIN", "40184000AB0180", 210000, date_mutation="2023-03-02",
               type_local="Maison", surface_reelle_bati="90",
               adresse_numero="15", adresse_nom_voie="RUE DES ECOLES"),
    ]
    monkeypatch.setattr("app.sources.dvf.telecharger", lambda code, progression=None: lignes)
    _parcelle("40184000AB0180")
    mutations.importer("40184")
    inserer_dpe(n_dpe="2440E1909752R", adresse="13 Rue des Ecoles 40200 Mimizan")
    with transaction() as conn:
        conn.execute("UPDATE dpe SET parcelle_approchee = '40184000AB0180',"
                     " distance_parcelle_m = 1.8 WHERE n_dpe = '2440E1909752R'")

    ventes = {v["id"]: v for v in mutations.pour_dpe("2440E1909752R")}
    assert set(ventes) == {"2022-685985", "2023-VOISIN"}
    assert ventes["2022-685985"]["parcelle_approchee"] is True
    assert ventes["2022-685985"]["distance_dpe_m"] == 1.8
    assert ventes["2022-685985"]["adresse_concordante"] is True
    # Une maison de 160 m2 sur 1 090 m2 de terrain — et non deux maisons
    # pour 320 m2, sans prix au m2.
    assert ventes["2022-685985"]["nb_locaux"] == 1
    assert ventes["2022-685985"]["surface_bati_m2"] == 160
    assert ventes["2022-685985"]["surface_terrain_m2"] == 1090
    assert ventes["2022-685985"]["prix_m2"] == 3482
    # Une autre adresse sur la meme parcelle : signalee, pas cachee.
    assert ventes["2023-VOISIN"]["adresse_concordante"] is False


def test_un_dpe_sur_sa_parcelle_ne_porte_pas_de_mention_d_approche(base, monkeypatch):
    lignes = [_ligne("M1", "40184000AT0148", 261030, type_local="Maison",
                     surface_reelle_bati="62")]
    monkeypatch.setattr("app.sources.dvf.telecharger", lambda code, progression=None: lignes)
    _parcelle("40184000AT0148")
    mutations.importer("40184")
    inserer_dpe(n_dpe="D1", adresse="53 Chemin des Roseaux")
    with transaction() as conn:
        conn.execute("UPDATE dpe SET parcelle_id = '40184000AT0148',"
                     " parcelle_approchee = 'AUTRE' WHERE n_dpe = 'D1'")
    (vente,) = mutations.pour_dpe("D1")
    assert "parcelle_approchee" not in vente


def test_un_local_repete_par_culture_ne_compte_qu_une_fois():
    """
    DVF ecrit une ligne par local ET par nature de culture. La maison du
    13 rue des Ecoles, sur « sols » 500 m2 et « terrain d'agrement » 590 m2,
    devenait deux maisons de 160 m2 — sans prix au m2.
    """
    maison = dict(type_local="Maison", surface_reelle_bati="160",
                  nombre_pieces_principales="6")
    vente, = mutations._regrouper([
        _ligne("M1", "P1", 557142, code_nature_culture="S", surface_terrain="500", **maison),
        _ligne("M1", "P1", 557142, code_nature_culture="AG", surface_terrain="590", **maison),
    ])
    assert vente["nb_locaux"] == 1
    assert vente["surface_bati_m2"] == 160
    assert vente["surface_terrain_m2"] == 1090


def test_deux_locaux_identiques_restent_deux():
    """
    Deux dependances sans surface, sur une meme culture : rien ne les
    distingue dans le fichier, mais ce sont deux biens. Repetees sur deux
    cultures, elles restent deux — pas quatre.
    """
    dependance = dict(type_local="Dépendance", nombre_pieces_principales="0")
    maison = dict(type_local="Maison", surface_reelle_bati="90",
                  nombre_pieces_principales="4")
    lignes = [_ligne("M1", "P1", 300000, code_nature_culture=culture,
                     surface_terrain=surface, **local)
              for culture, surface in (("S", "400"), ("J", "200"))
              for local in (maison, dependance, dependance)]
    vente, = mutations._regrouper(lignes)
    assert vente["nb_locaux"] == 3
    assert vente["surface_bati_m2"] == 90
    assert vente["surface_terrain_m2"] == 600


def test_un_local_present_sur_une_seule_culture_est_garde():
    """Le fichier n'est pas toujours un produit croise : 19 parcelles sur 843
    dans les Landes en 2025. Un local vu sur une seule culture compte."""
    vente, = mutations._regrouper([
        _ligne("M1", "P1", 150000, code_nature_culture="J", surface_terrain="300",
               type_local="Maison", surface_reelle_bati="33", lot1_numero="5"),
        _ligne("M1", "P1", 150000, code_nature_culture="",
               type_local="Dépendance", lot1_numero="4"),
    ])
    assert vente["nb_locaux"] == 2
    assert vente["types_locaux"] == ["Dépendance", "Maison"]


def _vente_des_ecoles(**champs):
    maison = dict(date_mutation="2022-06-23", type_local="Maison",
                  surface_reelle_bati="160", nombre_pieces_principales="6",
                  code_commune="40184")
    maison.update(champs)
    identifiant = maison.pop("id_mutation", "2022-685985")
    return [_ligne(identifiant, "40184000AB0180", 557142,
                   code_nature_culture=culture, surface_terrain=surface, **maison)
            for culture, surface in (("S", "500"), ("AG", "590"))]


def _composee_a_l_ancienne(monkeypatch, lignes):
    """Une vente en base telle que l'ancien regroupement l'avait ecrite."""
    monkeypatch.setattr("app.sources.dvf.telecharger", lambda code, progression=None: lignes)
    mutations.importer("40184")
    with transaction() as conn:
        conn.execute("DELETE FROM source_maj")
        conn.execute("UPDATE mutation SET nb_locaux = 2, surface_bati_m2 = 320,"
                     " surface_terrain_m2 = 590, alerte_le = '2022-07-01T07:00:00'")


def test_les_ventes_deja_en_base_sont_recomposees_une_fois(base, monkeypatch):
    """
    Corriger `_regrouper` ne corrige que les imports suivants : DVF ne
    republie une commune qu'a ses parutions. Les ventes deja en base sont
    donc relues une fois — sans etre signalees de nouveau.
    """
    monkeypatch.setattr(dvf, "millesimes", lambda *a, **n: tuple(range(2021, 2027)))
    _composee_a_l_ancienne(monkeypatch, _vente_des_ecoles())
    assert mutations.a_remettre_a_niveau() is True

    lus = []
    def departement(dep, annee):
        lus.append((dep, annee))
        # Une vente d'une commune absente de la base : la remise a niveau
        # corrige, elle n'etend pas.
        autre = _vente_des_ecoles(id_mutation="AILLEURS", code_commune="40065")
        return iter(_vente_des_ecoles() + autre) if annee == 2022 else None
    monkeypatch.setattr(dvf, "lignes_departement", departement)
    monkeypatch.setattr("app.sources.dvf_archive.telecharger",
                        lambda **n: pytest.fail("rien d'ancien : pas d'archive"))

    resultat = mutations.remettre_a_niveau()
    assert resultat["communes"] == 1
    assert resultat["recomposees"] == 1
    assert {dep for dep, _ in lus} == {"40"}

    vente, = mutations.pour_parcelle("40184000AB0180")
    assert (vente["nb_locaux"], vente["surface_bati_m2"], vente["surface_terrain_m2"]) \
        == (1, 160, 1090)
    assert vente["prix_m2"] == 3482
    assert vente["alerte_le"] == "2022-07-01T07:00:00"     # pas re-signalee
    with connexion() as conn:
        assert conn.execute("SELECT count(*) FROM mutation").fetchone()[0] == 1

    # Une fois, pas davantage.
    monkeypatch.setattr(dvf, "lignes_departement",
                        lambda dep, annee: pytest.fail("deja remise a niveau"))
    assert mutations.a_remettre_a_niveau() is False
    assert mutations.remettre_a_niveau() is None


def test_l_archive_est_relue_quand_la_base_garde_plus_ancien(base, monkeypatch):
    """2018-2020 ne viennent plus que de l'archive : sans elle, ces ventes
    garderaient leur erreur pour toujours."""
    monkeypatch.setattr(dvf, "millesimes", lambda *a, **n: tuple(range(2021, 2027)))
    ancienne = _vente_des_ecoles(id_mutation="ARCH-1", date_mutation="2019-03-14")
    _composee_a_l_ancienne(monkeypatch, ancienne)

    ordre = []
    def archive(dep=None, code_insee=None, progression=None):
        ordre.append("archive")
        return dvf_archive.Archive(lignes=ancienne, departement=dep, titre="t", url="u")
    monkeypatch.setattr("app.sources.dvf_archive.telecharger", archive)
    monkeypatch.setattr(dvf, "lignes_departement",
                        lambda dep, annee: ordre.append(annee))

    mutations.remettre_a_niveau()
    assert ordre[0] == "archive"          # la source vivante a le dernier mot
    vente, = mutations.pour_parcelle("40184000AB0180")
    assert vente["surface_bati_m2"] == 160


def test_une_panne_laisse_la_remise_a_niveau_a_refaire(base, monkeypatch):
    monkeypatch.setattr(dvf, "millesimes", lambda *a, **n: tuple(range(2021, 2027)))
    _composee_a_l_ancienne(monkeypatch, _vente_des_ecoles())

    def panne(dep, annee):
        raise ErreurSource("DVF injoignable")
    monkeypatch.setattr(dvf, "lignes_departement", panne)
    with pytest.raises(ErreurSource):
        mutations.remettre_a_niveau()
    assert mutations.a_remettre_a_niveau() is True


def test_une_base_sans_vente_n_a_rien_a_recomposer(base, monkeypatch):
    """Sinon le premier import, deja fait a la nouvelle maniere, serait
    recompose pour rien le lendemain."""
    assert mutations.a_remettre_a_niveau() is False
    monkeypatch.setattr("app.sources.dvf.telecharger",
                        lambda code, progression=None: _vente_des_ecoles())
    mutations.importer("40184")
    assert mutations.a_remettre_a_niveau() is False


def test_le_reimport_remplace_sans_doubler(base, monkeypatch):
    """DVF republie la commune entiere et corrige parfois le passe."""
    lignes = [_ligne("M1", "40184000AT0148", 261030, type_local="Maison",
                     surface_reelle_bati="62")]
    monkeypatch.setattr("app.sources.dvf.telecharger",
                        lambda code, progression=None: lignes)
    _parcelle("40184000AT0148")

    mutations.importer("40184")
    mutations.importer("40184")

    assert len(mutations.pour_parcelle("40184000AT0148")) == 1
    with connexion() as conn:
        assert conn.execute("SELECT count(*) FROM mutation").fetchone()[0] == 1
        assert conn.execute(
            "SELECT count(*) FROM mutation_parcelle").fetchone()[0] == 1


def test_une_ligne_sans_parcelle_est_ecartee(base, monkeypatch):
    """Sans parcelle, la vente ne pourrait se rattacher a rien."""
    lignes = [_ligne("M1", "", 100000, type_local="Maison")]
    monkeypatch.setattr("app.sources.dvf.telecharger",
                        lambda code, progression=None: lignes)
    assert mutations.importer("40184")["mutations"] == 0


def test_les_communes_sans_dvf_sont_annoncees():
    """L'Alsace-Moselle tient son propre livre foncier."""
    for code in ("57123", "67482", "68066", "97601"):
        assert dvf.indisponible(code)
    for code in ("40184", "31282", "2A004", "97411"):
        assert dvf.indisponible(code) is None

    with pytest.raises(ErreurSource, match="livre foncier"):
        dvf.telecharger("67482")


def test_l_url_suit_le_departement():
    assert dvf.url_annee("40184", 2024).endswith("/2024/communes/40/40184.csv")
    assert dvf.url_annee("97411", 2024).endswith("/2024/communes/974/97411.csv")


def test_une_commune_sans_ventes_est_signalee(base):
    """Comme pour le bati : une base montee avant DVF resterait muette."""
    assert mutations.manquantes("40184") is False      # pas de cadastre non plus
    _parcelle("40184000AT0148")
    assert mutations.manquantes("40184") is True


def test_les_millesimes_annonces_sont_ceux_que_la_source_sert(base, monkeypatch):
    """
    `dvf.millesimes()` deduit la fenetre de l'annee courante : en 2026 elle
    annonce 2021 a 2026. Or DVF parait deux fois l'an, avec plusieurs mois
    de retard — verifie le 13/09/2026, le fichier 2026 de Mimizan repond
    404 quand celui de 2025 porte ses 296 mutations, toutes en base.

    L'ecran annoncait donc un millesime que la source n'a pas publie, et le
    lecteur ne pouvait que le prendre pour un trou dans les donnees. Ce
    que la source sert se lit dans le releve du guet quotidien.
    """
    from app.metier import mutations
    from app.sources import dvf

    monkeypatch.setattr(dvf, "millesimes", lambda *a, **n: (2021, 2022, 2023))
    # Le millesime en cours n'est pas encore paru : HEAD a rendu None.
    mutations.noter_publication("40184", {2020: "vieux", 2021: "etag-1",
                                          2022: "etag-2", 2023: None})
    assert mutations.profondeur("40184")["millesimes_source"] == [2021, 2022]


def test_afficher_la_profondeur_n_interroge_pas_la_source(base, monkeypatch):
    """
    L'ecran s'ouvre avec l'application : il ne doit rien demander a un
    tiers (CDC 4). Il faisait six requetes HEAD a chaque ouverture. Sans
    releve, il se fie aux ventes en base, puis a la fenetre calculee.
    """
    from app.metier import mutations
    from app.sources import dvf

    monkeypatch.setattr(dvf, "millesimes", lambda *a, **n: (2021, 2022, 2023))
    monkeypatch.setattr(dvf, "signatures",
                        lambda *a, **n: pytest.fail("appel reseau a l'affichage"))
    assert mutations.profondeur("40184")["millesimes_source"] == [2021, 2022, 2023]
    monkeypatch.setattr("app.sources.dvf.telecharger", lambda code, progression=None: [
        _ligne("M1", "40184000AA0001", 1000, date_mutation="2022-05-01")])
    mutations.importer("40184")
    assert mutations.profondeur("40184")["millesimes_source"] == [2022]
