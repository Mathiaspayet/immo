// ====================================================================
//  fiche.js — F4 : la fiche d'un bien, sa chronologie, ses remplacements.
//
//  C'est le seul écran où l'on dépense de l'audace (CDC §7) : l'en-tête
//  reprend la forme d'un extrait cadastral — trame fine à l'encre,
//  référence en chasse fixe dans l'angle, mesures alignées en colonne.
//  Le polygone de la parcelle viendra du cadastre, au lot 3 ; en attendant
//  l'extrait porte le repère de position et le dit franchement.
// ====================================================================

import { api } from "./api.js";
import { creerVueSatellite } from "./carte.js";
import {
  $, afficherErreur, afficherTravail, dateFr, echapper, entierFr, etiquetteHtml,
  liensExternes, masquerErreur, masquerTravail, nombreFr,
} from "./format.js";
import { auProchainTerme, suivreImport } from "./import.js";
import { changerVue } from "./navigation.js";

let dernierRetour = "veille";

const LARGEUR = 420;
const HAUTEUR = 240;

/**
 * Ajuste le cadre géographique au format du dessin.
 *
 * Le serveur renvoie la boîte de la parcelle plus une marge ; son format
 * n'a aucune raison de correspondre à celui de l'image. On l'élargit donc
 * sur l'axe qui manque, et ce cadre-là sert AUX DEUX vues — c'est ce qui
 * leur donne exactement le même cadrage.
 *
 * Les degrés ne sont pas isotropes : un degré de longitude vaut un degré
 * de latitude multiplié par le cosinus de la latitude. Sans cette
 * correction, une parcelle carrée serait dessinée en rectangle.
 */
function cadrer(cadre) {
  const latCentre = (cadre.lat_min + cadre.lat_max) / 2;
  const lonCentre = (cadre.lon_min + cadre.lon_max) / 2;
  const metresParLon = 110540 * Math.cos((latCentre * Math.PI) / 180);

  let largeurM = (cadre.lon_max - cadre.lon_min) * metresParLon;
  let hauteurM = (cadre.lat_max - cadre.lat_min) * 110540;
  const format = LARGEUR / HAUTEUR;

  if (largeurM / hauteurM < format) largeurM = hauteurM * format;
  else hauteurM = largeurM / format;

  const demiLon = largeurM / 2 / metresParLon;
  const demiLat = hauteurM / 2 / 110540;

  return {
    lon_min: lonCentre - demiLon, lon_max: lonCentre + demiLon,
    lat_min: latCentre - demiLat, lat_max: latCentre + demiLat,
    // Échelle du dessin, en pixels par mètre.
    pixelsParMetre: LARGEUR / largeurM,
    versDessin: ([lon, lat]) => [
      ((lon - (lonCentre - demiLon)) / (2 * demiLon)) * LARGEUR,
      // L'axe des ordonnées du SVG descend : on retourne la latitude.
      HAUTEUR - ((lat - (latCentre - demiLat)) / (2 * demiLat)) * HAUTEUR,
    ],
  };
}

/** Contours d'une géométrie GeoJSON, en chemin SVG. */
function chemin(geometrie, cadre) {
  if (!geometrie) return "";
  const anneaux = geometrie.type === "MultiPolygon"
    ? geometrie.coordinates.map((polygone) => polygone[0])
    : [geometrie.coordinates[0]];

  return anneaux.map((anneau) => {
    const points = anneau.map((point) => cadre.versDessin(point));
    return "M" + points.map(([x, y]) => `${x.toFixed(1)} ${y.toFixed(1)}`).join(" L") + " Z";
  }).join(" ");
}

/** Barre d'échelle : un plan sans échelle ne se lit pas. */
function barreEchelle(pixelsParMetre) {
  const candidats = [5, 10, 20, 25, 50, 100, 200];
  const metres = candidats.find((m) => m * pixelsParMetre > 55) ?? 200;
  const largeur = metres * pixelsParMetre;
  const y = HAUTEUR - 14;
  return `
    <g stroke="var(--encre)" stroke-width="1" fill="var(--encre)">
      <path d="M14 ${y} h${largeur}" />
      <path d="M14 ${y - 3} v6 M${14 + largeur} ${y - 3} v6" />
      <text x="${14 + largeur + 6}" y="${y + 3}" font-size="8" stroke="none"
            font-family="var(--donnees)">${metres} m</text>
    </g>`;
}

