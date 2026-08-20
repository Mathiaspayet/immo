# -*- coding: utf-8 -*-
"""
import_dpe.py — Recuperation des DPE et mise en cache en base.

Trois exigences du cahier des charges se rejoignent ici :

  - CDC 4 : aucun appel externe ne doit etre declenche par l'affichage
    d'une page. On telecharge donc tout d'avance, et l'ecran Veille ne lit
    que la base.

  - CDC 8 : un echec ne doit jamais laisser la base dans un etat partiel.
    L'ecriture se fait en une seule transaction, apres que tout a ete
    telecharge et transforme.

  - CDC 7 : toute operation longue affiche sa progression. L'etat courant
    est publie au fil de l'eau et lisible par l'API.

On enregistre toutes les lignes du code postal, sans appliquer les filtres
de surface ou de type : ces filtres appartiennent a l'affichage. Les
changer ne doit pas obliger a retelecharger.
"""

import datetime
import json
import logging
import threading

from app.base import reglages
from app.base.connexion import connexion, transaction
from app.metier import coordonnees, zones
from app.metier.valeurs import entier, nombre, texte
from app.metier import parcelles as metier_parcelles
from app.sources import ademe, geo
from app.sources.client_http import ErreurSource

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------
#  Etat courant, partage entre le thread d'import et l'API
# ---------------------------------------------------------------------
_verrou = threading.Lock()
_etat = {
    "en_cours": False,
    "declencheur": None,
    "debut": None,
    "fin": None,
    "etape": "",
    "lignes": 0,
    "ajouts": 0,
    "statut": None,      # succes | echec
    "message": None,
    "journal_id": None,
}


def etat():
    """Copie de l'etat courant, pour l'API de progression."""
    with _verrou:
        return dict(_etat)


def _publier(**champs):
    with _verrou:
        _etat.update(champs)


def _maintenant():
    return datetime.datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------------
#  Transformation d'une ligne ADEME en enregistrement `dpe`
# ---------------------------------------------------------------------

def transformer(ligne, correspondances, points_de_zone, jeu, code_postal_demande,
                communes_par_insee=None, zones_code_insee=""):
    """Convertit une ligne brute de l'API en dictionnaire pret pour la base."""
    lire = lambda concept: ligne.get(correspondances[concept]) if correspondances.get(concept) else None

    n_dpe = texte(lire("numero_dpe"))
    if not n_dpe:
        return None      # sans numero, la ligne n'est pas identifiable

    position = coordonnees.extraire(
        geopoint=lire("geopoint"), x=lire("x_lambert"), y=lire("y_lambert"),
        latitude=lire("latitude"), longitude=lire("longitude"))
    latitude, longitude = position if position else (None, None)

    # La base ancienne ne porte aucun nom de commune : seul son code
    # INSEE l'identifie. On le traduit avec le referentiel de
    # geo.api.gouv.fr, sans quoi tout le filtrage par commune tomberait.
    # Le nom officiel du referentiel prime sur celui de l'ADEME : d'une base
    # a l'autre la meme commune s'ecrit « Mimizan », « MIMIZAN » ou
    # « PONTENX LES FORGES », ce qui eclaterait les regroupements.
    code_insee = texte(lire("code_insee"))
    officiel = (communes_par_insee or {}).get(code_insee) or {}
    commune = officiel.get("nom") or texte(lire("commune"))

    # Les secteurs ne valent que dans la commune ou leurs reperes ont ete
    # places : ailleurs, le « point le plus proche » n'a aucun sens.
    if zones_code_insee and code_insee != zones_code_insee:
        zone, distance = None, None
    else:
        zone, distance = zones.rattacher(latitude, longitude, points_de_zone)

    return {
        "n_dpe": n_dpe,
        "code_insee": code_insee,
        "code_postal": texte(lire("code_postal")) or code_postal_demande,
        "commune": commune,
        "adresse": texte(lire("adresse")),
        "latitude": latitude,
        "longitude": longitude,
        "zone": zone,
        "distance_zone_m": distance,
        "date_etablissement": (texte(lire("date")) or "")[:10] or None,
        "surface_habitable": nombre(lire("surface")),
        "type_batiment": texte(lire("type_batiment")),
        "etiquette_dpe": (texte(lire("etiquette_dpe")) or "").upper() or None,
        "etiquette_ges": (texte(lire("etiquette_ges")) or "").upper() or None,
        "conso_ep_m2": nombre(lire("conso_primaire")),
        "conso_ef_m2": nombre(lire("conso_finale")),
        "ges_m2": nombre(lire("ges_m2")),
        "cout_annuel": nombre(lire("cout_annuel")),
        "annee_construction": entier(lire("annee")),
        "n_dpe_remplace": texte(lire("n_dpe_remplace")),
        "jeu_de_donnees": jeu,
        # On conserve la ligne telle qu'elle est arrivee : les besoins
        # evolueront et la base ADEME compte plus de 200 colonnes (CDC 6).
        # Seules les colonnes demandees y figurent ; elargir la selection
        # se fait dans sources/ademe.py, sans toucher au schema.
        "donnees_brutes_json": json.dumps(ligne, ensure_ascii=False),
    }


