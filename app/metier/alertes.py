# -*- coding: utf-8 -*-
"""
alertes.py — Prevenir par courriel des DPE nouvellement parus (F6).

L'import quotidien apporte les nouveautes ; c'est a sa suite que l'alerte
part (CDC 8). Elle reprend exactement les criteres enregistres dans les
Reglages — secteur, fenetre, type de bien, surfaces — pour que ce qu'on
recoit soit ce que l'ecran Veille montre, sans second jeu de regles a tenir
a jour.

Ecart assume au CDC 9, qui ecrit « aucun envoi automatique de courrier » et
prevoyait en F6 un webhook Home Assistant. Le courriel a ete demande
explicitement ; il reste desactive par defaut, et n'envoie rien tant qu'un
destinataire n'est pas enregistre.
"""

import datetime
import html
import logging

from app.base import reglages
from app.base.connexion import connexion, transaction
from app.metier import veille
from app.sources import courriel
from app.sources.courriel import ErreurCourriel

logger = logging.getLogger(__name__)

# Au-dela, le courriel devient illisible et l'essentiel est ailleurs :
# c'est le signe qu'il faut ouvrir l'ecran Veille.
MAX_DETAILLES = 25


def _filtres():
    """
    Les criteres enregistres, restreints a la commune et au secteur
    surveilles.

    Sans restriction de commune, l'alerte porterait sur TOUT le registre :
    chaque commune exploree viendrait s'y ajouter, et le courriel finirait
    par parler de territoires qu'on ne cherche plus.
    """
    parametres = reglages.tous()
    filtres = veille.filtres_par_defaut()

    code_insee = (parametres.get("alerte_code_insee") or "").strip()
    if code_insee:
        filtres["code_insee"] = code_insee

    zone = (parametres.get("alerte_zone") or "").strip()
    if zone:
        filtres["zone"] = zone
    return filtres


def candidats(limite=200):
    """
    Les DPE a signaler : ceux qui repondent aux criteres et n'ont jamais
    fait l'objet d'une alerte.

    On s'appuie sur `alerte_le`, pas sur `vu_le` : consulter l'ecran Veille
    ne doit pas faire taire l'alerte, ni l'alerte effacer les badges.
    """
    filtres = _filtres()
    ou, parametres = veille._conditions(filtres)
    colonnes = ", ".join(veille.COLONNES)
    sql = f"""
        SELECT {colonnes} FROM dpe
        WHERE {ou} AND alerte_le IS NULL
        ORDER BY date_etablissement DESC, adresse
        LIMIT ?
    """
    with connexion() as conn:
        return [dict(ligne) for ligne in conn.execute(sql, parametres + [int(limite)])]


def marquer_alertes(numeros):
    """Note que ces DPE ont ete signales, pour ne pas les repeter."""
    if not numeros:
        return 0
    maintenant = datetime.datetime.now().isoformat(timespec="seconds")
    marques = ", ".join("?" * len(numeros))
    with transaction() as conn:
        curseur = conn.execute(
            f"UPDATE dpe SET alerte_le = ? WHERE alerte_le IS NULL "
            f"AND n_dpe IN ({marques})",
            [maintenant] + list(numeros))
    return curseur.rowcount or 0


def _lignes_texte(biens):
    for bien in biens[:MAX_DETAILLES]:
        surface = (f"{bien['surface_habitable']:.0f} m²"
                   if bien.get("surface_habitable") else "surface inconnue")
        yield (f"- {bien.get('adresse') or 'adresse inconnue'}"
               f" ({bien.get('commune') or ''})\n"
               f"  {surface} · classe {bien.get('etiquette_dpe') or '?'}"
               f" · établi le {bien.get('date_etablissement') or '?'}")