/**
 * L'extrait : la parcelle à l'encre au milieu de ses voisines, le bâti
 * dessiné dessus, l'échelle en bas et la référence dans l'angle.
 *
 * C'est le seul endroit où l'on dépense de l'audace (CDC §7). Le bâti dur
 * est plein, le bâti léger — abris, garages — hachuré : à Launaguet, sa
 * surface médiane est de 10 m² contre 129 pour le dur, les confondre
 * ferait lire un abri de jardin comme une maison.
 */
function extraitCadastral(bien, extrait) {
  const aPosition = bien.latitude != null && bien.longitude != null;
  const parcelle = extrait?.parcelle;
  const reference = echapper(parcelle?.id || bien.n_dpe || "");

  if (!extrait) {
    return `
    <figure class="extrait">
      <svg viewBox="0 0 ${LARGEUR} ${HAUTEUR}" role="img" aria-label="Extrait de repérage">
        ${FOND_TRAME}
        ${aPosition ? `
          <g transform="translate(${LARGEUR / 2} ${HAUTEUR / 2})">
            <circle r="46" fill="none" stroke="var(--pin)" stroke-width="1" stroke-dasharray="3 4"/>
            <path d="M-14 0 H14 M0 -14 V14" stroke="var(--encre)" stroke-width="1.2"/>
            <circle r="4.5" fill="var(--encre)"/>
          </g>` : `
          <text x="${LARGEUR / 2}" y="${HAUTEUR / 2}" text-anchor="middle" font-size="11"
                fill="var(--trait-fort)" font-family="var(--donnees)">position inconnue</text>`}
        ${ROSE_DES_VENTS}
        ${CADRE_SVG}
      </svg>
      <figcaption><span class="donnee">${reference}</span></figcaption>
    </figure>`;
  }

  const cadre = cadrer(extrait.cadre);
  const voisines = extrait.voisines
    .map((v) => `<path d="${chemin(v.geometrie, cadre)}" fill="none"
                       stroke="var(--trait-fort)" stroke-width="0.8"/>`).join("");

  const bati = extrait.batiments.map((batiment) => {
    const leger = String(batiment.type) === "02";
    const sien = batiment.sur_la_parcelle;
    return `<path d="${chemin(batiment.geometrie, cadre)}"
                  fill="${leger ? "url(#hachures)" : (sien ? "var(--encre)" : "var(--trait-fort)")}"
                  fill-opacity="${sien ? 0.9 : 0.45}"
                  stroke="var(--encre)" stroke-width="${sien ? 0.7 : 0.4}"/>`;
  }).join("");

  const point = aPosition ? cadre.versDessin([bien.longitude, bien.latitude]) : null;

  return `
  <figure class="extrait">
    <svg viewBox="0 0 ${LARGEUR} ${HAUTEUR}" role="img"
         aria-label="Extrait cadastral : la parcelle, ses voisines et le bâti">
      ${FOND_TRAME}
      <g>${voisines}</g>
      <path d="${chemin(parcelle.geometrie, cadre)}" fill="var(--pin)" fill-opacity="0.12"
            stroke="var(--encre)" stroke-width="1.6" stroke-linejoin="round"/>
      <g>${bati}</g>
      ${point ? `
        <g transform="translate(${point[0].toFixed(1)} ${point[1].toFixed(1)})">
          <path d="M-9 0 H9 M0 -9 V9" stroke="var(--alerte)" stroke-width="1.2"/>
          <circle r="3" fill="var(--alerte)"/>
        </g>` : ""}
      ${barreEchelle(cadre.pixelsParMetre)}
      ${ROSE_DES_VENTS}
      ${CADRE_SVG}
    </svg>
    <figcaption>
      <span class="donnee">${reference}</span>
      <span class="donnee coordonnees">terrain ${entierFr.format(
        Math.round(parcelle.contenance_m2 ?? 0))} m² ·
        bâti ${entierFr.format(Math.round(parcelle.emprise_batie_m2 ?? 0))} m²</span>
    </figcaption>
  </figure>`;
}

