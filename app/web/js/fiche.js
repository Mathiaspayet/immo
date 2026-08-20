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
import {
  $, afficherErreur, dateFr, echapper, entierFr, etiquetteHtml, liensExternes,
  masquerErreur, nombreFr,
} from "./format.js";
import { changerVue } from "./navigation.js";

let dernierRetour = "veille";

/**
 * Projette un contour géographique dans le repère du dessin.
 *
 * Les degrés ne sont pas isotropes : un degré de longitude vaut un degré de
 * latitude multiplié par le cosinus de la latitude. Sans cette correction,
 * une parcelle carrée serait dessinée en rectangle.
 */
function projeter(anneaux, largeur, hauteur, marge) {
  const tous = anneaux.flat();
  if (!tous.length) return null;

  const latMoyenne = tous.reduce((somme, p) => somme + p[1], 0) / tous.length;
  const metresParLon = 110540 * Math.cos((latMoyenne * Math.PI) / 180);
  const enMetres = anneaux.map((anneau) =>
    anneau.map(([lon, lat]) => [lon * metresParLon, lat * 110540]));

  const plats = enMetres.flat();
  const xMin = Math.min(...plats.map((p) => p[0]));
  const xMax = Math.max(...plats.map((p) => p[0]));
  const yMin = Math.min(...plats.map((p) => p[1]));
  const yMax = Math.max(...plats.map((p) => p[1]));

  const echelle = Math.min((largeur - 2 * marge) / Math.max(xMax - xMin, 1),
                           (hauteur - 2 * marge) / Math.max(yMax - yMin, 1));
  const decalageX = (largeur - (xMax - xMin) * echelle) / 2;
  const decalageY = (hauteur - (yMax - yMin) * echelle) / 2;

  return {
    echelle,
    metresParLon,
    // L'axe des ordonnées du SVG descend : on retourne la latitude.
    versDessin: ([lon, lat]) => [
      (lon * metresParLon - xMin) * echelle + decalageX,
      hauteur - ((lat * 110540 - yMin) * echelle + decalageY),
    ],
    anneaux,
  };
}

/** Barre d'échelle : un plan sans échelle ne se lit pas. */
function barreEchelle(echelle, hauteur) {
  const candidats = [5, 10, 20, 25, 50, 100, 200];
  const metres = candidats.find((m) => m * echelle > 45) ?? 200;
  const largeur = metres * echelle;
  const y = hauteur - 14;
  return `
    <g stroke="var(--encre)" stroke-width="1" fill="var(--encre)">
      <path d="M14 ${y} h${largeur}" />
      <path d="M14 ${y - 3} v6 M${14 + largeur} ${y - 3} v6" />
      <text x="${14 + largeur + 6}" y="${y + 3}" font-size="8" stroke="none"
            font-family="var(--donnees)">${metres} m</text>
    </g>`;
}

/**
 * L'extrait : le polygone de la parcelle tracé à l'encre sur une trame
 * fine, la référence en chasse fixe dans l'angle, l'échelle en bas.
 *
 * C'est le seul endroit où l'on dépense de l'audace (CDC §7). Sans
 * parcelle — cadastre pas encore chargé, ou logement hors parcelle — on
 * retombe sur le repère de position, et on le dit.
 */
