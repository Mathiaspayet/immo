# -*- coding: utf-8 -*-
"""
Verification de l'ecran Veille : filtres, dedoublonnage, marquage.
"""

import datetime

import pytest

from app.base import reglages
from app.metier import veille
from tests.conftest import inserer_dpe


def jours(n):
    return (datetime.date.today() - datetime.timedelta(days=n)).isoformat()


FILTRES = {"fenetre_jours": 120, "surface_min": 80, "surface_max": 400,
           "type_batiment": "maison"}


def test_une_seule_ligne_par_adresse(base):
    """Une adresse peut porter plusieurs DPE : seul le plus recent compte."""
    inserer_dpe(n_dpe="A", adresse="12 rue des Pins", date_etablissement=jours(5))
    inserer_dpe(n_dpe="B", adresse="12 RUE DES PINS ", date_etablissement=jours(60))

    resultats = veille.lister(FILTRES)
    assert len(resultats) == 1
    assert resultats[0]["n_dpe"] == "A"


def test_les_adresses_absentes_ne_sont_pas_regroupees(base):
    """Sans adresse, deux DPE distincts doivent rester deux lignes."""
    inserer_dpe(n_dpe="A", adresse=None, date_etablissement=jours(5))
    inserer_dpe(n_dpe="B", adresse=None, date_etablissement=jours(6))
    assert len(veille.lister(FILTRES)) == 2


def test_fenetre_temporelle(base):
    inserer_dpe(n_dpe="recent", date_etablissement=jours(10))
    inserer_dpe(n_dpe="ancien", adresse="2 rue Ancienne", date_etablissement=jours(300))

    assert len(veille.lister(FILTRES)) == 1
    assert len(veille.lister({**FILTRES, "fenetre_jours": 365})) == 2


def test_bornes_de_surface(base):
    inserer_dpe(n_dpe="petite", adresse="a", surface_habitable=40.0, date_etablissement=jours(3))
    inserer_dpe(n_dpe="bonne", adresse="b", surface_habitable=120.0, date_etablissement=jours(3))
    inserer_dpe(n_dpe="grande", adresse="c", surface_habitable=900.0, date_etablissement=jours(3))

    retenus = {ligne["n_dpe"] for ligne in veille.lister(FILTRES)}
    assert retenus == {"bonne"}


def test_surface_absente_conservee(base):
    """
    Une surface manquante ne doit pas faire disparaitre un bien : ce serait
    l'ecarter sans que rien ne l'explique.
    """
    inserer_dpe(n_dpe="sans-surface", surface_habitable=None, date_etablissement=jours(3))
    assert len(veille.lister(FILTRES)) == 1


def test_filtre_par_secteur(base):
    inserer_dpe(n_dpe="A", adresse="a", zone="bourg", date_etablissement=jours(3))
    inserer_dpe(n_dpe="B", adresse="b", zone="plage", date_etablissement=jours(3))

    resultats = veille.lister({**FILTRES, "zone": "plage"})
    assert [ligne["n_dpe"] for ligne in resultats] == ["B"]


def test_filtre_par_etiquette(base):
    inserer_dpe(n_dpe="A", adresse="a", etiquette_dpe="A", date_etablissement=jours(3))
    inserer_dpe(n_dpe="G", adresse="g", etiquette_dpe="G", date_etablissement=jours(3))

    resultats = veille.lister({**FILTRES, "etiquettes": ["a"]})   # casse indifferente
    assert [ligne["n_dpe"] for ligne in resultats] == ["A"]


def test_marquage_des_nouveautes(base):
    inserer_dpe(n_dpe="A", adresse="a", date_etablissement=jours(3))
    inserer_dpe(n_dpe="B", adresse="b", date_etablissement=jours(4), vu_le="2026-01-01T00:00:00")

    assert veille.resume(FILTRES)["nouveaux"] == 1
    assert len(veille.lister({**FILTRES, "seulement_nouveaux": True})) == 1

    assert veille.marquer_vus(["A"]) == 1
    assert veille.resume(FILTRES)["nouveaux"] == 0
    # Deja marque : la seconde fois ne change rien.
    assert veille.marquer_vus(["A"]) == 0


