# -*- coding: utf-8 -*-
"""
test_ventes_alerte.py — La fenetre glissante DVF, et l'alerte sur les ventes.

Le defaut central que ces tests gardent n'est pas une erreur de calcul mais
une PERTE : DVF ne publie que cinq millesimes, et l'import remplacait la
commune en bloc. Au premier passage suivant la parution d'automne, le
millesime sorti de la fenetre disparaissait de la base — sans message, la
commune paraissant simplement n'avoir eu aucune vente cette annee-la.
"""

import datetime

import pytest

from app.base import reglages
from app.base.connexion import connexion, transaction
from app.metier import alerte_ventes, mutations
from app.sources import dvf


def _ligne(id_mutation, parcelle, valeur, date="2024-11-04", **champs):
    ligne = {
        "id_mutation": id_mutation, "date_mutation": date,
        "nature_mutation": "Vente", "valeur_fonciere": str(valeur),
        "code_commune": "40184", "id_parcelle": parcelle,
        "type_local": "Maison", "surface_reelle_bati": "80",
        "surface_terrain": "500",
        "adresse_numero": "12", "adresse_suffixe": "",
        "adresse_nom_voie": "RUE DES LACS",
        # Le bourg de Mimizan, a quelques metres du repere par defaut.
        "latitude": "44.2011", "longitude": "-1.2286",
    }
    ligne.update(champs)
    return ligne


def _importer(monkeypatch, lignes):
    monkeypatch.setattr("app.sources.dvf.telecharger",
                        lambda code, progression=None: lignes)
    return mutations.importer("40184")


# =====================================================================
#  La fenetre glissante
# =====================================================================

def test_les_millesimes_suivent_l_annee_en_cours():
    """
    Une liste ecrite en dur se serait tue deux fois : en manquant le
    millesime neuf des sa parution, et sans jamais le dire.
    """
    vus = dvf.millesimes(datetime.date(2027, 3, 1))
    assert 2027 in vus, "l'annee en cours doit etre tentee"
    assert 2022 in vus, "cinq millesimes de profondeur"
    assert 2021 not in vus, "au-dela, Etalab ne sert plus rien"


def test_une_vente_sortie_de_la_fenetre_reste_en_base(base, monkeypatch):
    """
    LE test de cette livraison. Etalab ne garde que cinq millesimes :
    verifie le 24/08/2026, 2019 et 2020 rendent 404 pour toutes les
    communes, Toulouse comprise. Quand 2026 entrera, 2021 sortira — et la
    base est alors le SEUL endroit ou cette vente subsiste.

    Il echoue si l'import remplace la commune en bloc.
    """
    _importer(monkeypatch, [
        _ligne("M-2021", "40184000AA0265", 300000, date="2021-05-10"),
        _ligne("M-2025", "40184000AA0266", 400000, date="2025-05-10"),
    ])

    # Parution d'automne : 2021 est sorti de la fenetre, la source ne le
    # sert plus. Seul 2025 revient.
    _importer(monkeypatch, [
        _ligne("M-2025", "40184000AA0266", 400000, date="2025-05-10"),
        _ligne("M-2026", "40184000AA0267", 500000, date="2026-03-01"),
    ])

    with connexion() as conn:
        gardees = {l["id"] for l in conn.execute("SELECT id FROM mutation")}
    assert "M-2021" in gardees, (
        "la vente de 2021 a ete effacee : elle n'existe plus nulle part")
    assert gardees == {"M-2021", "M-2025", "M-2026"}


def test_une_correction_met_a_jour_sans_dupliquer(base, monkeypatch):
    """DVF corrige parfois une vente passee : elle doit etre mise a jour,
    pas ajoutee une seconde fois."""
    _importer(monkeypatch, [_ligne("M1", "40184000AA0265", 300000)])
    _importer(monkeypatch, [_ligne("M1", "40184000AA0265", 325000)])

    with connexion() as conn:
        lignes = list(conn.execute("SELECT id, valeur_fonciere FROM mutation"))
    assert len(lignes) == 1
    assert lignes[0]["valeur_fonciere"] == 325000


