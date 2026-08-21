# -*- coding: utf-8 -*-
"""
test_alertes.py — L'alerte courriel (F6).

Un courriel de trop est irrattrapable : il est deja parti. Les cas
couverts ici sont donc d'abord ceux du SILENCE — premiere decouverte d'une
commune, bien deja signale, echec d'envoi — avant ceux de l'envoi.
"""

import datetime
import json

import pytest

from app.base import reglages
from app.base.connexion import connexion, transaction
from app.metier import alertes
from app.sources.courriel import ErreurCourriel
from tests.conftest import inserer_dpe


@pytest.fixture()
def poste(monkeypatch):
    """Un bureau de poste en carton : retient ce qui part, n'envoie rien."""
    partis = []

    def faux_envoi(destinataire, sujet, texte, html=None):
        partis.append({"destinataire": destinataire, "sujet": sujet,
                       "texte": texte, "html": html})
        return True

    monkeypatch.setattr("app.sources.courriel.envoyer", faux_envoi)
    return partis


@pytest.fixture()
def client(base):
    """L'application entiere, pour verifier ce qui sort vraiment par HTTP."""
    from fastapi.testclient import TestClient

    from app.main import application
    with TestClient(application) as c:
        yield c


@pytest.fixture()
def alerte_prete(base):
    reglages.ecrire({"alerte_destinataire": "moi@exemple.fr",
                     "alerte_active": True})


def _nouveau(n_dpe, **champs):
    """Un DPE jamais signale, qui repond aux criteres par defaut."""
    champs.setdefault("surface_habitable", 120.0)
    champs.setdefault("type_batiment", "maison")
    champs.setdefault("date_etablissement", datetime.date.today().isoformat())
    inserer_dpe(n_dpe=n_dpe, adresse=f"{n_dpe} rue de l'Essai", **champs)


def test_rien_ne_part_sans_activation(base, poste):
    _nouveau("D1")
    resultat = alertes.envoyer_si_besoin()
    assert resultat["envoye"] is False
    assert resultat["raison"] == "desactivee"
    assert poste == []


def test_rien_ne_part_sans_destinataire(base, poste):
    # On force en base : la validation refuse justement ce couple.
    with transaction() as conn:
        conn.execute("INSERT INTO reglage (cle, valeur_json, maj_le) "
                     "VALUES ('alerte_active', 'true', '2026-08-20T10:00:00')")
    _nouveau("D1")
    assert alertes.envoyer_si_besoin()["raison"] == "sans_destinataire"
    assert poste == []


def test_rien_ne_part_sans_nouveaute(alerte_prete, poste):
    assert alertes.envoyer_si_besoin()["raison"] == "rien_de_neuf"
    assert poste == []


def test_un_bien_neuf_declenche_un_envoi(alerte_prete, poste):
    _nouveau("D1")
    resultat = alertes.envoyer_si_besoin()

    assert resultat["envoye"] is True
    assert resultat["biens"] == 1
    assert len(poste) == 1
    assert poste[0]["destinataire"] == "moi@exemple.fr"
    assert "1 nouveau DPE" in poste[0]["sujet"]
    assert "rue de l'Essai" in poste[0]["texte"]


def test_un_bien_n_est_signale_qu_une_fois(alerte_prete, poste):
    """
    Le coeur du garde-fou. Sans `alerte_le`, chaque import quotidien
    reexpedierait les memes biens — l'alerte deviendrait du bruit, et on
    cesserait de la lire.
    """
    _nouveau("D1")
    assert alertes.envoyer_si_besoin()["envoye"] is True
    assert alertes.envoyer_si_besoin()["raison"] == "rien_de_neuf"
    assert len(poste) == 1

    # Un second bien, lui, part bien.
    _nouveau("D2")
    assert alertes.envoyer_si_besoin()["biens"] == 1
    assert len(poste) == 2


def test_un_echec_ne_consomme_pas_les_biens(alerte_prete, monkeypatch):
    """
    Un serveur injoignable ne doit pas faire disparaitre l'alerte : les
    biens restent candidats pour le lendemain. Une alerte en retard vaut
    mieux qu'une alerte perdue.
    """
    def refus(*args, **kwargs):
        raise ErreurCourriel("connexion refusee")

    monkeypatch.setattr("app.sources.courriel.envoyer", refus)
    _nouveau("D1")

    resultat = alertes.envoyer_si_besoin()
    assert resultat["envoye"] is False
    assert resultat["raison"] == "echec_envoi"

    with connexion() as conn:
        reste = conn.execute(
            "SELECT alerte_le FROM dpe WHERE n_dpe = 'D1'").fetchone()[0]
    assert reste is None
    assert len(alertes.candidats()) == 1


