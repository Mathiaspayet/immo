// -*- coding: utf-8 -*-
/**
 * exploration.js — La carte d'exploration.
 *
 * On parcourt la commune sur photo aérienne, chaque parcelle colorée selon
 * ce qu'on en sait : un diagnostic, une vente, les deux, ou rien encore.
 * C'est le croisement qui informe — une parcelle vendue sans diagnostic
 * récent et une parcelle diagnostiquée sans vente ne racontent pas la même
 * histoire.
 *
 * Deux contraintes gouvernent ce module :
 *
 *   - le volume. Les 11 444 parcelles de Mimizan pèsent 3,8 Mo. On ne
 *     charge donc que le cadre affiché, et on prévient quand il en reste
 *     au-delà plutôt que d'en tracer une bouillie ;
 *   - le zoom. En dessous d'un certain niveau, les parcelles sont trop
 *     petites pour se distinguer et trop nombreuses pour se charger : la
 *     carte le dit au lieu de peiner en silence.
 */

import { api } from "./api.js";
import { creerCarteExploration, ETATS_PARCELLE, etatParcelle } from "./carte.js";
import { $, afficherErreur, echapper, entierFr, euroFr, masquerErreur } from "./format.js";
import { ouvrirFiche } from "./fiche.js";
import { auTermeDeLImport } from "./import.js";
import { auChangement } from "./navigation.js";
import { communeCourante, surCommunePrete } from "./parcours.js";

// En dessous, une commune entière tient à l'écran : des milliers de
// parcelles de quelques pixels, illisibles et lourdes à charger.
const ZOOM_MINIMAL = 15;

let carte = null;
let derniereRequete = 0;
let communeCadree = null;

/**
 * Amène la carte sur la commune, la première fois seulement.
 *
 * Le parcours ne retient de la commune que son code et son nom — ils
 * viennent des attributs du bouton cliqué. On va donc chercher son étendue
 * au registre, qui la tient des positions des DPE.
 *
 * « La première fois seulement » compte : revenir sur la carte après avoir
 * ouvert une fiche doit retrouver l'endroit qu'on regardait, pas repartir
 * du centre du bourg.
 */
async function cadrerSurLaCommune() {
  const commune = communeCourante();
  if (!commune || communeCadree === commune.code_insee) return;
  try {
    const { communes } = await api.communes();
    const trouvee = communes.find((c) => c.code_insee === commune.code_insee);
    if (trouvee?.cadre) {
      communeCadree = commune.code_insee;
      carte.cadrerSur(trouvee.cadre);
    }
  } catch (_) { /* on reste où on est : ce n'est pas bloquant */ }
}

function etat(message) {
  $("#carte-etat").innerHTML = message;
}

/** Charge et trace les parcelles du cadre courant. */
async function rafraichir() {
  const commune = communeCourante();
  if (!commune) {
    etat("Choisissez une commune pour commencer.");
    return;
  }
  if (carte.zoom() < ZOOM_MINIMAL) {
    carte.dessiner([]);
    etat("Zoomez pour voir les parcelles&nbsp;: à cette échelle, elles sont " +
         "trop nombreuses et trop petites pour être lisibles.");
    return;
  }

  // Un déplacement rapide peut lancer plusieurs requêtes ; seule la
  // dernière compte. Sans ce numéro d'ordre, une réponse tardive
  // écraserait l'affichage d'un cadre qu'on a déjà quitté.
  const rang = ++derniereRequete;
  etat("Chargement…");
  let reponse;
  try {
    reponse = await api.parcellesCarte(commune.code_insee, carte.cadre());
  } catch (erreur) {
    if (rang !== derniereRequete) return;
    etat("");
    afficherErreur("Les parcelles n'ont pas pu être chargées.", erreur.message);
    return;
  }
  if (rang !== derniereRequete) return;

  masquerErreur();
  const parcelles = reponse.parcelles || [];
  carte.dessiner(parcelles);

  const compte = (cle) => parcelles.filter((p) => etatParcelle(p) === cle).length;
  const resume = `${entierFr.format(parcelles.length)} parcelle(s)` +
    ` · ${entierFr.format(compte("deux"))} avec DPE et vente` +
    ` · ${entierFr.format(compte("dpe"))} DPE seul` +
    ` · ${entierFr.format(compte("vente"))} vente seule`;
  etat(reponse.tronque
    ? `${resume}. <strong>Il y en a davantage hors de ce compte</strong>&nbsp;: ` +
      "zoomez pour toutes les voir."
    : resume);
}