def test_une_correction_ne_fait_pas_resignaler_la_vente(base, monkeypatch):
    """
    `alerte_le` appartient a la ligne en base, pas au fichier. Sans cela,
    chaque republication semestrielle re-signalerait TOUTES les ventes du
    millesime corrige comme si elles etaient neuves.
    """
    _importer(monkeypatch, [_ligne("M1", "40184000AA0265", 300000)])
    _importer(monkeypatch, [_ligne("M2", "40184000AA0266", 400000)])
    alerte_ventes.marquer(["M2"])

    _importer(monkeypatch, [_ligne("M2", "40184000AA0266", 410000)])
    with connexion() as conn:
        ligne = conn.execute(
            "SELECT alerte_le, valeur_fonciere FROM mutation WHERE id = 'M2'"
        ).fetchone()
    assert ligne["valeur_fonciere"] == 410000, "la correction doit passer"
    assert ligne["alerte_le"] is not None, "mais la vente reste signalee"


def test_une_parcelle_retiree_d_une_vente_disparait(base, monkeypatch):
    """Une correction peut retirer une parcelle : le rattachement ancien
    ne doit pas survivre, sans quoi la fiche montrerait une vente qui ne
    la concerne plus."""
    _importer(monkeypatch, [
        _ligne("M1", "40184000AA0265", 300000),
        _ligne("M1", "40184000AA0266", 300000),
    ])
    _importer(monkeypatch, [_ligne("M1", "40184000AA0265", 300000)])

    with connexion() as conn:
        parcelles = {l["parcelle_id"] for l in conn.execute(
            "SELECT parcelle_id FROM mutation_parcelle WHERE mutation_id = 'M1'")}
    assert parcelles == {"40184000AA0265"}


# =====================================================================
#  Ce qui est signale
# =====================================================================

def test_le_premier_import_ne_signale_rien(base, monkeypatch):
    """
    Decouvrir une commune apporte son historique entier — 2 054 ventes
    pour Mimizan. Ce n'est pas une actualite, et un courriel les listant
    serait illisible et faux de sens.
    """
    resultat = _importer(monkeypatch, [
        _ligne(f"M{n}", f"40184000AA{n:04d}", 300000) for n in range(50)])
    assert resultat["premier_import"] is True
    assert resultat["nouvelles"] == 0
    assert alerte_ventes.candidats() == []


def test_une_vente_arrivee_ensuite_est_signalee(base, monkeypatch):
    _importer(monkeypatch, [_ligne("M1", "40184000AA0265", 300000)])
    _importer(monkeypatch, [
        _ligne("M1", "40184000AA0265", 300000),
        _ligne("M2", "40184000AA0266", 400000, date="2026-02-01"),
    ])
    assert [v["id"] for v in alerte_ventes.candidats()] == ["M2"]


def test_le_secteur_restreint_les_ventes_signalees(base, monkeypatch):
    """
    « Histoire de ne pas avoir des alertes sur tout » : le perimetre est
    celui des alertes DPE, commune ET secteur.
    """
    reglages.ecrire({"alerte_code_insee": "40184", "alerte_zone": "plage"})
    _importer(monkeypatch, [_ligne("M0", "40184000AA0100", 200000)])
    _importer(monkeypatch, [
        _ligne("M0", "40184000AA0100", 200000),
        # Au bourg : hors du secteur surveille.
        _ligne("M1", "40184000AA0265", 300000,
               latitude="44.2011", longitude="-1.2286"),
        # A la plage.
        _ligne("M2", "40184000AA0266", 400000,
               latitude="44.2044", longitude="-1.2914"),
    ])
    assert [v["id"] for v in alerte_ventes.candidats()] == ["M2"]


def test_une_vente_sans_position_n_est_pas_rangee_dans_un_secteur(base, monkeypatch):
    """Sans position, on ne peut pas affirmer qu'elle est dans le secteur.
    La taire vaut mieux que l'y ranger au hasard."""
    reglages.ecrire({"alerte_code_insee": "40184", "alerte_zone": "plage"})
    _importer(monkeypatch, [_ligne("M0", "40184000AA0100", 200000)])
    _importer(monkeypatch, [
        _ligne("M0", "40184000AA0100", 200000),
        _ligne("M1", "40184000AA0265", 300000, latitude="", longitude=""),
    ])
    assert alerte_ventes.candidats() == []


