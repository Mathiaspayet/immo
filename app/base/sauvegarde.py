# -*- coding: utf-8 -*-
"""
sauvegarde.py — Des copies datees de la base, verifiees et conservees.

Pourquoi l'application s'en charge plutot que l'utilisateur : la base est
en mode WAL, et les ecritures recentes vivent dans un fichier `-wal` a
cote. Copier `veille.db` seul rend donc une base INCOMPLETE — et le defaut
ne se voit qu'au moment de restaurer, c'est-a-dire trop tard.
`Connection.backup()` de SQLite prend le probleme a la racine : il copie
page a page, a chaud, en tenant compte du WAL.

Ce qui est en jeu n'est pas remplacable. DVF ne se consulte que sur cinq
ans ; a chaque parution d'automne, le millesime le plus ancien quitte la
source et ne subsiste plus que dans cette base. Les DPE, eux, ne sont pas
purges. Rien de tout cela ne se retelecharge.

Trois precautions valent d'etre dites :

  - une copie est VERIFIEE avant de compter — `quick_check` plus un
    recomptage des tables. Sauvegarder une base corrompue puis faire
    tourner la rotation est la maniere classique de perdre les donnees
    en croyant les proteger ;
  - la rotation garde le recent ET l'ancien : sept jours, douze mois, puis
    une par an. Une corruption remarquee tardivement se rattrape ainsi ;
  - tout reste sur le NAS. Aucune copie ne part vers un tiers (CDC 9).
    Contre la panne du disque lui-meme, c'est la sauvegarde du NAS —
    Hyper Backup — qui prend le relais, et c'est pour elle qu'un dossier
    lisible vaut mieux qu'un volume Docker.
"""

import collections
import datetime
import logging
import pathlib
import sqlite3

from app import config

logger = logging.getLogger(__name__)

PREFIXE = "veille-"
SUFFIXE = ".db"

# Les tables dont le recomptage vaut controle : celles qui portent ce
# qu'on ne pourrait pas retelecharger.
TABLES_TEMOINS = ("dpe", "mutation", "mutation_parcelle", "parcelle", "reglage")

# Combien de jours de copies quotidiennes on garde avant de n'en garder
# qu'une par mois. Sept couvre la semaine ou l'on remarque un probleme.
JOURS = 7
MOIS = 12


def dossier():
    """Ou vont les copies. Cree au besoin."""
    chemin = config.CHEMIN_SAUVEGARDES
    chemin.mkdir(parents=True, exist_ok=True)
    return chemin


def _compter(conn):
    comptes = {}
    for table in TABLES_TEMOINS:
        try:
            comptes[table] = conn.execute(
                f"SELECT count(*) FROM {table}").fetchone()[0]
        except sqlite3.Error:
            comptes[table] = None      # table absente d'une base ancienne
    return comptes


def _verifier(chemin, attendus):
    """
    La copie est-elle exploitable ?

    On ne se contente pas de sa taille : un fichier de la bonne taille peut
    etre illisible. `quick_check` lit les pages, et le recomptage confirme
    que le contenu a bien suivi.
    """
    conn = sqlite3.connect(f"file:{chemin}?mode=ro", uri=True, timeout=30.0)
    try:
        verdict = conn.execute("PRAGMA quick_check").fetchone()[0]
        if verdict != "ok":
            return False, f"quick_check : {verdict}"
        obtenus = _compter(conn)
    except sqlite3.Error as erreur:
        return False, f"illisible : {erreur}"
    finally:
        conn.close()

    for table, attendu in attendus.items():
        if attendu is not None and obtenus.get(table) != attendu:
            return False, (f"{table} : {obtenus.get(table)} lignes copiees"
                           f" pour {attendu} attendues")
    return True, "ok"


def _balayer(chemin):
    """Retire les fichiers annexes qu'une base SQLite laisse a cote."""
    for annexe in ("-wal", "-shm", "-journal"):
        chemin.with_name(chemin.name + annexe).unlink(missing_ok=True)


def _nom_libre(quand):
    """
    Un nom qui n'ecrase rien.

    La minute suffit au quotidien, mais pas si l'on demande une copie a la
    main juste apres celle du planificateur : les secondes departagent, et
    au-dela un suffixe.
    """
    base = dossier() / f"{PREFIXE}{quand:%Y-%m-%d-%H%M}{SUFFIXE}"
    if not base.exists():
        return base
    avec_secondes = dossier() / f"{PREFIXE}{quand:%Y-%m-%d-%H%M%S}{SUFFIXE}"
    if not avec_secondes.exists():
        return avec_secondes
    for n in range(2, 100):
        candidat = dossier() / f"{PREFIXE}{quand:%Y-%m-%d-%H%M%S}-{n}{SUFFIXE}"
        if not candidat.exists():
            return candidat
    raise OSError("trop de sauvegardes dans la meme seconde")