def _corps(biens):
    """Le message, en texte et en HTML."""
    total = len(biens)
    titre = (f"{total} nouveau DPE" if total == 1 else f"{total} nouveaux DPE")

    texte = [f"{titre} correspondant à vos critères.", ""]
    texte.extend(_lignes_texte(biens))
    if total > MAX_DETAILLES:
        texte.append(f"\n… et {total - MAX_DETAILLES} autres. "
                     "Ouvrez l'écran Veille pour la liste complète.")

    rangs = []
    for bien in biens[:MAX_DETAILLES]:
        surface = (f"{bien['surface_habitable']:.0f} m²"
                   if bien.get("surface_habitable") else "—")
        rangs.append(
            "<tr>"
            f"<td>{html.escape(str(bien.get('adresse') or 'adresse inconnue'))}</td>"
            f"<td>{html.escape(str(bien.get('commune') or ''))}</td>"
            f"<td style='text-align:right'>{surface}</td>"
            f"<td style='text-align:center'>{html.escape(str(bien.get('etiquette_dpe') or '?'))}</td>"
            f"<td>{html.escape(str(bien.get('date_etablissement') or '?'))}</td>"
            "</tr>")

    reste = (f"<p>… et {total - MAX_DETAILLES} autres.</p>"
             if total > MAX_DETAILLES else "")
    corps_html = f"""<html><body style="font-family:system-ui,sans-serif">
  <p>{html.escape(titre)} correspondant à vos critères.</p>
  <table cellpadding="6" style="border-collapse:collapse;font-size:14px">
    <tr style="text-align:left;border-bottom:1px solid #999">
      <th>Adresse</th><th>Commune</th><th>Surface</th><th>DPE</th><th>Établi le</th>
    </tr>
    {"".join(rangs)}
  </table>
  {reste}
</body></html>"""
    return "\n".join(texte), corps_html


def envoyer_si_besoin():
    """
    Envoie l'alerte s'il y a de quoi, et note ce qui a ete signale.

    Ne leve jamais : elle est appelee a la suite de l'import, et un serveur
    SMTP injoignable ne doit pas faire echouer une moisson reussie. Le
    resultat dit ce qui s'est passe, et l'echec part au journal.
    """
    parametres = reglages.tous()
    if not parametres.get("alerte_active"):
        return {"envoye": False, "raison": "desactivee", "biens": 0}

    destinataire = (parametres.get("alerte_destinataire") or "").strip()
    if not destinataire:
        return {"envoye": False, "raison": "sans_destinataire", "biens": 0}

    biens = candidats()
    if not biens:
        return {"envoye": False, "raison": "rien_de_neuf", "biens": 0}

    texte, corps_html = _corps(biens)
    sujet = (f"Veille immobilière — {len(biens)} nouveau"
             f"{'x' if len(biens) > 1 else ''} DPE")
    try:
        courriel.envoyer(destinataire, sujet, texte, corps_html)
    except ErreurCourriel as erreur:
        # On ne marque RIEN : les biens restent candidats, et le prochain
        # import les signalera. Une alerte en retard vaut mieux qu'une
        # alerte perdue.
        logger.error("alerte non envoyee : %s", erreur)
        return {"envoye": False, "raison": "echec_envoi",
                "biens": len(biens), "message": str(erreur)}

    marquer_alertes([b["n_dpe"] for b in biens])
    return {"envoye": True, "raison": "envoyee", "biens": len(biens),
            "destinataire": destinataire}


def essai(destinataire=None):
    """
    Envoie un message de controle, pour verifier la configuration SMTP sans
    attendre qu'un DPE paraisse. Leve ErreurCourriel si le serveur refuse :
    ici, contrairement a l'alerte, on VEUT voir l'echec.
    """
    destinataire = (destinataire
                    or reglages.lire("alerte_destinataire") or "").strip()
    courriel.envoyer(
        destinataire,
        "Veille immobilière — message de contrôle",
        "Si vous lisez ceci, l'envoi de courriel fonctionne.\n"
        "Les alertes de nouveaux DPE partiront par ce chemin.",
        "<html><body style=\"font-family:system-ui,sans-serif\">"
        "<p>Si vous lisez ceci, l'envoi de courriel fonctionne.</p>"
        "<p>Les alertes de nouveaux DPE partiront par ce chemin.</p>"
        "</body></html>")
    return {"envoye": True, "destinataire": destinataire}
