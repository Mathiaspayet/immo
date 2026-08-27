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

    def faux_envoi(destinataire, sujet, texte, html=None, trace=None):
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
        lambda code_insee, corr, jeu="existant", progression=None, champs=None:
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


def test_l_ecran_est_la_seule_source(base):
    """
    Une seule origine possible pour le serveur d'envoi : cette table.
    L'environnement ne joue plus aucun role — plus rien a poser dans le
    conteneur, et aucune ambiguite sur un reglage qui ne prend pas effet.
    """
    assert reglages.smtp()["source"] == "aucune"

    reglages.ecrire({"smtp_hote": "smtp.exemple.fr",
                     "smtp_expediteur": "veille@exemple.fr"})
    effectif = reglages.smtp()
    assert effectif["source"] == "reglages"
    assert effectif["hote"] == "smtp.exemple.fr"
    assert effectif["port"] == 587


def test_sans_serveur_l_envoi_est_refuse(base):
    """Le refus doit dire ou aller le corriger, pas seulement qu'il refuse."""
    from app.sources import courriel
    with pytest.raises(ErreurCourriel, match="Réglages"):
        courriel.envoyer("moi@exemple.fr", "sujet", "corps")


def test_le_diagnostic_est_ecrit_en_francais_accentue(base):
    """C'est ce que l'utilisateur lit pour deboguer son fournisseur : du
    texte sans accents au milieu d'une interface accentuee se lit comme
    une negligence, et ces phrases-la sont justement celles qu'on lit
    quand plus rien ne marche."""
    from app.metier import alertes

    fautes = []
    for etape, message in [
            ({"nom": "connexion"}, "ConnectionRefusedError : refused"),
            ({"nom": "connexion"}, "timed out"),
            ({"nom": "chiffrement"}, "starttls absent"),
            ({"nom": "authentification"}, "535 refuse"),
            ({"nom": "envoi"}, "certificate verify failed"),
            ({"nom": "envoi"}, "553 sender rejected")]:
        conseil = alertes._conseil(etape, message)
        assert conseil, f"aucune piste pour {etape['nom']} / {message}"
        # Un mot francais courant prive de son accent : le signe qu'on a
        # tape la phrase au clavier sans y revenir.
        for mot in ("verifier", "repondu", "refuses", "accepte", "symptome",
                    "general", "complete", "acces", "reglages", "dedie",
                    "valide", "expedition", "utilise", "ecoute", "ferme",
                    "errone", "laisse", "etre"):
            if mot in conseil.lower():
                fautes.append((mot, conseil[:60]))
    assert not fautes, fautes


def test_plus_aucune_variable_smtp_dans_la_configuration():
    """Le nettoyage doit etre complet : un reliquat reintroduirait la
    double source qu'on vient de retirer."""
    from app import config

    assert not [n for n in dir(config) if "SMTP" in n]


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


# ---------------------------------------------------------------------
#  Le controle d'envoi, et son diagnostic
# ---------------------------------------------------------------------
#  « Ca ne marche pas » ne se debogue pas : il faut savoir OU cela
#  s'arrete. Chaque etape franchie ecarte une moitie des causes.

def _smtp(**champs):
    valeurs = {"smtp_hote": "smtp.exemple.fr", "smtp_port": 587,
               "smtp_ssl": False, "smtp_expediteur": "veille@exemple.fr"}
    valeurs.update(champs)
    reglages.ecrire(valeurs)


def test_l_essai_raconte_les_etapes_franchies(base):
    """
    Sur le vrai chemin d'envoi — un port ferme fait echouer a la connexion,
    ce qui laisse voir les deux premieres etapes.
    """
    _smtp(smtp_hote="127.0.0.1", smtp_port=9)      # rien n'ecoute sur 9

    resultat = alertes.essai("moi@exemple.fr")
    assert resultat["envoye"] is False

    etapes = {e["nom"]: e for e in resultat["etapes"]}
    assert etapes["configuration"]["etat"] == "ok"
    assert etapes["connexion"]["etat"] == "echec"

    # La configuration se relit dans la trace : c'est la moitie du debogage.
    detail = etapes["configuration"]["detail"]
    assert "127.0.0.1:9" in detail
    assert "STARTTLS" in detail
    assert "veille@exemple.fr" in detail
    assert "moi@exemple.fr" in detail
    # Chaque etape est datee : un delai d'attente se reconnait a sa duree.
    assert all(isinstance(e["ms"], int) for e in resultat["etapes"])