COLONNES = [
    "n_dpe", "code_insee", "code_postal", "commune", "adresse", "latitude",
    "longitude", "zone", "distance_zone_m", "date_etablissement",
    "surface_habitable", "type_batiment", "etiquette_dpe", "etiquette_ges",
    "conso_ep_m2", "conso_ef_m2", "ges_m2", "cout_annuel",
    "annee_construction", "n_dpe_remplace", "jeu_de_donnees",
    "donnees_brutes_json",
]

# A la mise a jour, on ne touche ni a `importe_le`, ni a `vu_le`, ni a
# `alerte_le` : la premiere appartient a l'historique, la deuxieme a
# l'utilisateur, la troisieme au journal des alertes deja parties.
# `revu_le` en revanche est rafraichi a chaque passage : c'est lui qui dit
# que l'ADEME sert encore cette ligne (voir 002_lot2.sql).
_MAJ = ", ".join(f"{c} = excluded.{c}" for c in COLONNES if c != "n_dpe")

SQL_UPSERT = (
    f"INSERT INTO dpe ({', '.join(COLONNES)}, importe_le, revu_le, vu_le, alerte_le) "
    f"VALUES ({', '.join('?' * len(COLONNES))}, ?, ?, ?, ?) "
    f"ON CONFLICT(n_dpe) DO UPDATE SET {_MAJ}, revu_le = excluded.revu_le"
)


# ---------------------------------------------------------------------
#  Import complet
# ---------------------------------------------------------------------

def communes_suivies():
    """
    Les communes deja consultees, avec la date de leur derniere moisson.

    C'est le registre de l'application : on n'y declare rien a l'avance, il
    se remplit a mesure qu'on consulte des communes. C'est lui que l'import
    hebdomadaire rafraichit.
    """
    with connexion() as conn:
        return [dict(ligne) for ligne in conn.execute(
            "SELECT code_insee, nom, code_postal, derniere_maj_dpe FROM commune "
            "ORDER BY derniere_maj_dpe IS NULL DESC, nom")]


def age_commune(code_insee):
    """Heures ecoulees depuis la derniere moisson de cette commune, ou None."""
    with connexion() as conn:
        ligne = conn.execute(
            "SELECT derniere_maj_dpe FROM commune WHERE code_insee = ?",
            (str(code_insee),)).fetchone()
    if ligne is None or not ligne["derniere_maj_dpe"]:
        return None
    try:
        moisson = datetime.datetime.fromisoformat(ligne["derniere_maj_dpe"])
    except ValueError:
        return None
    return (datetime.datetime.now() - moisson).total_seconds() / 3600


# ---------------------------------------------------------------------
#  Moisson
# ---------------------------------------------------------------------

def _demarrer(declencheur, quoi):
    """Prend le verrou et ouvre le journal. Leve si une moisson tourne deja."""
    with _verrou:
        if _etat["en_cours"]:
            raise RuntimeError("Un import est deja en cours.")
        _etat.update({"en_cours": True, "declencheur": declencheur,
                      "debut": _maintenant(), "fin": None,
                      "etape": f"demarrage — {quoi}", "lignes": 0, "ajouts": 0,
                      "statut": None, "message": None, "journal_id": None,
                      "cible": quoi})
    journal_id = _ouvrir_journal(declencheur)
    _publier(journal_id=journal_id)
    return journal_id