def test_tri_du_plus_recent_au_plus_ancien(base):
    for n, age in [("vieux", 100), ("recent", 2), ("moyen", 40)]:
        inserer_dpe(n_dpe=n, adresse=n, date_etablissement=jours(age))
    assert [l["n_dpe"] for l in veille.lister(FILTRES)] == ["recent", "moyen", "vieux"]


def test_anciennete_calculee(base):
    inserer_dpe(date_etablissement=jours(13))
    assert veille.lister(FILTRES)[0]["anciennete_jours"] == 13


def test_export_csv(base):
    inserer_dpe(adresse="1 rue de l'Essai", date_etablissement=jours(3))
    contenu = veille.exporter_csv(FILTRES)

    assert contenu.startswith("﻿")          # BOM attendu par Excel
    lignes = contenu.splitlines()
    assert lignes[0].count(";") > 10             # separateur point-virgule
    assert "1 rue de l'Essai" in lignes[1]


def test_resume_par_secteur(base):
    inserer_dpe(n_dpe="A", adresse="a", zone="bourg", date_etablissement=jours(3))
    inserer_dpe(n_dpe="B", adresse="b", zone="plage", date_etablissement=jours(3))
    inserer_dpe(n_dpe="C", adresse="c", zone=None, date_etablissement=jours(3))

    resume = veille.resume(FILTRES)
    assert resume["par_zone"] == {"bourg": 1, "plage": 1, "hors secteur": 1}
    assert resume["total"] == 3


# ---------------------------------------------------------------------
#  Reglages
# ---------------------------------------------------------------------

def test_reglages_par_defaut(base):
    """
    Les communes ne sont plus un reglage : elles entrent au registre a
    mesure qu'on les consulte. Les reglages ne gardent que ce qui est
    vraiment un choix — secteurs, filtres, tolerances, retention.
    """
    valeurs = reglages.tous()
    assert "communes" not in valeurs
    assert set(valeurs["zones"]) == {"bourg", "plage"}
    assert valeurs["zones_code_insee"] == "40184"


def test_reglage_enregistre_et_relu(base):
    reglages.ecrire({"fenetre_jours": 45})
    assert reglages.lire("fenetre_jours") == 45


@pytest.mark.parametrize("valeurs, extrait", [
    ({"surface_min": 500, "surface_max": 100}, "depasse"),
    ({"zones": {"plage": [200, 0]}}, "hors des bornes"),
    ({"zones": {"plage": ["nord"]}}, "latitude et longitude"),
    ({"fenetre_jours": 0}, "compris entre"),
    ({"type_batiment": "chateau"}, "maison"),
    ({"inconnu": 1}, "inconnu"),
])
def test_reglages_refuses(base, valeurs, extrait):
    """Un reglage aberrant doit etre refuse avec un message comprehensible."""
    with pytest.raises(ValueError) as erreur:
        reglages.ecrire(valeurs)
    assert extrait in str(erreur.value)


def test_marquage_avec_liste_vide_ne_marque_rien(base):
    """
    Une selection vide ne doit pas etre confondue avec « tout marquer » :
    l'utilisateur perdrait tous ses badges d'un coup.
    """
    inserer_dpe(n_dpe="A", adresse="a", date_etablissement=jours(3))
    assert veille.marquer_vus([]) == 0
    assert veille.resume(FILTRES)["nouveaux"] == 1

    assert veille.marquer_vus(None) == 1
    assert veille.resume(FILTRES)["nouveaux"] == 0


# ---------------------------------------------------------------------
#  Communes : plusieurs, et identifiees par leur code INSEE
# ---------------------------------------------------------------------