def test_sans_secteur_toutes_les_ventes_de_la_commune_comptent(base, monkeypatch):
    reglages.ecrire({"alerte_code_insee": "40184", "alerte_zone": ""})
    _importer(monkeypatch, [_ligne("M0", "40184000AA0100", 200000)])
    _importer(monkeypatch, [
        _ligne("M0", "40184000AA0100", 200000),
        _ligne("M1", "40184000AA0265", 300000),
        _ligne("M2", "40184000AA0266", 400000, latitude="44.2044",
               longitude="-1.2914"),
    ])
    assert {v["id"] for v in alerte_ventes.candidats()} == {"M1", "M2"}


# =====================================================================
#  Le guet de la publication
# =====================================================================

def _signatures(monkeypatch, table):
    monkeypatch.setattr("app.sources.dvf.signatures",
                        lambda code, annees=None: table)


def test_le_premier_releve_ne_declenche_rien(base, monkeypatch):
    """
    Sans point de comparaison, tout paraitrait neuf : l'import complet
    partirait pour apprendre ce que la base sait deja.
    """
    _signatures(monkeypatch, {2025: "aaa", 2026: None})
    etat = mutations.publication("40184")
    assert etat["premier_releve"] is True
    assert etat["changees"] == []


def test_une_publication_inchangee_ne_declenche_rien(base, monkeypatch):
    _signatures(monkeypatch, {2025: "aaa", 2026: None})
    mutations.publication("40184")
    assert mutations.publication("40184")["changees"] == []


def test_un_millesime_republie_est_detecte(base, monkeypatch):
    _signatures(monkeypatch, {2025: "aaa", 2026: None})
    mutations.publication("40184")
    _signatures(monkeypatch, {2025: "bbb", 2026: None})
    assert mutations.publication("40184")["changees"] == [2025]


def test_un_millesime_neuf_est_detecte(base, monkeypatch):
    """La parution d'automne fait apparaitre l'annee en cours."""
    _signatures(monkeypatch, {2025: "aaa", 2026: None})
    mutations.publication("40184")
    _signatures(monkeypatch, {2025: "aaa", 2026: "ccc"})
    assert mutations.publication("40184")["changees"] == [2026]


def test_un_millesime_absent_ne_clignote_pas(base, monkeypatch):
    """
    L'annee en cours rend 404 jusqu'a la parution d'automne. La comparer
    chaque jour ferait clignoter un changement qui n'existe pas — et un
    import complet quotidien avec.
    """
    _signatures(monkeypatch, {2025: "aaa", 2026: None})
    mutations.publication("40184")
    for _ in range(5):
        assert mutations.publication("40184")["changees"] == []


# =====================================================================
#  Le courriel
# =====================================================================

class FauxCourriel:
    def __init__(self):
        self.envois = []

    def __call__(self, destinataire, sujet, texte, html=None, **reste):
        self.envois.append({"destinataire": destinataire, "sujet": sujet,
                            "texte": texte, "html": html})
        return True


@pytest.fixture()
def poste(monkeypatch):
    faux = FauxCourriel()
    monkeypatch.setattr("app.sources.courriel.envoyer", faux)
    return faux


def _deux_imports(monkeypatch, secondes):
    _importer(monkeypatch, [_ligne("M0", "40184000AA0100", 200000)])
    _importer(monkeypatch, [_ligne("M0", "40184000AA0100", 200000)] + secondes)


def test_rien_ne_part_si_l_alerte_est_desactivee(base, monkeypatch, poste):
    reglages.ecrire({"alerte_active": False,
                     "alerte_destinataire": "moi@exemple.fr"})
    _deux_imports(monkeypatch, [_ligne("M1", "40184000AA0265", 300000)])
    assert alerte_ventes.envoyer_si_besoin()["raison"] == "desactivee"
    assert poste.envois == []


