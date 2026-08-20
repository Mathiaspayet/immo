// ====================================================================
//  parcelles.js — F3 : la recherche cadastrale.
//
//  On cherche un terrain : telle surface de parcelle, telle emprise bâtie
//  au sol. Et surtout le croisement que demande le CDC : une parcelle au
//  bon gabarit QUI PORTE en plus un diagnostic récent. Les deux signaux
//  sont indépendants — leur rencontre est ce qui distingue un terrain qui
//  correspond d'un terrain qui bouge.
// ====================================================================

import { api } from "./api.js";
import { creerCarte } from "./carte.js";
import {
  $, afficherErreur, dateFr, echapper, entierFr, masquerErreur, nombreFr,
} from "./format.js";
import { auTermeDeLImport } from "./import.js";
import { auChangement } from "./navigation.js";
import { communeCourante, dessinerContexte, surCommunePrete } from "./parcours.js";

let carte = null;
let derniersResultats = [];

function lireFiltres() {
  const nombre = (identifiant) => {
    const brut = $(identifiant).value.trim();
    return brut === "" ? null : Number(brut);
  };
  const dpe = $("#p-dpe").value;

  return {
    code_insee: communeCourante()?.code_insee ?? "",
    terrain_min: nombre("#p-terrain-min"),
    terrain_max: nombre("#p-terrain-max"),
    emprise_min: nombre("#p-emprise-min"),
    emprise_max: nombre("#p-emprise-max"),
    avec_dpe: dpe === "oui",
    dpe_depuis_jours: /^\d+$/.test(dpe) ? Number(dpe) : null,
  };
}

function gabaritParcelle(parcelle) {
  const reference = `${parcelle.section ?? ""}${parcelle.numero ?? ""}`;
  const adresse = parcelle.adresses?.[0];
  const recent = parcelle.dpe_recent;

  return `
  <article class="releve parcelle ${recent ? "parcelle-signalee" : ""}"
           data-parcelle="${echapper(parcelle.id)}"
           data-lat="${parcelle.latitude ?? ""}" data-lon="${parcelle.longitude ?? ""}"
           tabindex="0">
    <div class="releve-tete">
      <span class="reference-parcelle donnee">${echapper(reference)}</span>
      ${recent
        ? `<span class="pastille pastille-nouveau">DPE du ${dateFr(recent)}</span>`
        : ""}
      ${parcelle.dpe > 1
        ? `<span class="pastille">${parcelle.dpe} diagnostics</span>` : ""}
    </div>
    <h3 class="adresse">${echapper(adresse || "Parcelle sans adresse connue")}</h3>
    <dl class="mesures">
      <div><dt>terrain</dt><dd>${entierFr.format(parcelle.contenance_m2 ?? 0)} m²</dd></div>
      <div><dt>emprise bâtie</dt><dd>${entierFr.format(parcelle.emprise_batie_m2 ?? 0)} m²</dd></div>
      <div><dt>bâtiments</dt><dd>${parcelle.nb_batiments ?? 0}</dd></div>
      <div><dt>emprise / terrain</dt><dd>${
        parcelle.contenance_m2
          ? nombreFr.format(100 * (parcelle.emprise_batie_m2 ?? 0) / parcelle.contenance_m2) + " %"
          : "—"}</dd></div>
    </dl>
    <div class="liens">
      ${parcelle.latitude != null ? `
        <a href="https://www.geoportail.gouv.fr/carte?c=${parcelle.longitude},${parcelle.latitude}&z=19&l0=ORTHOIMAGERY.ORTHOPHOTOS::GEOPORTAIL:OGC:WMTS(1)&l1=CADASTRALPARCELS.PARCELLAIRE_EXPRESS::GEOPORTAIL:OGC:WMTS(1)&permalink=yes"
           target="_blank" rel="noopener">Géoportail</a>
        <a href="https://www.google.com/maps/@?api=1&map_action=map&center=${parcelle.latitude},${parcelle.longitude}&zoom=19&basemap=satellite"
           target="_blank" rel="noopener">Satellite</a>` : ""}
      <span class="reference donnee">${echapper(parcelle.id)}</span>
    </div>
  </article>`;
}

function dessinerCompteurs(reponse) {
  const { resume, total } = reponse;
  const signalees = reponse.resultats.filter((p) => p.dpe_recent).length;

  $("#compteurs-parcelles").innerHTML = `
    <span class="bloc"><span class="chiffre">${entierFr.format(total)}</span> parcelle(s)</span>
    <span class="separation"></span>
    <span class="bloc"><span class="chiffre">${entierFr.format(signalees)}</span> avec diagnostic</span>
    <span class="separation"></span>
    <span class="bloc"><span class="donnee">${entierFr.format(resume.parcelles)}</span> au cadastre,
      dont <span class="donnee">${entierFr.format(resume.baties)}</span> bâties</span>
    <span class="separation"></span>
    <span class="bloc"><span class="donnee">${entierFr.format(resume.dpe_rattaches)}</span> DPE rattachés</span>`;
}