def test_les_criteres_enregistres_s_appliquent(alerte_prete, poste):
    """Ce qu'on recoit doit etre ce que l'ecran Veille montre."""
    reglages.ecrire({"surface_min": 100, "surface_max": 200})
    _nouveau("TROP-PETIT", surface_habitable=40.0)
    _nouveau("AU-GABARIT", surface_habitable=150.0)

    resultat = alertes.envoyer_si_besoin()
    assert resultat["biens"] == 1
    assert "AU-GABARIT" in poste[0]["texte"] or "AU-GABARIT rue" in poste[0]["texte"]
    assert "TROP-PETIT" not in poste[0]["texte"]


def test_le_secteur_restreint_l_alerte(alerte_prete, poste):
    """« Une zone en particulier » : on ne veut pas du reste."""
    reglages.ecrire({"alerte_zone": "plage"})
    _nouveau("BOURG", zone="bourg")
    _nouveau("PLAGE", zone="plage")

    assert alertes.envoyer_si_besoin()["biens"] == 1
    assert "PLAGE" in poste[0]["texte"]
    assert "BOURG" not in poste[0]["texte"]


def test_le_courriel_reste_lisible_en_nombre(alerte_prete, poste):
    """Au-dela de 25 biens, on renvoie a l'ecran plutot que de tout lister."""
    for i in range(30):
        _nouveau(f"D{i:02d}")

    resultat = alertes.envoyer_si_besoin()
    assert resultat["biens"] == 30
    assert "et 5 autres" in poste[0]["texte"]


def test_l_adresse_est_controlee(base):
    with pytest.raises(ValueError):
        reglages.ecrire({"alerte_destinataire": "pas-une-adresse"})
    reglages.ecrire({"alerte_destinataire": "moi@exemple.fr"})


def test_activer_sans_destinataire_est_refuse(base):
    """Sinon rien ne partirait, et rien ne le dirait."""
    with pytest.raises(ValueError):
        reglages.ecrire({"alerte_active": True})


# ---------------------------------------------------------------------
#  Le silence a la decouverte d'une commune
# ---------------------------------------------------------------------
#  C'est le garde-fou le plus important, et il porte sur le vrai chemin
#  d'import : on remplace l'ADEME, pas la logique testee.

@pytest.fixture()
def ademe_en_carton(monkeypatch):
    """Une ADEME de test : on lui dit quoi servir, par commune."""
    from app.sources import ademe

    parc = {}
    correspondances = {c: c for c in ademe.CONCEPTS}

    monkeypatch.setattr("app.sources.ademe.preparer",
                        lambda jeu="existant": (correspondances, []))
    monkeypatch.setattr(
        "app.sources.ademe.telecharger",
        lambda code_insee, corr, jeu="existant", progression=None:
            parc.get((code_insee, jeu), []))
    return parc


def _ligne(n_dpe, code_insee, commune):
    return {
        "numero_dpe": n_dpe, "date": datetime.date.today().isoformat(),
        "adresse": f"{n_dpe} rue de l'Essai", "commune": commune,
        "code_insee": code_insee, "code_postal": "40200",
        "surface": 120.0, "type_batiment": "maison", "etiquette_dpe": "D",
    }


