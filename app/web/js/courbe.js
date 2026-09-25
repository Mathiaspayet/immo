// ====================================================================
//  courbe.js — La valeur d'un bien dans le temps, en SVG.
//
//  Une seule série — la valeur estimée —, sa fourchette en voile, et des
//  événements posés dessus : les ventes réelles du bien, les estimations
//  enregistrées. Aucune bibliothèque : le graphique tient en un chemin et
//  quelques points, et l'application ne charge rien de l'extérieur (CDC 3).
//
//  Les couleurs sont passées au validateur (écarts sous daltonisme, contraste
//  sur le fond) ; chaque marque a aussi sa FORME — trait, rond, losange —,
//  la couleur n'est donc jamais seule à dire ce qu'on regarde.
// ====================================================================

import { euroFr } from "./format.js";

export const COULEURS = { valeur: "#0F8A5F", estimation: "#355FC4", vente: "#C95F1C" };

const NS = "http://www.w3.org/2000/svg";
const HAUTEUR = 240;
const MARGES = { haut: 18, droite: 18, bas: 28, gauche: 58 };
const GRILLE = "#E2E6E3";
const AXE = "#9AA6A0";
const ENCRE = "#5D6E71";

function element(nom, attributs = {}, parent = null) {
  const noeud = document.createElementNS(NS, nom);
  for (const [cle, valeur] of Object.entries(attributs)) noeud.setAttribute(cle, valeur);
  if (parent) parent.appendChild(noeud);
  return noeud;
}

/** Un pas « rond » pour l'axe des valeurs : 10 000, 20 000, 50 000… */
function pasRond(etendue, graduations = 4) {
  const brut = etendue / graduations;
  const puissance = 10 ** Math.floor(Math.log10(brut));
  return [1, 2, 2.5, 5, 10].map((m) => m * puissance).find((p) => p >= brut) || brut;
}

const milliers = (valeur) => `${Math.round(valeur / 1000).toLocaleString("fr-FR")} k€`;

export function libelleTrimestre(code) {
  const [annee, t] = String(code || "").split("-Q");
  if (!t) return code || "";
  return `${t === "1" ? "1er" : `${t}e`} trimestre ${annee}`;
}

/**
 * Trace la courbe dans `conteneur`, à sa largeur réelle : un graphique mis
 * à l'échelle par viewBox rapetisse aussi ses textes, illisibles sur
 * téléphone. On redessine donc quand la largeur change.
 *
 * donnees : { points: [{trimestre, valeur, bas, haut, source}],
 *             ventes: [{trimestre, date, prix}],
 *             estimations: [{trimestre, date, valeur}], ancre }
 */
export function tracerCourbe(conteneur, donnees) {
  if (!conteneur || !donnees?.points?.length) return;
  let largeurTracee = 0;
  const dessiner = () => {
    const largeur = Math.max(280, Math.round(conteneur.clientWidth));
    if (largeur === largeurTracee) return;
    largeurTracee = largeur;
    dessinerA(conteneur, donnees, largeur);
  };
  dessiner();
  if (typeof ResizeObserver === "function") new ResizeObserver(dessiner).observe(conteneur);
}