function dessinerListe(reponse) {
  const liste = $("#liste-parcelles");
  const { resultats, resume } = reponse;

  if (!resultats.length) {
    liste.innerHTML = resume.parcelles === 0
      ? `<div class="vide">
           <h3>Le cadastre de cette commune n'est pas encore chargé</h3>
           <p>Revenez à l'accueil et choisissez « Chercher par le terrain » :
              l'application ira le télécharger. Comptez une dizaine de secondes.</p>
         </div>`
      : `<div class="vide">
           <h3>Aucune parcelle ne correspond</h3>
           <p>La commune en compte ${entierFr.format(resume.parcelles)}, dont
              ${entierFr.format(resume.baties)} bâties. Élargissez les bornes de
              terrain ou d'emprise, ou retirez la condition de diagnostic récent —
              c'est elle qui resserre le plus.</p>
         </div>`;
    return;
  }

  liste.innerHTML = resultats.map(gabaritParcelle).join("");
  liste.querySelectorAll(".parcelle").forEach((element) => {
    element.addEventListener("click", (evenement) => {
      if (evenement.target.closest("a")) return;
      deplierCarte();
      carte?.centrerSur(Number(element.dataset.lat), Number(element.dataset.lon));
    });
  });
}

async function charger() {
  if (!communeCourante()) return;
  masquerErreur();
  const filtres = lireFiltres();

  try {
    const reponse = await api.parcelles(filtres);
    derniersResultats = reponse.resultats;
    dessinerCompteurs(reponse);
    dessinerListe(reponse);
    dessinerContexte({ dpe: reponse.resume.dpe_rattaches });
    if (carte) carte.afficherParcelles(reponse.resultats);
    $("#export-parcelles").href = "#";
  } catch (erreur) {
    afficherErreur("Impossible de charger les parcelles.", erreur.message);
  }
}

function deplierCarte() {
  const panneau = $("#panneau-carte-parcelles");
  if (panneau.dataset.replie === "oui") {
    panneau.dataset.replie = "non";
    $("#bascule-carte-parcelles").setAttribute("aria-expanded", "true");
    carte?.redimensionner();
  }
}

export function initialiserParcelles() {
  carte = creerCarte("carte-parcelles", (identifiant) => {
    const element = $(`[data-parcelle="${CSS.escape(identifiant)}"]`);
    if (element) element.scrollIntoView({ block: "center", behavior: "smooth" });
  });
  if (window.matchMedia("(min-width: 940px)").matches) {
    $("#panneau-carte-parcelles").dataset.replie = "non";
  }

  $("#filtres-parcelles").addEventListener("change", charger);
  $("#filtres-parcelles").addEventListener("submit", (e) => e.preventDefault());

  $("#bascule-carte-parcelles").addEventListener("click", () => {
    const panneau = $("#panneau-carte-parcelles");
    const replie = panneau.dataset.replie === "oui";
    panneau.dataset.replie = replie ? "non" : "oui";
    $("#bascule-carte-parcelles").setAttribute("aria-expanded", String(replie));
    if (replie) carte?.redimensionner();
  });

  // Leaflet mesure son conteneur à la création : l'écran étant masqué à ce
  // moment-là, il calcule une taille nulle et ne dessine rien. Il faut le
  // prévenir quand l'écran devient visible.
  auChangement("parcelles", () => {
    carte?.redimensionner();
    if (derniersResultats.length) carte?.afficherParcelles(derniersResultats);
  });

  // Le parcours nous prévient quand une commune est choisie et prête.
  surCommunePrete(() => { if (!$("#vue-parcelles").hidden) charger(); });
  auTermeDeLImport(() => { if (!$("#vue-parcelles").hidden) charger(); });

  // L'export reprend les colonnes du tableau, sans passer par le serveur :
  // les données sont déjà là.
  $("#export-parcelles").addEventListener("click", (evenement) => {
    if (!derniersResultats.length) { evenement.preventDefault(); return; }
    const colonnes = ["id", "section", "numero", "contenance_m2", "emprise_batie_m2",
                      "nb_batiments", "dpe", "dpe_recent", "latitude", "longitude"];
    const lignes = [colonnes.join(";")].concat(derniersResultats.map((p) =>
      colonnes.map((c) => (Array.isArray(p[c]) ? p[c].join(" ") : p[c] ?? "")).join(";")));
    const contenu = "﻿" + lignes.join("\r\n");
    evenement.target.href = URL.createObjectURL(
      new Blob([contenu], { type: "text/csv;charset=utf-8" }));
    evenement.target.download =
      `parcelles-${communeCourante()?.nom ?? "commune"}.csv`;
  });
}

export function chargerParcelles() { return charger(); }
