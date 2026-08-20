// ====================================================================
//  import.js — Déclenchement et suivi des moissons ADEME.
//
//  Deux façons de partir :
//    - le bouton « Rafraîchir », qui force un import ;
//    - le rafraîchissement paresseux, déclenché au lancement d'une
//      recherche quand la dernière moisson date de plus de 24 h.
//
//  Le second respecte le CDC §4 : c'est l'action de recherche qui
//  déclenche, jamais le simple affichage d'un écran. Les données déjà en
//  cache s'affichent tout de suite, l'import tourne derrière, et les
//  écrans abonnés se rafraîchissent quand il aboutit.
// ====================================================================

import { api } from "./api.js";
import {
  $, afficherErreur, afficherSucces, afficherTravail, entierFr, masquerTravail,
} from "./format.js";

let sondage = null;
const abonnes = new Set();

/** S'abonner à la fin d'un import (pour recharger l'écran concerné). */
export function auTermeDeLImport(rappel) {
  abonnes.add(rappel);
}

function prevenirLesAbonnes() {
  for (const rappel of abonnes) {
    try { rappel(); } catch (_) { /* un écran fautif n'en bloque pas un autre */ }
  }
}

// Le bouton de moisson forcée vit désormais dans les réglages, et peut
// donc être absent de l'écran courant.
function bouton() { return $("#forcer-import"); }
function griser(etat) { const b = bouton(); if (b) b.disabled = etat; }

/** Interroge /statut jusqu'à la fin, en affichant la progression. */
export function suivreImport() {
  clearInterval(sondage);
  sondage = setInterval(async () => {
    let statut;
    try {
      statut = await api.statutImport();
    } catch (erreur) {
      clearInterval(sondage);
      griser(false);
      masquerTravail();
      afficherErreur("Le suivi de l'import s'est interrompu.", erreur.message);
      return;
    }

    if (statut.en_cours) {
      const lignes = statut.lignes ? ` — ${entierFr.format(statut.lignes)} lignes` : "";
      afficherTravail(`${statut.etape || "import en cours"}${lignes}`);
      return;
    }

    clearInterval(sondage);
    griser(false);
    masquerTravail();

    if (statut.statut === "echec") {
      afficherErreur("L'import a échoué.", statut.message || "");
    } else if (statut.statut === "succes") {
      afficherSucces(statut.message || "Import terminé.");
    }
    prevenirLesAbonnes();
  }, 1500);
}

/** Le bouton « Rafraîchir » : force une moisson, quelle que soit son âge. */
export async function lancerImport() {
  griser(true);
  try {
    await api.lancerImport();
    afficherTravail("Moisson démarrée…");
    suivreImport();
  } catch (erreur) {
    griser(false);
    afficherErreur(erreur.message);
  }
}

/** Au chargement de la page, un import planifié peut déjà tourner. */
export async function reprendreSuiviEventuel() {
  try {
    const statut = await api.statutImport();
    if (statut.en_cours) {
      griser(true);
      afficherTravail(statut.etape || "import en cours");
      suivreImport();
    }
  } catch (_) { /* la page se chargera quand même */ }
}
