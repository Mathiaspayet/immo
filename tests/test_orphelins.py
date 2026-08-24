# -*- coding: utf-8 -*-
"""
test_orphelins.py — Les DPE que l'ADEME n'a pas su geocoder.

Environ 5 % des DPE d'une commune n'ont aucun code INSEE : le geocodage de
l'ADEME a echoue, le plus souvent sur des adresses trop bavardes. Comme
l'import interroge par code INSEE, ces lignes lui etaient INVISIBLES.

Mesure sur Mimizan le 24/08/2026 : 102 manquantes pour 2 023 vues, dont 48
maisons — et 46 de ces maisons de 2025 ou 2026. Un import reel apres
correctif est passe de 4 343 a 4 448 DPE, les 105 nouveaux tous positionnes
et ranges dans un secteur.
"""

import pytest

from app.sources import ban


# =====================================================================
#  Le nettoyage de l'adresse
# =====================================================================

def test_le_complement_de_residence_est_coupe():
    """
    C'est exactement ce qui manquait au geocodeur de l'ADEME : ni la
    residence ni le numero d'appartement ne figurent dans un referentiel
    d'adresses.
    """
    assert ban.nettoyer("5 rue Bremontier - Résidence Cap Océan - Apt 317") \
        == "5 rue Bremontier"
    assert ban.nettoyer("Rue du Camp d'Argent - Rés La Foret - Appt n°87") \
        == "Rue du Camp d'Argent"
    assert ban.nettoyer("3 allée des Pins Bât B") == "3 allée des Pins"


def test_les_tirets_legitimes_survivent():
    """Un tiret colle appartient au nom. Le couper donnerait « 5 rue
    Bremontier » pour un « 5-7 », et « Saint » pour « Saint-Julien »."""
    assert ban.nettoyer("5-7 Rue Bremontier") == "5-7 Rue Bremontier"
    assert ban.nettoyer("12 rue Saint-Julien") == "12 rue Saint-Julien"


def test_une_adresse_simple_n_est_pas_touchee():
    assert ban.nettoyer("18 BIS RUE DES PINSONS") == "18 BIS RUE DES PINSONS"
    assert ban.nettoyer("257 route de Baleste") == "257 route de Baleste"
    assert ban.nettoyer("") == ""
    assert ban.nettoyer(None) == ""


# =====================================================================
#  Le garde-fou : la commune rendue par la BAN
# =====================================================================

def _faux_lot(reponses):
    """Remplace l'appel reseau par une table adresse → resultat."""
    def _lot(adresses, code_postal):
        rendu = []
        for adresse in adresses:
            r = reponses.get(adresse)
            if r:
                rendu.append({"adresse": adresse, **r})
        return rendu
    return _lot


def test_une_adresse_placee_ailleurs_est_ecartee(monkeypatch):
    """
    Un code postal couvre plusieurs communes — le 40200 en couvre cinq.
    Sans ce controle, reparer les orphelins de Mimizan y ferait entrer
    ceux d'Aureilhan.
    """
    monkeypatch.setattr(ban, "_lot", _faux_lot({
        "1 rue A": {"result_score": "0.9", "result_citycode": "40184",
                    "result_label": "1 Rue A 40200 Mimizan",
                    "latitude": "44.2", "longitude": "-1.29"},
        "2 rue B": {"result_score": "0.9", "result_citycode": "40018",
                    "result_label": "2 Rue B 40200 Aureilhan",
                    "latitude": "44.19", "longitude": "-1.18"},
    }))
    trouvees = ban.geocoder(["1 rue A", "2 rue B"], "40200", "40184")
    assert set(trouvees) == {"1 rue A"}, "une adresse d'Aureilhan est entree"


