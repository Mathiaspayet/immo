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


def perimetre(parametres=None):
    """
    Ou porte l'alerte : (code_insee, zone), chacun pouvant etre vide.

    Extrait a part parce que les DPE et les ventes s'en servent tous deux.
    Un second jeu de reglages pour les ventes obligerait a les tenir
    accordes a la main, et la premiere divergence passerait inapercue :
    on croirait surveiller le meme perimetre des deux cotes.
    """
    parametres = reglages.tous() if parametres is None else parametres
    return ((parametres.get("alerte_code_insee") or "").strip(),
            (parametres.get("alerte_zone") or "").strip())


def commune_surveillee(parametres=None):
    """
    La commune sur laquelle porte la veille : celle des alertes, a defaut
    celle des secteurs.

    Elle se lit dans les REGLAGES, jamais dans l'ecran. Les champs de
    l'ecran dorment masques et vides tant qu'on n'a pas clique sur
    « Modifier » : les lire rendait la chaine vide, et le geste — reprendre
    l'archive, guetter les ventes — visait alors toutes les communes ou
    aucune. Le meme piege avait deja fait echouer le controle d'envoi.
    """
    parametres = reglages.tous() if parametres is None else parametres
    code_insee, _ = perimetre(parametres)
    return code_insee or (parametres.get("zones_code_insee") or "").strip()


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

    code_insee, zone = perimetre(parametres)
    if code_insee:
        filtres["code_insee"] = code_insee
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


def _jour(iso):
    """Une date lisible et insecable : « 07/08/2026 »."""
    texte = str(iso or "")
    if len(texte) >= 10 and texte[4] == "-":
        return f"{texte[8:10]}/{texte[5:7]}/{texte[0:4]}"
    return texte or "?"