function extraitCadastral(bien, parcelle) {
  const aPosition = bien.latitude != null && bien.longitude != null;
  const reference = echapper(parcelle?.id || bien.n_dpe || "");
  const L = 400;
  const H = 220;

  const anneaux = parcelle?.geometrie
    ? (parcelle.geometrie.type === "MultiPolygon"
        ? parcelle.geometrie.coordinates.map((p) => p[0])
        : [parcelle.geometrie.coordinates[0]])
    : null;
  const projection = anneaux ? projeter(anneaux, L, H, 26) : null;

  let dessin;
  if (projection) {
    const chemins = projection.anneaux.map((anneau) => {
      const points = anneau.map((point) => projection.versDessin(point));
      return "M" + points.map(([x, y]) => `${x.toFixed(1)} ${y.toFixed(1)}`).join(" L") + " Z";
    }).join(" ");

    const point = aPosition ? projection.versDessin([bien.longitude, bien.latitude]) : null;
    dessin = `
      <path d="${chemins}" fill="var(--pin)" fill-opacity="0.10"
            stroke="var(--encre)" stroke-width="1.4" stroke-linejoin="round"/>
      ${point ? `
        <g transform="translate(${point[0].toFixed(1)} ${point[1].toFixed(1)})">
          <path d="M-9 0 H9 M0 -9 V9" stroke="var(--alerte)" stroke-width="1.1"/>
          <circle r="3" fill="var(--alerte)"/>
        </g>` : ""}
      ${barreEchelle(projection.echelle, H)}`;
  } else if (aPosition) {
    dessin = `
      <g transform="translate(200 110)">
        <circle r="46" fill="none" stroke="var(--pin)" stroke-width="1" stroke-dasharray="3 4"/>
        <path d="M-14 0 H14 M0 -14 V14" stroke="var(--encre)" stroke-width="1.2"/>
        <circle r="4.5" fill="var(--encre)"/>
      </g>
      <text x="200" y="196" text-anchor="middle" font-size="8"
            fill="var(--trait-fort)" font-family="var(--donnees)">
        parcelle non chargée
      </text>`;
  } else {
    dessin = `<text x="200" y="115" text-anchor="middle" font-size="11"
                    fill="var(--trait-fort)" font-family="var(--donnees)">
                position inconnue
              </text>`;
  }

  return `
  <figure class="extrait">
    <svg viewBox="0 0 ${L} ${H}" role="img"
         aria-label="${parcelle ? "Extrait cadastral de la parcelle" : "Extrait de repérage"}">
      <defs>
        <pattern id="trame" width="10" height="10" patternUnits="userSpaceOnUse">
          <path d="M10 0 L0 0 0 10" fill="none" stroke="var(--trait)" stroke-width="0.5"/>
        </pattern>
        <pattern id="trame-large" width="50" height="50" patternUnits="userSpaceOnUse">
          <path d="M50 0 L0 0 0 50" fill="none" stroke="var(--trait-fort)" stroke-width="0.6"/>
        </pattern>
      </defs>
      <rect width="${L}" height="${H}" fill="var(--papier-carte)"/>
      <rect width="${L}" height="${H}" fill="url(#trame)"/>
      <rect width="${L}" height="${H}" fill="url(#trame-large)"/>

      ${dessin}

      <!-- Rose des vents, comme sur un plan -->
      <g transform="translate(376 26)" stroke="var(--encre)" fill="var(--encre)">
        <path d="M0 -12 L3.5 3.5 L0 1 L-3.5 3.5 Z" stroke-width="0.8"/>
        <text x="0" y="16" text-anchor="middle" font-size="8"
              font-family="var(--donnees)" stroke="none">N</text>
      </g>

      <rect x="0.5" y="0.5" width="${L - 1}" height="${H - 1}" fill="none"
            stroke="var(--encre)" stroke-width="1"/>
    </svg>
    <figcaption>
      <span class="donnee">${reference}</span>
      ${parcelle
        ? `<span class="donnee coordonnees">terrain ${entierFr.format(
             Math.round(parcelle.contenance_m2 ?? 0))} m² ·
             bâti ${entierFr.format(Math.round(parcelle.emprise_batie_m2 ?? 0))} m²</span>`
        : (aPosition
            ? `<span class="donnee coordonnees">${nombreFr.format(bien.latitude)} N
                 ${nombreFr.format(bien.longitude)} E</span>`
            : "")}
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

  // La parcelle vient du cadastre (lot 3) : absente tant qu'il n'est pas
  // chargé, ce que l'extrait dit alors franchement.
  let parcelle = null;
  try {
    parcelle = (await api.parcelleDuDpe(principal.n_dpe)).parcelle;
  } catch (_) { /* l'extrait retombe sur le repère de position */ }

  $("#fiche-contenu").innerHTML = `
    <div class="fiche-entete">
      ${extraitCadastral(principal, parcelle)}
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

  $("#fiche-retour").addEventListener("click", () => changerVue(dernierRetour));
  $("#fiche-contenu").querySelectorAll("[data-chaine]").forEach((bouton) => {
    bouton.addEventListener("click", () => remonterChaine(bouton.dataset.chaine));
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
