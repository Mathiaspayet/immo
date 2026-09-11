// -*- coding: utf-8 -*-
/**
 * exploration.js — L'écran de la carte, et la liste des DPE récents.
 *
 * On parcourt la commune sur photo aérienne, chaque parcelle colorée selon
 * ce qu'on en sait : un diagnostic, une vente, les deux, ou rien encore.
 * C'est le croisement qui informe — une parcelle vendue sans diagnostic
 * récent et une parcelle diagnostiquée sans vente ne racontent pas la même
 * histoire.
 *
 * LA LISTE ET LA CARTE SONT LE MÊME ÉCRAN. C'étaient deux parcours
 * distincts — « Les DPE récents » et « Explorer la carte » — qui montraient
 * la même commune sans jamais se rejoindre. Ils n'en font plus qu'un : la
 * carte seule tant qu'on explore, la liste à côté dès qu'on demande une
 * fenêtre de diagnostics récents.
 *
 * Les deux se complètent, et ce n'est pas un confort. Les parcelles ne
 * portent que les DPE rattachés au cadastre ; sur un an à Mimizan, 18 sur
 * 307 ne le sont pas — l'ADEME ne les a pas géocodés assez finement. La
 * liste et les repères, eux, travaillent sur les coordonnées : rien ne
 * disparaît en silence.
 *
 * Deux contraintes gouvernent la partie cartographique :
 *
 *   - le volume. Les 11 444 parcelles de Mimizan pèsent 3,8 Mo. On ne
 *     charge donc que le cadre affiché, et on prévient quand il en reste
 *     au-delà plutôt que d'en tracer une bouillie ;
 *   - le zoom. En dessous d'un certain niveau, les parcelles sont trop
 *     petites pour se distinguer et trop nombreuses pour se charger : la
 *     carte le dit au lieu de peiner en silence. Les repères des
 *     diagnostics, eux, restent visibles à toute échelle.
 */

import { api, ErreurApi } from "./api.js";
import { creerCarteExploration, etatParcelle } from "./carte.js";
import {
  $, afficherErreur, afficherSucces, anciennete, dateFr, echapper, entierFr,
  etiquetteHtml, liensExternes, masquerErreur, mesure, nombreFr,
} from "./format.js";
import { ouvrirFiche } from "./fiche.js";
import { auTermeDeLImport } from "./import.js";
import { auChangement } from "./navigation.js";
import { communeCourante, dessinerContexte, surCommunePrete } from "./parcours.js";

// En dessous, une commune entière tient à l'écran : des milliers de
// parcelles de quelques pixels, illisibles et lourdes à charger.
const ZOOM_MINIMAL = 15;

let carte = null;
let derniereRequete = 0;
let communeCadree = null;

// L'etat de l'ecran. `etat` tout court etait deja pris par la ligne
// d'etat de la carte, plus bas.
const ecran = {
  filtres: {},
  resultats: [],
  selection: null,
  listeVisible: false,
};

// ====================================================================
//  La liste des DPE récents
//
//  Elle n'apparaît que si on la demande : choisir une fenêtre, c'est
//  dire « montre-moi ce qui vient d'être diagnostiqué ». Tant qu'aucune
//  n'est choisie, l'écran reste ce qu'il était — une carte, en grand.
// ====================================================================