def _terminer(journal_id, resume=None, erreur=None):
    if erreur is not None:
        message = str(erreur) or type(erreur).__name__
        _fermer_journal(journal_id, "echec", 0, 0, message)
        _publier(en_cours=False, fin=_maintenant(), statut="echec", message=message)
        return
    _fermer_journal(journal_id, "succes", resume["lignes"], resume["ajouts"],
                    resume["message"])
    _publier(en_cours=False, fin=_maintenant(), statut="succes",
             message=resume["message"], lignes=resume["lignes"],
             ajouts=resume["ajouts"], etape="termine")


def importer_commune(code_insee, declencheur="commune", jeux=None,
                     avec_dpe=True, avec_cadastre=False):
    """
    Moissonne UNE commune : ses DPE, son cadastre, ou les deux.

    C'est l'operation de base de l'application : on consulte une commune, on
    l'importe. Le code postal ne sert plus a filtrer — le 31140 couvre sept
    communes, le 40200 en couvre cinq, et on n'en veut qu'une.

    Les deux travaux sont independants : demander le cadastre d'une commune
    dont les DPE sont a jour ne doit pas les retelecharger.
    """
    code_insee = str(code_insee).strip()
    fiche = geo.commune_par_insee(code_insee) or {}
    nom = fiche.get("nom") or code_insee

    quoi = nom + ("" if avec_dpe else " — cadastre")
    journal_id = _demarrer(declencheur, quoi)
    resume = {"lignes": 0, "ajouts": 0, "message": ""}

    try:
        if avec_dpe:
            resume = _moissonner([{"code_insee": code_insee, "nom": nom,
                                   "code_postal": fiche.get("code_postal")}], jeux)
    except Exception as erreur:                      # noqa: BLE001
        logger.exception("import de %s en echec : %s", nom, erreur)
        _terminer(journal_id, erreur=erreur)
        raise

    if avec_cadastre:
        # Le cadastre vient apres les DPE : il s'appuie sur eux pour le
        # rattachement. Son echec ne doit pas invalider la moisson.
        try:
            _publier(etape=f"{nom} — cadastre")
            cadastre = metier_parcelles.importer_cadastre(
                code_insee, progression=lambda message: _publier(etape=message))
            resume["message"] = " · ".join(
                filter(None, [resume["message"], cadastre["message"]]))
        except Exception as erreur:                  # noqa: BLE001
            logger.warning("cadastre de %s indisponible : %s", nom, erreur)
            resume["message"] = " · ".join(filter(None, [
                resume["message"], f"cadastre indisponible ({erreur})"]))

    if not resume["message"]:
        resume["message"] = f"{nom} — rien a faire"
    _terminer(journal_id, resume=resume)
    return resume


def importer(declencheur="planifie", jeux=None):
    """
    Rafraichit toutes les communes deja consultees.

    C'est ce que lance le planificateur hebdomadaire. Sans commune au
    registre, il n'y a rien a rafraichir et on le dit.
    """
    communes = communes_suivies()
    if not communes:
        raise ErreurSource(
            "Aucune commune n'a encore ete consultee : il n'y a rien a "
            "rafraichir. Choisissez une commune depuis l'accueil.")

    journal_id = _demarrer(declencheur, f"{len(communes)} commune(s)")
    try:
        resume = _moissonner(communes, jeux)
    except Exception as erreur:                      # noqa: BLE001
        logger.exception("rafraichissement en echec : %s", erreur)
        _terminer(journal_id, erreur=erreur)
        raise

    # Le cadastre se rafraichit mensuellement (CDC 8), et seulement la ou il
    # est deja pose : on ne va pas le telecharger pour une commune dont
    # personne n'a demande les parcelles.
    cadastres = _rafraichir_cadastres()
    if cadastres:
        resume["message"] += f" · cadastre : {cadastres}"

    _terminer(journal_id, resume=resume)
    return resume