def test_activer_l_alerte_sans_destinataire_est_refuse(base):
    """Les Reglages refusent l'etat absurde a la source : une alerte
    active sans personne a prevenir ne se verrait qu'au premier bien
    manque."""
    with pytest.raises(ValueError, match="destinataire"):
        reglages.ecrire({"alerte_active": True, "alerte_destinataire": ""})


def test_rien_ne_part_si_le_destinataire_a_ete_efface(base, monkeypatch, poste):
    """L'adresse peut etre effacee APRES activation : ce chemin-la reste
    ouvert, et l'envoi doit s'y taire plutot que de lever."""
    reglages.ecrire({"alerte_active": True,
                     "alerte_destinataire": "moi@exemple.fr"})
    reglages.ecrire({"alerte_destinataire": ""})
    _deux_imports(monkeypatch, [_ligne("M1", "40184000AA0265", 300000)])
    assert alerte_ventes.envoyer_si_besoin()["raison"] == "sans_destinataire"
    assert poste.envois == []


def test_les_ventes_peuvent_etre_tues_seules(base, monkeypatch, poste):
    """On peut vouloir les DPE sans les ventes."""
    reglages.ecrire({"alerte_active": True, "alerte_ventes_active": False,
                     "alerte_destinataire": "moi@exemple.fr"})
    _deux_imports(monkeypatch, [_ligne("M1", "40184000AA0265", 300000)])
    assert alerte_ventes.envoyer_si_besoin()["raison"] == "ventes_desactivees"
    assert poste.envois == []


def test_une_vente_neuve_part_et_n_est_pas_repetee(base, monkeypatch, poste):
    reglages.ecrire({"alerte_active": True,
                     "alerte_destinataire": "moi@exemple.fr"})
    _deux_imports(monkeypatch, [_ligne("M1", "40184000AA0265", 300000)])

    resultat = alerte_ventes.envoyer_si_besoin()
    assert resultat["envoye"] is True and resultat["ventes"] == 1
    assert len(poste.envois) == 1
    assert "RUE DES LACS" in poste.envois[0]["texte"]

    # Le second passage ne doit rien renvoyer.
    assert alerte_ventes.envoyer_si_besoin()["raison"] == "rien_de_neuf"
    assert len(poste.envois) == 1


def test_un_echec_d_envoi_ne_consomme_pas_les_ventes(base, monkeypatch):
    """Une alerte en retard vaut mieux qu'une alerte perdue."""
    from app.sources.courriel import ErreurCourriel

    def refuser(*args, **kwargs):
        raise ErreurCourriel("serveur injoignable")

    monkeypatch.setattr("app.sources.courriel.envoyer", refuser)
    reglages.ecrire({"alerte_active": True,
                     "alerte_destinataire": "moi@exemple.fr"})
    _deux_imports(monkeypatch, [_ligne("M1", "40184000AA0265", 300000)])

    assert alerte_ventes.envoyer_si_besoin()["raison"] == "echec_envoi"
    assert [v["id"] for v in alerte_ventes.candidats()] == ["M1"]


def test_le_courriel_ne_multiplie_pas_le_prix(base, monkeypatch, poste):
    """
    Le piege du fichier source, jusque dans le courriel : une vente a
    400 000 EUR etalee sur quatre lignes ne doit pas s'y annoncer a
    1 600 000.
    """
    reglages.ecrire({"alerte_active": True,
                     "alerte_destinataire": "moi@exemple.fr"})
    _importer(monkeypatch, [_ligne("M0", "40184000AA0100", 200000)])
    _importer(monkeypatch, [
        _ligne("M0", "40184000AA0100", 200000),
        _ligne("M1", "40184000AA0265", 400000, surface_reelle_bati="80"),
        _ligne("M1", "40184000AA0266", 400000, surface_reelle_bati="30",
               type_local="Dépendance"),
        _ligne("M1", "40184000AA0267", 400000, surface_reelle_bati="124",
               type_local="Dépendance"),
    ])
    alerte_ventes.envoyer_si_besoin()
    # Les espaces du montant sont insecables : on compare sur un texte
    # normalise, sans quoi le test porterait sur la typographie plutot
    # que sur l'arithmetique.
    texte = " ".join(poste.envois[0]["texte"].split())
    assert "400 000 €" in texte
    assert "1 600 000" not in texte