def test_l_essai_ne_leve_jamais(base, monkeypatch):
    """
    Un echec est le RESULTAT de l'appel, pas une erreur de l'appel : c'est
    justement ce qu'on est venu voir.
    """
    _smtp()

    def refus(*args, **kwargs):
        raise ErreurCourriel("connexion refusee")

    monkeypatch.setattr("app.sources.courriel.envoyer", refus)
    resultat = alertes.essai("moi@exemple.fr")
    assert resultat["envoye"] is False
    assert "connexion refusee" in resultat["message"]


def test_l_essai_repond_200_meme_en_echec(client):
    """L'ecran a besoin de la trace, qu'un code d'erreur lui refuserait."""
    _smtp(smtp_hote="127.0.0.1", smtp_port=9)      # rien n'ecoute sur 9
    reponse = client.post("/api/alertes/essai",
                          json={"destinataire": "moi@exemple.fr"})
    assert reponse.status_code == 200
    corps = reponse.json()
    assert corps["envoye"] is False
    assert corps["etapes"][0]["nom"] == "configuration"
    assert corps["etapes"][-1]["etat"] == "echec"
    assert corps["conseil"]


def test_la_trace_ne_divulgue_jamais_le_mot_de_passe(client):
    """Elle est faite pour etre affichee : le secret n'y a pas sa place."""
    _smtp(smtp_hote="127.0.0.1", smtp_port=9,
          smtp_utilisateur="moi@exemple.fr", smtp_motdepasse="secret-absolu")
    corps = client.post("/api/alertes/essai",
                        json={"destinataire": "moi@exemple.fr"}).text
    assert "secret-absolu" not in corps


def test_le_conseil_vise_la_cause(base):
    """Un « verifiez vos parametres » n'a aucune prise ; on nomme la piste."""
    from app.metier.alertes import _conseil

    assert "port" in _conseil({"nom": "connexion"}, "Connection refused").lower()
    assert "starttls" in _conseil({"nom": "chiffrement"},
                                  "n'offre pas STARTTLS").lower()
    assert "pop3" in _conseil({"nom": "authentification"},
                              "535 refuse").lower()
    assert "sortie" in _conseil({"nom": "connexion"}, "timed out").lower()
    # Un echec inconnu ne doit pas inventer de piste.
    assert _conseil({"nom": "envoi"}, "quelque chose d'inedit") is None


def test_le_controle_eprouve_ce_que_l_ecran_affiche(client):
    """
    Le geste naturel : remplir les champs, cliquer sur « controle »,
    enregistrer quand cela marche. Sans cela, le controle testait la table
    — vide — pendant que l'ecran montrait une configuration complete, et
    le diagnostic accusait une absence que l'utilisateur voyait remplie.
    """
    # Rien d'enregistre : la table est vide.
    corps = client.post("/api/alertes/essai", json={
        "destinataire": "moi@exemple.fr",
        "smtp": {"hote": "127.0.0.1", "port": 9, "ssl": False,
                 "expediteur": "veille@exemple.fr"},
    }).json()

    assert corps["envoye"] is False
    etapes = {e["nom"]: e for e in corps["etapes"]}
    # La configuration passe : c'est bien le brouillon qui a ete lu.
    assert etapes["configuration"]["etat"] == "ok"
    assert "127.0.0.1:9" in etapes["configuration"]["detail"]
    assert etapes["connexion"]["etat"] == "echec"


def test_sans_brouillon_le_controle_lit_la_table(client):
    """L'ancien comportement reste celui du chemin automatique."""
    _smtp(smtp_hote="127.0.0.1", smtp_port=9)
    corps = client.post("/api/alertes/essai",
                        json={"destinataire": "moi@exemple.fr"}).json()
    assert "127.0.0.1:9" in corps["etapes"][0]["detail"]


