// ====================================================================
//  navigation.js — Passage d'un écran à l'autre, et retour arrière.
//
//  Isolé dans son propre module pour éviter un cycle d'imports : la fiche
//  d'un bien s'ouvre depuis la carte comme depuis l'identification, et
//  aucun des trois n'a besoin de connaître les deux autres.
// ====================================================================

import { $ } from "./format.js";

// La fiche n'est pas un onglet : on y entre depuis un relevé ou un
// résultat d'identification, et on en revient.
// Toute vue doit figurer ici : `changerVue` masque tout ce qu'elle
// connait et montre le reste. Une vue absente de la liste n'est jamais
// affichee — l'ecran reste vide, sans erreur pour le signaler.
const VUES = ["accueil", "commune", "identifier",
              "carte", "reglages", "fiche", "estimation", "estimations"];

const rappels = {};
const restaurateurs = {};

/** Enregistre ce qu'il faut faire quand un écran devient visible. */
export function auChangement(vue, rappel) {
  rappels[vue] = rappel;
}

/**
 * Comment reconstruire un écran à partir de ce que l'historique en garde.
 *
 * L'écran de la carte se recharge de lui-même ; la fiche, non — elle a besoin
 * de savoir QUEL bien afficher. Un module qui a des paramètres à retenir
 * s'enregistre donc ici, et reçoit l'état au retour arrière.
 */
export function auRetourArriere(vue, rappel) {
  restaurateurs[vue] = rappel;
}

/**
 * Publie la hauteur réelle du bandeau dans `--bandeau-reel`.
 *
 * `--bandeau-hauteur` est une hauteur MINIMALE, pas la hauteur effective :
 * sur téléphone le bandeau passe à la ligne et atteint 105 px là où le
 * jeton en annonce 60. Les éléments qui se collent dessous — la barre de
 * retour d'une fiche, le panneau de carte — se retrouvaient à moitié
 * cachés derrière lui.
 *
 * On mesure donc, et on remesure quand la largeur change : la hauteur
 * dépend du repli du contenu, qu'aucune constante ne peut prévoir.
 */
export function mesurerBandeau() {
  const bandeau = document.querySelector(".bandeau");
  if (!bandeau) return;
  const poser = () => document.documentElement.style.setProperty(
    "--bandeau-reel", `${Math.round(bandeau.getBoundingClientRect().height)}px`);
  poser();
  if (typeof ResizeObserver === "function") {
    new ResizeObserver(poser).observe(bandeau);
  } else {
    window.addEventListener("resize", poser);
  }
}


/** Montre un écran. N'écrit rien dans l'historique. */
function montrer(vue) {
  for (const nom of VUES) {
    const section = $(`#vue-${nom}`);
    if (section) section.hidden = nom !== vue;
  }
  document.querySelectorAll("[data-vue]").forEach((bouton) => {
    bouton.setAttribute("aria-pressed", String(bouton.dataset.vue === vue));
  });

  // Le bouton « Filtres » n'a de sens que sur la carte, seul écran qui
  // en porte.
  const filtres = $("#bascule-filtres");
  if (filtres) filtres.hidden = vue !== "carte";
  if (rappels[vue]) rappels[vue]();
  window.scrollTo({ top: 0 });
}

/**
 * Change d'écran, et laisse une trace dans l'historique du navigateur.
 *
 * Sans cette trace, le bouton « retour » du téléphone quittait
 * l'application : elle tient en une seule page, et rien ne distinguait
 * l'écran d'une fiche de celui de la carte. Chaque écran devient une
 * étape, et le geste habituel — glisser depuis le bord, ou le bouton
 * matériel — remonte le parcours au lieu d'en sortir.
 *
 * `etat` porte ce qu'il faut pour reconstruire l'écran : pour une fiche,
 * de quel bien il s'agit. Sans lui, revenir sur une fiche en montrerait
 * une vide.
 */
export function changerVue(vue, etat = {}) {
  const courant = history.state;
  montrer(vue);
  // Rejouer le même écran n'ajoute pas d'étape : sinon un rafraîchissement
  // de la liste empilerait des entrées identiques, et il faudrait presser
  // « retour » dix fois pour sortir d'un écran.
  if (courant && courant.vue === vue && !etat.n_dpe && !etat.parcelle_id
      && !etat.adresse) {
    history.replaceState({ vue, ...etat }, "");
    return;
  }
  history.pushState({ vue, ...etat }, "");
}

export function vueCourante() {
  return VUES.find((nom) => $(`#vue-${nom}`) && !$(`#vue-${nom}`).hidden);
}

/**
 * Branche le retour arrière. À appeler une fois, au démarrage.
 *
 * L'état initial est posé en remplacement, pas en ajout : la première
 * entrée doit rester celle par laquelle on est entré, faute de quoi un
 * premier « retour » ne ferait que revenir sur le même écran.
 */
export function brancherHistorique(vueInitiale = "accueil") {
  mesurerBandeau();
  history.replaceState({ vue: vueInitiale }, "");

  window.addEventListener("popstate", (evenement) => {
    const etat = evenement.state;
    // Pas d'état : on est remonté avant l'application. On laisse faire.
    if (!etat || !etat.vue) return;
    // L'écran est montré DANS TOUS LES CAS : le restaurateur ne fait que
    // le remplir. Le laisser s'en charger l'oublierait, et le retour
    // arrière ne montrerait rien.
    montrer(etat.vue);
    const restaurer = restaurateurs[etat.vue];
    if (restaurer) restaurer(etat);
  });
}
