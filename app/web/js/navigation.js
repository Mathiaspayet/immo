// ====================================================================
//  navigation.js — Passage d'un écran à l'autre.
//
//  Isolé dans son propre module pour éviter un cycle d'imports : la fiche
//  d'un bien s'ouvre depuis l'écran Veille comme depuis l'identification,
//  et aucun des trois n'a besoin de connaître les deux autres.
// ====================================================================

import { $ } from "./format.js";

// La fiche n'est pas un onglet : on y entre depuis un relevé ou un
// résultat d'identification, et on en revient.
const VUES = ["veille", "identifier", "reglages", "fiche"];

const rappels = {};

/** Enregistre ce qu'il faut faire quand un écran devient visible. */
export function auChangement(vue, rappel) {
  rappels[vue] = rappel;
}

export function changerVue(vue) {
  for (const nom of VUES) {
    const section = $(`#vue-${nom}`);
    if (section) section.hidden = nom !== vue;
  }
  document.querySelectorAll("[data-vue]").forEach((bouton) => {
    bouton.setAttribute("aria-pressed", String(bouton.dataset.vue === vue));
  });
  if (rappels[vue]) rappels[vue]();
  window.scrollTo({ top: 0 });
}

export function vueCourante() {
  return VUES.find((nom) => $(`#vue-${nom}`) && !$(`#vue-${nom}`).hidden);
}
