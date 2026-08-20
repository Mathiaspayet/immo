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

function bouton() { return $("#rafraichir"); }

/** Interroge /statut jusqu'à la fin, en affichant la progression. */
export function suivreImport() {
  clearInterval(sondage);
  sondage = setInterval(async () => {
    let statut;
    try {
      statut = await api.statutImport();
    } catch (erreur) {
      clearInterval(sondage);
      bouton().disabled = false;
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
    bouton().disabled = false;
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
  bouton().disabled = true;
  try {
    await api.lancerImport();
    afficherTravail("Import démarré…");
    suivreImport();
  } catch (erreur) {
    bouton().disabled = false;
    afficherErreur(erreur.message);
  }
}

/**
 * À appeler au lancement d'une recherche. Ne fait rien si la moisson est
 * récente, si un import tourne déjà, ou si le réglage est à zéro.
 *
 * N'échoue jamais bruyamment : ne pas pouvoir rafraîchir n'empêche pas de
 * consulter ce qui est déjà là.
 */
export async function rafraichirSiPerime() {
  try {
    const reponse = await api.rafraichirSiPerime();
    if (!reponse.lance) return false;

    const age = reponse.age_heures;
    afficherTravail(
      age == null
        ? "Première moisson des données ADEME…"
        : `Données vieilles de ${Math.round(age)} h — mise à jour en cours…`
    );
    bouton().disabled = true;
    suivreImport();
    return true;
  } catch (_) {
    return false;      // le cache reste consultable, on n'alarme personne
  }
}

/** Au chargement de la page, un import planifié peut déjà tourner. */
export async function reprendreSuiviEventuel() {
  try {
    const statut = await api.statutImport();
    if (statut.en_cours) {
      bouton().disabled = true;
      afficherTravail(statut.etape || "import en cours");
      suivreImport();
    }
  } catch (_) { /* la page se chargera quand même */ }
}