function gabaritReleve(bien) {
  return `
  <article class="releve" data-dpe="${echapper(bien.n_dpe)}"
           data-nouveau="${bien.nouveau ? "oui" : "non"}" tabindex="0">
    <div class="releve-tete">
      <span class="date donnee">${dateFr(bien.date_etablissement)}</span>
      <span>${anciennete(bien.anciennete_jours)}</span>
      ${bien.nouveau ? '<span class="pastille pastille-nouveau">nouveau</span>' : ""}
      ${bien.zone ? `<span class="secteur">${echapper(bien.zone)}</span>` : ""}
      ${bien.type_batiment ? `<span>${echapper(bien.type_batiment)}</span>` : ""}
    </div>
    <h3 class="adresse">${echapper(bien.adresse || "Adresse absente de la base")}</h3>
    <dl class="mesures">
      ${mesure("surface", bien.surface_habitable, "m²")}
      <div><dt>classe</dt><dd>${etiquetteHtml(bien.etiquette_dpe)}</dd></div>
      ${mesure("énergie ép.", bien.conso_ep_m2, "kWh/m²", entierFr)}
      ${mesure("GES", bien.ges_m2, "kg/m²", nombreFr)}
      ${mesure("coût annuel", bien.cout_annuel, "€", entierFr)}
      ${mesure("construit", bien.annee_construction, "", entierFr)}
    </dl>
    <div class="liens">
      <button type="button" class="bouton-lien" data-fiche="${echapper(bien.n_dpe)}">Fiche du bien</button>
      ${liensExternes(bien)}
      <span class="reference donnee">${echapper(bien.n_dpe)}</span>
    </div>
  </article>`;
}

/** La fenêtre est l'interrupteur : vide, pas de liste. */
function fenetreChoisie() {
  return $("#filtres").fenetre_jours.value !== "";
}

function lireFiltres() {
  const formulaire = $("#filtres");
  const etiquette = formulaire.etiquettes.value;
  return {
    fenetre_jours: formulaire.fenetre_jours.value,
    // La commune vient du parcours, pas d'un filtre : on l'a choisie avant
    // d'arriver ici. Par son code INSEE, l'ADEME écrivant le même nom de
    // plusieurs façons.
    code_insee: communeCourante()?.code_insee ?? "",
    zone: formulaire.zone.value,
    type_batiment: formulaire.type_batiment.value,
    surface_min: formulaire.surface_min.value,
    surface_max: formulaire.surface_max.value,
    etiquettes: etiquette ? [etiquette] : [],
    seulement_nouveaux: formulaire.seulement_nouveaux.checked,
  };
}

/**
 * Installe les critères enregistrés, SAUF la fenêtre.
 *
 * La fenêtre reste vide au démarrage : c'est elle qui ouvre la liste, et
 * l'écran doit s'ouvrir sur la carte. Les autres critères — surface, type,
 * classe — sont ceux des réglages, donc ceux du courriel d'alerte : à la
 * première fenêtre demandée, la liste montre exactement ce que l'alerte
 * surveille, sans rien avoir à ressaisir.
 */
function appliquerFiltres(filtres) {
  const formulaire = $("#filtres");

  // Les réglages autorisent n'importe quelle fenêtre (45 jours par
  // exemple). Si elle ne figure pas dans la liste déroulante, on l'y
  // ajoute : sans cela l'utilisateur ne pourrait pas retrouver d'un clic
  // le périmètre exact de son alerte.
  const fenetre = String(filtres.fenetre_jours ?? 120);
  const choix = formulaire.fenetre_jours;
  if (![...choix.options].some((option) => option.value === fenetre)) {
    choix.add(new Option(`${fenetre} jours`, fenetre));
  }
  formulaire.type_batiment.value = filtres.type_batiment ?? "";
  formulaire.surface_min.value = filtres.surface_min ?? "";
  formulaire.surface_max.value = filtres.surface_max ?? "";
  formulaire.seulement_nouveaux.checked = Boolean(filtres.seulement_nouveaux);
}