def test_une_correspondance_douteuse_est_ecartee(monkeypatch):
    """En deca du seuil, la reponse de la BAN est une devinette. Mesure :
    les bonnes correspondances sortent entre 0,70 et 0,96, une rue sans
    numero mal reconnue a 0,40."""
    monkeypatch.setattr(ban, "_lot", _faux_lot({
        "1 rue A": {"result_score": "0.40", "result_citycode": "40184",
                    "result_label": "Rue A", "latitude": "44.2",
                    "longitude": "-1.29"},
    }))
    assert ban.geocoder(["1 rue A"], "40200", "40184") == {}


def test_les_doublons_d_adresse_sont_tous_rattaches(monkeypatch):
    """Deux DPE a la meme adresse — un logement diagnostique deux fois —
    ne doivent pas couter deux appels, mais tous deux etre places."""
    appels = []

    def _lot(adresses, code_postal):
        appels.append(list(adresses))
        return [{"adresse": a, "result_score": "0.9", "result_citycode": "40184",
                 "result_label": "1 Rue A 40200 Mimizan",
                 "latitude": "44.2", "longitude": "-1.29"} for a in adresses]

    monkeypatch.setattr(ban, "_lot", _lot)
    trouvees = ban.geocoder(["1 rue A", "1 rue A", "1 rue A"], "40200", "40184")
    assert appels == [["1 rue A"]], "l'adresse a ete demandee plusieurs fois"
    assert trouvees["1 rue A"]["code_insee"] == "40184"


# =====================================================================
#  La reparation dans l'import
# =====================================================================

CORRESPONDANCES = {
    "numero_dpe": "numero_dpe", "date": "date_etablissement_dpe",
    "adresse": "adresse_ban", "code_insee": "code_insee_ban",
    "geopoint": "_geopoint", "code_postal": "code_postal_ban",
}
CHAMPS = [(c, c, c) for c in
          ("numero_dpe", "date_etablissement_dpe", "adresse_ban", "adresse_brut",
           "code_insee_ban", "_geopoint", "code_postal_brut")]
COMMUNE = {"code_insee": "40184", "nom": "Mimizan", "code_postal": "40200"}


def _orphelin(numero, adresse_brute):
    return {"numero_dpe": numero, "date_etablissement_dpe": "2026-07-01",
            "adresse_ban": None, "code_insee_ban": None, "_geopoint": None,
            "adresse_brut": adresse_brute}


def _preparer(monkeypatch, lignes, placees):
    from app.metier import import_dpe
    monkeypatch.setattr("app.sources.ademe.orphelins",
                        lambda *a, **k: list(lignes))
    monkeypatch.setattr("app.sources.ban.geocoder",
                        lambda adresses, cp, insee=None: placees)
    return import_dpe


def test_une_ligne_reparee_recoit_code_insee_position_et_adresse(monkeypatch):
    """
    Reparee, la ligne redevient ordinaire : elle a sa position, donc son
    secteur, sa parcelle et son historique de ventes. Sans l'adresse
    normalisee — vide chez ces lignes, c'est le symptome meme — la fiche
    s'afficherait sans adresse.
    """
    import_dpe = _preparer(
        monkeypatch,
        [_orphelin("A1", "5 rue Bremontier - Rés Cap Océan - Apt 317")],
        {"5 rue Bremontier - Rés Cap Océan - Apt 317": {
            "latitude": 44.2126, "longitude": -1.2964, "score": 0.96,
            "code_insee": "40184", "label": "5 Rue Bremontier 40200 Mimizan"}})

    reparees = import_dpe._reparer_orphelins(COMMUNE, CORRESPONDANCES, CHAMPS, "existant")
    assert len(reparees) == 1
    ligne = reparees[0]
    assert ligne["code_insee_ban"] == "40184"
    assert ligne["_geopoint"] == "44.2126,-1.2964"
    assert ligne["adresse_ban"] == "5 Rue Bremontier 40200 Mimizan"


def test_une_ligne_que_la_ban_ne_place_pas_reste_dehors(monkeypatch):
    import_dpe = _preparer(monkeypatch, [_orphelin("A1", "lieu-dit inconnu")], {})
    assert import_dpe._reparer_orphelins(COMMUNE, CORRESPONDANCES, CHAMPS, "existant") == []