/** Ce qu'on montre au clic sur une parcelle. */
function decrire(parcelle, forme) {
  const reference = `${parcelle.section ?? ""}${parcelle.numero ?? ""}`;
  const faits = [];
  if (parcelle.contenance_m2) {
    faits.push(`terrain ${entierFr.format(parcelle.contenance_m2)} m²`);
  }
  if (parcelle.emprise_batie_m2) {
    faits.push(`bâti ${entierFr.format(parcelle.emprise_batie_m2)} m²`);
  }

  const lignes = [];
  if (parcelle.dpe > 0) {
    lignes.push(`${entierFr.format(parcelle.dpe)} diagnostic(s)` +
      (parcelle.dpe_dernier ? `, dernier le ${echapper(parcelle.dpe_dernier)}` : ""));
  }
  if (parcelle.ventes > 0) {
    lignes.push(`${entierFr.format(parcelle.ventes)} vente(s) connue(s)`);
  }
  if (!lignes.length) lignes.push("Ni diagnostic ni vente connus.");

  forme.bindPopup(
    `<span class="adresse-popup">Parcelle ${echapper(reference)}</span>` +
    `<span class="donnee">${echapper(faits.join(" · "))}</span>` +
    `<span class="donnee">${lignes.join("<br>")}</span>` +
    (parcelle.n_dpe
      ? `<button type="button" class="bouton-lien" data-fiche="${echapper(parcelle.n_dpe)}">
           Ouvrir la fiche →
         </button>`
      : "")
  ).openPopup();
}

// --------------------------------------------------------------------
//  Recherche : une adresse, ou une référence cadastrale
// --------------------------------------------------------------------

let minuterieRecherche = null;

async function suggerer() {
  const boite = $("#carte-suggestions");
  const texte = $("#carte-adresse").value.trim();
  const commune = communeCourante();
  if (texte.length < 2 || !commune) {
    boite.hidden = true;
    return;
  }

  let resultats;
  try {
    resultats = (await api.chercherSurCarte(commune.code_insee, texte)).resultats;
  } catch (_) {
    boite.hidden = true;
    return;
  }
  if (!resultats.length) {
    boite.innerHTML = '<li class="suggestion-vide">Aucun résultat dans cette commune.</li>';
    boite.hidden = false;
    return;
  }

  boite.innerHTML = resultats.map((r, index) => `
    <li>
      <button type="button" data-suggestion="${index}">
        <span>${echapper(r.libelle)}</span>
        <span class="donnee">${r.type === "parcelle" ? "parcelle"
          : `${entierFr.format(r.diagnostics || 0)} DPE`}</span>
      </button>
    </li>`).join("");
  boite.hidden = false;
  boite.querySelectorAll("[data-suggestion]").forEach((bouton) => {
    bouton.addEventListener("click", () => {
      const choix = resultats[Number(bouton.dataset.suggestion)];
      boite.hidden = true;
      $("#carte-adresse").value = choix.libelle;
      carte.allerA(choix.latitude, choix.longitude);
    });
  });
}

export function initialiserExploration() {
  carte = creerCarteExploration("carte-exploration", {
    surDeplacement: rafraichir,
    surParcelle: decrire,
  });

  // Leaflet mesure son conteneur à la création : l'écran étant masqué à ce
  // moment-là, il calcule une taille nulle. Il faut le prévenir.
  auChangement("carte", async () => {
    carte.redimensionner();
    await cadrerSurLaCommune();
    rafraichir();
  });

  surCommunePrete(async () => {
    if ($("#vue-carte").hidden) return;
    await cadrerSurLaCommune();
    rafraichir();
  });
  auTermeDeLImport(() => { if (!$("#vue-carte").hidden) rafraichir(); });

  $("#carte-adresse").addEventListener("input", () => {
    clearTimeout(minuterieRecherche);
    minuterieRecherche = setTimeout(suggerer, 220);
  });

  // Le bouton de la bulle est créé par Leaflet après coup : on écoute au
  // niveau de la vue plutôt que sur un élément qui n'existe pas encore.
  $("#vue-carte").addEventListener("click", (evenement) => {
    const cible = evenement.target.closest("[data-fiche]");
    if (cible) ouvrirFiche({ n_dpe: cible.dataset.fiche, retour: "carte" });
  });
}
