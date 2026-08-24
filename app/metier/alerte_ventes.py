# -*- coding: utf-8 -*-
"""
alerte_ventes.py — Prevenir par courriel des ventes nouvellement publiees.

Le pendant de `alertes.py` pour DVF, avec deux differences qui tiennent a
la nature de la source.

La premiere est le RYTHME. Un DPE parait en continu ; DVF parait deux fois
l'an, par blocs. On ne guette donc pas la donnee mais sa PUBLICATION : une
requete HEAD quotidienne compare la signature du fichier a celle du dernier
passage, et l'import complet ne part que lorsqu'elle a bouge. Telecharger
un megaoctet de CSV chaque jour pour decouvrir deux fois l'an qu'il a change
serait le meme resultat au prix de trois cent soixante-trois telechargements
inutiles.

La seconde est le SECTEUR. Le DPE porte sa zone en colonne, calculee a
l'import. Une vente la calcule au moment de l'alerte, a partir de la
position que DVF pose sur chaque ligne. C'est volontaire : les reperes de
secteur sont modifiables dans les Reglages, et une colonne figee dirait
« plage » pour une vente que les reperes actuels rangent au bourg.

Le perimetre — commune et secteur — est celui des alertes DPE, sans reglage
distinct : c'est ce qui a ete demande, et deux jeux de criteres finiraient
par diverger sans qu'on s'en apercoive.
"""

import datetime
import html
import logging

from app.base import reglages
from app.base.connexion import connexion, transaction
from app.metier import alertes, zones
from app.sources import courriel
from app.sources.courriel import ErreurCourriel

logger = logging.getLogger(__name__)

# Au-dela, le courriel devient illisible. Une parution semestrielle peut
# apporter plusieurs centaines de ventes d'un coup : le detail appartient
# alors a l'ecran, pas au message.
MAX_DETAILLEES = 30


def _dans_le_secteur(ligne, zone_voulue, points, zones_code_insee):
    """La vente tombe-t-elle dans le secteur surveille ?"""
    if not zone_voulue:
        return True
    # Les secteurs n'ont de sens que la ou leurs reperes sont poses.
    if zones_code_insee and ligne["code_insee"] != zones_code_insee:
        return False
    zone, _ = zones.rattacher(ligne["latitude"], ligne["longitude"], points)
    return zone == zone_voulue


def candidats(limite=300):
    """
    Les ventes a signaler : jamais signalees, dans le perimetre surveille.

    Comme pour les DPE, le marqueur est `alerte_le` et non `vu_le` :
    consulter une fiche ne doit pas faire taire l'alerte.
    """
    parametres = reglages.tous()
    code_insee, zone = alertes.perimetre(parametres)
    points = parametres.get("zones") or {}
    zones_code_insee = (parametres.get("zones_code_insee") or "").strip()

    clauses, valeurs = ["alerte_le IS NULL"], []
    if code_insee:
        clauses.append("code_insee = ?")
        valeurs.append(code_insee)
    sql = ("SELECT * FROM mutation WHERE " + " AND ".join(clauses)
           + " ORDER BY date_mutation DESC, id LIMIT ?")
    with connexion() as conn:
        lignes = [dict(l) for l in conn.execute(sql, valeurs + [int(limite)])]

    return [l for l in lignes
            if _dans_le_secteur(l, zone, points, zones_code_insee)]


def marquer(identifiants):
    """Note que ces ventes ont ete signalees, pour ne pas les repeter."""
    if not identifiants:
        return 0
    maintenant = datetime.datetime.now().isoformat(timespec="seconds")
    marques = ", ".join("?" * len(identifiants))
    with transaction() as conn:
        curseur = conn.execute(
            f"UPDATE mutation SET alerte_le = ? WHERE alerte_le IS NULL"
            f" AND id IN ({marques})",
            [maintenant] + list(identifiants))
    return curseur.rowcount or 0


def _jour(iso):
    """Une date lisible et insecable : « 30/12/2025 ».

    L'ISO se coupait en fin de colonne — « 2025-12- » puis « 30 » — parce
    que le tiret est un point de cesure legitime pour le navigateur.
    """
    texte = str(iso or "")
    if len(texte) >= 10 and texte[4] == "-":
        return f"{texte[8:10]}/{texte[5:7]}/{texte[0:4]}"
    return texte or "?"


def _euros(valeur):
    if not valeur:
        return "prix non publié"
    # Espace insecable etroite : « 320 000 € » ne doit pas se couper en
    # fin de ligne dans un client de messagerie.
    return f"{valeur:,.0f}".replace(",", " ") + " €"


def _surface(ligne):
    if ligne.get("surface_bati_m2"):
        return f"{ligne['surface_bati_m2']:.0f} m²"
    if ligne.get("surface_terrain_m2"):
        return f"terrain {ligne['surface_terrain_m2']:.0f} m²"
    return "surface inconnue"


# L'habitation en tete : « Maison + Dependance » se lit, « Dependance +
# Maison » fait chercher. L'ordre alphabetique mettait le garage devant.
ORDRE_LOCAUX = {"Maison": 0, "Appartement": 1}


