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
  euroFr, liensExternes, masquerErreur, masquerTravail, nombreFr,
} from "./format.js";
import { ouvrirEstimation } from "./estimation.js";
import { auProchainTerme, suivreImport } from "./import.js";
import { auRetourArriere, changerVue } from "./navigation.js";

let dernierRetour = "carte";

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
        bâti ${entierFr.format(Math.round(parcelle.emprise_batie_m2 ?? 0))} m² ·
        ${entierFr.format(parcelle.nb_batiments ?? 0)} bât.</span>
    </figcaption>
    ${parcelle.approchee ? `
      <p class="extrait-approche">
        <span class="pastille pastille-lot">position approchée</span>
        Le diagnostic est géocodé hors de toute parcelle, sur la voie, à
        ${nombreFr.format(parcelle.distance_dpe_m ?? 0)}&nbsp;m de celle-ci&nbsp;— la plus
        proche, sans autre à moins de 3&nbsp;m de plus.
      </p>` : ""}
  </figure>`;
}

/**
 * L'invite à charger — ou à compléter — le cadastre.
 *
 * Deux manques distincts mènent ici, et arriver depuis « Les DPE récents »
 * les rendait tous deux sans issue :
 *
 *   - aucun cadastre : l'extrait ne peut tracer aucun contour ;
 *   - un cadastre importé avant qu'on ne conserve les contours de bâtiments :
 *     les parcelles se dessinent, le bâti manque, et rien ne le disait.
 *
 * Le second est le plus trompeur : le dessin paraît complet. On l'annonce
 * donc explicitement, et le bouton relance l'import dans les deux cas.
 */
function inviteCadastre(bien, extrait, cadastreCharge = false) {
  if (!bien.code_insee) return "";
  // Le cadastre est là, mais aucune parcelle ne porte ce diagnostic : le
  // recharger n'y changerait rien. Le message disait « pas encore chargé »
  // à tort.
  if (!extrait && cadastreCharge) {
    return `
      <p class="extrait-manquant">
        Ce diagnostic n'est rattaché à aucune parcelle&nbsp;: l'ADEME l'a géocodé
        à l'écart de tout contour — au milieu de la voie quand l'adresse n'a pas
        de numéro, ou à égale distance de deux parcelles. Ses ventes ne peuvent
        donc pas lui être rattachées sans risquer celles du voisin.
      </p>`;
  }
  const commune = echapper(bien.commune || "cette commune");
  const attributs = `data-charger-cadastre data-insee="${echapper(bien.code_insee)}"
                     data-commune="${echapper(bien.commune || "")}"`;

  if (!extrait) {
    return `
      <p class="extrait-manquant">
        Le cadastre de ${commune} n'est pas encore chargé, le contour de la
        parcelle ne peut donc pas être tracé.
        <button type="button" class="bouton-lien" ${attributs}>
          Le charger maintenant
        </button>
      </p>`;
  }

  if (extrait.batiments_manquants) {
    return `
      <p class="extrait-manquant">
        Le cadastre de ${commune} a été chargé avant que l'application ne
        conserve les contours de bâtiments : les parcelles se dessinent, le
        bâti non. Un nouvel import le complète.
        <button type="button" class="bouton-lien" ${attributs}>
          Compléter maintenant
        </button>
      </p>`;
  }
  return "";
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

/**
 * L'historique des ventes du bien, tire de DVF.
 *
 * Le prix au mètre carré n'est affiché que lorsqu'il veut dire quelque
 * chose : une vente d'un seul local sur une seule parcelle. Rapporter le
 * prix d'un immeuble entier à la surface d'un appartement donnerait un
 * chiffre faux, et flatteur — c'est le cas de plus d'une mutation sur
 * deux, qui portent sur plusieurs lots.
 */
function blocVentes(ventes) {
  if (!ventes || ventes.length === 0) return "";

  const lignes = ventes.map((v) => {
    const prix = v.valeur_fonciere != null
      ? euroFr.format(v.valeur_fonciere) : "prix non publié";
    const detail = [];
    if (v.nb_parcelles > 1) detail.push(`${entierFr.format(v.nb_parcelles)} parcelles`);
    if (v.types_locaux && v.types_locaux.length) {
      detail.push(v.types_locaux.join(", ").toLowerCase());
    }
    if (v.surface_bati_m2) detail.push(`${entierFr.format(v.surface_bati_m2)} m² bâtis`);
    if (v.surface_terrain_m2) {
      detail.push(`${entierFr.format(v.surface_terrain_m2)} m² de terrain`);
    }
    return `
      <li class="vente">
        <div class="vente-date donnee">${dateFr(v.date_mutation)}</div>
        <div class="vente-corps">
          <div class="vente-tete">
            <span class="vente-prix donnee">${echapper(prix)}</span>
            ${v.prix_m2 != null
              ? `<span class="pastille">${entierFr.format(v.prix_m2)} €/m²</span>`
              : ""}
            <span class="pastille">${echapper(v.nature || "vente")}</span>
            ${v.adresse_concordante === true
              ? '<span class="pastille pastille-concordante">même adresse que le diagnostic</span>' : ""}
            ${v.adresse_concordante === false
              ? '<span class="pastille pastille-retire">autre adresse : à vérifier</span>' : ""}
          </div>
          ${v.adresse ? `<p class="explication">${echapper(v.adresse)}</p>` : ""}
          ${detail.length
            ? `<p class="explication">${echapper(detail.join(" · "))}</p>` : ""}
          ${v.prix_m2 == null && v.surface_bati_m2 ? `
            <p class="explication">
              Prix au m² non calculé&nbsp;: la vente porte sur plusieurs biens,
              le montant les couvre tous.
            </p>` : ""}
        </div>
      </li>`;
  }).join("");

  return `
    <h2>Ventes connues — ${entierFr.format(ventes.length)}</h2>
    <p class="explication">
      Source DVF (DGFiP), rattachée par la parcelle et non par l'adresse.
      Ne couvre que les cinq derniers millésimes publiés, et jamais
      l'Alsace-Moselle ni Mayotte.
    </p>
    ${ventes.some((v) => v.parcelle_approchee) ? `
      <p class="explication">
        Le diagnostic n'est pas posé sur une parcelle mais devant, à
        ${nombreFr.format(ventes[0].distance_dpe_m ?? 0)}&nbsp;m&nbsp;: ces ventes sont celles de
        la parcelle la plus proche. L'adresse de chaque vente est comparée à
        celle du diagnostic pour écarter la vente d'un voisin.
      </p>` : ""}
    <ol class="ventes">${lignes}</ol>`;
}

/**
 * La vue de rue, quand une clé est configurée et qu'un cliché existe.
 *
 * Elle prend sa propre bande plutôt que de rejoindre la paire
 * cadastre/satellite : celle-ci tire sa valeur de son cadrage identique,
 * qu'une troisième vue romprait. Et la photo dit autre chose — ce que le
 * bien donne à voir depuis la voie.
 *
 * L'image passe par le NAS : la page n'appelle aucun tiers, et la clé
 * d'API reste sur le serveur. Un cliché absent est le cas courant, pas
 * une panne : la figure se retire alors sans bruit.
 */
function vueDeRue(bien) {
  if (bien.latitude == null || bien.longitude == null) return "";
  // Un diagnostic, ou à défaut une parcelle : le serveur retrouve la
  // position, l'adresse de la page n'en porte aucune.
  const cible = bien.n_dpe
    ? `n_dpe=${encodeURIComponent(bien.n_dpe)}`
    : `parcelle_id=${encodeURIComponent(bien.parcelle_id)}`;
  return `
  <figure class="extrait extrait-rue" id="figure-rue" hidden>
    <img id="image-rue" alt="Vue depuis la rue"
         src="/api/parcelles/vue-rue?${cible}">
    <figcaption>
      <span>Vue depuis la rue</span>
      <span class="donnee">Google</span>
    </figcaption>
  </figure>`;
}

/** Montre la figure si le cliché arrive, la retire sinon. */
function brancherVueDeRue() {
  const image = document.getElementById("image-rue");
  if (!image) return;
  image.addEventListener("load", () => {
    const figure = document.getElementById("figure-rue");
    if (figure) figure.hidden = false;
  });
  // 404 quand rien n'a été photographié là, ou quand aucune clé n'est
  // renseignée. Dans les deux cas il n'y a rien à dire à l'utilisateur.
  image.addEventListener("error", () => {
    document.getElementById("figure-rue")?.remove();
  });
}

/**
 * Où ce diagnostic est posé, quand ce n'est pas sur la parcelle de la
 * fiche. Sur une fiche sans parcelle, rien à dire : aucun ne l'est.
 */
function pastillePose(diagnostic, aUneParcelle) {
  if (!aUneParcelle) return "";
  if (diagnostic.lieu_du_diagnostic === "approchee") {
    return '<span class="pastille pastille-lot">position approchée</span>';
  }
  if (diagnostic.lieu_du_diagnostic === "ailleurs"
      || diagnostic.lieu_du_diagnostic === "sans_parcelle") {
    return '<span class="pastille pastille-lot">géocodé hors de cette parcelle</span>';
  }
  return "";
}

function ligneChronologie(diagnostic, aUneParcelle) {
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
        ${pastillePose(diagnostic, aUneParcelle)}
      </div>
      <dl class="mesures">
        ${diagnostic.surface_habitable != null
          ? `<div><dt>surface</dt><dd>${nombreFr.format(diagnostic.surface_habitable)} m²</dd></div>` : ""}
        ${diagnostic.type_batiment
          ? `<div><dt>type</dt><dd>${echapper(diagnostic.type_batiment.toLowerCase())}</dd></div>` : ""}
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

/** Ce que la chronologie apprend — écrit une fois, replié : on le sait vite. */
const LECTURE = `
  <details class="lecture">
    <summary>Lire une chronologie</summary>
    <ul class="explication liste-lecture">
      <li>Plusieurs DPE espacés de quelques années : le bien a déjà été proposé
          à la vente ou à la location.</li>
      <li>Deux DPE très rapprochés : correction du diagnostic.</li>
      <li>Une classe qui s'améliore : des travaux ont eu lieu entre les deux.</li>
      <li>Un DPE est valable dix ans ; ceux établis avant juillet 2021 ont
          toutefois été invalidés par la réforme.</li>
    </ul>
  </details>`;

// Le retour arrière ramène sur une fiche : il faut savoir laquelle.
// `sansHistorique` évite d'empiler une entrée en la rouvrant.
auRetourArriere("fiche", (etat) => {
  ouvrirFiche({ ...etat, sansHistorique: true });
});


/**
 * Revenir — le même geste que le bouton du téléphone.
 *
 * On remonte l'historique plutôt que d'y ajouter une étape : sans cela,
 * quitter une fiche empilerait une entrée de plus, et le retour arrière
 * ramènerait sur la fiche qu'on vient de fermer.
 */
function revenir() {
  if (history.state && history.state.vue === "fiche") history.back();
  else changerVue(dernierRetour);
}


/**
 * La fiche d'un lieu : on y entre par un diagnostic (les listes), une
 * parcelle (la carte) ou une adresse (l'écran Identifier).
 *
 * Il y avait deux fiches, celle d'un diagnostic et celle d'une parcelle.
 * Elles se recouvraient aux trois quarts — même extrait, mêmes ventes — et
 * renvoyaient l'une à l'autre. Il n'en reste qu'une : la parcelle et ses
 * ventes, puis chaque logement avec la chronologie de ses diagnostics. Le
 * diagnostic d'entrée désigne le logement mis en tête, dont l'identité
 * montre les mesures.
 */
export async function ouvrirFiche({ n_dpe = null, adresse = null,
                                    parcelle_id = null, retour = null,
                                    sansHistorique = false } = {}) {
  masquerErreur();
  dernierRetour = retour || "carte";
  // L'historique retient DE QUEL bien il s'agit : sans cela, un retour
  // arrière ramènerait sur une fiche vide.
  if (!sansHistorique) {
    changerVue("fiche", { n_dpe, adresse, parcelle_id, retour: dernierRetour });
  }
  $("#fiche-contenu").innerHTML = '<p class="message message-travail">Chargement de la fiche…</p>';

  let reponse;
  try {
    reponse = await api.lieu({ n_dpe, parcelle_id, adresse });
  } catch (erreur) {
    $("#fiche-contenu").innerHTML = "";
    afficherErreur("Impossible d'ouvrir la fiche.", erreur.message);
    return;
  }

  if (!reponse.trouve) {
    const suggestions = (reponse.suggestions || []).map((voie) =>
      `<li><button type="button" class="bouton-lien" data-adresse="${echapper(voie)}">${echapper(voie)}</button></li>`
    ).join("");
    $("#fiche-contenu").innerHTML = `
      <div class="fiche-barre">
        <button type="button" class="bouton bouton-retour" id="fiche-retour">
          ← Retour
        </button>
      </div>
      <div class="vide">
        <h3>Aucun diagnostic pour cette adresse</h3>
        <p>${echapper(reponse.message || "")}</p>
        ${suggestions ? `<p>Adresses proches dans le cache :</p><ul class="suggestions">${suggestions}</ul>` : ""}
      </div>`;
    $("#fiche-retour").addEventListener("click", revenir);
    $("#fiche-contenu").querySelectorAll("[data-adresse]").forEach((bouton) => {
      bouton.addEventListener("click", () => ouvrirFiche({ adresse: bouton.dataset.adresse }));
    });
    return;
  }

  afficherLieu(reponse, { n_dpe, parcelle_id, adresse });
}


function afficherLieu(reponse, entree) {
  const { parcelle, extrait, ventes = [], logements = [] } = reponse;
  // Le logement en tête, et son diagnostic le plus récent : c'est lui qui
  // porte les mesures de l'identité, comme sur l'ancienne fiche du bien.
  const tete = reponse.en_tete ? logements[0] : null;
  const principal = tete ? tete.diagnostics[tete.diagnostics.length - 1] : null;
  const centre = parcelle
    ? { latitude: parcelle.latitude, longitude: parcelle.longitude }
    : { latitude: null, longitude: null };
  const reference = parcelle ? `${parcelle.section ?? ""}${parcelle.numero ?? ""}` : "";
  const titre = tete
    ? (tete.adresse || principal.adresse || "Adresse inconnue")
    : `Parcelle ${reference}`;

  $("#fiche-contenu").innerHTML = `
  <div class="fiche-barre">
    <button type="button" class="bouton bouton-retour" id="fiche-retour">
      ← Retour
    </button>
  </div>
    <div class="fiche-entete">
      ${extraitCadastral(principal ?? centre, extrait)}
      ${panneauSatellite(extrait)}
      <div class="fiche-identite">
        <h1>${echapper(titre)}</h1>
        <p class="explication">
          ${principal ? `${echapper(principal.commune || "")} ${echapper(principal.code_postal || "")}
            ${principal.zone ? `· secteur ${echapper(principal.zone)}` : ""}
            ${parcelle ? `· parcelle ${echapper(reference)}` : ""}`
          : echapper(parcelle?.id || "")}
        </p>
        ${principal ? mesuresLogement(principal) : mesuresParcelle(parcelle)}
        <div class="liens">${liensExternes(principal ?? {
          ...centre, adresse: logements[0]?.adresse })}</div>
        ${boutonEstimer()}
      </div>
    </div>
    ${inviteCadastre(principal ?? { code_insee: parcelle?.code_insee }, extrait,
                     reponse.cadastre_charge)}

    ${vueDeRue(principal ?? { ...centre, parcelle_id: parcelle?.id })}

    ${blocVentes(ventes)}

    ${blocLogements(logements, Boolean(tete), Boolean(parcelle), ventes.length)}

    <div id="chaine-remplacements"></div>
    ${logements.length ? LECTURE : ""}`;

  // La photo aérienne attend que la mise en page soit posée : Leaflet
  // mesure son conteneur à la création, et `aspect-ratio` ne lui donne sa
  // hauteur qu'après le premier calcul de style.
  if (extrait) {
    requestAnimationFrame(() => {
      if (!document.getElementById("satellite-fiche")) return;
      const satellite = creerVueSatellite("satellite-fiche",
                                          cadrerPourSatellite(extrait.cadre));
      satellite.tracer(extrait.parcelle.geometrie, { couleur: "#FFFFFF", epaisseur: 2.5 });
    });
  }

  $("#fiche-retour").addEventListener("click", revenir);
  $("#fiche-estimer")?.addEventListener("click", () =>
    ouvrirEstimation(principal
      ? { n_dpe: principal.n_dpe, retour: "fiche" }
      : { parcelle_id: parcelle.id, retour: "fiche" }));
  brancherVueDeRue();

  const chargeur = $("#fiche-contenu").querySelector("[data-charger-cadastre]");
  if (chargeur) {
    chargeur.addEventListener("click", () => chargerLeCadastre(chargeur, entree));
  }
  $("#fiche-contenu").querySelectorAll("[data-chaine]").forEach((bouton) => {
    bouton.addEventListener("click", () => remonterChaine(bouton.dataset.chaine));
  });
  $("#fiche-contenu").querySelectorAll("[data-en-tete]").forEach((bouton) => {
    bouton.addEventListener("click", () =>
      ouvrirFiche({ n_dpe: bouton.dataset.enTete, retour: dernierRetour }));
  });
}


/** Les mesures du logement en tête, telles que son dernier DPE les donne. */
function mesuresLogement(principal) {
  return `
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
    </dl>`;
}

/**
 * Les mesures du terrain, quand aucun logement n'est en tête. Sinon elles
 * restent sous l'extrait : terrain, bâti et bâtiments y sont déjà écrits.
 */
function mesuresParcelle(parcelle) {
  if (!parcelle) return "";
  return `
    <dl class="mesures mesures-colonne">
      <div><dt>terrain</dt><dd>${parcelle.contenance_m2 != null
        ? entierFr.format(parcelle.contenance_m2) + " m²" : "—"}</dd></div>
      <div><dt>emprise bâtie</dt><dd>${parcelle.emprise_batie_m2
        ? entierFr.format(parcelle.emprise_batie_m2) + " m²" : "—"}</dd></div>
      <div><dt>bâtiments</dt><dd>${entierFr.format(parcelle.nb_batiments ?? 0)}</dd></div>
    </dl>`;
}


/** L'avertissement d'une adresse qui couvre plusieurs logements. */
function avertissementPlusieurs(logement) {
  if (!logement.plusieurs_logements) return "";
  return `
    <p class="message message-travail">
      Jusqu'à ${entierFr.format(logement.logements_estimes)} diagnostics portent
      la même date à cette adresse : elle couvre donc plusieurs logements —
      immeuble, ou voie sans numéro. La chronologie ci-dessous les mélange.
    </p>`;
}

/**
 * Les logements du lieu, chacun avec sa chronologie.
 *
 * Un seul : sa chronologie directement, comme l'ancienne fiche du bien.
 * Plusieurs : un bloc repliable par adresse, celui en tête ouvert. C'est
 * ce qui remplace la liste « Diagnostics sur cette parcelle » et ses
 * renvois : rien n'oblige plus à changer de fiche pour lire un logement.
 */
function blocLogements(logements, enTete, aUneParcelle, nbVentes) {
  if (!logements.length) {
    return `
    <div class="vide">
      <h3>Aucun diagnostic connu sur cette parcelle</h3>
      <p>
        Cela ne veut pas dire qu'il n'y a rien à voir&nbsp;: un logement peut
        n'avoir jamais été diagnostiqué, ou l'avoir été sous une adresse que
        l'ADEME rattache ailleurs. ${nbVentes
          ? "La ou les ventes ci-dessus, elles, sont attestées."
          : "Aucune vente n'est connue non plus sur les cinq derniers millésimes."}
      </p>
    </div>`;
  }

  if (logements.length === 1) {
    const [logement] = logements;
    return `
    <h2>Chronologie — ${entierFr.format(logement.diagnostics.length)} diagnostic(s)</h2>
    ${avertissementPlusieurs(logement)}
    <ol class="chronologie">
      ${logement.diagnostics.map((d) => ligneChronologie(d, aUneParcelle)).join("")}
    </ol>`;
  }

  const total = logements.reduce((somme, l) => somme + l.diagnostics.length, 0);
  return `
    <h2>Logements — ${entierFr.format(logements.length)}</h2>
    <p class="explication">
      ${entierFr.format(total)} diagnostics, rangés par adresse.
      Beaucoup d'adresses de l'ADEME n'ont pas de numéro de rue et sont
      géocodées au centre de la voie ou de la résidence&nbsp;: une parcelle
      peut donc en porter qui ne s'y trouvent pas.
    </p>
    <div class="logements">
      ${logements.map((l, rang) => blocLogement(l, enTete && rang === 0, aUneParcelle)).join("")}
    </div>`;
}

function blocLogement(logement, enTete, aUneParcelle) {
  const dernier = logement.diagnostics[logement.diagnostics.length - 1];
  const resume = [];
  if (dernier.surface_habitable != null) {
    resume.push(`${nombreFr.format(dernier.surface_habitable)} m²`);
  }
  if (dernier.type_batiment) resume.push(dernier.type_batiment.toLowerCase());
  resume.push(`${entierFr.format(logement.diagnostics.length)} diagnostic(s)`);
  return `
    <details class="logement" ${enTete ? "open" : ""}>
      <summary>
        <span class="logement-adresse">${echapper(logement.adresse || dernier.adresse
                                                   || "adresse absente")}</span>
        ${etiquetteHtml(dernier.etiquette_dpe)}
        <span class="logement-resume">${echapper(resume.join(" · "))}</span>
        ${enTete ? '<span class="pastille pastille-concordante">en tête</span>' : ""}
      </summary>
      ${avertissementPlusieurs(logement)}
      <ol class="chronologie">
        ${logement.diagnostics.map((d) => ligneChronologie(d, aUneParcelle)).join("")}
      </ol>
      ${enTete ? "" : `
        <p class="logement-actions">
          <button type="button" class="bouton-lien"
                  data-en-tete="${echapper(dernier.n_dpe)}">Mettre ce logement en tête</button>
        </p>`}
    </details>`;
}


/**
 * L'entrée de l'estimation, dans l'identité du bien : c'est là qu'on se
 * pose la question « combien vaut-il ? », le bien sous les yeux.
 */
function boutonEstimer() {
  return `
    <p class="fiche-estimer">
      <button type="button" class="bouton bouton-principal" id="fiche-estimer">
        Estimer ce bien
      </button>
    </p>`;
}


/**
 * Charge le cadastre de la commune du bien, puis redessine la fiche.
 *
 * Sans cela, arriver ici depuis « Les DPE récents » menait à une impasse :
 * l'extrait annonçait une parcelle absente sans offrir de moyen de
 * l'obtenir, et il fallait deviner qu'il fallait ressortir par l'accueil.
 */
async function chargerLeCadastre(bouton, entree) {
  const commune = bouton.dataset.commune || "cette commune";
  // Le bouton dit « charger » ou « compléter » selon le manque : on le
  // retient pour le rétablir tel quel si la demande échoue.
  const libelle = bouton.textContent.trim();
  bouton.disabled = true;
  bouton.textContent = "Téléchargement…";
  masquerErreur();

  let etat;
  try {
    etat = await api.preparerCommune(bouton.dataset.insee, "cadastre");
  } catch (erreur) {
    bouton.disabled = false;
    bouton.textContent = libelle;
    afficherErreur(`Le cadastre de ${commune} n'a pas pu être demandé.`, erreur.message);
    return;
  }

  if (!etat.lance) {
    // Déjà là, ou une moisson occupe la place : on retente l'affichage.
    ouvrirFiche({ ...entree, retour: dernierRetour, sansHistorique: true });
    return;
  }

  afficherTravail(`Téléchargement du cadastre de ${commune}…`);
  suivreImport();
  auProchainTerme(() => {
    masquerTravail();
    ouvrirFiche({ ...entree, retour: dernierRetour, sansHistorique: true });
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