def test_une_ban_injoignable_ne_casse_pas_l_import(monkeypatch):
    """
    C'est un COMPLEMENT, jamais une condition. Un import reussi ne doit
    pas echouer parce que ce supplement n'a pas abouti — sans quoi une
    panne de la BAN priverait la veille de tout son import quotidien.
    """
    from app.metier import import_dpe
    from app.sources.client_http import ErreurSource

    monkeypatch.setattr("app.sources.ademe.orphelins",
                        lambda *a, **k: [_orphelin("A1", "5 rue Bremontier")])

    def tombe(*a, **k):
        raise ErreurSource("BAN injoignable (URLError)")

    monkeypatch.setattr("app.sources.ban.geocoder", tombe)
    assert import_dpe._reparer_orphelins(COMMUNE, CORRESPONDANCES, CHAMPS, "existant") == []


def test_l_ademe_injoignable_sur_les_orphelins_ne_casse_rien(monkeypatch):
    from app.metier import import_dpe
    from app.sources.client_http import ErreurSource

    def tombe(*a, **k):
        raise ErreurSource("HTTP 503")

    monkeypatch.setattr("app.sources.ademe.orphelins", tombe)
    assert import_dpe._reparer_orphelins(COMMUNE, CORRESPONDANCES, CHAMPS, "existant") == []


def test_sans_code_postal_on_ne_tente_rien(monkeypatch):
    """Le code postal est le seul reperage geographique qui reste a ces
    lignes : sans lui, la recherche porterait sur la France entiere."""
    from app.metier import import_dpe

    appels = []
    monkeypatch.setattr("app.sources.ademe.orphelins",
                        lambda *a, **k: appels.append(a) or [])
    sans_cp = {"code_insee": "40184", "nom": "Mimizan", "code_postal": None}
    assert import_dpe._reparer_orphelins(sans_cp, CORRESPONDANCES, CHAMPS, "existant") == []
    assert appels == []


def test_une_adresse_normalisee_deja_presente_est_respectee(monkeypatch):
    """On ne remplace que ce qui manque : ecraser une adresse deja
    normalisee par celle de la BAN perdrait le complement d'appartement."""
    ligne = _orphelin("A1", "5 rue Bremontier - Apt 317")
    ligne["adresse_ban"] = "5 Rue Bremontier Apt 317"
    import_dpe = _preparer(monkeypatch, [ligne], {
        "5 rue Bremontier - Apt 317": {
            "latitude": 44.2, "longitude": -1.29, "score": 0.9,
            "code_insee": "40184", "label": "5 Rue Bremontier 40200 Mimizan"}})
    reparees = import_dpe._reparer_orphelins(COMMUNE, CORRESPONDANCES, CHAMPS, "existant")
    assert reparees[0]["adresse_ban"] == "5 Rue Bremontier Apt 317"


# =====================================================================
#  Les positions aberrantes
# =====================================================================
#  Cas different des orphelines : ces lignes ONT un code INSEE, elles
#  sont donc en base — mais sans position exploitable, donc sans
#  secteur, sans parcelle et sans historique de ventes. Elles manquaient
#  a la carte et aux alertes filtrees par secteur.
#
#  Mesure sur Mimizan : 21 lignes du jeu « existant » portent toutes le
#  MEME `_geopoint`, « -5.98, -1.36 » — en plein Atlantique. C'est le
#  Lambert-93 (0,0) converti, et leur `statut_geocodage` annonce pourtant
#  « adresse geocodee ban a l'adresse ».
# =====================================================================

GEOPOINT_ABERRANT = "-5.98385630920877,-1.363081210117898"


def test_une_position_hors_de_france_est_vue_comme_absente():
    from app.metier import import_dpe

    aberrante = {"_geopoint": GEOPOINT_ABERRANT}
    assert import_dpe._sans_position(aberrante, CORRESPONDANCES)

    bonne = {"_geopoint": "44.2011,-1.2286"}
    assert not import_dpe._sans_position(bonne, CORRESPONDANCES)


