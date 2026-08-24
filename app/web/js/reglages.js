// ====================================================================
//  reglages.js — Ce qui est enregistré, et ce qu'on est en train de saisir.
//
//  L'écran montrait des champs de saisie déjà remplis, et rien ne
//  distinguait une valeur enregistrée d'une valeur qu'on venait de taper.
//  Un seul bouton « Enregistrer », posé au milieu de la page, enregistrait
//  pourtant toutes les zones — y compris celles situées en dessous.
//
//  Chaque zone montre donc désormais CE QUI EST ENREGISTRÉ, et rien
//  d'autre. « Modifier » ouvre les champs, « Enregistrer » n'écrit que
//  cette zone-là, « Annuler » referme sans rien changer.
// ====================================================================

import { api } from "./api.js";
import { $, afficherErreur, afficherSucces, echapper, entierFr,
         masquerErreur } from "./format.js";

/**
 * Ce que chaque zone possède, et comment le raconter.
 *
 * `cles` sert à deux choses : n'enregistrer que cette zone, et remplir ses
 * champs depuis les valeurs en base au moment de les ouvrir.
 */
const ZONES = {
  secteurs: {
    cles: ["zones", "zones_code_insee"],
    resume: (r) => {
      const noms = Object.keys(r.zones || {});
      return [
        ["Secteurs", noms.length
          ? noms.join(", ")
          : "aucun — tous les logements sont « hors secteur »"],
        ["Commune concernée", r.zones_code_insee
          || "toutes (les secteurs s'appliquent partout)"],
      ];
    },
  },

  filtres: {
    cles: ["fenetre_jours", "type_batiment", "surface_min", "surface_max",
           "purge_mois"],
    resume: (r) => [
      ["Fenêtre", `${entierFr.format(r.fenetre_jours)} jours`],
      ["Type de bâtiment", r.type_batiment || "tous"],
      ["Surface", `${entierFr.format(r.surface_min)} à `
        + `${entierFr.format(r.surface_max)} m²`],
      ["Purge", r.purge_mois
        ? `au-delà de ${entierFr.format(r.purge_mois)} mois sans être revu`
        : "jamais — tout l'historique est conservé"],
    ],
  },

  alerte: {
    cles: ["alerte_active", "alerte_destinataire", "alerte_code_insee",
           "alerte_zone", "alerte_ventes_active"],
    resume: (r, extra) => [
      ["État", r.alerte_active ? "activée" : "désactivée"],
      ["Destinataire", r.alerte_destinataire || "aucun"],
      ["Commune surveillée", extra.nomCommune(r.alerte_code_insee)],
      ["Secteur", r.alerte_zone || "tous"],
      ["Ventes publiées (DVF)", r.alerte_ventes_active
        ? "signalées — deux parutions par an"
        : "non signalées"],
    ],
  },

  envoi: {
    cles: ["smtp_hote", "smtp_port", "smtp_ssl", "smtp_expediteur",
           "smtp_utilisateur", "smtp_motdepasse"],
    resume: (r) => r.smtp_hote ? [
      ["Serveur", `${r.smtp_hote}:${entierFr.format(r.smtp_port)}`],
      ["Chiffrement", r.smtp_ssl ? "SSL direct" : "STARTTLS"],
      ["Adresse d'expédition", r.smtp_expediteur || "aucune"],
      ["Identifiant", r.smtp_utilisateur || "aucun (sans authentification)"],
      ["Mot de passe", r.smtp_motdepasse_defini ? "enregistré" : "aucun"],
    ] : [["Serveur", "aucun — l'alerte ne peut rien envoyer"]],
  },

  "vue-rue": {
    cles: ["streetview_cle"],
    resume: (r) => [
      ["Clé d'API", r.streetview_cle_defini
        ? "enregistrée — la fiche affiche le cliché de rue"
        : "aucune — la fiche garde son simple lien, rien n'est transmis"],
    ],
  },
};

// Comment chaque réglage se lit et s'écrit dans son champ. Le reste du
// module n'a ainsi rien à savoir des identifiants ni des types.
const CHAMPS = {
  zones: { champ: "#r-zones", lire: (v) => texteVersZones(v),
           poser: (e, v) => { e.value = zonesVersTexte(v); } },
  zones_code_insee: { champ: "#r-zones-insee" },
  fenetre_jours: { champ: "#r-fenetre", nombre: true },
  type_batiment: { champ: "#r-type" },
  surface_min: { champ: "#r-surface-min", nombre: true },
  surface_max: { champ: "#r-surface-max", nombre: true },
  purge_mois: { champ: "#r-purge", nombre: true },
  alerte_active: { champ: "#r-alerte-active", booleen: true },
  alerte_destinataire: { champ: "#r-alerte-destinataire" },
  alerte_code_insee: { champ: "#r-alerte-commune" },
  alerte_zone: { champ: "#r-alerte-zone" },
  alerte_ventes_active: { champ: "#r-alerte-ventes", booleen: true },
  smtp_hote: { champ: "#r-smtp-hote" },
  smtp_port: { champ: "#r-smtp-port", nombre: true },
  smtp_ssl: { champ: "#r-smtp-ssl", booleen: true },
  smtp_expediteur: { champ: "#r-smtp-expediteur" },
  smtp_utilisateur: { champ: "#r-smtp-utilisateur" },
  smtp_motdepasse: { champ: "#r-smtp-motdepasse", brut: true },
  streetview_cle: { champ: "#r-streetview", brut: true },
};