function dessinerCompteurs(resume) {
  const secteurs = Object.entries(resume.par_zone || {})
    .sort((a, b) => b[1] - a[1])
    .map(([nom, n]) => `${echapper(nom)} <span class="donnee">${n}</span>`)
    .join(" · ");

  const dernier = resume.dernier_import;
  const etatImport = dernier
    ? `${dernier.statut === "succes" ? "dernier import" : "dernier import en échec"} ` +
      `<span class="donnee">${dateFr(dernier.fin)}</span>`
    : "aucun import effectué";

  $("#compteurs").innerHTML = `
    <span class="bloc"><span class="chiffre">${resume.total}</span> logement(s)</span>
    <span class="separation"></span>
    <span class="bloc"><span class="chiffre">${resume.nouveaux}</span> nouveauté(s)</span>
    ${secteurs ? `<span class="separation"></span><span class="bloc">${secteurs}</span>` : ""}
    <span class="separation"></span>
    <span class="bloc">${etatImport}</span>
    <span class="separation"></span>
    <span class="bloc"><span class="donnee">${entierFr.format(resume.total_base)}</span> DPE en cache</span>`;
}

function dessinerListe(resultats, resume) {
  const liste = $("#liste");

  if (!resultats.length) {
    // Un etat vide doit dire ce qui s'est passe et quoi faire (CDC 7).
    const jamais = resume.total_base === 0;
    liste.innerHTML = jamais
      ? `<div class="vide">
           <h3>La base est vide</h3>
           <p>Aucun DPE n'a encore été importé. Lancez un premier import depuis
              les <strong>Réglages</strong>, bouton « Forcer une moisson
              maintenant » : il télécharge les diagnostics des communes
              surveillées, ce qui prend une à deux minutes.</p>
         </div>`
      : `<div class="vide">
           <h3>Aucun logement ne correspond à ces filtres</h3>
           <p>La base contient ${resume.total_base} DPE. Élargissez la fenêtre
              temporelle, ou desserrez les bornes de surface. Un secteur peut
              aussi n'avoir simplement aucun diagnostic récent : il ne
              s'établit qu'environ 1,6 DPE par jour sur l'ensemble du 40200,
              toutes communes et tous types confondus.</p>
         </div>`;
    return;
  }

  liste.innerHTML = resultats.map(gabaritReleve).join("");

  liste.querySelectorAll("[data-fiche]").forEach((bouton) => {
    bouton.addEventListener("click", (evenement) => {
      evenement.stopPropagation();
      ouvrirFiche({ n_dpe: bouton.dataset.fiche, retour: "carte" });
    });
  });

  liste.querySelectorAll(".releve").forEach((element) => {
    const choisir = () => selectionner(element.dataset.dpe);
    element.addEventListener("click", (evenement) => {
      // On laisse passer les liens externes et le bouton de fiche.
      if (evenement.target.closest("a, button")) return;
      choisir();
    });
    element.addEventListener("keydown", (evenement) => {
      if (evenement.key === "Enter" || evenement.key === " ") {
        evenement.preventDefault();
        choisir();
      }
    });
  });
}

/** Une ligne choisie s'allume, et la carte va la chercher. */
function selectionner(numero) {
  ecran.selection = numero;
  document.querySelectorAll(".releve").forEach((element) => {
    element.setAttribute("aria-current",
                         element.dataset.dpe === numero ? "true" : "false");
  });
  deplierCarte();
  carte?.surlignerBien(numero);
}

/**
 * Remplit la liste des secteurs.
 *
 * Elle ne l'a JAMAIS été : le menu « Secteur » n'a proposé que « tous »
 * depuis qu'il existe, alors que les secteurs sont comptés juste à côté,
 * dans la ligne de compteurs (« bourg 96 · plage 82 »). Un filtre qui ne
 * peut rien filtrer vaut moins que pas de filtre : il se désactive
 * maintenant tout seul quand la commune n'en porte aucun.
 */
function peuplerSecteurs(zones) {
  const liste = $("#f-zone");
  const choisi = liste.value;
  liste.innerHTML = '<option value="">tous</option>'
    + (zones || []).map((z) =>
        `<option value="${echapper(z)}">${echapper(z)}</option>`).join("");
  liste.disabled = !(zones || []).length;
  liste.value = (zones || []).includes(choisi) ? choisi : "";
}