def test_le_cache_couvre_plusieurs_communes(base):
    """
    Un code postal couvre souvent plusieurs communes : le 40200 en compte
    cinq. L'application doit toutes les proposer, pas seulement la premiere.
    """
    inserer_dpe(n_dpe="M1", adresse="1 rue A", commune="Mimizan", code_insee="40184")
    inserer_dpe(n_dpe="M2", adresse="2 rue A", commune="Mimizan", code_insee="40184")
    inserer_dpe(n_dpe="A1", adresse="3 rue B", commune="Aureilhan", code_insee="40019")

    communes = veille.communes_en_cache()
    assert [c["nom"] for c in communes] == ["Mimizan", "Aureilhan"]   # tri par volume
    assert [c["dpe"] for c in communes] == [2, 1]


def test_les_variantes_d_ecriture_sont_regroupees(base):
    """
    L'ADEME ecrit « Sainte-Eulalie-en-Born », « STE EULALIE EN BORN » ou
    « SAINTE-EULALIE-EN-BORN » selon les lignes. Aucun LIKE ne les rattrape
    toutes ; le code INSEE, lui, est le meme.
    """
    for numero, ecriture in [("A", "Sainte-Eulalie-en-Born"),
                             ("B", "STE EULALIE EN BORN"),
                             ("C", "SAINTE-EULALIE-EN-BORN")]:
        inserer_dpe(n_dpe=numero, adresse=f"{numero} rue", commune=ecriture,
                    code_insee="40257")

    communes = veille.communes_en_cache()
    assert len(communes) == 1
    assert communes[0]["dpe"] == 3
    assert len(communes[0]["variantes"]) == 3


def test_le_nom_officiel_prime_sur_celui_de_l_ademe(base):
    from app.base.connexion import transaction
    with transaction() as conn:
        conn.execute("INSERT INTO commune (code_insee, nom, code_postal) "
                     "VALUES ('40257', 'Sainte-Eulalie-en-Born', '40200')")
    inserer_dpe(n_dpe="A", adresse="1 rue", commune="STE EULALIE EN BORN",
                code_insee="40257")
    assert veille.communes_en_cache()[0]["nom"] == "Sainte-Eulalie-en-Born"


def test_un_code_insee_stocke_comme_nom_ne_prime_sur_rien(base):
    """
    « 40184 » n'est pas un nom de commune : c'est le repli inscrit quand
    geo.api.gouv.fr n'a pas repondu. L'ecran doit alors montrer la variante
    de l'ADEME, pas un numero.
    """
    from app.base.connexion import transaction
    with transaction() as conn:
        conn.execute("INSERT INTO commune (code_insee, nom) VALUES ('40257', '40257')")
    inserer_dpe(n_dpe="A", adresse="1 rue", commune="STE EULALIE EN BORN",
                code_insee="40257")
    assert veille.communes_en_cache()[0]["nom"] == "STE EULALIE EN BORN"


def test_filtre_par_code_insee_insensible_aux_variantes(base):
    inserer_dpe(n_dpe="A", adresse="1 rue", commune="STE EULALIE EN BORN",
                code_insee="40257", date_etablissement="2026-08-01")
    inserer_dpe(n_dpe="B", adresse="2 rue", commune="Sainte-Eulalie-en-Born",
                code_insee="40257", date_etablissement="2026-08-01")
    inserer_dpe(n_dpe="C", adresse="3 rue", commune="Mimizan",
                code_insee="40184", date_etablissement="2026-08-01")

    filtres = {**FILTRES, "code_insee": "40257"}
    assert {l["n_dpe"] for l in veille.lister(filtres)} == {"A", "B"}

    # Le nom seul en aurait manque une.
    par_nom = {**FILTRES, "commune": "Sainte-Eulalie-en-Born"}
    assert {l["n_dpe"] for l in veille.lister(par_nom)} == {"B"}