def sauvegarder(horodatage=None):
    """
    Ecrit une copie datee et verifiee, puis fait le menage.

    Ne leve pas : appelee a la suite de l'import quotidien, elle ne doit
    pas faire echouer une moisson reussie. Le resultat dit ce qui s'est
    passe, et l'echec part au journal.
    """
    quand = horodatage or datetime.datetime.now()
    cible = _nom_libre(quand)
    # On ecrit A COTE, puis on publie. Ecrire directement sur le nom final
    # serait le pire des defauts possibles ici : deux sauvegardes dans la
    # meme minute portent le meme nom, et une seconde qui echoue aurait
    # deja ecrase la premiere — la bonne copie detruite par la tentative
    # de sauvegarde. Le fichier temporaire rend cela impossible.
    partiel = cible.with_name(cible.name + ".partiel")

    try:
        partiel.unlink(missing_ok=True)
        _balayer(partiel)
        source = sqlite3.connect(str(config.CHEMIN_BASE), timeout=60.0)
        try:
            attendus = _compter(source)
            # `backup()` copie page a page, a chaud, WAL compris. Une copie
            # du seul fichier .db laisserait dehors les ecritures recentes.
            copie = sqlite3.connect(str(partiel))
            try:
                source.backup(copie)
                # `backup()` reproduit le mode WAL de la source, et la
                # copie traine alors un `-wal` et un `-shm` a cote d'elle.
                # Une sauvegarde doit tenir en UN fichier : c'est ce qu'on
                # glisse sur une cle, ce qu'Hyper Backup emporte, et ce
                # qu'on rouvrira dans dix ans sans se demander quels
                # fichiers vont ensemble. `DELETE` replie tout dedans.
                copie.execute("PRAGMA journal_mode = DELETE")
            finally:
                copie.close()
            _balayer(partiel)
        finally:
            source.close()
    except Exception as erreur:                      # noqa: BLE001
        logger.error("sauvegarde impossible : %s", erreur)
        partiel.unlink(missing_ok=True)
        _balayer(partiel)
        return {"faite": False, "raison": str(erreur)}

    bonne, detail = _verifier(partiel, attendus)
    if not bonne:
        # Rien n'a ete publie : les copies deja en place sont intactes, et
        # la rotation ne tourne pas.
        partiel.unlink(missing_ok=True)
        _balayer(partiel)
        logger.error("sauvegarde rejetee — %s", detail)
        return {"faite": False, "raison": detail}

    # Verifiee, donc publiee. `replace` est atomique sur le meme systeme
    # de fichiers : a aucun instant le nom final ne designe un fichier
    # incomplet.
    _balayer(partiel)
    partiel.replace(cible)
    _balayer(cible)

    retirees = _rotation(garder=cible.name)
    taille = cible.stat().st_size
    logger.info("sauvegarde %s (%.1f Mo), %d ancienne(s) retiree(s)",
                cible.name, taille / 1e6, len(retirees))
    return {"faite": True, "fichier": cible.name, "octets": taille,
            "verifie": True, "retirees": retirees, "lignes": attendus}


def _datee(chemin):
    """La date portee par le nom, ou None si le fichier n'est pas des notres."""
    nom = chemin.name
    if not (nom.startswith(PREFIXE) and nom.endswith(SUFFIXE)):
        return None
    horodatage = nom[len(PREFIXE):-len(SUFFIXE)]
    # Trois formes, par anciennete de nom : la minute, la seconde, puis la
    # seconde suffixee quand meme elle ne suffit pas a departager.
    for forme in ("%Y-%m-%d-%H%M", "%Y-%m-%d-%H%M%S"):
        try:
            return datetime.datetime.strptime(horodatage, forme)
        except ValueError:
            continue
    if "-" in horodatage:
        try:
            return datetime.datetime.strptime(
                horodatage.rsplit("-", 1)[0], "%Y-%m-%d-%H%M%S")
        except ValueError:
            return None
    return None


def copies():
    """
    Les copies presentes, de la plus recente a la plus ancienne.

    Le NOM departage les dates egales. Deux copies d'une meme minute —
    « ...-1430.db » et « ...-143000.db » — se lisent a la meme seconde, et
    sans ce second critere leur ordre venait de celui du systeme de
    fichiers. La rotation en supprimait alors une au hasard : le meme code
    gardait l'une ici et l'autre la. Un test l'a montre en passant en
    local et en echouant sur le serveur d'integration.
    """
    trouvees = []
    for chemin in dossier().glob(f"{PREFIXE}*{SUFFIXE}"):
        quand = _datee(chemin)
        if quand is not None:
            trouvees.append({"fichier": chemin.name, "quand": quand,
                             "octets": chemin.stat().st_size})
    return sorted(trouvees, key=lambda c: (c["quand"], c["fichier"]), reverse=True)