const FOND_TRAME = `
  <defs>
    <pattern id="trame" width="10" height="10" patternUnits="userSpaceOnUse">
      <path d="M10 0 L0 0 0 10" fill="none" stroke="var(--trait)" stroke-width="0.5"/>
    </pattern>
    <pattern id="trame-large" width="50" height="50" patternUnits="userSpaceOnUse">
      <path d="M50 0 L0 0 0 50" fill="none" stroke="var(--trait-fort)" stroke-width="0.6"/>
    </pattern>
    <pattern id="hachures" width="4" height="4" patternUnits="userSpaceOnUse"
             patternTransform="rotate(45)">
      <path d="M0 0 v4" stroke="var(--encre)" stroke-width="1.1" opacity="0.55"/>
    </pattern>
  </defs>
  <rect width="${LARGEUR}" height="${HAUTEUR}" fill="var(--papier-carte)"/>
  <rect width="${LARGEUR}" height="${HAUTEUR}" fill="url(#trame)"/>
  <rect width="${LARGEUR}" height="${HAUTEUR}" fill="url(#trame-large)"/>`;

const ROSE_DES_VENTS = `
  <g transform="translate(${LARGEUR - 24} 26)" stroke="var(--encre)" fill="var(--encre)">
    <path d="M0 -12 L3.5 3.5 L0 1 L-3.5 3.5 Z" stroke-width="0.8"/>
    <text x="0" y="16" text-anchor="middle" font-size="8"
          font-family="var(--donnees)" stroke="none">N</text>
  </g>`;

const CADRE_SVG = `
  <rect x="0.5" y="0.5" width="${LARGEUR - 1}" height="${HAUTEUR - 1}" fill="none"
        stroke="var(--encre)" stroke-width="1"/>`;

/**
 * Le même cadre que le dessin, sous forme de bornes géographiques.
 * Les deux vues doivent montrer exactement le même rectangle — c'est
 * l'intérêt de les mettre côte à côte.
 */
function cadrerPourSatellite(cadre) {
  const { lon_min, lon_max, lat_min, lat_max } = cadrer(cadre);
  return { lon_min, lon_max, lat_min, lat_max };
}

/** La photo aérienne, cadrée exactement comme le dessin. */
function panneauSatellite(extrait) {
  if (!extrait) return "";
  return `
  <figure class="extrait extrait-satellite">
    <div id="satellite-fiche" class="vue-satellite"></div>
    <figcaption>
      <span>Vue aérienne, même cadrage</span>
      <span class="donnee coordonnees">IGN</span>
    </figcaption>
  </figure>`;
}

function ligneChronologie(diagnostic, dernierImport) {
  const retire = !diagnostic.encore_publie;
  return `
  <li class="jalon ${retire ? "jalon-retire" : ""}">
    <div class="jalon-date donnee">${dateFr(diagnostic.date_etablissement)}</div>
    <div class="jalon-corps">
      <div class="jalon-tete">
        ${etiquetteHtml(diagnostic.etiquette_dpe)}
        <span class="donnee">${echapper(diagnostic.n_dpe)}</span>
        <span class="pastille">${echapper(diagnostic.jeu_libelle || diagnostic.jeu_de_donnees)}</span>
        ${retire ? '<span class="pastille pastille-retire">retiré de la base active</span>' : ""}
      </div>
      <dl class="mesures">
        ${diagnostic.surface_habitable != null
          ? `<div><dt>surface</dt><dd>${nombreFr.format(diagnostic.surface_habitable)} m²</dd></div>` : ""}
        ${diagnostic.conso_ep_m2 != null
          ? `<div><dt>énergie ép.</dt><dd>${entierFr.format(diagnostic.conso_ep_m2)} kWh/m²</dd></div>` : ""}
        ${diagnostic.ges_m2 != null
          ? `<div><dt>GES</dt><dd>${nombreFr.format(diagnostic.ges_m2)} kg/m²</dd></div>` : ""}
        ${diagnostic.annee_construction != null
          ? `<div><dt>construit</dt><dd>${diagnostic.annee_construction}</dd></div>` : ""}
      </dl>
      ${diagnostic.n_dpe_remplace ? `
        <p class="remplacement">
          remplace <span class="donnee">${echapper(diagnostic.n_dpe_remplace)}</span>
          <button type="button" class="bouton-lien"
                  data-chaine="${echapper(diagnostic.n_dpe)}">Remonter la chaîne</button>
        </p>` : ""}
    </div>
  </li>`;
}