def _rafraichir_cadastres():
    """Remet a jour les cadastres deja telecharges et devenus trop vieux."""
    seuil_jours = reglages.lire("cadastre_apres_jours")
    if not seuil_jours:
        return ""

    faits = []
    for commune in communes_suivies():
        age = metier_parcelles.age_cadastre(commune["code_insee"])
        if age is None or age < float(seuil_jours) * 24:
            continue      # jamais telecharge, ou encore frais
        _publier(etape=f"cadastre — {commune['nom']}")
        try:
            resume = metier_parcelles.importer_cadastre(commune["code_insee"])
            faits.append(f"{commune['nom']} ({resume['parcelles']})")
        except Exception as erreur:                  # noqa: BLE001
            logger.warning("cadastre de %s non rafraichi : %s", commune["nom"], erreur)
    return ", ".join(faits)


def _moissonner(communes, jeux=None):
    """
    Telecharge puis enregistre, pour une liste de communes.

    Tout est telecharge et transforme AVANT la moindre ecriture : un echec
    ne doit jamais laisser la base a moitie remplie (CDC 8).
    """
    parametres = reglages.tous()
    points_de_zone = parametres["zones"]
    jeux = list(jeux or parametres["jeux_de_donnees"])
    par_insee = {c["code_insee"]: c for c in communes}

    enregistrements = {}
    detail, avertissements = [], []

    for jeu in jeux:
        _publier(etape=f"lecture du schema ({ademe.JEUX[jeu]})")
        try:
            correspondances, _champs = ademe.preparer(jeu)
        except ErreurSource as erreur:
            # Une base indisponible ne doit pas faire echouer les autres :
            # la veille ne depend que de « existant ».
            avertissements.append(f"{ademe.JEUX[jeu]} ignoree ({erreur})")
            logger.warning("%s ignoree : %s", jeu, erreur)
            continue

        for commune in communes:
            code_insee = commune["code_insee"]
            nom = commune.get("nom") or code_insee
            _publier(etape=f"{nom} — {ademe.JEUX[jeu]}")

            def progression(nombre_lignes, message, _nom=nom):
                _publier(etape=f"{_nom} — {message}", lignes=nombre_lignes)

            try:
                lignes = ademe.telecharger(code_insee, correspondances, jeu=jeu,
                                           progression=progression)
            except ErreurSource as erreur:
                avertissements.append(f"{nom} / {ademe.JEUX[jeu]} : {erreur}")
                logger.warning("%s / %s : %s", nom, jeu, erreur)
                continue

            retenues = 0
            for ligne in lignes:
                enregistrement = transformer(
                    ligne, correspondances, points_de_zone, jeu,
                    commune.get("code_postal"), par_insee,
                    parametres["zones_code_insee"])
                if enregistrement:
                    enregistrements[enregistrement["n_dpe"]] = enregistrement
                    retenues += 1
            detail.append(f"{nom}/{jeu} : {retenues}")
            logger.info("%s / %s : %d ligne(s) sur %d", nom, jeu, retenues, len(lignes))

    if not enregistrements:
        raise ErreurSource(
            "L'ADEME n'a renvoye aucune ligne exploitable pour "
            + ", ".join(c.get("nom") or c["code_insee"] for c in communes)
            + ". " + (" ".join(avertissements) if avertissements else ""))

    # --- Ecriture, en une seule transaction ----------------------------
    _publier(etape="enregistrement en base", lignes=len(enregistrements))
    maintenant = _maintenant()

    with transaction() as conn:
        connus = {ligne["n_dpe"] for ligne in conn.execute("SELECT n_dpe FROM dpe")}
        premier_import = not connus

        # L'alerte se tait au PREMIER import d'une commune, et non
        # seulement au premier import tout court. Explorer une commune
        # nouvelle en fait paraitre le parc entier — plusieurs milliers de
        # lignes — comme neuf : sans cette distinction, la decouvrir
        # declencherait un courriel a chaque fois. Le badge « nouveau »,
        # lui, garde son seuil global : une pastille de trop se ferme d'un
        # clic, un courriel de trop est deja parti.
        communes_connues = {
            ligne["code_insee"] for ligne in
            conn.execute("SELECT DISTINCT code_insee FROM dpe "
                         "WHERE code_insee IS NOT NULL")}

        ajouts = 0
        for enregistrement in enregistrements.values():
            ajouts += enregistrement["n_dpe"] not in connus
            # Au tout premier import, tout est « nouveau » : marquer les
            # lignes comme deja vues evite de noyer l'ecran sous les badges.
            vu_le = maintenant if premier_import else None
            alerte_le = (maintenant
                         if enregistrement.get("code_insee") not in communes_connues
                         else None)
            conn.execute(SQL_UPSERT,
                         [enregistrement[c] for c in COLONNES]
                         + [maintenant, maintenant, vu_le, alerte_le])

        # Le registre des communes consultees : c'est lui que le
        # rafraichissement hebdomadaire parcourra.
        for commune in communes:
            conn.execute(
                "INSERT INTO commune (code_insee, nom, code_postal, derniere_maj_dpe) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(code_insee) DO UPDATE SET nom = excluded.nom, "
                "  code_postal = coalesce(excluded.code_postal, commune.code_postal), "
                "  derniere_maj_dpe = excluded.derniere_maj_dpe",
                (commune["code_insee"], commune.get("nom") or commune["code_insee"],
                 commune.get("code_postal"), maintenant))

        purges = _purger(conn, parametres["purge_mois"])

    noms = ", ".join(c.get("nom") or c["code_insee"] for c in communes)
    message = f"{noms} — {len(enregistrements)} DPE, {ajouts} nouveau(x)"
    if purges:
        message += f", {purges} purge(s)"
    if premier_import:
        message += " — premier import, rien n'est signale comme nouveau"
    if avertissements:
        message += " | " + " ; ".join(avertissements[:2])

    return {"lignes": len(enregistrements), "ajouts": ajouts, "purges": purges,
            "communes": [c["code_insee"] for c in communes],
            "avertissements": avertissements, "detail": detail,
            "message": message}