function dessinerA(conteneur, donnees, largeur) {
  const points = donnees.points;
  const rang = new Map(points.map((p, i) => [p.trimestre, i]));
  const ventes = (donnees.ventes || []).filter((v) => rang.has(v.trimestre));
  const estimations = (donnees.estimations || []).filter((e) => rang.has(e.trimestre));

  const valeurs = [
    ...points.flatMap((p) => [p.bas, p.haut]),
    ...ventes.map((v) => v.prix), ...estimations.map((e) => e.valeur),
  ];
  const pas = pasRond(Math.max(...valeurs) - Math.min(...valeurs) || 1000);
  const yMin = Math.floor(Math.min(...valeurs) / pas) * pas;
  const yMax = Math.ceil(Math.max(...valeurs) / pas) * pas;
  const x0 = MARGES.gauche;
  const x1 = largeur - MARGES.droite;
  const y0 = HAUTEUR - MARGES.bas;
  const y1 = MARGES.haut;
  const x = (i) => x0 + (points.length > 1 ? (i / (points.length - 1)) * (x1 - x0) : (x1 - x0) / 2);
  const y = (valeur) => y0 - ((valeur - yMin) / (yMax - yMin || 1)) * (y0 - y1);

  conteneur.replaceChildren();
  const svg = element("svg", {
    width: largeur, height: HAUTEUR, viewBox: `0 0 ${largeur} ${HAUTEUR}`,
    "aria-hidden": "true", class: "courbe-svg",
  }, conteneur);

  // Grille horizontale et graduations : des filets pleins, en retrait.
  for (let v = yMin; v <= yMax + 1; v += pas) {
    element("line", { x1: x0, x2: x1, y1: y(v), y2: y(v), stroke: GRILLE, "stroke-width": 1 }, svg);
    const texte = element("text", { x: x0 - 8, y: y(v) + 4, "text-anchor": "end",
                                    "font-size": 11, fill: ENCRE, class: "donnee" }, svg);
    texte.textContent = milliers(v);
  }
  // Les années, au premier trimestre de chacune.
  points.forEach((p, i) => {
    if (!p.trimestre.endsWith("Q1")) return;
    element("line", { x1: x(i), x2: x(i), y1: y0, y2: y0 + 4, stroke: AXE, "stroke-width": 1 }, svg);
    const texte = element("text", { x: x(i), y: y0 + 17, "text-anchor": "middle",
                                    "font-size": 11, fill: ENCRE }, svg);
    texte.textContent = p.trimestre.slice(0, 4);
  });
  element("line", { x1: x0, x2: x1, y1: y0, y2: y0, stroke: AXE, "stroke-width": 1 }, svg);

  // La fourchette : un voile de la couleur de la série.
  const voile = points.map((p, i) => `${x(i).toFixed(1)},${y(p.haut).toFixed(1)}`)
    .concat(points.slice().reverse().map((p, j) => {
      const i = points.length - 1 - j;
      return `${x(i).toFixed(1)},${y(p.bas).toFixed(1)}`;
    }));
  element("polygon", { points: voile.join(" "), fill: COULEURS.valeur, "fill-opacity": 0.1 }, svg);

  // La valeur : trait plein sur DVF, pointillé là où seul l'indice officiel
  // la prolonge — c'est une projection, et elle doit se lire comme telle.
  const trace = (debut, fin, pointille) => {
    if (fin <= debut) return;
    const chemin = points.slice(debut, fin + 1)
      .map((p, k) => `${k ? "L" : "M"}${x(debut + k).toFixed(1)} ${y(p.valeur).toFixed(1)}`).join(" ");
    element("path", {
      d: chemin, fill: "none", stroke: COULEURS.valeur, "stroke-width": 2,
      "stroke-linejoin": "round", "stroke-linecap": "round",
      ...(pointille ? { "stroke-dasharray": "4 4" } : {}),
    }, svg);
  };
  const premierProjete = points.findIndex((p) => p.source !== "dvf");
  if (premierProjete === -1) {
    trace(0, points.length - 1, false);
  } else {
    trace(0, Math.max(premierProjete - 1, 0), false);
    trace(Math.max(premierProjete - 1, 0), points.length - 1, true);
  }

  // Le point final d'abord : une estimation enregistrée tombe souvent
  // dessus, et c'est elle qu'on doit voir.
  const dernierPoint = points.length - 1;
  element("circle", { cx: x(dernierPoint), cy: y(points[dernierPoint].valeur), r: 4.5,
                      fill: COULEURS.valeur, stroke: "#FAFBFA", "stroke-width": 2 }, svg);

  // Les événements : un anneau de la couleur du fond les détache du trait.
  for (const vente of ventes) {
    element("circle", { cx: x(rang.get(vente.trimestre)), cy: y(vente.prix), r: 5,
                        fill: COULEURS.vente, stroke: "#FAFBFA", "stroke-width": 2 }, svg);
  }
  for (const estimation of estimations) {
    const cx = x(rang.get(estimation.trimestre));
    const cy = y(estimation.valeur);
    element("rect", { x: cx - 4.5, y: cy - 4.5, width: 9, height: 9,
                      transform: `rotate(45 ${cx} ${cy})`, fill: COULEURS.estimation,
                      stroke: "#FAFBFA", "stroke-width": 2 }, svg);
  }

  // Étiquettes choisies : la valeur au dernier trimestre, et le sommet s'il
  // est ailleurs — jamais un nombre sur chaque point.
  const dernier = points.length - 1;
  const iMax = points.reduce((meilleur, p, i) => (p.valeur > points[meilleur].valeur ? i : meilleur), 0);
  const etiqueter = (i, ancre) => {
    const texte = element("text", {
      x: x(i) + (ancre === "end" ? -6 : 6), y: y(points[i].valeur) - 9, "text-anchor": ancre,
      "font-size": 12, "font-weight": 600, fill: "#12262B", class: "donnee",
    }, svg);
    texte.textContent = euroFr.format(Math.round(points[i].valeur / 1000) * 1000);
  };
  etiqueter(dernier, "end");
  if (iMax !== dernier && Math.abs(x(iMax) - x(dernier)) > 90) etiqueter(iMax, "middle");

  // Le réticule : il trouve le trimestre le plus proche du doigt.
  const reticule = element("line", { y1: y1, y2: y0, stroke: AXE, "stroke-width": 1,
                                     visibility: "hidden" }, svg);
  const repere = element("circle", { r: 4.5, fill: COULEURS.valeur, stroke: "#FAFBFA",
                                     "stroke-width": 2, visibility: "hidden" }, svg);
  const bulle = document.createElement("div");
  bulle.className = "courbe-bulle";
  bulle.hidden = true;
  conteneur.appendChild(bulle);

  const montrer = (i) => {
    const p = points[i];
    reticule.setAttribute("x1", x(i));
    reticule.setAttribute("x2", x(i));
    reticule.setAttribute("visibility", "visible");
    repere.setAttribute("cx", x(i));
    repere.setAttribute("cy", y(p.valeur));
    repere.setAttribute("visibility", "visible");
    bulle.replaceChildren();
    const valeur = document.createElement("strong");
    valeur.textContent = euroFr.format(Math.round(p.valeur / 1000) * 1000);
    const quand = document.createElement("span");
    quand.textContent = `${libelleTrimestre(p.trimestre)}${p.source !== "dvf" ? " · indice officiel" : ""}`;
    const fourchette = document.createElement("span");
    fourchette.textContent = `entre ${euroFr.format(Math.round(p.bas / 1000) * 1000)} et ${
      euroFr.format(Math.round(p.haut / 1000) * 1000)}`;
    bulle.append(valeur, quand, fourchette);
    for (const vente of ventes.filter((v) => v.trimestre === p.trimestre)) {
      const ligne = document.createElement("span");
      ligne.className = "courbe-bulle-vente";
      ligne.textContent = `Vendu ${euroFr.format(vente.prix)}`;
      bulle.appendChild(ligne);
    }
    for (const estimation of estimations.filter((e) => e.trimestre === p.trimestre)) {
      const ligne = document.createElement("span");
      ligne.className = "courbe-bulle-estimation";
      ligne.textContent = `Votre estimation : ${euroFr.format(estimation.valeur)}`;
      bulle.appendChild(ligne);
    }
    bulle.hidden = false;
    const gauche = Math.min(Math.max(x(i) - bulle.offsetWidth / 2, 0), largeur - bulle.offsetWidth);
    bulle.style.left = `${gauche}px`;
    conteneur.dataset.index = String(i);
  };
  const cacher = () => {
    reticule.setAttribute("visibility", "hidden");
    repere.setAttribute("visibility", "hidden");
    bulle.hidden = true;
  };
  const indiceSous = (evenement) => {
    const cadre = svg.getBoundingClientRect();
    const position = evenement.clientX - cadre.left;
    const i = Math.round(((position - x0) / (x1 - x0)) * (points.length - 1));
    return Math.min(Math.max(i, 0), points.length - 1);
  };
  svg.addEventListener("pointermove", (evenement) => montrer(indiceSous(evenement)));
  svg.addEventListener("pointerdown", (evenement) => montrer(indiceSous(evenement)));
  svg.addEventListener("pointerleave", cacher);
  // Au clavier : les flèches parcourent les trimestres.
  conteneur.onkeydown = (evenement) => {
    if (evenement.key !== "ArrowLeft" && evenement.key !== "ArrowRight") return;
    evenement.preventDefault();
    const courant = conteneur.dataset.index ? Number(conteneur.dataset.index) : dernier;
    const suivant = evenement.key === "ArrowLeft" ? courant - 1 : courant + 1;
    montrer(Math.min(Math.max(suivant, 0), dernier));
  };
  conteneur.onblur = cacher;
}
