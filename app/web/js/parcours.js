// ====================================================================
//  parcours.js — Le chemin de l'utilisateur.
//
//      accueil  →  commune  →  résultats
//
//  L'intention d'abord — regarder les DPE récents, ou identifier un bien
//  depuis une annonce — puis la commune, puis les résultats. La commune ne
//  se déclare nulle part : on la choisit dans le parcours, et l'application
//  va chercher ses diagnostics si elle ne les a pas.
// ====================================================================

import { api } from "./api.js";
import {
  $, afficherErreur, afficherTravail, debounce, echapper, entierFr,
  masquerErreur, masquerTravail,
} from "./format.js";
import { auProchainTerme, auTermeDeLImport, suivreImport } from "./import.js";
import { changerVue } from "./navigation.js";

const parcours = { intention: null, commune: null };
const abonnes = new Set();

export function communeCourante() { return parcours.commune; }
export function intentionCourante() { return parcours.intention; }

/** Le nom lisible de l'intention en cours, pour le bandeau. */
export function libelleIntention() {
  return LIBELLES[parcours.intention] || "Veille immobilière";
}

/** Prévenu quand une commune est choisie et prête à être consultée. */
export function surCommunePrete(rappel) { abonnes.add(rappel); }

const LIBELLES = {
  veille: "Les DPE récents",
  identifier: "Identifier un bien",
  carte: "Explorer la carte",
};

// La carte d'exploration a besoin du parcellaire et des ventes, qui
// arrivent ensemble : un second téléchargement, déclenché pour elle seule.
const BESOIN = { carte: "cadastre" };

const QUESTIONS = {
  veille: "Les DPE récents de quelle commune&nbsp;?",
  identifier: "Identifier un bien de quelle commune&nbsp;?",
  carte: "Explorer la carte de quelle commune&nbsp;?",
};

// --------------------------------------------------------------------
//  Étape 1 — l'intention
// --------------------------------------------------------------------

function choisirIntention(intention) {
  parcours.intention = intention;
  $("#question-commune").innerHTML =
    QUESTIONS[intention] || "Sur quelle commune&nbsp;?";
  changerVue("commune");
  $("#recherche-commune").focus();
  chargerCommunesConnues();
}

// --------------------------------------------------------------------
//  Étape 2 — la commune
// --------------------------------------------------------------------

function gabaritCommune(commune, deja) {
  const detail = [
    commune.departement,
    commune.population ? `${entierFr.format(commune.population)} hab.` : null,
    commune.code_postal,
  ].filter(Boolean).join(" · ");

  const etat = commune.en_cache || deja
    ? `<span class="pastille">${entierFr.format(commune.dpe || 0)} DPE en cache</span>`
    : '<span class="pastille pastille-a-chercher">à télécharger</span>';

  return `
    <li>
      <button type="button" class="commune" data-insee="${echapper(commune.code_insee)}"
              data-nom="${echapper(commune.nom)}">
        <span class="commune-nom">${echapper(commune.nom)}</span>
        <span class="commune-detail">${echapper(detail)}</span>
        ${etat}
      </button>
    </li>`;
}

function brancherChoix(racine) {
  racine.querySelectorAll("[data-insee]").forEach((bouton) => {
    bouton.addEventListener("click", () =>
      choisirCommune({ code_insee: bouton.dataset.insee, nom: bouton.dataset.nom }));
  });
}

async function chercherCommunes(texte) {
  const liste = $("#resultats-commune");
  if (texte.trim().length < 2) {
    liste.innerHTML = "";
    return;
  }

  try {
    const { communes } = await api.chercherCommunes(texte);
    liste.innerHTML = communes.length
      ? communes.map((c) => gabaritCommune(c, false)).join("")
      : `<li class="vide-court">Aucune commune ne correspond à « ${echapper(texte)} ».</li>`;
    brancherChoix(liste);
  } catch (erreur) {
    liste.innerHTML =
      '<li class="vide-court">La recherche de communes est indisponible. ' +
      "Vérifiez la connexion du NAS, ou choisissez une commune déjà consultée.</li>";
  }
}

