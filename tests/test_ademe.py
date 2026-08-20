# -*- coding: utf-8 -*-
"""
Verification du reperage des colonnes de l'ADEME.

Ces tests n'appellent pas le reseau : ils rejouent des schemas connus, dont
celui qui a reellement piege les scripts d'origine.
"""

from app.sources.ademe import associer_champs, sans_accents


def schema(*cles):
    """Fabrique un schema minimal a partir de noms de colonnes."""
    return [(cle, cle, sans_accents(cle)) for cle in cles]


def test_le_numero_de_dpe_ne_capture_pas_la_date_de_modification():
    """
    `date_derniere_modification_dpe` contient litteralement « n_dpe ».
    Une recherche par sous-chaine prendrait cette date pour le numero.
    """
    champs = schema("date_derniere_modification_dpe", "n_dpe")
    assert associer_champs(champs)["numero_dpe"] == "n_dpe"


def test_le_renommage_en_numero_dpe_est_suivi():
    """L'ADEME a renomme `n_dpe` en `numero_dpe` : le repli doit fonctionner."""
    champs = schema("numero_dpe", "date_derniere_modification_dpe")
    assert associer_champs(champs)["numero_dpe"] == "numero_dpe"


def test_le_cout_total_ne_prend_pas_le_cout_d_une_seule_energie():
    """
    `cout_total_5_usages_energie_n1` est le cout d'UNE energie du logement.
    Le total cherche est `cout_total_5_usages` — la cle la plus courte.
    """
    champs = schema("cout_total_5_usages_energie_n1", "cout_total_5_usages",
                    "cout_total_5_usages_energie_n2")
    assert associer_champs(champs)["cout_annuel"] == "cout_total_5_usages"


def test_le_cout_total_est_trouve_meme_si_le_nom_change():
    """Sans le nom exact, les mots-cles doivent encore retomber dessus."""
    champs = schema("cout_total_5_usages_annuel", "cout_chauffage")
    assert associer_champs(champs)["cout_annuel"] == "cout_total_5_usages_annuel"


def test_les_ges_sont_pris_par_metre_carre():
    """
    `emission_ges_5_usages` est un total annuel, `..._par_m2` la valeur
    comparable d'un logement a l'autre.
    """
    champs = schema("emission_ges_5_usages", "emission_ges_5_usages_par_m2")
    assert associer_champs(champs)["ges_m2"] == "emission_ges_5_usages_par_m2"


def test_energie_primaire_et_finale_ne_sont_pas_confondues():
    champs = schema("conso_5_usages_par_m2_ep", "conso_5_usages_par_m2_ef")
    correspondances = associer_champs(champs)
    assert correspondances["conso_primaire"] == "conso_5_usages_par_m2_ep"
    assert correspondances["conso_finale"] == "conso_5_usages_par_m2_ef"


def test_colonne_absente_renvoie_none():
    """Une colonne manquante doit valoir None, pas une valeur approchante."""
    assert associer_champs(schema("numero_dpe"))["surface"] is None


# =====================================================================
#  Deux generations de schemas (CDC 4)
# =====================================================================

from app.sources.ademe import cle_de_filtrage      # noqa: E402


SCHEMA_ANCIEN = schema(
    "numero_dpe", "date_etablissement_dpe", "consommation_energie",
    "classe_consommation_energie", "estimation_ges", "classe_estimation_ges",
    "annee_construction", "surface_thermique_lot", "latitude", "longitude",
    "tr002_type_batiment_description", "code_insee_commune_actualise",
    "tv016_departement_code", "geo_adresse", "_geopoint")


def test_schema_ancien_reconnu():
    """La base d'avant juillet 2021 nomme tout differemment."""
    champs = associer_champs(SCHEMA_ANCIEN)
    assert champs["adresse"] == "geo_adresse"
    assert champs["surface"] == "surface_thermique_lot"
    assert champs["conso_primaire"] == "consommation_energie"
    assert champs["etiquette_dpe"] == "classe_consommation_energie"
    assert champs["etiquette_ges"] == "classe_estimation_ges"
    assert champs["ges_m2"] == "estimation_ges"
    assert champs["type_batiment"] == "tr002_type_batiment_description"
    assert champs["latitude"] == "latitude"


def test_le_nom_de_commune_ne_capture_pas_le_champ_insee():
    """
    PIEGE : `code_insee_commune_actualise` contient le mot « commune ».
    Sans exiger « nom », le code INSEE se retrouverait enregistre comme nom
    de commune pour toute la base ancienne.
    """
    champs = associer_champs(SCHEMA_ANCIEN)
    assert champs["commune"] is None
    assert champs["code_insee"] == "code_insee_commune_actualise"


def test_les_trois_bases_se_filtrent_par_code_insee():
    """
    Le code INSEE est le seul identifiant commun aux deux generations, et
    c'est l'unite de travail de l'application : on consulte une commune, pas
    un code postal — le 31140 en couvre sept, le 40200 en couvre cinq.

    PIEGE VERIFIE CONTRE L'API : la base ancienne n'a pas de colonne de code
    postal. La filtrer avec « 40200 » ne provoque aucune erreur — elle
    renvoie les logements de la commune dont le code INSEE vaut 40200
    (Moustey), au lieu de Mimizan (INSEE 40184).
    """
    champ, nature = cle_de_filtrage("ancien", associer_champs(SCHEMA_ANCIEN))
    assert champ == "code_insee_commune_actualise"
    assert nature == "code INSEE"

    recents = associer_champs(schema("code_postal_ban", "code_insee_ban",
                                     "adresse_ban", "numero_dpe"))
    for jeu in ("existant", "neuf"):
        champ, nature = cle_de_filtrage(jeu, recents)
        assert champ == "code_insee_ban", jeu
        assert nature == "code INSEE"