/** Ce que la chronologie apprend — écrit une fois, pas à chaque bien. */
const LECTURE = `
  <h2>Lecture</h2>
  <ul class="explication liste-lecture">
    <li>Plusieurs DPE espacés de quelques années : le bien a déjà été proposé
        à la vente ou à la location.</li>
    <li>Deux DPE très rapprochés : correction du diagnostic.</li>
    <li>Une classe qui s'améliore : des travaux ont eu lieu entre les deux.</li>
    <li>Un DPE est valable dix ans ; ceux établis avant juillet 2021 ont
        toutefois été invalidés par la réforme.</li>
  </ul>`;

export async function ouvrirFiche({ n_dpe = null, adresse = null, retour = null } = {}) {
  masquerErreur();
  dernierRetour = retour || "veille";
  changerVue("fiche");
  $("#fiche-contenu").innerHTML = '<p class="message message-travail">Chargement de la fiche…</p>';

  let reponse;
  try {
    reponse = await api.fiche({ n_dpe, adresse });
  } catch (erreur) {
    $("#fiche-contenu").innerHTML = "";
    afficherErreur("Impossible d'ouvrir la fiche.", erreur.message);
    return;
  }

  if (!reponse.diagnostics.length) {
    const suggestions = (reponse.suggestions || []).map((voie) =>
      `<li><button type="button" class="bouton-lien" data-adresse="${echapper(voie)}">${echapper(voie)}</button></li>`
    ).join("");
    $("#fiche-contenu").innerHTML = `
      <div class="vide">
        <h3>Aucun diagnostic pour cette adresse</h3>
        <p>${echapper(reponse.message || "")}</p>
        ${suggestions ? `<p>Adresses proches dans le cache :</p><ul class="suggestions">${suggestions}</ul>` : ""}
      </div>`;
    $("#fiche-contenu").querySelectorAll("[data-adresse]").forEach((bouton) => {
      bouton.addEventListener("click", () => ouvrirFiche({ adresse: bouton.dataset.adresse }));
    });
    return;
  }

  // Le plus récent porte les caractéristiques affichées en tête.
  const diagnostics = reponse.diagnostics;
  const principal = diagnostics[diagnostics.length - 1];

  // L'extrait vient du cadastre : parcelle, voisines et bâti. Absent tant
  // que le cadastre n'est pas chargé, ce que le dessin dit alors
  // franchement, en proposant de le charger.
  let extrait = null;
  try {
    extrait = (await api.extraitCadastral(principal.n_dpe)).extrait;
  } catch (_) { /* on retombe sur le repère de position */ }
  const parcelle = extrait?.parcelle ?? null;

  $("#fiche-contenu").innerHTML = `
    <div class="fiche-entete">
      ${extraitCadastral(principal, extrait)}
      ${panneauSatellite(extrait)}
      <div class="fiche-identite">
        <h1>${echapper(reponse.adresse || "Adresse inconnue")}</h1>
        <p class="explication">
          ${echapper(principal.commune || "")} ${echapper(principal.code_postal || "")}
          ${principal.zone ? `· secteur ${echapper(principal.zone)}` : ""}
        </p>
        <dl class="mesures mesures-colonne">
          <div><dt>surface</dt><dd>${principal.surface_habitable != null
            ? nombreFr.format(principal.surface_habitable) + " m²" : "—"}</dd></div>
          <div><dt>classe énergie</dt><dd>${etiquetteHtml(principal.etiquette_dpe)}</dd></div>
          <div><dt>classe GES</dt><dd>${etiquetteHtml(principal.etiquette_ges)}</dd></div>
          <div><dt>énergie primaire</dt><dd>${principal.conso_ep_m2 != null
            ? entierFr.format(principal.conso_ep_m2) + " kWh/m²" : "—"}</dd></div>
          <div><dt>coût annuel</dt><dd>${principal.cout_annuel != null
            ? entierFr.format(principal.cout_annuel) + " €" : "—"}</dd></div>
          <div><dt>construit</dt><dd>${principal.annee_construction ?? "—"}</dd></div>
        </dl>
        <div class="liens">${liensExternes(principal)}</div>
      </div>
    </div>

    ${reponse.plusieurs_logements ? `
      <p class="message message-travail">
        ${entierFr.format(reponse.en_vigueur)} diagnostics sont en vigueur en même
        temps à cette adresse : elle couvre donc plusieurs logements — immeuble,
        ou voie sans numéro. La chronologie ci-dessous les mélange.
      </p>` : ""}

    <h2>Chronologie — ${entierFr.format(diagnostics.length)} diagnostic(s)</h2>
    <ol class="chronologie">
      ${diagnostics.map((d) => ligneChronologie(d, reponse.dernier_import)).join("")}
    </ol>

    <div id="chaine-remplacements"></div>
    ${LECTURE}
    <p><button type="button" class="bouton" id="fiche-retour">Retour</button></p>`;

  // La photo aérienne attend que la mise en page soit posée : Leaflet
  // mesure son conteneur à la création, et `aspect-ratio` ne lui donne sa
  // hauteur qu'après le premier calcul de style.
  if (extrait) {
    requestAnimationFrame(() => {
      if (!document.getElementById("satellite-fiche")) return;
      const satellite = creerVueSatellite("satellite-fiche",
                                          cadrerPourSatellite(extrait.cadre));
      satellite.tracer(parcelle.geometrie, { couleur: "#FFFFFF", epaisseur: 2.5 });
    });
  }

  $("#fiche-retour").addEventListener("click", () => changerVue(dernierRetour));

  const chargeur = $("#fiche-contenu").querySelector("[data-charger-cadastre]");
  if (chargeur) {
    chargeur.addEventListener("click", () => chargerLeCadastre(chargeur, principal));
  }
  $("#fiche-contenu").querySelectorAll("[data-chaine]").forEach((bouton) => {
    bouton.addEventListener("click", () => remonterChaine(bouton.dataset.chaine));
  });
}