def _a_garder(presentes, maintenant):
    """
    Ce qu'on garde : le recent ET l'ancien.

    Ne garder que les dernieres copies serait un piege. Une corruption ou
    un effacement passe rarement inapercu le jour meme ; s'il faut trois
    semaines pour le remarquer, une retention de sept jours n'a plus rien
    a offrir. On garde donc sept jours de quotidiennes, puis une par mois
    sur douze mois, puis une par an — sans limite, parce qu'une base de
    quelques dizaines de mega-octets ne justifie pas d'oublier une annee.
    """
    gardees = set()
    limite_jours = maintenant - datetime.timedelta(days=JOURS)
    par_mois, par_an = collections.OrderedDict(), collections.OrderedDict()

    # On retrie ici plutot que de faire confiance a l'appelant. Deux copies
    # d'une meme minute — « ...-1430.db » et « ...-143000.db » — se lisent
    # a la meme seconde : sans le nom pour les departager, la decision
    # suivait l'ordre d'arrivee, donc celui du systeme de fichiers. Le meme
    # code gardait alors l'une ici et l'autre la, et le test qui l'a
    # revele passait en local en echouant sur le serveur d'integration.
    presentes = sorted(presentes, key=lambda c: (c["quand"], c["fichier"]),
                       reverse=True)

    for copie in presentes:                          # recent d'abord
        quand = copie["quand"]
        if quand >= limite_jours:
            gardees.add(copie["fichier"])
            continue
        mois = (quand.year, quand.month)
        annee = quand.year
        # La premiere rencontree dans un mois est la plus recente de ce
        # mois : c'est celle qu'on garde.
        if len(par_mois) < MOIS and mois not in par_mois:
            par_mois[mois] = copie["fichier"]
            par_an.setdefault(annee, copie["fichier"])
            gardees.add(copie["fichier"])
        elif annee not in par_an:
            # Une annuelle n'a de sens que si l'annee n'est pas deja
            # couverte par une mensuelle : sinon on garderait deux copies
            # a un jour d'intervalle pour rien.
            par_an[annee] = copie["fichier"]
            gardees.add(copie["fichier"])
    return gardees


def _rotation(maintenant=None, garder=None):
    """Retire ce qui n'est plus a garder. Renvoie les noms retires."""
    maintenant = maintenant or datetime.datetime.now()
    presentes = copies()
    gardees = _a_garder(presentes, maintenant)
    # La copie qu'on vient d'ecrire ne se retire JAMAIS, quelle que soit
    # la regle. Sans cette garde, une copie demandee a la main portant une
    # date deja couverte par la retention mensuelle etait effacee dans la
    # foulee : l'utilisateur croyait avoir une sauvegarde, il n'en avait
    # pas. Sauvegarder ne doit jamais avoir pour effet net de ne rien
    # sauvegarder.
    if garder:
        gardees.add(garder)

    retirees = []
    for copie in presentes:
        if copie["fichier"] in gardees:
            continue
        try:
            (dossier() / copie["fichier"]).unlink()
            retirees.append(copie["fichier"])
        except OSError as erreur:
            logger.warning("copie %s non retiree : %s", copie["fichier"], erreur)
    return retirees


def etat():
    """De quoi dire a l'ecran si les sauvegardes se font vraiment."""
    presentes = copies()
    if not presentes:
        return {"copies": 0, "derniere": None, "octets": 0,
                "dossier": str(dossier()), "alerte": "aucune sauvegarde"}

    derniere = presentes[0]
    age = datetime.datetime.now() - derniere["quand"]
    return {
        "copies": len(presentes),
        "derniere": derniere["quand"].isoformat(timespec="minutes"),
        "derniere_fichier": derniere["fichier"],
        "age_heures": round(age.total_seconds() / 3600, 1),
        "octets": sum(c["octets"] for c in presentes),
        "depuis": presentes[-1]["quand"].isoformat(timespec="minutes"),
        "dossier": str(dossier()),
        # Deux jours sans copie alors que l'import tourne tous les jours :
        # quelque chose ne va pas, et il vaut mieux le voir a l'ecran
        # qu'au moment de restaurer.
        "alerte": ("aucune sauvegarde depuis plus de deux jours"
                   if age > datetime.timedelta(days=2) else None),
    }