def test_le_code_insee_prime_sur_le_nom(base):
    inserer_dpe(n_dpe="A", adresse="1 rue", commune="Mimizan", code_insee="40184",
                date_etablissement="2026-08-01")
    filtres = {**FILTRES, "code_insee": "40184", "commune": "Aureilhan"}
    assert [l["n_dpe"] for l in veille.lister(filtres)] == ["A"]


def test_les_secteurs_ne_debordent_pas_sur_les_communes_voisines(base):
    """
    Le decoupage bourg / plage est interne a Mimizan. Sans restriction, un
    logement d'Aureilhan se verrait etiqueter « bourg » parce que c'est le
    repere le plus proche — a 2 km. Aucun seuil de distance ne separe
    proprement les deux, seule la commune le fait.
    """
    from app.metier.import_dpe import transformer

    correspondances = {"numero_dpe": "n", "code_insee": "i", "latitude": "lat",
                       "longitude": "lon", "adresse": "a"}
    zones_points = {"bourg": [44.2011, -1.2286], "plage": [44.2044, -1.2914]}

    mimizan = transformer(
        {"n": "M", "i": "40184", "lat": 44.2015, "lon": -1.2280, "a": "1 rue"},
        correspondances, zones_points, "existant", "40200", None, "40184")
    assert mimizan["zone"] == "bourg"

    aureilhan = transformer(
        {"n": "A", "i": "40019", "lat": 44.2200, "lon": -1.2000, "a": "2 rue"},
        correspondances, zones_points, "existant", "40200", None, "40184")
    assert aureilhan["zone"] is None
    assert aureilhan["distance_zone_m"] is None

    # Reglage vide : les secteurs s'appliquent partout, comme avant.
    partout = transformer(
        {"n": "A", "i": "40019", "lat": 44.2200, "lon": -1.2000, "a": "2 rue"},
        correspondances, zones_points, "existant", "40200", None, "")
    assert partout["zone"] == "bourg"


def test_les_secteurs_disponibles_suivent_le_contenu(base):
    """
    En surveillant un autre territoire, plus aucun logement ne porte de
    secteur : le filtre correspondant n'a plus rien a filtrer et doit
    disparaitre de l'ecran.
    """
    assert veille.zones_en_cache() == []

    inserer_dpe(n_dpe="A", adresse="1 rue", zone="bourg")
    inserer_dpe(n_dpe="B", adresse="2 rue", zone="plage")
    inserer_dpe(n_dpe="C", adresse="3 rue", zone="bourg")
    assert veille.zones_en_cache() == ["bourg", "plage"]    # tri par volume

    inserer_dpe(n_dpe="D", adresse="4 rue", zone=None)
    assert veille.zones_en_cache() == ["bourg", "plage"]


@pytest.mark.parametrize("valeur, valide", [
    ("40184", True), ("31282", True), ("", True),      # vide = partout
    ("401", False), ("401845", False), ("40 18", False),
])
def test_reglage_commune_des_secteurs(base, valeur, valide):
    if valide:
        reglages.ecrire({"zones_code_insee": valeur})
        assert reglages.lire("zones_code_insee") == valeur
    else:
        with pytest.raises(ValueError, match="Code INSEE invalide"):
            reglages.ecrire({"zones_code_insee": valeur})


# ---------------------------------------------------------------------
#  Le registre des communes
# ---------------------------------------------------------------------