def _purger(conn, purge_mois):
    """
    Supprime ce que l'ADEME ne sert plus depuis trop longtemps (CDC 9).

    La purge porte sur `revu_le`, pas sur la date du diagnostic : purger sur
    la date d'etablissement viderait la chronologie F4, qui remonte a 2013,
    et priverait F2 des DPE anterieurs que cite une annonce. Sur `revu_le`,
    la regle garde tout son sens — on ne conserve pas une donnee qu'on ne
    rafraichit plus.

    Zero mois veut dire « ne jamais purger », et se traite AVANT tout calcul :
    l'appliquer par le calcul donnerait une limite au jour meme, et
    supprimerait donc tout ce qui n'a pas ete revu dans la journee — soit
    l'exact contraire de ce qui est demande.
    """
    if not purge_mois:
        return 0

    limite = (datetime.date.today()
              - datetime.timedelta(days=int(float(purge_mois) * 30.44)))
    curseur = conn.execute(
        "DELETE FROM dpe WHERE revu_le IS NOT NULL AND revu_le < ?",
        (limite.isoformat(),))
    return curseur.rowcount or 0


# ---------------------------------------------------------------------
#  Journal (CDC 8)
# ---------------------------------------------------------------------

def _ouvrir_journal(declencheur):
    with transaction() as conn:
        curseur = conn.execute(
            "INSERT INTO journal_import (source, debut, statut) VALUES (?, ?, 'en_cours')",
            (f"ademe/{declencheur}", _maintenant()))
        return curseur.lastrowid


def _fermer_journal(journal_id, statut, lignes, ajouts, message):
    with transaction() as conn:
        conn.execute(
            "UPDATE journal_import SET fin = ?, statut = ?, lignes = ?, "
            "ajouts = ?, message = ? WHERE id = ?",
            (_maintenant(), statut, lignes, ajouts, (message or "")[:500], journal_id))


# ---------------------------------------------------------------------
#  Rafraichissement paresseux
# ---------------------------------------------------------------------

def age_dernier_import():
    """Heures depuis la derniere moisson reussie, toutes communes confondues."""
    with connexion() as conn:
        ligne = conn.execute(
            "SELECT fin FROM journal_import WHERE statut = 'succes' "
            "AND fin IS NOT NULL ORDER BY id DESC LIMIT 1").fetchone()
    if ligne is None:
        return None
    try:
        fin = datetime.datetime.fromisoformat(ligne["fin"])
    except ValueError:
        return None
    return (datetime.datetime.now() - fin).total_seconds() / 3600


