# -*- coding: utf-8 -*-
"""
identification.py — F2 : retrouver un bien a partir des chiffres d'une annonce.

Toute maison mise en vente a un DPE, et la base de l'ADEME est publique
AVEC l'adresse. En saisissant la surface et les consommations lues sur
l'annonce, on retrouve donc l'adresse du bien.

LE PRINCIPE, ET IL EST IMPORTANT : on n'elimine personne. On NOTE tout le
monde et on classe. Une annonce arrondit les surfaces, recopie parfois un
chiffre de travers ; un filtre strict ferait disparaitre le bon logement
sans que rien ne l'explique.

D'ou l'entonnoir : pour chaque critere pris isolement, combien de logements
tombent dans la tolerance, puis combien y restent en cumulant. C'est ce qui
montre immediatement quel chiffre de l'annonce pose probleme (CDC F2).

Repris de scripts_existants/dpe_recherche.py.
"""

import logging

from app.base import reglages
from app.base.connexion import connexion

logger = logging.getLogger(__name__)

COLONNES = [
    "n_dpe", "adresse", "commune", "code_postal", "latitude", "longitude",
    "zone", "date_etablissement", "surface_habitable", "type_batiment",
    "etiquette_dpe", "etiquette_ges", "conso_ep_m2", "conso_ef_m2", "ges_m2",
    "cout_annuel", "annee_construction", "n_dpe_remplace", "jeu_de_donnees",
]

# (critere saisi, colonne en base, cle de tolerance, unite, libelle)
CRITERES_NUMERIQUES = [
    ("surface", "surface_habitable", "surface", "m²", "surface habitable"),
    ("conso_ep", "conso_ep_m2", "conso", "kWh/m² ép.", "énergie primaire"),
    ("conso_ef", "conso_ef_m2", "conso", "kWh/m² éf.", "énergie finale"),
    ("ges", "ges_m2", "ges", "kgCO₂/m²", "émissions GES"),
]

CRITERES_ETIQUETTES = [
    ("etiquette_dpe", "etiquette_dpe", "classe énergie"),
    ("etiquette_ges", "etiquette_ges", "classe GES"),
]