def test_le_masque_designe_le_mot_de_passe_enregistre(base):
    """
    L'ecran ne peut pas relire le mot de passe : il affiche des puces et
    les renvoie. Les prendre pour un mot de passe ferait echouer tout
    controle des qu'un secret est enregistre.
    """
    _smtp(smtp_utilisateur="moi@exemple.fr", smtp_motdepasse="vrai-secret")

    effectif = reglages.smtp({"hote": "autre.exemple.fr",
                              "motdepasse": reglages.MASQUE})
    assert effectif["hote"] == "autre.exemple.fr"
    assert effectif["motdepasse"] == "vrai-secret"

    # Un mot de passe reellement saisi remplace bien l'ancien.
    remplace = reglages.smtp({"motdepasse": "nouveau"})
    assert remplace["motdepasse"] == "nouveau"

    # Et la table n'a pas bouge : un controle n'enregistre rien.
    assert reglages.lire("smtp_motdepasse") == "vrai-secret"
    assert reglages.lire("smtp_hote") == "smtp.exemple.fr"


def test_l_etat_dit_quand_l_alerte_part(base):
    """
    « Je n'ai rien recu aujourd'hui » restait sans reponse : l'ecran ne
    disait ni l'heure du passage, ni s'il avait lieu sur ce conteneur, ni
    quels criteres decident d'un envoi.
    """
    from fastapi.testclient import TestClient
    from app.main import application

    with TestClient(application) as client:
        etat = client.get("/api/alertes").json()

    p = etat["planificateur"]
    assert set(p) >= {"actif", "heure", "jours", "fuseau", "prochaine"}
    assert isinstance(p["heure"], int) and 0 <= p["heure"] <= 23
    assert p["fuseau"]

    c = etat["criteres"]
    assert c["fenetre_jours"] and c["surface_min"] and c["surface_max"]
    assert c["type_batiment"]


# =====================================================================
#  Le journal des tentatives
# =====================================================================

def test_chaque_passage_laisse_une_trace_meme_muet(base, monkeypatch):
    """
    C'est LE cas qu'on cherche a expliquer. Sans trace du silence, « je
    n'ai rien recu ce matin » ne se distingue pas de « le passage n'a pas
    eu lieu » — et l'issue partait au journal du conteneur, illisible
    depuis un NAS.
    """
    resultat = alertes.envoyer_si_besoin()
    assert resultat["raison"] == "desactivee"

    tentatives = alertes.journal()
    assert len(tentatives) == 1
    assert tentatives[0]["sujet"] == "dpe"
    assert tentatives[0]["envoye"] == 0
    assert tentatives[0]["raison"] == "desactivee"


def test_un_envoi_reussi_est_journalise_avec_son_compte(base, monkeypatch):
    envois = []
    monkeypatch.setattr("app.sources.courriel.envoyer",
                        lambda *a, **k: envois.append(a) or True)
    reglages.ecrire({"alerte_active": True,
                     "alerte_destinataire": "moi@exemple.fr"})
    inserer_dpe(n_dpe="D1", commune="Mimizan", code_insee="40184",
                surface_habitable=100, type_batiment="maison",
                date_etablissement=datetime.date.today().isoformat())

    resultat = alertes.envoyer_si_besoin()
    assert resultat["envoye"] is True

    trace = alertes.journal()[0]
    assert trace["envoye"] == 1
    assert trace["raison"] == "envoyee"
    assert trace["biens"] == resultat["biens"]
    assert trace["destinataire"] == "moi@exemple.fr"