def test_le_prix_au_m2_se_tait_quand_la_vente_porte_sur_plusieurs_biens(
        base, monkeypatch, poste):
    """Rapporter le prix d'une maison ET de son garage a la seule surface
    de la maison donne un chiffre faux, et flatteur."""
    reglages.ecrire({"alerte_active": True,
                     "alerte_destinataire": "moi@exemple.fr"})
    _importer(monkeypatch, [_ligne("M0", "40184000AA0100", 200000)])
    _importer(monkeypatch, [
        _ligne("M0", "40184000AA0100", 200000),
        _ligne("M1", "40184000AA0265", 400000, surface_reelle_bati="80"),
        _ligne("M1", "40184000AA0266", 400000, surface_reelle_bati="30",
               type_local="Dépendance"),
    ])
    alerte_ventes.envoyer_si_besoin()
    assert "€/m²" not in poste.envois[0]["texte"]


# =====================================================================
#  Le passage de version
# =====================================================================

def test_la_migration_ne_transforme_pas_l_historique_en_nouveautes(tmp_path):
    """
    La base du NAS contient deja 2 054 ventes, importees avant que
    l'alerte n'existe. `alerte_le` y nait donc a NULL — et sans
    precaution, le premier courriel les listerait TOUTES.

    Ce chemin ne s'emprunte qu'une fois par base : il ne casserait pas un
    test au passage, il enverrait un courriel absurde le jour de la
    parution. On le joue donc pour de bon, sur une base a part.
    """
    import shutil
    import sqlite3

    from app.base import migrations

    sept = migrations.DOSSIER_SCHEMA / "007_ventes.sql"
    garde = tmp_path / "007.sql"
    shutil.copy(sept, garde)

    base = tmp_path / "nas.db"
    conn = sqlite3.connect(base)
    try:
        # La base telle qu'elle est aujourd'hui : migree jusqu'au 006.
        conn.execute("CREATE TABLE migration (nom TEXT PRIMARY KEY,"
                     " applique_le TEXT NOT NULL)")
        for chemin in sorted(migrations.DOSSIER_SCHEMA.glob("*.sql")):
            if chemin.name >= "007":
                continue
            conn.executescript(chemin.read_text(encoding="utf-8"))
            conn.execute("INSERT INTO migration VALUES (?, '2026-01-01')",
                         (chemin.name,))
        conn.executemany(
            "INSERT INTO mutation (id, code_insee, date_mutation, nature,"
            " valeur_fonciere, nb_parcelles, nb_locaux, types_locaux_json,"
            " importe_le) VALUES (?,'40184','2021-05-10','Vente',300000,1,1,"
            " '[]','2026-01-01T10:00:00')",
            [(f"M{n}",) for n in range(200)])
        conn.commit()

        # Le passage de version.
        conn.executescript(garde.read_text(encoding="utf-8"))
        conn.commit()

        restantes = conn.execute(
            "SELECT count(*) FROM mutation WHERE alerte_le IS NULL").fetchone()[0]
    finally:
        conn.close()

    assert restantes == 0, (
        f"{restantes} ventes d'archive seraient signalees comme neuves")


def test_le_guet_quotidien_ne_telecharge_rien_sans_parution(base, monkeypatch):
    """
    L'interet du guet est la : une requete HEAD par millesime, et pas un
    octet de CSV les trois cent soixante-trois jours ou DVF n'a rien
    publie. Sans cela, il faudrait retirer un megaoctet chaque jour pour
    decouvrir deux fois l'an qu'il a bouge.
    """
    import app.planificateur as planificateur

    telechargements = []
    monkeypatch.setattr("app.sources.dvf.telecharger",
                        lambda code, progression=None: telechargements.append(code) or [])
    _signatures(monkeypatch, {2025: "aaa", 2026: None})
    reglages.ecrire({"alerte_code_insee": "40184"})

    planificateur._ventes()          # premier releve
    for _ in range(10):              # dix jours sans parution
        planificateur._ventes()
    assert telechargements == [], "le guet a telecharge sans raison"

    # Parution : la, on telecharge.
    _signatures(monkeypatch, {2025: "bbb", 2026: None})
    planificateur._ventes()
    assert telechargements == ["40184"]