def _moissonner_hors_ligne(monkeypatch, communes):
    """
    Rejoue un import sans toucher au reseau : seul le registre des communes
    est observe ici. La moisson refusant un resultat vide, on lui rend une
    ligne, deja transformee.
    """
    from app.metier import import_dpe
    from app.sources import ademe

    def enregistrement(ligne, *args, **nommes):
        return dict.fromkeys(import_dpe.COLONNES) | {
            "n_dpe": ligne["num"], "code_insee": ligne["insee"],
            "adresse": "1 rue", "commune": "peu importe",
            "date_etablissement": "2026-08-01", "surface_habitable": 100.0,
            "type_batiment": "maison", "etiquette_dpe": "D",
            "jeu_de_donnees": "existant", "donnees_brutes_json": "{}",
        }

    monkeypatch.setattr(ademe, "preparer", lambda jeu: ({"numero_dpe": "num"}, []))
    monkeypatch.setattr(ademe, "telecharger", lambda code_insee, *a, **n: iter(
        [{"num": f"DPE-{code_insee}", "insee": code_insee}]))
    monkeypatch.setattr(import_dpe, "transformer", enregistrement)
    monkeypatch.setattr(import_dpe, "reparer_par_la_ban", lambda *a, **n: 0)
    monkeypatch.setattr(import_dpe, "_reparer_orphelins", lambda *a, **n: [])
    monkeypatch.setattr(import_dpe, "_publier", lambda **nommes: None)
    return import_dpe._moissonner(communes, jeux=["existant"])


def test_un_referentiel_injoignable_n_efface_pas_le_nom_connu(base, monkeypatch):
    """
    Quand geo.api.gouv.fr ne repond pas, l'import se rabat sur le code
    INSEE en guise de nom. Il ne doit pas l'ECRIRE par-dessus le vrai :
    une coupure d'une minute rebaptisait « Mimizan » en « 40184 » dans
    tous les ecrans, jusqu'au prochain import reussi.
    """
    from app.base.connexion import connexion, transaction
    with transaction() as conn:
        conn.execute("INSERT INTO commune (code_insee, nom, code_postal) "
                     "VALUES ('40184', 'Mimizan', '40200')")

    # Le repli : pas de nom, donc le code INSEE.
    _moissonner_hors_ligne(monkeypatch, [{"code_insee": "40184", "nom": "40184",
                                      "code_postal": None}])

    with connexion() as conn:
        ligne = conn.execute(
            "SELECT nom, code_postal FROM commune WHERE code_insee = '40184'").fetchone()
    assert ligne["nom"] == "Mimizan"
    assert ligne["code_postal"] == "40200"


def test_le_referentiel_joignable_corrige_le_nom(base, monkeypatch):
    """L'inverse doit rester vrai : un vrai nom remplace bien l'ancien."""
    from app.base.connexion import connexion, transaction
    with transaction() as conn:
        conn.execute("INSERT INTO commune (code_insee, nom) VALUES ('40184', '40184')")

    _moissonner_hors_ligne(monkeypatch, [{"code_insee": "40184", "nom": "Mimizan",
                                      "code_postal": "40200"}])

    with connexion() as conn:
        assert conn.execute(
            "SELECT nom FROM commune WHERE code_insee = '40184'").fetchone()["nom"] == "Mimizan"


def test_une_commune_inconnue_s_inscrit_meme_sans_referentiel(base, monkeypatch):
    """Premier import sans reseau : le code vaut mieux que rien."""
    from app.base.connexion import connexion
    _moissonner_hors_ligne(monkeypatch, [{"code_insee": "40184", "nom": "40184",
                                      "code_postal": None}])
    with connexion() as conn:
        assert conn.execute(
            "SELECT nom FROM commune WHERE code_insee = '40184'").fetchone()["nom"] == "40184"


def test_le_nom_de_repli_ne_s_inscrit_pas_dans_les_lignes(base):
    """
    Le referentiel muet, `importer_commune` se rabat sur le code INSEE en
    guise de nom. Ce repli ne doit pas descendre jusqu'aux lignes : il
    baptisait chaque logement moissonne « 40184 ». L'ecriture de l'ADEME,
    si rustre soit-elle, vaut mieux qu'un numero.
    """
    from app.metier.import_dpe import transformer

    correspondances = {"numero_dpe": "n", "code_insee": "i", "commune": "c",
                       "adresse": "a"}
    ligne = {"n": "A", "i": "40184", "c": "MIMIZAN", "a": "1 rue"}

    repli = transformer(ligne, correspondances, {}, "existant", "40200",
                        {"40184": {"nom": "40184"}}, "")
    assert repli["commune"] == "MIMIZAN"

    # Un vrai nom officiel continue de primer : c'est lui qui reunit
    # « MIMIZAN » et « Mimizan » sous une seule entree.
    officiel = transformer(ligne, correspondances, {}, "existant", "40200",
                           {"40184": {"nom": "Mimizan"}}, "")
    assert officiel["commune"] == "Mimizan"