/**
 * Charge le cadastre de la commune du bien, puis redessine la fiche.
 *
 * Sans cela, arriver ici depuis « Les DPE récents » menait à une impasse :
 * l'extrait annonçait une parcelle absente sans offrir de moyen de
 * l'obtenir, et il fallait deviner qu'il fallait ressortir par l'accueil.
 */
async function chargerLeCadastre(bouton, bien) {
  const commune = bouton.dataset.commune || "cette commune";
  bouton.disabled = true;
  bouton.textContent = "Téléchargement…";
  masquerErreur();

  let etat;
  try {
    etat = await api.preparerCommune(bouton.dataset.insee, "cadastre");
  } catch (erreur) {
    bouton.disabled = false;
    bouton.textContent = "Le charger maintenant";
    afficherErreur(`Le cadastre de ${commune} n'a pas pu être demandé.`, erreur.message);
    return;
  }

  if (!etat.lance) {
    // Déjà là, ou une moisson occupe la place : on retente l'affichage.
    ouvrirFiche({ n_dpe: bien.n_dpe, retour: dernierRetour });
    return;
  }

  afficherTravail(`Téléchargement du cadastre de ${commune}…`);
  suivreImport();
  auProchainTerme(() => {
    masquerTravail();
    ouvrirFiche({ n_dpe: bien.n_dpe, retour: dernierRetour });
  });
}