/** Rafraîchit la barre de contexte : la commune, et son nombre de DPE. */
async function chargerContexte() {
  const commune = communeCourante();
  if (!commune) return;
  try {
    const reponse = await api.communes();
    const trouvee = (reponse.communes || []).find(
      (c) => c.code_insee === commune.code_insee);
    peuplerSecteurs(reponse.zones);
    dessinerContexte(trouvee ? { dpe: trouvee.dpe } : {});
  } catch (_) {
    // Le compte est un agrément : sans lui la barre reste juste, elle
    // annonce seulement la commune.
    dessinerContexte();
  }
}

/**
 * Montre ou cache la liste, et tout ce qui l'accompagne.
 *
 * `data-liste` sur le plan commande la mise en page : une colonne et une
 * carte haute quand il n'y a pas de liste, deux colonnes sinon.
 */
function afficherLaListe(visible) {
  const ouverture = visible && !ecran.listeVisible;
  ecran.listeVisible = visible;
  const marque = visible ? "oui" : "non";
  $("#plan-carte").dataset.liste = marque;
  $("#filtres").dataset.liste = marque;
  $("#liste").hidden = !visible;
  $("#compteurs").hidden = !visible;
  $("#filtres-detail").hidden = !visible;

  if (!visible) {
    // On VIDE, on ne se contente pas de masquer : `selectionner` cherche
    // les relevés dans toute la page, et des lignes d'une recherche
    // abandonnée continueraient d'y répondre. Elles réapparaîtraient
    // aussi le temps d'un battement à la fenêtre suivante.
    $("#liste").innerHTML = "";
    $("#compteurs").innerHTML = "";
    ecran.selection = null;
  }

  // Leaflet mesure son conteneur : la colonne vient de changer de largeur.
  setTimeout(() => carte?.redimensionner(), 60);
  return ouverture;
}

/**
 * Charge la liste si une fenêtre est demandée, la retire sinon.
 *
 * `cadrer` n'est vrai qu'à l'ouverture : on recadre sur les résultats la
 * fois où on les demande, puis on laisse la carte où l'utilisateur la met.
 */
async function chargerListe() {
  if (!fenetreChoisie()) {
    afficherLaListe(false);
    carte?.effacerBiens();
    ecran.resultats = [];
    return;
  }

  masquerErreur();
  ecran.filtres = lireFiltres();
  $("#export-csv").href = api.urlExport(ecran.filtres);

  let reponse;
  try {
    reponse = await api.veille(ecran.filtres);
  } catch (erreur) {
    afficherErreur(
      erreur instanceof ErreurApi ? erreur.message : "Impossible de charger la liste.",
      erreur instanceof ErreurApi ? "" : String(erreur));
    return;
  }

  const ouverture = afficherLaListe(true);
  ecran.resultats = reponse.resultats;
  dessinerCompteurs(reponse.resume);
  dessinerListe(reponse.resultats, reponse.resume);
  carte?.marquer(reponse.resultats);
  if (ouverture) carte?.cadrerSurLesBiens(reponse.resultats);
}

/** Sur téléphone la carte est repliée : la liste passe d'abord. */
function deplierCarte() {
  const panneau = $(".panneau-carte");
  if (panneau?.dataset.replie === "oui") {
    panneau.dataset.replie = "non";
    $("#bascule-carte").setAttribute("aria-expanded", "true");
    carte?.redimensionner();
  }
}

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
    // Les repères des DPE, eux, tiennent à toute échelle : le dire évite
    // de lire ce message comme une panne quand on vient d'ouvrir la liste
    // et que le cadrage sur les résultats a fait reculer la carte.
    etat("Zoomez pour voir les parcelles&nbsp;: à cette échelle, elles sont " +
         "trop nombreuses et trop petites pour être lisibles." +
         (ecran.listeVisible
           ? " Les repères des DPE filtrés, eux, restent affichés."
           : ""));
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