def test_decouvrir_une_commune_n_alerte_pas(base, poste, ademe_en_carton,
                                            monkeypatch):
    """
    Le piege : `premier_import` ne vaut que si la base entiere est vide.
    Ajouter une commune a une base deja peuplee ferait paraitre son parc
    entier comme neuf — et partirait en courriel a chaque exploration.
    """
    from app.metier import import_dpe

    monkeypatch.setattr("app.metier.import_dpe._rafraichir_cadastres", lambda: None)
    reglages.ecrire({"alerte_destinataire": "moi@exemple.fr", "alerte_active": True})

    # Une premiere commune, deja connue et deja signalee.
    ademe_en_carton[("40184", "existant")] = [_ligne("M1", "40184", "Mimizan")]
    import_dpe.importer_commune("40184", jeux=["existant"])
    alertes.envoyer_si_besoin()
    poste.clear()

    # On decouvre Launaguet : la base n'est plus vide, mais cette commune
    # l'est. Son parc ne doit rien declencher.
    ademe_en_carton[("31282", "existant")] = [
        _ligne(f"L{i}", "31282", "Launaguet") for i in range(5)]
    import_dpe.importer_commune("31282", jeux=["existant"])

    assert alertes.candidats() == []
    assert alertes.envoyer_si_besoin()["raison"] == "rien_de_neuf"
    assert poste == []

    # En revanche, un bien qui PARAIT ensuite dans cette commune part bien.
    ademe_en_carton[("31282", "existant")].append(
        _ligne("L-NEUF", "31282", "Launaguet"))
    import_dpe.importer_commune("31282", jeux=["existant"])

    resultat = alertes.envoyer_si_besoin()
    assert resultat["envoye"] is True
    assert resultat["biens"] == 1
    assert "L-NEUF" in poste[0]["texte"]


# ---------------------------------------------------------------------
#  Le perimetre : une commune, un secteur
# ---------------------------------------------------------------------

def test_la_commune_restreint_l_alerte(alerte_prete, poste):
    """
    Sans commune choisie, l'alerte porte sur tout le registre — et chaque
    commune exploree viendrait s'y ajouter. C'est precisement ce qu'on ne
    veut pas.
    """
    reglages.ecrire({"alerte_code_insee": "40184"})
    _nouveau("MIMIZAN", code_insee="40184", commune="Mimizan")
    _nouveau("LAUNAGUET", code_insee="31282", commune="Launaguet")

    resultat = alertes.envoyer_si_besoin()
    assert resultat["biens"] == 1
    assert "MIMIZAN" in poste[0]["texte"]
    assert "LAUNAGUET" not in poste[0]["texte"]


def test_commune_et_secteur_se_cumulent(alerte_prete, poste):
    reglages.ecrire({"alerte_code_insee": "40184", "alerte_zone": "plage"})
    _nouveau("BON", code_insee="40184", commune="Mimizan", zone="plage")
    _nouveau("MAUVAIS-SECTEUR", code_insee="40184", commune="Mimizan", zone="bourg")
    _nouveau("MAUVAISE-COMMUNE", code_insee="31282", commune="Launaguet", zone="plage")

    resultat = alertes.envoyer_si_besoin()
    assert resultat["biens"] == 1
    assert "BON" in poste[0]["texte"]
    assert "MAUVAIS-SECTEUR" not in poste[0]["texte"]
    assert "MAUVAISE-COMMUNE" not in poste[0]["texte"]


def test_sans_commune_choisie_tout_remonte(alerte_prete, poste):
    """Le defaut reste explicite : vide = toutes les communes."""
    _nouveau("A", code_insee="40184", commune="Mimizan")
    _nouveau("B", code_insee="31282", commune="Launaguet")
    assert alertes.envoyer_si_besoin()["biens"] == 2


def test_le_code_insee_de_l_alerte_est_controle(base):
    with pytest.raises(ValueError):
        reglages.ecrire({"alerte_code_insee": "40"})
    reglages.ecrire({"alerte_code_insee": "40184"})
    reglages.ecrire({"alerte_code_insee": ""})


def test_les_secteurs_proposes_sont_ceux_de_la_commune(base):
    """
    Proposer « plage » a qui surveille Launaguet ne remonterait jamais
    rien : les secteurs sont propres a une commune.
    """
    from app.metier import veille

    _nouveau("M1", code_insee="40184", commune="Mimizan", zone="plage")
    _nouveau("M2", code_insee="40184", commune="Mimizan", zone="bourg")
    _nouveau("L1", code_insee="31282", commune="Launaguet", zone="centre")

    assert sorted(veille.zones_en_cache("40184")) == ["bourg", "plage"]
    assert veille.zones_en_cache("31282") == ["centre"]
    assert sorted(veille.zones_en_cache()) == ["bourg", "centre", "plage"]


# ---------------------------------------------------------------------
#  Le serveur d'envoi, regle depuis l'ecran
# ---------------------------------------------------------------------