# ---------------------------------------------------------------------
#  Carte et liste doivent repondre a la MEME question
# ---------------------------------------------------------------------

def test_sans_defauts_les_criteres_absents_le_restent(base):
    """
    La carte colore ses parcelles selon les criteres de l'ecran ; la liste
    posee sous elle doit en faire autant. Sans `defauts=false`, le serveur
    completait ce qui manquait par les reglages enregistres — une fenetre
    de 120 jours, des bornes de surface — et la liste annoncait un nombre
    que la carte ne montrait pas. Deux reponses a la meme question, sur le
    meme ecran.
    """
    from fastapi.testclient import TestClient
    from app.main import application

    reglages.ecrire({"fenetre_jours": 30, "surface_min": 200, "surface_max": 300,
                     "type_batiment": "appartement"})
    # Une maison de 90 m², diagnostiquee il y a 200 jours : AUCUN des
    # reglages ci-dessus ne la retient.
    inserer_dpe(n_dpe="A", adresse="1 rue", code_insee="40184",
                type_batiment="maison", surface_habitable=90.0,
                date_etablissement=jours(200))

    client = TestClient(application)

    avec = client.get("/api/veille", params={"code_insee": "40184"}).json()
    assert avec["resultats"] == [], "les reglages doivent s'appliquer par defaut"
    assert avec["filtres"]["fenetre_jours"] == 30

    sans = client.get("/api/veille",
                      params={"code_insee": "40184", "defauts": "false"}).json()
    assert [r["n_dpe"] for r in sans["resultats"]] == ["A"]
    assert sans["filtres"]["fenetre_jours"] is None
    assert sans["filtres"]["type_batiment"] == ""


def test_la_carte_et_la_liste_comptent_pareil(base):
    """
    Les memes criteres, deux chemins : le drapeau « DPE » des parcelles et
    la liste. Ils doivent designer les memes diagnostics — c'est tout
    l'interet d'avoir une seule ecriture des conditions.
    """
    from app.metier import parcelles as metier_parcelles

    for numero, quand, surface in [("VIEUX", jours(300), 100.0),
                                   ("RECENT", jours(10), 100.0),
                                   ("PETIT", jours(10), 40.0)]:
        inserer_dpe(n_dpe=numero, adresse=f"{numero} rue", code_insee="40184",
                    type_batiment="maison", surface_habitable=surface,
                    date_etablissement=quand,
                    latitude=44.2011, longitude=-1.2286)

    criteres = {"fenetre_jours": 60, "surface_min": 80, "code_insee": "40184"}
    attendus = {r["n_dpe"] for r in veille.lister(criteres)}
    assert attendus == {"RECENT"}

    # Aucune parcelle en base : les trois sont « sans parcelle », et seul
    # celui qui repond aux criteres doit ressortir.
    points, tronques = metier_parcelles._dpe_sans_parcelle(
        "40184", (-2.0, 44.0, -1.0, 45.0), criteres)
    assert {p["n_dpe"] for p in points} == attendus
    assert tronques is False


# ---------------------------------------------------------------------
#  Le regroupement : un logement, et non une adresse
# ---------------------------------------------------------------------

