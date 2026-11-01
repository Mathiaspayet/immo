// ====================================================================
//  acces.js — L'écran de connexion, et la zone « Accès » des réglages.
//
//  L'API refuse tout sans session. Ce module passe donc AVANT le reste :
//  tant qu'on n'est pas connecté, aucun écran ne se charge — il n'aurait
//  que des refus à montrer.
//
//  Trois cas, selon ce que dit le serveur :
//    - aucun mot de passe encore : on propose d'envoyer le lien ;
//    - un mot de passe existe : on le demande, le lien en recours ;
//    - on arrive par le lien (#acces=…) : on choisit le mot de passe.
//
//  Le jeton du lien est dans le FRAGMENT de l'adresse : le navigateur ne
//  l'envoie jamais au serveur, et on l'efface de la barre d'adresse dès
//  qu'il a servi.
// ====================================================================

import { api } from "./api.js";
import { $, afficherSucces } from "./format.js";

const MARQUE = "acces=";

function jetonDuLien() {
  const fragment = location.hash.replace(/^#/, "");
  return fragment.startsWith(MARQUE) ? fragment.slice(MARQUE.length) : "";
}

function oublierLeLien() {
  history.replaceState(history.state, "", location.pathname + location.search);
}

function dire(message, genre = "erreur") {
  const zone = $("#acces-message");
  zone.textContent = message || "";
  zone.className = `message message-${genre}`;
  zone.hidden = !message;
}

const TEXTES = {
  premier: (etat) => [
    "Choisir le mot de passe",
    "L'application est désormais protégée par un mot de passe. Pour le "
    + "choisir, recevez un lien par courriel"
    + (etat.destinataire ? ` à ${etat.destinataire}.` : "."),
  ],
  connexion: () => ["Connexion", "Saisissez le mot de passe de l'application."],
  definir: (etat) => [
    "Nouveau mot de passe",
    `Au moins ${etat.longueur_min} caractères. Il remplace l'ancien s'il y en `
    + "avait un, et déconnecte les autres appareils.",
  ],
};

function montrer(mode, etat) {
  document.body.classList.add("verrouille");
  $("#ecran-acces").hidden = false;
  $("#acces-connexion").hidden = mode !== "connexion";
  $("#acces-definir").hidden = mode !== "definir";

  const [titre, explication] = TEXTES[mode](etat);
  $("#acces-titre").textContent = titre;
  $("#acces-explication").textContent = explication;

  const lien = $("#acces-lien");
  lien.hidden = mode === "definir";
  lien.disabled = !etat.envoi_possible;
  lien.textContent = mode === "premier"
    ? "Recevoir le lien par courriel" : "Mot de passe oublié ? Recevoir un lien";
  lien.className = mode === "premier" ? "bouton bouton-principal" : "bouton bouton-discret";
  dire(mode !== "definir" && !etat.envoi_possible
    ? "Le lien ne peut pas partir : le serveur d'envoi ou l'adresse manque. "
      + "Le recours depuis le NAS est décrit dans la documentation (README, « Accès »)."
    : "", "travail");

  const champ = mode === "connexion" ? $("#acces-motdepasse")
    : mode === "definir" ? $("#acces-nouveau") : lien;
  champ.focus();
}

function fermer() {
  document.body.classList.remove("verrouille");
  $("#ecran-acces").hidden = true;
  dire("");
  ["#acces-motdepasse", "#acces-nouveau", "#acces-confirmation"]
    .forEach((selecteur) => { $(selecteur).value = ""; });
}

// Branché une seule fois : `suite` dit quoi faire une fois connecté, et
// `etatCourant` ce que le serveur a dit en dernier.
let suite = () => {};
let etatCourant = {};
let branche = false;

function brancher() {
  if (branche) return;
  branche = true;

  $("#acces-connexion").addEventListener("submit", async (evenement) => {
    evenement.preventDefault();
    const champ = $("#acces-motdepasse");
    try {
      await api.seConnecter(champ.value);
      fermer();
      suite();
    } catch (erreur) {
      champ.value = "";
      champ.focus();
      dire(erreur.message);
    }
  });

  $("#acces-definir").addEventListener("submit", async (evenement) => {
    evenement.preventDefault();
    const nouveau = $("#acces-nouveau").value;
    if (nouveau !== $("#acces-confirmation").value) {
      dire("Les deux saisies ne sont pas identiques.");
      return;
    }
    try {
      await api.definirMotDePasse(jetonDuLien(), nouveau);
      oublierLeLien();
      fermer();
      afficherSucces("Mot de passe enregistré.");
      suite();
    } catch (erreur) {
      dire(erreur.message);
      // Un lien perimé ne se rattrape pas : on offre d'en demander un autre.
      $("#acces-lien").hidden = false;
    }
  });

  $("#acces-lien").addEventListener("click", async () => {
    const bouton = $("#acces-lien");
    bouton.disabled = true;
    try {
      const envoi = await api.demanderLien();
      dire(`Lien envoyé à ${envoi.destinataire}. Il est valable `
           + `${envoi.valable_minutes} minutes : ouvrez-le depuis le courriel.`, "succes");
    } catch (erreur) {
      dire(erreur.message);
    } finally {
      bouton.disabled = !etatCourant.envoi_possible;
    }
  });
}

function ouvrir(etat, apres) {
  suite = apres;
  etatCourant = etat;
  brancher();
  montrer(jetonDuLien() ? "definir" : etat.initialise ? "connexion" : "premier", etat);
}

/**
 * Rend la main quand on est connecté. Sinon montre l'écran d'accès, et ne
 * la rend qu'après — le reste du démarrage attend.
 */
export async function garantirAcces() {
  let etat;
  try {
    etat = await api.etatAcces();
  } catch (erreur) {
    // Serveur injoignable : on le dit, et rien d'autre ne démarre.
    ouvrir({ initialise: true, envoi_possible: false, longueur_min: 10 }, () => {});
    dire(erreur.message);
    return new Promise(() => {});
  }
  if (etat.connecte && !jetonDuLien()) return;
  await new Promise((resoudre) => ouvrir(etat, resoudre));
}

// Une session qui tombe en cours de route — trente jours sans venir, une
// déconnexion depuis un autre appareil : on redemande le mot de passe, puis
// on recharge, l'écran courant ayant été coupé en plein travail.
window.addEventListener("acces-requis", async () => {
  if (!$("#ecran-acces").hidden) return;
  const etat = await api.etatAcces().catch(() => null);
  if (etat && !etat.connecte) ouvrir(etat, () => location.reload());
});

// --------------------------------------------------------------------
//  La zone « Accès » des réglages
// --------------------------------------------------------------------

export function initialiserAccesReglages() {
  api.etatAcces().then((etat) => {
    $("#acces-destinataire").textContent = etat.destinataire || "aucune adresse";
  }).catch(() => {});

  $("#acces-changer").addEventListener("submit", async (evenement) => {
    evenement.preventDefault();
    const zone = $("#acces-changer-message");
    const nouveau = $("#acces-change-nouveau").value;
    zone.hidden = false;
    zone.className = "message message-erreur";
    if (nouveau !== $("#acces-change-confirmation").value) {
      zone.textContent = "Les deux saisies du nouveau mot de passe ne sont pas identiques.";
      return;
    }
    try {
      await api.changerMotDePasse($("#acces-actuel").value, nouveau);
      $("#acces-changer").reset();
      zone.className = "message message-succes";
      zone.textContent = "Mot de passe changé. Les autres appareils ont été déconnectés.";
    } catch (erreur) {
      zone.textContent = erreur.message;
    }
  });

  $("#acces-deconnexion").addEventListener("click", async () => {
    await api.seDeconnecter(false).catch(() => {});
    location.reload();
  });

  $("#acces-deconnexion-partout").addEventListener("click", async () => {
    if (!window.confirm("Déconnecter tous les appareils, celui-ci compris ?")) return;
    await api.seDeconnecter(true).catch(() => {});
    location.reload();
  });
}