def _nombre(valeur):
    try:
        return float(str(valeur).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _candidats(filtres):
    """Tous les logements du perimetre, sans aucune elimination."""
    clauses, parametres = [], []
    if filtres.get("commune"):
        clauses.append("lower(commune) LIKE ?")
        parametres.append(f"%{str(filtres['commune']).lower()}%")
    if filtres.get("code_postal"):
        clauses.append("code_postal = ?")
        parametres.append(str(filtres["code_postal"]))
    if filtres.get("type_batiment"):
        clauses.append("lower(type_batiment) LIKE ?")
        parametres.append(f"%{str(filtres['type_batiment']).lower()}%")
    if filtres.get("jeu_de_donnees"):
        clauses.append("jeu_de_donnees = ?")
        parametres.append(filtres["jeu_de_donnees"])

    sql = (f"SELECT {', '.join(COLONNES)} FROM dpe"
           + (f" WHERE {' AND '.join(clauses)}" if clauses else ""))
    with connexion() as conn:
        return [dict(ligne) for ligne in conn.execute(sql, parametres)]


def _ecart(ligne, colonne, attendu, tolerance):
    """
    Ecart d'un logement sur un critere, exprime en nombre de tolerances.
    None si la base ne renseigne pas cette valeur — ce n'est pas un echec,
    c'est une information a afficher telle quelle.
    """
    valeur = _nombre(ligne.get(colonne))
    if valeur is None:
        return None
    return abs(valeur - attendu) / tolerance


def identifier(criteres, tolerances=None, filtres=None, combien=40):
    """
    Classe les logements par ressemblance avec les chiffres d'une annonce.

    Renvoie l'entonnoir, le classement, et de quoi comprendre l'un et
    l'autre. Aucune ligne n'est ecartee du classement pour cause d'ecart
    trop grand.
    """
    parametres = reglages.tous()
    tolerances = {**parametres["tolerances"], **(tolerances or {})}
    filtres = filtres or {}

    lignes = _candidats(filtres)

    # --- Criteres effectivement renseignes par l'utilisateur -----------
    actifs = []
    for cle, colonne, cle_tolerance, unite, libelle in CRITERES_NUMERIQUES:
        attendu = _nombre(criteres.get(cle))
        if attendu is None:
            continue
        tolerance = float(tolerances.get(cle_tolerance) or 1)
        actifs.append((cle, colonne, attendu, tolerance, unite, libelle))

    etiquettes_actives = []
    for cle, colonne, libelle in CRITERES_ETIQUETTES:
        attendue = str(criteres.get(cle) or "").strip().upper()
        if attendue:
            etiquettes_actives.append((cle, colonne, attendue, libelle))

    # --- Entonnoir : chaque critere seul, puis en cumule ---------------
    entonnoir = []
    cumules = list(lignes)

    for cle, colonne, attendu, tolerance, unite, libelle in actifs:
        seuls = [l for l in lignes
                 if (e := _ecart(l, colonne, attendu, tolerance)) is not None and e <= 1]
        cumules = [l for l in cumules
                   if (e := _ecart(l, colonne, attendu, tolerance)) is not None and e <= 1]
        entonnoir.append({
            "critere": cle,
            "libelle": libelle,
            "attendu": attendu,
            "tolerance": tolerance,
            "unite": unite,
            "seuls": len(seuls),
            "cumules": len(cumules),
            # Un critere que la base ne renseigne presque jamais ne prouve
            # rien : le dire evite de conclure a tort d'un entonnoir vide.
            "renseignes": sum(1 for l in lignes if _nombre(l.get(colonne)) is not None),
        })

    for cle, colonne, attendue, libelle in etiquettes_actives:
        seuls = [l for l in lignes
                 if str(l.get(colonne) or "").strip().upper() == attendue]
        cumules = [l for l in cumules
                   if str(l.get(colonne) or "").strip().upper() == attendue]
        entonnoir.append({
            "critere": cle,
            "libelle": libelle,
            "attendu": attendue,
            "tolerance": None,
            "unite": "",
            "seuls": len(seuls),
            "cumules": len(cumules),
            "renseignes": sum(1 for l in lignes if l.get(colonne)),
        })

    # --- Classement, sans elimination ----------------------------------
    notes = []
    for ligne in lignes:
        ecarts, total, renseignes = {}, 0.0, 0
        for cle, colonne, attendu, tolerance, _unite, _libelle in actifs:
            e = _ecart(ligne, colonne, attendu, tolerance)
            ecarts[cle] = None if e is None else round(e, 3)
            if e is not None:
                total += e
                renseignes += 1

        concordances = 0
        for cle, colonne, attendue, _libelle in etiquettes_actives:
            correspond = str(ligne.get(colonne) or "").strip().upper() == attendue
            ecarts[cle] = correspond
            concordances += correspond

        if actifs and renseignes == 0:
            continue      # rien de comparable sur cette ligne

        ligne = dict(ligne, ecarts=ecarts,
                     criteres_renseignes=renseignes,
                     etiquettes_concordantes=concordances)
        ligne["ecart_moyen"] = round(total / renseignes, 3) if renseignes else None
        notes.append(ligne)

    if actifs:
        # A egalite d'ecart, celui qui renseigne le plus de criteres passe
        # devant : un logement note sur un seul chiffre est moins probant.
        notes.sort(key=lambda l: (l["ecart_moyen"], -l["etiquettes_concordantes"],
                                  -l["criteres_renseignes"]))
    else:
        # Aucun chiffre saisi : on ne peut classer que sur les etiquettes.
        notes.sort(key=lambda l: (-l["etiquettes_concordantes"],
                                  str(l.get("date_etablissement") or ""), ),
                   reverse=False)

    return {
        "criteres": criteres,
        "tolerances": tolerances,
        "entonnoir": entonnoir,
        "examines": len(lignes),
        "classes": len(notes),
        "resultats": notes[:combien],
        "diagnostic": _diagnostic(entonnoir, lignes, actifs, etiquettes_actives, notes),
    }


def _diagnostic(entonnoir, lignes, actifs, etiquettes, notes):
    """
    Explication a afficher quand l'entonnoir se ferme.

    « Aucun résultat » n'est jamais une reponse suffisante (CDC 7). Et
    l'etape ou le cumul tombe a zero n'est pas forcement la coupable : elle
    peut simplement arriver apres un critere qui avait deja ecarte le bon
    logement. On regarde donc aussi sur quel critere le mieux classe
    s'ecarte le plus — c'est lui, le chiffre douteux de l'annonce.
    """
    if not lignes:
        return ("Le cache est vide pour ce périmètre. Lancez un import depuis "
                "l'écran Veille avant de chercher.")
    if not actifs and not etiquettes:
        return ("Saisissez au moins un chiffre de l'annonce : surface, "
                "consommation ou émissions.")
    if not entonnoir or entonnoir[-1]["cumules"] > 0:
        return None

    phrases = []

    # 1. L'etape ou le cumul s'annule.
    precedent = len(lignes)
    for etape in entonnoir:
        if etape["cumules"] == 0 and precedent > 0:
            phrases.append(
                f"Aucun logement ne satisfait tous les critères à la fois : le "
                f"cumul s'annule sur « {etape['libelle']} », qui en retenait "
                f"pourtant {etape['seuls']} pris isolément.")
            if etape["renseignes"] < len(lignes) / 2:
                phrases.append(
                    f"Attention, la base ne renseigne ce critère que pour "
                    f"{etape['renseignes']} logement(s) sur {len(lignes)}.")
            break
        precedent = etape["cumules"]

    # 2. Le critere sur lequel le mieux classe s'ecarte le plus.
    if notes:
        meilleur = notes[0]
        pires = [(cle, valeur) for cle, valeur in meilleur["ecarts"].items()
                 if isinstance(valeur, (int, float)) and not isinstance(valeur, bool)]
        if pires:
            cle, ecart = max(pires, key=lambda couple: couple[1])
            reference = {c[0]: c for c in actifs}.get(cle)
            if reference and ecart > 1:
                _cle, colonne, attendu, tolerance, unite, libelle = reference
                observe = meilleur.get(colonne)
                phrases.append(
                    f"Le mieux classé — {meilleur.get('adresse') or meilleur['n_dpe']} — "
                    f"colle sur tout sauf « {libelle} » : {observe} {unite} en base "
                    f"contre {attendu} {unite} annoncés, soit {ecart:.1f} fois la "
                    f"tolérance. C'est ce chiffre de l'annonce qu'il faut suspecter.")

    phrases.append("Le classement ci-dessous reste valable : rien n'a été éliminé.")
    return " ".join(phrases)