let enregistres = {};
let communes = [];
let auxChangements = null;

function zonesVersTexte(zones) {
  return Object.entries(zones || {})
    .map(([nom, [lat, lon]]) => `${nom} ${lat} ${lon}`).join("\n");
}

function texteVersZones(texte) {
  const zones = {};
  for (const ligne of String(texte || "").split("\n")) {
    const mots = ligne.trim().split(/\s+/);
    if (mots.length < 3 || !mots[0]) continue;
    const lat = Number(mots[1]);
    const lon = Number(mots[2]);
    if (Number.isNaN(lat) || Number.isNaN(lon)) {
      throw new Error(`Secteur « ${mots[0]} » : coordonnées illisibles.`);
    }
    zones[mots[0]] = [lat, lon];
  }
  return zones;
}

function nomCommune(code) {
  if (!code) return "toutes les communes";
  const trouvee = communes.find((c) => c.code_insee === code);
  return trouvee ? `${trouvee.nom} (${code})` : code;
}

/** Le résumé d'une zone : uniquement ce que la base contient. */
function dessinerResume(nom) {
  const section = document.querySelector(`[data-reglage="${nom}"]`);
  const boite = section?.querySelector(".reglage-resume");
  if (!boite) return;
  const lignes = ZONES[nom].resume(enregistres, { nomCommune });
  boite.innerHTML = lignes.map(([etiquette, valeur]) => `
    <div>
      <dt>${echapper(etiquette)}</dt>
      <dd>${echapper(String(valeur))}</dd>
    </div>`).join("");
}

/** Remplit les champs d'une zone depuis ce qui est enregistré. */
function poserChamps(nom) {
  for (const cle of ZONES[nom].cles) {
    const regle = CHAMPS[cle];
    const element = $(regle.champ);
    if (!element) continue;
    const valeur = enregistres[cle];
    if (regle.poser) regle.poser(element, valeur);
    else if (regle.booleen) element.value = valeur ? "1" : "0";
    else element.value = valeur ?? "";
  }
}

function lireChamps(nom) {
  const valeurs = {};
  for (const cle of ZONES[nom].cles) {
    const regle = CHAMPS[cle];
    const element = $(regle.champ);
    if (!element) continue;
    if (regle.lire) valeurs[cle] = regle.lire(element.value);
    else if (regle.booleen) valeurs[cle] = element.value === "1";
    else if (regle.nombre) valeurs[cle] = Number(element.value);
    // `brut` : un secret se renvoie tel quel, puces comprises — le serveur
    // reconnaît son propre masque et conserve la valeur.
    else if (regle.brut) valeurs[cle] = element.value;
    else valeurs[cle] = element.value.trim();
  }
  return valeurs;
}

function basculer(nom, enEdition) {
  const section = document.querySelector(`[data-reglage="${nom}"]`);
  if (!section) return;
  section.querySelector(".reglage-edition").hidden = !enEdition;
  const resume = section.querySelector(".reglage-resume");
  if (resume) resume.hidden = enEdition;
  const modifier = section.querySelector(".bouton-modifier");
  if (modifier) modifier.hidden = enEdition;
}

async function enregistrerZone(nom) {
  masquerErreur();
  let valeurs;
  try {
    valeurs = lireChamps(nom);
  } catch (erreur) {
    afficherErreur(erreur.message);
    return;
  }
  try {
    const { reglages } = await api.enregistrerReglages(valeurs);
    enregistres = reglages;
    dessinerResume(nom);
    basculer(nom, false);
    afficherSucces("Enregistré.");
    if (auxChangements) auxChangements();
  } catch (erreur) {
    afficherErreur("Réglages refusés.", erreur.message);
  }
}

/** Relit tout depuis le serveur et redessine les résumés. */
export async function rafraichirReglages() {
  const [{ reglages }, listeCommunes] = await Promise.all([
    api.reglages(),
    api.communes().then((r) => r.communes).catch(() => []),
  ]);
  enregistres = reglages;
  communes = listeCommunes;
  for (const nom of Object.keys(ZONES)) dessinerResume(nom);
}

export function initialiserReglages(surChangement) {
  auxChangements = surChangement;

  document.querySelectorAll("[data-reglage]").forEach((section) => {
    const nom = section.dataset.reglage;
    if (!ZONES[nom]) return;          // la zone de contrôle n'a rien à régler

    section.querySelector(".bouton-modifier")?.addEventListener("click", () => {
      poserChamps(nom);
      basculer(nom, true);
      section.querySelector("input, select, textarea")?.focus();
    });
    section.querySelector("[data-enregistrer]")?.addEventListener(
      "click", () => enregistrerZone(nom));
    section.querySelector("[data-annuler]")?.addEventListener("click", () => {
      basculer(nom, false);
      masquerErreur();
    });
  });
}