def test_un_echec_d_envoi_garde_son_message(base, monkeypatch):
    """Le detail de l'echec est ce qu'on vient lire : « serveur
    injoignable » et « identifiants refuses » ne se corrigent pas
    pareil."""
    from app.sources.courriel import ErreurCourriel

    def refuser(*a, **k):
        raise ErreurCourriel("535 identifiants refuses")

    monkeypatch.setattr("app.sources.courriel.envoyer", refuser)
    reglages.ecrire({"alerte_active": True,
                     "alerte_destinataire": "moi@exemple.fr"})
    inserer_dpe(n_dpe="D1", commune="Mimizan", code_insee="40184",
                surface_habitable=100, type_batiment="maison",
                date_etablissement=datetime.date.today().isoformat())

    alertes.envoyer_si_besoin()
    trace = alertes.journal()[0]
    assert trace["raison"] == "echec_envoi"
    assert "535" in trace["message"]


def test_le_journal_ne_melange_pas_dpe_et_ventes(base):
    from app.metier import alerte_ventes

    alertes.envoyer_si_besoin()
    alerte_ventes.envoyer_si_besoin()
    sujets = [t["sujet"] for t in alertes.journal()]
    assert set(sujets) == {"dpe", "ventes"}


def test_un_journal_illisible_ne_fait_pas_echouer_l_alerte(base, monkeypatch):
    """Le journal est un temoin, jamais une condition : une ecriture
    impossible ne doit pas empecher un courriel de partir."""
    def tombe(*a, **k):
        raise RuntimeError("base verrouillee")

    monkeypatch.setattr("app.metier.alertes.transaction", tombe)
    resultat = alertes.envoyer_si_besoin()
    assert resultat["raison"] == "desactivee"      # l'alerte a bien repondu


def test_la_sante_dit_le_rythme_reel_de_l_import(base):
    """
    L'ecran annoncait « Import automatique hebdomadaire » quelle que soit
    la configuration : juste par hasard sur un deploiement hebdomadaire,
    faux sur tous les autres. Or c'est precisement cette ligne qu'on vient
    lire pour savoir pourquoi aucun courriel n'est arrive.
    """
    from fastapi.testclient import TestClient
    from app import config, planificateur
    from app.main import application

    with TestClient(application) as client:
        sante = client.get("/api/sante").json()

    jour, heure = planificateur.horaire()
    assert sante["import_jours"] == jour
    assert sante["import_heure"] == heure
    assert sante["import_fuseau"] == config.FUSEAU


def test_le_courriel_annonce_ses_propres_criteres(base):
    """
    Sans eux, le courriel se lit mal : un appartement de 54 m² au milieu
    d'une liste qu'on croit reservee aux maisons de 80 m² fait douter de
    l'outil, alors que ce sont les reglages qui le veulent. La confusion
    est arrivee — 109 biens dont des surfaces sous le plancher que je
    citais de memoire — et elle ne se dissipait qu'en ouvrant l'ecran.
    """
    reglages.ecrire({"type_batiment": "", "surface_min": 50,
                     "surface_max": 400, "fenetre_jours": 120,
                     "alerte_zone": "plage", "alerte_code_insee": "40184"})
    texte, corps_html = alertes._corps([{
        "n_dpe": "X", "adresse": "1 Rue A", "zone": "plage",
        "surface_habitable": 54, "etiquette_dpe": "C",
        "date_etablissement": "2026-08-20"}])

    for rendu in (texte, corps_html):
        # Le HTML met une majuscule initiale ; on compare sans elle.
        assert "ous types de biens" in rendu
        assert "50" in rendu and "400" in rendu
        assert "120" in rendu
        assert "plage" in rendu

    # La majuscule ne doit pas ecraser le reste de la phrase.
    assert "Tous types de biens" in corps_html
    assert "m²" in corps_html


def test_les_criteres_annonces_suivent_les_reglages(base):
    """Ils sont lus a l'envoi, pas figes : c'est ce qui evite de decrire
    des criteres que l'utilisateur a changes depuis."""
    reglages.ecrire({"type_batiment": "maison", "surface_min": 80,
                     "surface_max": 400, "alerte_zone": ""})
    texte, _ = alertes._corps([{
        "n_dpe": "X", "adresse": "1 Rue A", "zone": "bourg",
        "surface_habitable": 100, "etiquette_dpe": "C",
        "date_etablissement": "2026-08-20"}])
    assert "maison" in texte
    assert "de 80 à 400 m²" in texte
    assert "tous types" not in texte