# =====================================================================
#  La renumerotation
# =====================================================================

def test_une_vente_republiee_sous_un_autre_numero_est_reconnue(base, monkeypatch):
    """
    `id_mutation` est un numero d'ordre, pas une clef. Mesure sur
    Mimizan 2021 : deux chaines de publication decrivent les MEMES 574
    ventes avec seulement 15 identifiants en commun, et le meme numero y
    designe deux ventes sans rapport.

    Si l'import ne s'appuyait que sur le numero, une republication
    renumerotee ferait deux degats d'un coup : les anciennes lignes
    resteraient en base en doublon, et toutes les ventes du millesime
    paraitraient neuves — le courriel en annoncerait des centaines.
    """
    _importer(monkeypatch, [
        _ligne("2021-111", "40184000AA0265", 300000, date="2021-05-10"),
        _ligne("2021-112", "40184000AA0266", 400000, date="2021-06-20"),
    ])

    # Meme millesime, memes ventes, numeros entierement differents.
    resultat = _importer(monkeypatch, [
        _ligne("2021-999", "40184000AA0265", 300000, date="2021-05-10"),
        _ligne("2021-998", "40184000AA0266", 400000, date="2021-06-20"),
    ])

    with connexion() as conn:
        total = conn.execute("SELECT count(*) FROM mutation").fetchone()[0]
    assert total == 2, f"{total} lignes : la republication a fait des doublons"
    assert resultat["renumerotees"] == 2
    assert alerte_ventes.candidats() == [], (
        "des ventes deja connues seraient annoncees comme neuves")


def test_la_renumerotation_ne_perd_pas_le_marquage(base, monkeypatch):
    """Une vente deja signalee ne doit pas l'etre a nouveau parce que son
    numero a change."""
    _importer(monkeypatch, [_ligne("2021-111", "40184000AA0265", 300000,
                                   date="2021-05-10")])
    _importer(monkeypatch, [
        _ligne("2021-111", "40184000AA0265", 300000, date="2021-05-10"),
        _ligne("2021-112", "40184000AA0266", 400000, date="2021-06-20"),
    ])
    alerte_ventes.marquer([v["id"] for v in alerte_ventes.candidats()])
    assert alerte_ventes.candidats() == []

    # Republication renumerotee : rien ne doit reparaitre.
    _importer(monkeypatch, [
        _ligne("2021-777", "40184000AA0265", 300000, date="2021-05-10"),
        _ligne("2021-778", "40184000AA0266", 400000, date="2021-06-20"),
    ])
    assert alerte_ventes.candidats() == []


def test_deux_ventes_indiscernables_restent_deux(base, monkeypatch):
    """
    Trois paires sur les 2 054 ventes de Mimizan partagent date, montant
    ET parcelles — `numero_disposition` compris. Les confondre en
    perdrait une ; un rang les distingue.
    """
    _importer(monkeypatch, [
        _ligne("A", "40184000AA0265", 172000, date="2021-10-01"),
        _ligne("B", "40184000AA0265", 172000, date="2021-10-01"),
    ])
    with connexion() as conn:
        total = conn.execute("SELECT count(*) FROM mutation").fetchone()[0]
        empreintes = [l["empreinte"] for l in conn.execute(
            "SELECT empreinte FROM mutation ORDER BY empreinte")]
    assert total == 2, "une des deux ventes jumelles a ete perdue"
    assert empreintes[1].endswith("#2")

    # Et une reimportation ne doit pas les dedoubler non plus.
    _importer(monkeypatch, [
        _ligne("C", "40184000AA0265", 172000, date="2021-10-01"),
        _ligne("D", "40184000AA0265", 172000, date="2021-10-01"),
    ])
    with connexion() as conn:
        assert conn.execute("SELECT count(*) FROM mutation").fetchone()[0] == 2


# =====================================================================
#  La reprise d'historique ancien
# =====================================================================