/**
 * Un clic sur une parcelle ouvre sa fiche, directement.
 *
 * La bulle intermédiaire n'apportait rien : elle répétait ce que la
 * couleur disait déjà, et imposait un second clic pour arriver là où on
 * allait de toute façon.
 *
 * Les deux chemins mènent à une fiche. Quand la parcelle porte un
 * diagnostic, c'est la fiche du bien, avec sa chronologie ; sinon c'est
 * celle de la parcelle — contour, voisinage, bâti, ventes. Le second cas
 * est de loin le plus fréquent sur la carte.
 */
function ouvrir(parcelle) {
  if (parcelle.n_dpe) {
    ouvrirFiche({ n_dpe: parcelle.n_dpe, retour: "carte" });
  } else {
    ouvrirFiche({ parcelle_id: parcelle.id, retour: "carte" });
  }
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

export async function initialiserExploration() {
  carte = creerCarteExploration("carte-exploration", {
    surDeplacement: rafraichir,
    surParcelle: ouvrir,
    // Un clic sur un repère ouvre la fiche du bien, comme un clic sur une
    // parcelle : c'est là qu'on allait de toute façon.
    surBien: (numero) => ouvrirFiche({ n_dpe: numero, retour: "carte" }),
  });

  // Leaflet mesure son conteneur à la création : l'écran étant masqué à ce
  // moment-là, il calcule une taille nulle. Il faut le prévenir.
  auChangement("carte", async () => {
    carte.redimensionner();
    await cadrerSurLaCommune();
    rafraichir();
  });

  surCommunePrete(async () => {
    chargerContexte();
    if ($("#vue-carte").hidden) return;
    await cadrerSurLaCommune();
    rafraichir();
    chargerListe();
  });
  auTermeDeLImport(() => {
    chargerContexte();
    if ($("#vue-carte").hidden) return;
    rafraichir();
    chargerListe();
  });

  $("#carte-adresse").addEventListener("input", () => {
    clearTimeout(minuterieRecherche);
    minuterieRecherche = setTimeout(suggerer, 220);
  });

  $("#filtres").addEventListener("change", () => chargerListe());
  $("#filtres").addEventListener("submit", (e) => e.preventDefault());

  $("#marquer-vus").addEventListener("click", async () => {
    try {
      const { marques } = await api.marquerVus(null);
      afficherSucces(marques ? `${marques} logement(s) marqué(s) comme vus.`
                             : "Rien à marquer.");
      chargerListe();
    } catch (erreur) {
      afficherErreur(erreur.message);
    }
  });

  // Filtres repliables, fermés d'emblée sur téléphone : la première chose
  // visible doit être la carte.
  const surTelephone = window.matchMedia("(max-width: 700px)");
  const replierFiltres = (replie) => {
    $("#filtres").dataset.replie = replie ? "oui" : "non";
    $("#bascule-filtres").setAttribute("aria-expanded", String(!replie));
  };
  replierFiltres(surTelephone.matches);
  surTelephone.addEventListener("change", (e) => replierFiltres(e.matches));
  $("#bascule-filtres").addEventListener("click", () => {
    replierFiltres($("#filtres").dataset.replie === "non");
  });

  $("#bascule-carte").addEventListener("click", () => {
    const panneau = $(".panneau-carte");
    const replie = panneau.dataset.replie === "oui";
    panneau.dataset.replie = replie ? "non" : "oui";
    $("#bascule-carte").setAttribute("aria-expanded", String(replie));
    if (replie) carte.redimensionner();
  });

  // Sur grand écran la carte reste visible quand la liste s'ouvre ; sur
  // téléphone elle se replie pour que la liste passe en premier.
  if (window.matchMedia("(min-width: 940px)").matches) {
    $(".panneau-carte").dataset.replie = "non";
  }

  // Les critères par défaut viennent des réglages — donc du courriel
  // d'alerte. On les demande une fois, sans rien afficher : la fenêtre
  // reste vide, et la carte s'ouvre seule.
  try {
    appliquerFiltres((await api.veille({})).filtres);
  } catch (_) { /* les critères restent ceux de la page */ }
}