def _lignes_texte(biens):
    for bien in biens[:MAX_DETAILLES]:
        surface = (f"{bien['surface_habitable']:.0f} m²"
                   if bien.get("surface_habitable") else "surface inconnue")
        yield (f"- {bien.get('adresse') or 'adresse inconnue'}"
               f" ({bien.get('zone') or 'hors secteur'})\n"
               f"  {surface} · classe {bien.get('etiquette_dpe') or '?'}"
               f" · établi le {_jour(bien.get('date_etablissement'))}")


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
            f"<td>{html.escape(str(bien.get('zone') or '—'))}</td>"
            f"<td style='text-align:right'>{surface}</td>"
            f"<td style='text-align:center'>{html.escape(str(bien.get('etiquette_dpe') or '?'))}</td>"
            f"<td style='white-space:nowrap'>"
            f"{html.escape(_jour(bien.get('date_etablissement')))}</td>"
            "</tr>")

    reste = (f"<p>… et {total - MAX_DETAILLES} autres.</p>"
             if total > MAX_DETAILLES else "")
    corps_html = f"""<html><body style="font-family:system-ui,sans-serif">
  <p>{html.escape(titre)} correspondant à vos critères.</p>
  <table cellpadding="6" style="border-collapse:collapse;font-size:14px">
    <tr style="text-align:left;border-bottom:1px solid #999">
      <th>Adresse</th><th>Secteur</th><th>Surface</th><th>DPE</th><th>Établi le</th>
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
        return noter("dpe", {"envoye": False, "raison": "desactivee", "biens": 0})

    destinataire = (parametres.get("alerte_destinataire") or "").strip()
    if not destinataire:
        return noter("dpe", {"envoye": False, "raison": "sans_destinataire",
                             "biens": 0})

    biens = candidats()
    if not biens:
        return noter("dpe", {"envoye": False, "raison": "rien_de_neuf", "biens": 0})

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
        return noter("dpe", {"envoye": False, "raison": "echec_envoi",
                             "biens": len(biens), "message": str(erreur),
                             "destinataire": destinataire})

    marquer_alertes([b["n_dpe"] for b in biens])
    return noter("dpe", {"envoye": True, "raison": "envoyee", "biens": len(biens),
                         "destinataire": destinataire})


def essai(destinataire=None, brouillon=None):
    """
    Envoie un message de controle, et raconte ce qui s'est passe.

    Ne leve jamais : un echec est justement ce qu'on est venu voir. Le
    resultat porte la trace pas a pas — configuration, connexion,
    chiffrement, authentification, envoi — parce que « ca ne marche pas »
    ne se debogue pas sans savoir OU cela s'arrete.

    `brouillon` est la configuration AFFICHEE, pas celle enregistree : on
    eprouve ce qu'on voit. Sans cela, remplir les champs puis cliquer sur
    « controle » sans enregistrer testait une table vide, et le diagnostic
    accusait une configuration absente que l'ecran montrait pourtant.
    """
    destinataire = (destinataire
                    or reglages.lire("alerte_destinataire") or "").strip()
    trace = courriel.Trace()
    try:
        courriel.envoyer(
            destinataire,
            "Veille immobilière — message de contrôle",
            "Si vous lisez ceci, l'envoi de courriel fonctionne.\n"
            "Les alertes de nouveaux DPE partiront par ce chemin.",
            "<html><body style=\"font-family:system-ui,sans-serif\">"
            "<p>Si vous lisez ceci, l'envoi de courriel fonctionne.</p>"
            "<p>Les alertes de nouveaux DPE partiront par ce chemin.</p>"
            "</body></html>",
            trace=trace, brouillon=brouillon)
    except ErreurCourriel as erreur:
        echec = trace.dernier_echec()
        return {
            "envoye": False,
            "destinataire": destinataire,
            "message": str(erreur),
            "etapes": trace.etapes,
            "conseil": _conseil(echec, str(erreur)),
        }
    return {"envoye": True, "destinataire": destinataire,
            "etapes": trace.etapes, "conseil": None}


# Ce que dit l'echec, et ce qu'on peut en faire. Chaque piste vise une
# cause concrete plutot qu'un « verifiez vos parametres » sans prise.
def _conseil(echec, message):
    etape = (echec or {}).get("nom", "")
    bavard = f"{etape} {message}".lower()

    if "timed out" in bavard or "timeout" in bavard:
        return ("Le serveur n'a pas répondu. Le port est peut-être fermé en "
                "sortie du réseau, ou le nom du serveur est erroné. Beaucoup "
                "de fournisseurs offrent 587 (STARTTLS) et 465 (SSL direct) : "
                "essayer l'autre.")
    if "refused" in bavard or "connexion" in etape:
        return ("Rien n'écoute à cette adresse. Vérifier le nom du serveur et "
                "le port ; si le port est 465, « SSL direct » doit être "
                "choisi, et s'il est 587, ce doit être STARTTLS.")
    if "starttls" in bavard or "chiffrement" in etape:
        return ("Ce port ne propose pas STARTTLS. C'est le symptôme d'un port "
                "SSL direct (465) laissé en STARTTLS, ou l'inverse : accorder "
                "le port et le mode de chiffrement.")
    if "authentification" in etape or "auth" in bavard or "535" in bavard:
        return ("Les identifiants ont été refusés. L'identifiant est en "
                "général l'adresse complète. Chez plusieurs fournisseurs, "
                "l'envoi par un logiciel tiers demande d'activer l'accès "
                "POP3/IMAP dans les réglages du compte, voire un mot de passe "
                "dédié à l'application.")
    if "certificate" in bavard or "ssl" in bavard:
        return ("Le certificat du serveur n'a pas été validé. Vérifier que le "
                "nom du serveur est exactement celui du fournisseur.")
    if "sender" in bavard or "from" in bavard or "553" in bavard or "550" in bavard:
        return ("Le serveur a refusé l'adresse d'expédition. Elle doit "
                "correspondre au compte utilisé pour s'authentifier.")
    return None


# ---------------------------------------------------------------------
#  Journal des tentatives (F6)
# ---------------------------------------------------------------------
#  Une ligne par passage, MEME quand rien ne part. C'est justement le cas
#  qu'on cherche a expliquer : sans trace du silence, « je n'ai rien recu
#  ce matin » ne se distingue pas de « le passage n'a pas eu lieu ».
# ---------------------------------------------------------------------

def noter(sujet, resultat):
    """Enregistre l'issue d'une tentative d'alerte. Ne leve jamais."""
    try:
        with transaction() as conn:
            conn.execute(
                "INSERT INTO journal_alerte (quand, sujet, envoye, raison,"
                " biens, destinataire, message) VALUES (?,?,?,?,?,?,?)",
                (datetime.datetime.now().isoformat(timespec="seconds"),
                 sujet,
                 1 if resultat.get("envoye") else 0,
                 resultat.get("raison") or "?",
                 int(resultat.get("biens") or resultat.get("ventes") or 0),
                 resultat.get("destinataire"),
                 resultat.get("message")))
    except Exception as erreur:                      # noqa: BLE001
        logger.warning("tentative d'alerte non journalisee : %s", erreur)
    return resultat


def journal(limite=20):
    """Les dernieres tentatives, la plus recente d'abord."""
    with connexion() as conn:
        return [dict(l) for l in conn.execute(
            "SELECT quand, sujet, envoye, raison, biens, destinataire, message"
            " FROM journal_alerte ORDER BY quand DESC, id DESC LIMIT ?",
            (int(limite),))]