def test_une_ligne_mal_placee_est_repositionnee(monkeypatch):
    """Elle a son code INSEE et son adresse ; seule la position est
    fausse. La reparer lui rend son secteur."""
    from app.metier import import_dpe

    monkeypatch.setattr("app.sources.ban.geocoder",
                        lambda adresses, cp, insee=None: {
                            "18 Avenue des Oiseaux": {
                                "latitude": 44.2044, "longitude": -1.2914,
                                "score": 0.9, "code_insee": "40184",
                                "label": "18 Avenue des Oiseaux 40200 Mimizan"}})
    ligne = {"numero_dpe": "X1", "code_insee_ban": "40184",
             "adresse_ban": "18 Avenue des Oiseaux 40200 Mimizan",
             "_geopoint": GEOPOINT_ABERRANT,
             "adresse_brut": "18 Avenue des Oiseaux"}
    lignes = [ligne]

    assert import_dpe.reparer_par_la_ban(lignes, COMMUNE, CORRESPONDANCES) == 1
    assert lignes[0]["_geopoint"] == "44.2044,-1.2914"
    # Le code INSEE etait deja bon : on n'y touche pas.
    assert lignes[0]["code_insee_ban"] == "40184"


def test_une_ligne_sans_aucune_adresse_reste_en_l_etat(monkeypatch):
    """
    Le cas irreparable, et il est majoritaire : 84 des 85 lignes qui
    restent sans position a Mimizan viennent de la base d'avant 2021 et
    ne portent AUCUNE adresse — `geo_score` y vaut zero. Il n'y a rien a
    geocoder, et aucune requete ne doit partir pour rien.
    """
    from app.metier import import_dpe

    appels = []
    monkeypatch.setattr("app.sources.ban.geocoder",
                        lambda *a, **k: appels.append(a) or {})
    lignes = [{"numero_dpe": "X1", "code_insee_ban": "40184",
               "adresse_ban": None, "_geopoint": None}]
    assert import_dpe.reparer_par_la_ban(lignes, COMMUNE, CORRESPONDANCES) == 0
    assert appels == [], "une requete est partie sans adresse a geocoder"


def test_une_ligne_bien_placee_n_est_pas_soumise_a_la_ban(monkeypatch):
    """On ne geocode que ce qui manque : soumettre tout le parc ferait
    des milliers d'appels inutiles a chaque import."""
    from app.metier import import_dpe

    appels = []
    monkeypatch.setattr("app.sources.ban.geocoder",
                        lambda *a, **k: appels.append(a) or {})
    lignes = [{"numero_dpe": "X1", "code_insee_ban": "40184",
               "adresse_ban": "1 Rue A", "_geopoint": "44.2011,-1.2286",
               "adresse_brut": "1 rue A"}]
    assert import_dpe.reparer_par_la_ban(lignes, COMMUNE, CORRESPONDANCES) == 0
    assert appels == []


def test_plusieurs_lignes_a_la_meme_adresse_sont_toutes_replacees(monkeypatch):
    """Un logement diagnostique deux fois donne deux lignes : les deux
    doivent retrouver leur position, pour une seule demande."""
    from app.metier import import_dpe

    monkeypatch.setattr("app.sources.ban.geocoder",
                        lambda adresses, cp, insee=None: {
                            "1 rue A": {"latitude": 44.2, "longitude": -1.29,
                                        "score": 0.9, "code_insee": "40184",
                                        "label": "1 Rue A 40200 Mimizan"}})
    lignes = [{"numero_dpe": f"X{n}", "code_insee_ban": "40184",
               "adresse_ban": "1 Rue A", "_geopoint": GEOPOINT_ABERRANT,
               "adresse_brut": "1 rue A"} for n in range(3)]
    assert import_dpe.reparer_par_la_ban(lignes, COMMUNE, CORRESPONDANCES) == 3
    assert all(l["_geopoint"] == "44.2,-1.29" for l in lignes)