def test_deux_logements_a_la_meme_adresse_font_deux_lignes(base):
    """
    Le trou le plus large de la base, et il ne se voyait pas.

    Beaucoup de lignes de l'ADEME n'ont pas de numero de rue : « rue des
    Hournails 40200 Mimizan » designe alors toute une rue. Regroupees sur
    la seule ADRESSE, elles se reduisaient a une ligne. Mesure sur
    Mimizan : 4 468 diagnostics pour 1 568 adresses, et 2 705 lignes
    ecartees — dont 22 sur les 64 de la fenetre de soixante jours.

    Ce ne sont pas des doublons : « 211 rue Cantegrit » portait 22
    diagnostics de 22 SURFACES differentes sur quatre-vingt-dix jours.
    Vingt-deux logements, dont un seul etait montre.
    """
    inserer_dpe(n_dpe="PETIT", adresse="Rue des Hournails 40200 Mimizan",
                surface_habitable=42.0, date_etablissement=jours(5))
    inserer_dpe(n_dpe="GRAND", adresse="Rue des Hournails 40200 Mimizan",
                surface_habitable=88.0, date_etablissement=jours(6))

    resultats = veille.lister({"fenetre_jours": 60})
    assert {r["n_dpe"] for r in resultats} == {"PETIT", "GRAND"}
    assert all(r["logements"] == 1 for r in resultats)


def test_des_logements_indistinguables_font_une_ligne_qui_le_dit(base):
    """
    Restent les residences ou plusieurs logements ont la meme surface au
    metre pres : 51 appartements de 40,5 m² au 18 rue de l'Abbaye,
    diagnostiques le meme jour. Les separer serait arbitraire ; les taire
    serait le defaut qu'on corrige. La ligne porte donc leur NOMBRE.
    """
    for numero in range(3):
        inserer_dpe(n_dpe=f"LOT{numero}", adresse="18 Rue de l'Abbaye 40200 Mimizan",
                    surface_habitable=40.5, date_etablissement=jours(10))

    resultats = veille.lister({"fenetre_jours": 60})
    assert len(resultats) == 1
    assert resultats[0]["logements"] == 3


def test_le_meme_logement_rediagnostique_reste_une_ligne(base):
    """La regle d'origine tient : meme adresse, meme surface, le plus recent."""
    inserer_dpe(n_dpe="ANCIEN", adresse="12 Rue des Pins", surface_habitable=120.0,
                date_etablissement=jours(400))
    inserer_dpe(n_dpe="RECENT", adresse="12 RUE DES PINS ", surface_habitable=120.0,
                date_etablissement=jours(5))

    resultats = veille.lister({"fenetre_jours": 730})
    assert [r["n_dpe"] for r in resultats] == ["RECENT"]
    assert resultats[0]["logements"] == 2


# ---------------------------------------------------------------------
#  Ce qui n'est pas mesure ne doit pas s'afficher comme une mesure
# ---------------------------------------------------------------------

def test_un_dpe_vierge_ne_passe_pas_pour_une_classe_A(base):
    """
    Un logement ne consomme pas ZERO. Quand la consommation primaire est
    nulle, le diagnostic n'a pas ete etabli : c'est le « DPE vierge » que
    l'ancien regime autorisait. L'ADEME le note tantot « N » (non
    renseigne), tantot « A » par defaut.

    L'ecran affichait donc « classe A · 0 kWh/m² » — un logement NON
    EVALUE presente comme la meilleure performance possible — et le filtre
    par classe le ramenait parmi les A.

    Mesure sur Mimizan : 1 194 vraies classes A, de 18,8 a 82,8 kWh/m²,
    aucune a zero ; et 72 diagnostics a zero, tous de la base anterieure a
    juillet 2021, tous sans consommation finale ni cout annuel.
    """
    from app.metier.import_dpe import transformer

    correspondances = {"numero_dpe": "n", "adresse": "a", "code_insee": "i",
                       "etiquette_dpe": "e", "etiquette_ges": "g",
                       "conso_primaire": "c", "ges_m2": "ges", "surface": "s"}

    vierge = transformer(
        {"n": "VIERGE", "a": "1 rue", "i": "40184", "e": "A", "g": "A",
         "c": "0", "ges": "0", "s": "80"},
        correspondances, {}, "ancien", "40200", None, "")
    assert vierge["etiquette_dpe"] is None
    assert vierge["etiquette_ges"] is None
    assert vierge["conso_ep_m2"] is None
    assert vierge["ges_m2"] is None
    # Ce qui EST mesure reste : surface, adresse, date.
    assert vierge["surface_habitable"] == 80.0

    non_renseigne = transformer(
        {"n": "N", "a": "2 rue", "i": "40184", "e": "N", "g": "N",
         "c": "150", "ges": "12", "s": "80"},
        correspondances, {}, "ancien", "40200", None, "")
    assert non_renseigne["etiquette_dpe"] is None, "« N » n'est pas une classe"

    vraie = transformer(
        {"n": "VRAIE", "a": "3 rue", "i": "40184", "e": "A", "g": "A",
         "c": "45", "ges": "2", "s": "80"},
        correspondances, {}, "ancien", "40200", None, "")
    assert vraie["etiquette_dpe"] == "A" and vraie["conso_ep_m2"] == 45.0