// --------------------------------------------------------------------
//  Chaîne des remplacements et comparaison
// --------------------------------------------------------------------

async function remonterChaine(n_dpe) {
  const boite = $("#chaine-remplacements");
  boite.innerHTML = '<p class="message message-travail">Interrogation de l\'ADEME…<span class="jauge"><span></span></span></p>';

  let reponse;
  try {
    reponse = await api.chaine(n_dpe);
  } catch (erreur) {
    boite.innerHTML = "";
    afficherErreur("La chaîne n'a pas pu être remontée.", erreur.message);
    return;
  }

  const maillons = reponse.maillons.map((maillon, index) => {
    if (maillon.absent) {
      return `
        <li class="maillon maillon-absent">
          <span class="donnee">${echapper(maillon.n_dpe)}</span>
          <p class="explication">${echapper(maillon.explication)}</p>
        </li>`;
    }
    return `
      <li class="maillon">
        <span class="donnee">${echapper(maillon.n_dpe)}</span>
        <span class="pastille">${echapper(maillon.origine)}</span>
        <p class="explication">
          ${dateFr(maillon.date_etablissement)} ·
          ${maillon.surface_habitable != null ? nombreFr.format(maillon.surface_habitable) + " m² · " : ""}
          classe ${echapper(maillon.etiquette_dpe || "?")}
        </p>
        ${index > 0 ? `
          <button type="button" class="bouton-lien"
                  data-comparer="${echapper(reponse.maillons[index - 1].n_dpe)}"
                  data-avec="${echapper(maillon.n_dpe)}">
            Comparer avec le suivant
          </button>` : ""}
      </li>`;
  }).join("");

  boite.innerHTML = `
    <h2>Chaîne des remplacements</h2>
    <p class="explication">
      Un DPE remplacé est retiré de la base active de l'ADEME : ses valeurs ne
      sont plus accessibles, sauf si un import antérieur au remplacement en a
      gardé la trace.
    </p>
    <ol class="chaine">${maillons}</ol>
    <div id="comparaison"></div>`;

  boite.querySelectorAll("[data-comparer]").forEach((bouton) => {
    bouton.addEventListener("click", () =>
      comparer(bouton.dataset.comparer, bouton.dataset.avec));
  });
}

async function comparer(recent, ancien) {
  const boite = $("#comparaison");
  boite.innerHTML = '<p class="message message-travail">Comparaison…<span class="jauge"><span></span></span></p>';

  let reponse;
  try {
    reponse = await api.comparer(recent, ancien);
  } catch (erreur) {
    boite.innerHTML = "";
    afficherErreur("La comparaison a échoué.", erreur.message);
    return;
  }

  if (!reponse.comparables) {
    boite.innerHTML = `<p class="message message-erreur">${echapper(reponse.message)}</p>`;
    return;
  }

  if (reponse.identiques) {
    boite.innerHTML = '<p class="message message-succes">Les deux enregistrements sont identiques.</p>';
    return;
  }

  const lignes = reponse.differences.map((difference) => `
    <tr>
      <td class="donnee">${echapper(difference.champ)}</td>
      <td class="donnee avant">${echapper(difference.avant ?? "—")}</td>
      <td class="donnee apres">${echapper(difference.apres ?? "—")}</td>
    </tr>`).join("");

  boite.innerHTML = `
    <h3>Ce qui a changé</h3>
    <p class="explication">
      <span class="donnee">${echapper(ancien)}</span> (${echapper(reponse.ancien.source)})
      → <span class="donnee">${echapper(recent)}</span> (${echapper(reponse.recent.source)}) ·
      ${entierFr.format(reponse.differences.length)} champ(s) modifié(s)
      ${reponse.techniques.length
        ? `, plus ${entierFr.format(reponse.techniques.length)} champ(s) techniques masqués`
        : ""}
    </p>
    <div class="cadre-defilant"><table class="comparaison">
      <tr><th>Champ</th><th>Avant</th><th>Après</th></tr>
      ${lignes}
    </table></div>`;
}