def test_le_mot_de_passe_ne_sort_jamais(base):
    """
    L'invariant qui rend acceptable de garder ce secret en base : l'API des
    Reglages sert `tous()` tel quel. S'il n'etait pas masque la, il
    partirait vers le navigateur a chaque ouverture de l'ecran.
    """
    reglages.ecrire({"smtp_hote": "smtp.exemple.fr",
                     "smtp_expediteur": "veille@exemple.fr",
                     "smtp_motdepasse": "mot-de-passe-reel"})

    public = reglages.tous()
    assert public["smtp_motdepasse"] == reglages.MASQUE
    assert "mot-de-passe-reel" not in json.dumps(public)
    # L'ecran a besoin de savoir qu'il en existe un, pas de sa valeur.
    assert public["smtp_motdepasse_defini"] is True

    # Il reste accessible a qui le demande explicitement — l'envoi.
    assert reglages.tous(avec_secrets=True)["smtp_motdepasse"] == "mot-de-passe-reel"
    assert reglages.lire("smtp_motdepasse") == "mot-de-passe-reel"


def test_l_api_des_reglages_ne_divulgue_pas_le_secret(client):
    """Le meme invariant, verifie de bout en bout sur la reponse HTTP."""
    reglages.ecrire({"smtp_hote": "smtp.exemple.fr",
                     "smtp_expediteur": "veille@exemple.fr",
                     "smtp_motdepasse": "mot-de-passe-reel"})

    corps = client.get("/api/reglages").text
    assert "mot-de-passe-reel" not in corps

    etat = client.get("/api/alertes").text
    assert "mot-de-passe-reel" not in etat


def test_reposter_le_masque_conserve_le_mot_de_passe(base):
    """
    L'ecran affiche des puces et les renvoie en enregistrant autre chose.
    Les prendre au pied de la lettre remplacerait le mot de passe par huit
    puces, et l'alerte cesserait de partir sans que rien ne l'explique.
    """
    reglages.ecrire({"smtp_hote": "smtp.exemple.fr",
                     "smtp_expediteur": "veille@exemple.fr",
                     "smtp_motdepasse": "mot-de-passe-reel"})

    reglages.ecrire({"smtp_utilisateur": "moi",
                     "smtp_motdepasse": reglages.MASQUE})
    assert reglages.lire("smtp_motdepasse") == "mot-de-passe-reel"
    assert reglages.lire("smtp_utilisateur") == "moi"


def test_vider_le_champ_efface_le_mot_de_passe(base):
    """Le seul moyen de retirer un mot de passe une fois pose."""
    reglages.ecrire({"smtp_hote": "smtp.exemple.fr",
                     "smtp_expediteur": "veille@exemple.fr",
                     "smtp_motdepasse": "mot-de-passe-reel"})
    reglages.ecrire({"smtp_motdepasse": ""})
    assert reglages.lire("smtp_motdepasse") == ""
    assert reglages.tous()["smtp_motdepasse_defini"] is False


def test_les_reglages_priment_sur_l_environnement(base, monkeypatch):
    monkeypatch.setattr("app.config.SMTP_HOTE", "ancien.exemple.fr")
    monkeypatch.setattr("app.config.SMTP_EXPEDITEUR", "ancien@exemple.fr")

    assert reglages.smtp()["source"] == "environnement"
    assert reglages.smtp()["hote"] == "ancien.exemple.fr"

    reglages.ecrire({"smtp_hote": "nouveau.exemple.fr",
                     "smtp_expediteur": "nouveau@exemple.fr"})
    effectif = reglages.smtp()
    assert effectif["source"] == "reglages"
    assert effectif["hote"] == "nouveau.exemple.fr"


def test_sans_rien_nulle_part_l_envoi_est_refuse(base, monkeypatch):
    monkeypatch.setattr("app.config.SMTP_HOTE", "")
    monkeypatch.setattr("app.config.SMTP_EXPEDITEUR", "")
    assert reglages.smtp()["source"] == "aucune"

    from app.sources import courriel
    with pytest.raises(ErreurCourriel, match="Reglages"):
        courriel.envoyer("moi@exemple.fr", "sujet", "corps")


def test_un_serveur_sans_expediteur_est_refuse(base):
    """Le serveur refuserait a la premiere alerte ; autant le dire ici."""
    with pytest.raises(ValueError):
        reglages.ecrire({"smtp_hote": "smtp.exemple.fr"})


def test_le_port_est_controle(base):
    with pytest.raises(ValueError):
        reglages.ecrire({"smtp_port": 0})
    with pytest.raises(ValueError):
        reglages.ecrire({"smtp_port": 99999})
    reglages.ecrire({"smtp_port": 465})