def test_le_filtre_par_type_garde_les_types_generiques(base):
    """
    La base anterieure a juillet 2021 ne distingue pas maison et
    appartement : elle ecrit « Logement ». Choisir « maison » faisait donc
    disparaitre 238 diagnostics sur dix ans — dont des maisons de 150 et
    223 m², que seule la surface trahissait.

    Meme principe que les bornes de surface, deja en place : un critere ne
    doit pas ecarter les lignes qui ne portent pas l'information.
    """
    inserer_dpe(n_dpe="MAISON", adresse="1 rue", type_batiment="maison",
                date_etablissement=jours(5))
    inserer_dpe(n_dpe="APPART", adresse="2 rue", type_batiment="appartement",
                date_etablissement=jours(5))
    inserer_dpe(n_dpe="GENERIQUE", adresse="3 rue", type_batiment="Logement",
                date_etablissement=jours(5))
    inserer_dpe(n_dpe="IMMEUBLE", adresse="4 rue", type_batiment="immeuble",
                date_etablissement=jours(5))

    maisons = {r["n_dpe"] for r in
               veille.lister({"fenetre_jours": 60, "type_batiment": "maison"})}
    assert maisons == {"MAISON", "GENERIQUE"}, (
        "« Logement » ne dit pas que ce n'est pas une maison ; "
        "« immeuble », si")


def test_le_compte_en_cache_suit_la_commune_affichee(base):
    """
    « N DPE en cache » s'affiche a cote du nom de la commune : il doit donc
    compter CETTE commune. Sans la restriction, en suivre une seconde
    ferait annoncer a Mimizan le total des deux.
    """
    inserer_dpe(n_dpe="ICI", adresse="1 rue", code_insee="40184")
    inserer_dpe(n_dpe="AILLEURS", adresse="2 rue", code_insee="31282",
                commune="Launaguet", code_postal="31140")

    assert veille.resume({"code_insee": "40184"})["total_base"] == 1
    assert veille.resume({})["total_base"] == 2


def test_l_export_dit_combien_de_logements_chaque_ligne_represente(base):
    """Sans cette colonne, le fichier laisse croire qu'une ligne vaut un
    logement, alors qu'elle peut en representer cinquante-et-un."""
    for numero in range(3):
        inserer_dpe(n_dpe=f"LOT{numero}", adresse="18 Rue de l'Abbaye",
                    surface_habitable=40.5, date_etablissement=jours(5))

    csv_texte = veille.exporter_csv({"fenetre_jours": 60})
    entete, ligne = csv_texte.splitlines()[0], csv_texte.splitlines()[1]
    colonnes = entete.lstrip("﻿").split(";")
    assert "logements" in colonnes
    assert ligne.split(";")[colonnes.index("logements")] == "3"