def _archiver(monkeypatch, lignes):
    monkeypatch.setattr("app.sources.dvf_archive.telecharger",
                        lambda code, progression=None: lignes)
    return mutations.reprendre_archive("40184")


def test_la_reprise_ajoute_les_millesimes_disparus(base, monkeypatch):
    """
    DVF ne se consulte que sur cinq ans, et la restriction est en amont
    d'Etalab : le jeu officiel de la DGFiP n'en offre pas davantage.
    L'archive rend les millesimes qu'aucune source vivante ne sert plus.
    """
    _importer(monkeypatch, [_ligne("2021-1", "40184000AA0265", 300000,
                                   date="2021-05-10")])
    resultat = _archiver(monkeypatch, [
        # Numeros de l'AUTRE chaine de publication : sans rapport.
        _ligne("A-77", "40184000AA0100", 150000, date="2018-03-02"),
        _ligne("A-78", "40184000AA0101", 160000, date="2019-07-15"),
        _ligne("A-79", "40184000AA0265", 300000, date="2021-05-10"),
    ])
    assert resultat["ajoutees"] == 2, "seules les ventes inconnues s'ajoutent"
    assert resultat["depuis"] == "2018-03-02"

    with connexion() as conn:
        total = conn.execute("SELECT count(*) FROM mutation").fetchone()[0]
    assert total == 3, "la vente de 2021 a ete dupliquee"


def test_la_reprise_ne_signale_rien(base, monkeypatch):
    """Annoncer par courriel des ventes de 2018 n'aurait aucun sens : ce
    n'est pas une actualite, c'est de l'histoire."""
    _importer(monkeypatch, [_ligne("2021-1", "40184000AA0265", 300000,
                                   date="2021-05-10")])
    _importer(monkeypatch, [
        _ligne("2021-1", "40184000AA0265", 300000, date="2021-05-10")])
    _archiver(monkeypatch, [
        _ligne("A-77", "40184000AA0100", 150000, date="2018-03-02"),
        _ligne("A-78", "40184000AA0101", 160000, date="2019-07-15"),
    ])
    assert alerte_ventes.candidats() == []


def test_deux_reprises_ne_dupliquent_rien(base, monkeypatch):
    lignes = [_ligne("A-77", "40184000AA0100", 150000, date="2018-03-02")]
    _importer(monkeypatch, [_ligne("2021-1", "40184000AA0265", 300000,
                                   date="2021-05-10")])
    _archiver(monkeypatch, lignes)
    second = _archiver(monkeypatch, lignes)
    assert second["ajoutees"] == 0


def test_un_import_courant_ne_detruit_pas_l_archive(base, monkeypatch):
    """
    Le point qui compte : geo-dvf ne servira jamais 2018. Si l'import
    courant effacait ce qu'il ne voit pas, la reprise serait annulee au
    passage suivant.
    """
    _importer(monkeypatch, [_ligne("2021-1", "40184000AA0265", 300000,
                                   date="2021-05-10")])
    _archiver(monkeypatch, [
        _ligne("A-77", "40184000AA0100", 150000, date="2018-03-02")])

    _importer(monkeypatch, [_ligne("2021-1", "40184000AA0265", 300000,
                                   date="2021-05-10")])
    with connexion() as conn:
        anciennes = conn.execute(
            "SELECT count(*) FROM mutation WHERE date_mutation < '2019'"
        ).fetchone()[0]
    assert anciennes == 1, "l'import courant a efface l'archive"


def test_la_profondeur_dit_ce_que_la_base_garde_en_plus(base, monkeypatch):
    """La profondeur ne se devine pas : la source n'offre que cinq ans, et
    rien d'autre ne dit ou l'on en est."""
    _importer(monkeypatch, [_ligne("2021-1", "40184000AA0265", 300000,
                                   date="2021-05-10")])
    _archiver(monkeypatch, [
        _ligne("A-77", "40184000AA0100", 150000, date="2018-03-02")])

    p = mutations.profondeur("40184")
    assert p["ventes"] == 2
    assert p["depuis"] == "2018-03-02"
    assert min(p["millesimes_source"]) > 2018, (
        "2018 doit etre hors de ce que la source sert encore")