/** Les communes déjà en cache : un clic, pas de téléchargement. */
async function chargerCommunesConnues() {
  const boite = $("#communes-connues");
  try {
    const { communes } = await api.communes();
    if (!communes.length) {
      boite.innerHTML = "";
      return;
    }
    boite.innerHTML =
      "<h3>Déjà consultées</h3>" +
      '<ul class="liste-communes">' +
      communes.map((c) => gabaritCommune({ ...c, en_cache: true }, true)).join("") +
      "</ul>";
    brancherChoix(boite);
  } catch (_) {
    boite.innerHTML = "";
  }
}

// --------------------------------------------------------------------
//  Étape 3 — les résultats
// --------------------------------------------------------------------

async function choisirCommune(commune) {
  masquerErreur();
  parcours.commune = commune;

  const besoin = BESOIN[parcours.intention] || "dpe";

  let etat;
  try {
    etat = await api.preparerCommune(commune.code_insee, besoin);
  } catch (erreur) {
    afficherErreur(`Impossible de préparer ${commune.nom}.`, erreur.message);
    return;
  }

  if (!etat.lance) {
    afficherResultats();
    return;
  }

  // Rien à montrer tant que la première moisson n'a pas abouti — ni les
  // DPE, ni le cadastre. Une simple mise à jour, elle, se fait derrière
  // pendant qu'on consulte ce qui est déjà là.
  const premiere = etat.raison === "jamais_moissonnee"
                   || etat.raison === "cadastre_manquant";
  afficherTravail(premiere
    ? (etat.raison === "cadastre_manquant"
        ? `Téléchargement du cadastre de ${commune.nom}…`
        : `Téléchargement des diagnostics de ${commune.nom}…`)
    : `${commune.nom} — mise à jour en cours…`);
  suivreImport();

  if (premiere) {
    $("#vue-commune").querySelector(".liste-communes").innerHTML = "";
    auProchainTerme(afficherResultats);
  } else {
    afficherResultats();
  }
}

function afficherResultats() {
  masquerTravail();
  changerVue(parcours.intention || "veille");
  dessinerContexte();
  for (const rappel of abonnes) {
    try { rappel(parcours.commune); } catch (_) { /* un écran fautif n'en bloque pas un autre */ }
  }
}

/** La barre qui rappelle où l'on est, et permet d'en changer. */
export function dessinerContexte(informations = {}) {
  const commune = parcours.commune;
  if (!commune) return;

  const compte = informations.dpe != null
    ? ` · <span class="donnee">${entierFr.format(informations.dpe)}</span> DPE en cache`
    : "";

  const contenu = `
    <span class="contexte-intention">${echapper(LIBELLES[parcours.intention] || "")}</span>
    <span class="contexte-commune">${echapper(commune.nom)}</span>${compte}
    <button type="button" class="bouton-lien" data-changer>Changer de commune</button>`;

  for (const identifiant of ["#contexte-veille", "#contexte-identifier"]) {
    const boite = $(identifiant);
    if (!boite) continue;
    boite.innerHTML = contenu;
    boite.querySelector("[data-changer]").addEventListener("click", () => {
      changerVue("commune");
      chargerCommunesConnues();
      $("#recherche-commune").focus();
    });
  }
}

// --------------------------------------------------------------------
//  Mise en route
// --------------------------------------------------------------------

export function initialiserParcours() {
  document.querySelectorAll("[data-intention]").forEach((carte) => {
    carte.addEventListener("click", () => choisirIntention(carte.dataset.intention));
  });

  $("#recherche-commune").addEventListener("input",
    debounce((evenement) => chercherCommunes(evenement.target.value), 280));

  // Entrée sur le premier résultat : on ne fait pas cliquer pour rien.
  $("#recherche-commune").addEventListener("keydown", (evenement) => {
    if (evenement.key !== "Enter") return;
    evenement.preventDefault();
    const premier = $("#resultats-commune").querySelector("[data-insee]");
    if (premier) premier.click();
  });

  // Une moisson qui aboutit change le contenu du cache.
  auTermeDeLImport(() => {
    if (!$("#vue-commune").hidden) chargerCommunesConnues();
  });

  changerVue("accueil");
}