def _nature(ligne):
    """Ce qui a change de mains, en clair, l'habitation en tete."""
    types = ligne.get("types_locaux") or []
    if types:
        return " + ".join(sorted(types, key=lambda t: (ORDRE_LOCAUX.get(t, 9), t)))
    return ligne.get("nature") or "bien non bati"


def _corps(ventes):
    """Le message, en texte et en HTML."""
    total = len(ventes)
    titre = (f"{total} nouvelle vente publiée" if total == 1
             else f"{total} nouvelles ventes publiées")

    texte = [f"{titre} par Etalab, correspondant à votre secteur.", ""]
    for v in ventes[:MAX_DETAILLEES]:
        prix_m2 = (f" · {v['prix_m2']:,.0f}".replace(",", " ") + " €/m²"
                   if v.get("prix_m2") else "")
        texte.append(
            f"- {v.get('adresse') or 'adresse non publiée'}\n"
            f"  vendu le {_jour(v.get('date_mutation'))} · {_euros(v.get('valeur_fonciere'))}\n"
            f"  {_nature(v)} · {_surface(v)}{prix_m2}")
    if total > MAX_DETAILLEES:
        texte.append(f"\n… et {total - MAX_DETAILLEES} autres. "
                     "Ouvrez la carte pour la liste complète.")
    texte.append("\nDVF ne publie qu'avec plusieurs mois de décalage : "
                 "ces ventes sont nouvellement PUBLIÉES, pas nouvellement "
                 "signées.")

    rangs = []
    for v in ventes[:MAX_DETAILLEES]:
        prix_m2 = (f"{v['prix_m2']:,.0f}".replace(",", " ") + " €"
                   if v.get("prix_m2") else "—")
        rangs.append(
            "<tr>"
            f"<td>{html.escape(str(v.get('adresse') or 'adresse non publiée'))}</td>"
            f"<td style='white-space:nowrap'>{html.escape(_jour(v.get('date_mutation')))}</td>"
            f"<td style='text-align:right'>{html.escape(_euros(v.get('valeur_fonciere')))}</td>"
            f"<td>{html.escape(_nature(v))}</td>"
            f"<td style='text-align:right'>{html.escape(_surface(v))}</td>"
            f"<td style='text-align:right'>{html.escape(prix_m2)}</td>"
            "</tr>")

    reste = (f"<p>… et {total - MAX_DETAILLEES} autres.</p>"
             if total > MAX_DETAILLEES else "")
    corps_html = f"""<html><body style="font-family:system-ui,sans-serif">
  <p>{html.escape(titre)} par Etalab, correspondant à votre secteur.</p>
  <table cellpadding="6" style="border-collapse:collapse;font-size:14px">
    <tr style="text-align:left;border-bottom:1px solid #999">
      <th>Adresse</th><th>Vendu le</th><th>Prix</th>
      <th>Nature</th><th>Surface</th><th>€/m²</th>
    </tr>
    {"".join(rangs)}
  </table>
  {reste}
  <p style="color:#555;font-size:13px">DVF ne publie qu'avec plusieurs mois
  de décalage : ces ventes sont nouvellement <em>publiées</em>, pas
  nouvellement signées.</p>
</body></html>"""
    return "\n".join(texte), corps_html


def envoyer_si_besoin():
    """
    Envoie l'alerte des ventes s'il y a de quoi, et note ce qui a ete
    signale.

    Ne leve jamais, pour la meme raison que son homologue DPE : un serveur
    de courriel injoignable ne doit pas faire echouer un import reussi. En
    cas d'echec on ne marque RIEN — les ventes restent candidates, et le
    passage suivant les signalera. Une alerte en retard vaut mieux qu'une
    alerte perdue.
    """
    parametres = reglages.tous()
    if not parametres.get("alerte_active"):
        return {"envoye": False, "raison": "desactivee", "ventes": 0}
    if not parametres.get("alerte_ventes_active"):
        return {"envoye": False, "raison": "ventes_desactivees", "ventes": 0}

    destinataire = (parametres.get("alerte_destinataire") or "").strip()
    if not destinataire:
        return {"envoye": False, "raison": "sans_destinataire", "ventes": 0}

    # `_decorer` apporte le prix au metre carre, et surtout son refus de le
    # calculer quand la vente porte sur plusieurs biens : afficher le prix
    # d'une maison AVEC son garage rapporte a la seule surface de la maison
    # donnerait un chiffre faux, et flatteur.
    from app.metier import mutations
    ventes = [mutations._decorer(v) for v in candidats()]
    if not ventes:
        return {"envoye": False, "raison": "rien_de_neuf", "ventes": 0}

    texte, corps_html = _corps(ventes)
    sujet = (f"Veille immobilière — {len(ventes)} nouvelle"
             f"{'s' if len(ventes) > 1 else ''} vente"
             f"{'s' if len(ventes) > 1 else ''} publiée"
             f"{'s' if len(ventes) > 1 else ''}")
    try:
        courriel.envoyer(destinataire, sujet, texte, corps_html)
    except ErreurCourriel as erreur:
        logger.error("alerte ventes non envoyee : %s", erreur)
        return {"envoye": False, "raison": "echec_envoi",
                "ventes": len(ventes), "message": str(erreur)}

    marquer([v["id"] for v in ventes])
    return {"envoye": True, "raison": "envoyee", "ventes": len(ventes),
            "destinataire": destinataire}