def cadastre_a_refaire(code_insee):
    """Le cadastre de cette commune manque-t-il, date-t-il, ou est-il incomplet ?"""
    age = metier_parcelles.age_cadastre(code_insee)
    if age is None:
        return True
    # Les cadastres importes avant que les contours de batiments ne soient
    # conserves n'ont que des parcelles : la fiche ne peut rien dessiner
    # dessus tant qu'on ne les a pas repris.
    if metier_parcelles.batiments_manquants(code_insee):
        return True
    seuil_jours = reglages.lire("cadastre_apres_jours")
    return bool(seuil_jours) and age >= float(seuil_jours) * 24


def preparer_commune(code_insee, seuil_heures=None, declencheur="consultation",
                     besoin="dpe"):
    """
    S'assure qu'une commune est consultable, et a jour.

    C'est le pivot du parcours : on choisit une commune, et l'application
    va chercher ce qu'il faut sans qu'on ait rien a declarer. Trois cas :

      - jamais moissonnee : on la moissonne, quoi qu'il arrive. C'est la
        seule facon d'afficher quelque chose ;
      - moissonnee mais trop vieille : on rafraichit en tache de fond, les
        donnees en cache restant consultables pendant ce temps ;
      - a jour : on ne fait rien.

    Ne leve jamais : ne pas pouvoir rafraichir n'empeche pas de consulter.
    """
    code_insee = str(code_insee).strip()
    parametres = reglages.tous()
    seuil = parametres["rafraichir_apres_heures"] if seuil_heures is None else seuil_heures
    age = age_commune(code_insee)
    cadastre = besoin == "cadastre" and cadastre_a_refaire(code_insee)

    # Les deux travaux sont decides separement : demander le cadastre d'une
    # commune dont les DPE sont frais ne doit pas les retelecharger.
    if age is None:
        dpe, raison = True, "jamais_moissonnee"
    elif seuil and age >= float(seuil):
        dpe, raison = True, "perimee"
    elif cadastre:
        dpe, raison = False, "cadastre_manquant"
    else:
        return {"lance": False, "raison": "a_jour", "age_heures": round(age, 2),
                "en_cache": True, "cadastre": False}

    if _etat["en_cours"]:
        return {"lance": False, "raison": "deja_en_cours", "age_heures": age,
                "en_cache": age is not None, "cadastre": cadastre}

    try:
        lancer_en_tache_de_fond(declencheur=declencheur, code_insee=code_insee,
                                avec_dpe=dpe, avec_cadastre=cadastre)
    except RuntimeError:
        return {"lance": False, "raison": "deja_en_cours", "age_heures": age,
                "en_cache": age is not None, "cadastre": cadastre}

    return {"lance": True, "raison": raison,
            "age_heures": None if age is None else round(age, 2),
            "en_cache": age is not None, "cadastre": cadastre}


def journal(limite=20):
    """Les derniers imports, pour l'ecran Reglages."""
    with connexion() as conn:
        return [dict(ligne) for ligne in conn.execute(
            "SELECT * FROM journal_import ORDER BY id DESC LIMIT ?", (limite,))]


# ---------------------------------------------------------------------
#  Lancement en tache de fond
# ---------------------------------------------------------------------

def lancer_en_tache_de_fond(declencheur="manuel", code_insee=None,
                            avec_dpe=True, avec_cadastre=False):
    """
    Demarre une moisson sans bloquer l'appelant.

    `code_insee` vise une commune precise ; sans lui, tout le registre est
    rafraichi. L'interface interroge ensuite /api/import/statut pour suivre
    l'avancee : une moisson prend plusieurs dizaines de secondes, et une
    requete HTTP qui attendrait la fin serait coupee par le navigateur.
    """
    with _verrou:
        if _etat["en_cours"]:
            raise RuntimeError("Un import est deja en cours.")

    def travail():
        try:
            if code_insee:
                importer_commune(code_insee, declencheur=declencheur,
                                 avec_dpe=avec_dpe, avec_cadastre=avec_cadastre)
            else:
                importer(declencheur=declencheur)
        except Exception:                            # noqa: BLE001
            pass      # deja journalise et publie dans l'etat

    fil = threading.Thread(target=travail, name="import-dpe", daemon=True)
    fil.start()
    return fil
