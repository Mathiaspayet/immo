// ====================================================================
//  veille.js — Orchestration de l'interface.
//
//  Modules ES natifs, aucun outil de construction : le fichier que vous
//  lisez est exactement celui que le navigateur exécute (CDC 3).
// ====================================================================

import { api, ErreurApi } from "./api.js";
import { creerCarte } from "./carte.js";

const $ = (selecteur) => document.querySelector(selecteur);

const etat = {
  filtres: {},
  resultats: [],
  selection: null,
  carte: null,
  sondage: null,      // identifiant du minuteur de suivi d'import
};

// --------------------------------------------------------------------
//  Mise en forme
// --------------------------------------------------------------------

const nombreFr = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 1 });
const entierFr = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 0 });

function dateFr(iso) {
  if (!iso) return "—";
  const [a, m, j] = String(iso).slice(0, 10).split("-");
  return j && m && a ? `${j}/${m}/${a}` : iso;
}

function anciennete(jours) {
  if (jours == null) return "";
  if (jours === 0) return "aujourd'hui";
  if (jours === 1) return "hier";
  if (jours < 31) return `il y a ${jours} j`;
  const mois = Math.round(jours / 30.44);
  return `il y a ${mois} mois`;
}

function echapper(texte) {
  const boite = document.createElement("span");
  boite.textContent = texte ?? "";
  return boite.innerHTML;
}

/** Une mesure : valeur en chasse fixe, ou tiret explicite si absente. */
function mesure(libelle, valeur, unite = "", format = nombreFr) {
  const absent = valeur === null || valeur === undefined || valeur === "";
  const affiche = absent ? "—" : `${format.format(valeur)}${unite ? " " + unite : ""}`;
  return `<div><dt>${libelle}</dt><dd class="${absent ? "absent" : ""}">${affiche}</dd></div>`;
}

function liensExternes(bien) {
  const aCoordonnees = bien.latitude != null && bien.longitude != null;
  const point = aCoordonnees ? `${bien.latitude},${bien.longitude}` : "";
  const requete = encodeURIComponent(bien.adresse || "");

  const satellite = aCoordonnees
    ? `https://www.google.com/maps/@?api=1&map_action=map&center=${point}&zoom=19&basemap=satellite`
    : `https://www.google.com/maps/search/?api=1&query=${requete}`;
  const pano = aCoordonnees
    ? `https://www.google.com/maps/@?api=1&map_action=pano&viewpoint=${point}`
    : `https://www.google.com/maps/search/?api=1&query=${requete}`;
  const geoportail = aCoordonnees
    ? `https://www.geoportail.gouv.fr/carte?c=${bien.longitude},${bien.latitude}&z=19` +
      "&l0=ORTHOIMAGERY.ORTHOPHOTOS::GEOPORTAIL:OGC:WMTS(1)" +
      "&l1=CADASTRALPARCELS.PARCELLAIRE_EXPRESS::GEOPORTAIL:OGC:WMTS(1)&permalink=yes"
    : "https://www.geoportail.gouv.fr/";

  return `
    <a href="${satellite}" target="_blank" rel="noopener">Satellite</a>
    <a href="${pano}" target="_blank" rel="noopener">Street View</a>
    <a href="${geoportail}" target="_blank" rel="noopener">Géoportail</a>
    <span class="reference donnee">${echapper(bien.n_dpe)}</span>`;
}

function gabaritReleve(bien) {
  const classe = (bien.etiquette_dpe || "").toUpperCase();
  const etiquette = classe
    ? `<span class="etiquette etiquette-${classe}" title="Classe ${classe}">${classe}</span>`
    : '<span class="absent">—</span>';

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
      <div><dt>classe</dt><dd>${etiquette}</dd></div>
      ${mesure("énergie ép.", bien.conso_ep_m2, "kWh/m²", entierFr)}
      ${mesure("GES", bien.ges_m2, "kg/m²", nombreFr)}
      ${mesure("coût annuel", bien.cout_annuel, "€", entierFr)}
      ${mesure("construit", bien.annee_construction, "", entierFr)}
    </dl>
    <div class="liens">${liensExternes(bien)}</div>
  </article>`;
}

// --------------------------------------------------------------------
//  Messages d'état
// --------------------------------------------------------------------

function afficherErreur(message, detail = "") {
  const boite = $("#erreur");
  boite.innerHTML = echapper(message) + (detail ? `<span class="detail">${echapper(detail)}</span>` : "");
  boite.hidden = false;
}
function masquerErreur() { $("#erreur").hidden = true; }

function afficherSucces(message) {
  const boite = $("#succes");
  boite.textContent = message;
  boite.hidden = false;
  setTimeout(() => { boite.hidden = true; }, 8000);
}

function afficherTravail(message, avecJauge = true) {
  const boite = $("#progression");
  boite.innerHTML = echapper(message) + (avecJauge ? '<span class="jauge"><span></span></span>' : "");
  boite.hidden = false;
}
function masquerTravail() { $("#progression").hidden = true; }

// --------------------------------------------------------------------
//  Écran Veille
// --------------------------------------------------------------------

function lireFiltres() {
  const formulaire = $("#filtres");
  const etiquette = formulaire.etiquettes.value;
  return {
    fenetre_jours: formulaire.fenetre_jours.value,
    commune: formulaire.commune.value.trim(),
    zone: formulaire.zone.value,
    type_batiment: formulaire.type_batiment.value,
    surface_min: formulaire.surface_min.value,
    surface_max: formulaire.surface_max.value,
    etiquettes: etiquette ? [etiquette] : [],
    seulement_nouveaux: formulaire.seulement_nouveaux.checked,
  };
}

function appliquerFiltres(filtres) {
  const formulaire = $("#filtres");
  formulaire.fenetre_jours.value = filtres.fenetre_jours ?? 120;
  formulaire.commune.value = filtres.commune ?? "";
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
    <span class="bloc"><span class="donnee">${resume.total_base}</span> DPE en cache</span>`;
}

function dessinerListe(resultats, resume) {
  const liste = $("#liste");

  if (!resultats.length) {
    // Un etat vide doit dire ce qui s'est passe et quoi faire (CDC 7).
    const jamais = resume.total_base === 0;
    liste.innerHTML = jamais
      ? `<div class="vide">
           <h3>La base est vide</h3>
           <p>Aucun DPE n'a encore été importé. Lancez un premier import avec le
              bouton <strong>Rafraîchir</strong> en haut à droite : il télécharge
              les diagnostics des communes surveillées, ce qui prend une à deux
              minutes.</p>
         </div>`
      : `<div class="vide">
           <h3>Aucun logement ne correspond à ces filtres</h3>
           <p>La base contient ${resume.total_base} DPE. Élargissez la fenêtre
              temporelle, retirez le filtre de commune ou desserrez les bornes de
              surface. Un secteur peut aussi n'avoir aucun diagnostic récent :
              la transmission des DPE à l'ADEME prend quelques semaines.</p>
         </div>`;
    return;
  }

  liste.innerHTML = resultats.map(gabaritReleve).join("");

  liste.querySelectorAll(".releve").forEach((element) => {
    const choisir = () => selectionner(element.dataset.dpe);
    element.addEventListener("click", (evenement) => {
      if (evenement.target.closest("a")) return;   // on laisse passer les liens
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

function selectionner(numero) {
  etat.selection = numero;
  document.querySelectorAll(".releve").forEach((element) => {
    element.setAttribute("aria-current", element.dataset.dpe === numero ? "true" : "false");
  });
  if (etat.carte) {
    deplierCarte();
    etat.carte.surligner(numero);
  }
}

async function charger() {
  masquerErreur();
  etat.filtres = lireFiltres();
  $("#export-csv").href = api.urlExport(etat.filtres);

  try {
    const reponse = await api.veille(etat.filtres);
    etat.resultats = reponse.resultats;
    dessinerCompteurs(reponse.resume);
    dessinerListe(reponse.resultats, reponse.resume);
    if (etat.carte) etat.carte.afficher(reponse.resultats);
  } catch (erreur) {
    afficherErreur(
      erreur instanceof ErreurApi ? erreur.message : "Impossible de charger la veille.",
      erreur instanceof ErreurApi ? "" : String(erreur)
    );
  }
}

// --------------------------------------------------------------------
//  Import : lancement et suivi
// --------------------------------------------------------------------

async function lancerImport() {
  masquerErreur();
  $("#rafraichir").disabled = true;
  try {
    await api.lancerImport();
    afficherTravail("Import démarré…");
    suivreImport();
  } catch (erreur) {
    $("#rafraichir").disabled = false;
    afficherErreur(erreur.message);
  }
}

function suivreImport() {
  clearInterval(etat.sondage);
  etat.sondage = setInterval(async () => {
    let statut;
    try {
      statut = await api.statutImport();
    } catch (erreur) {
      clearInterval(etat.sondage);
      $("#rafraichir").disabled = false;
      masquerTravail();
      afficherErreur("Le suivi de l'import s'est interrompu.", erreur.message);
      return;
    }

    if (statut.en_cours) {
      const lignes = statut.lignes ? ` — ${entierFr.format(statut.lignes)} lignes` : "";
      afficherTravail(`${statut.etape || "import en cours"}${lignes}`);
      return;
    }

    clearInterval(etat.sondage);
    $("#rafraichir").disabled = false;
    masquerTravail();

    if (statut.statut === "echec") {
      afficherErreur("L'import a échoué.", statut.message || "");
    } else if (statut.statut === "succes") {
      afficherSucces(statut.message || "Import terminé.");
    }
    charger();
  }, 1500);
}

/** Au chargement de la page, un import planifié peut déjà tourner. */
async function reprendreSuiviEventuel() {
  try {
    const statut = await api.statutImport();
    if (statut.en_cours) {
      $("#rafraichir").disabled = true;
      afficherTravail(statut.etape || "import en cours");
      suivreImport();
    }
  } catch (_) { /* la page se chargera quand même */ }
}

// --------------------------------------------------------------------
//  Écran Réglages
// --------------------------------------------------------------------

function communesVersTexte(communes) {
  return communes.map((c) => `${c.code_postal} ${c.commune || ""}`.trim()).join("\n");
}

function texteVersCommunes(texte) {
  return texte.split("\n").map((ligne) => ligne.trim()).filter(Boolean)
    .map((ligne) => {
      const [code, ...reste] = ligne.split(/\s+/);
      return { code_postal: code, commune: reste.join(" ") };
    });
}

function zonesVersTexte(zones) {
  return Object.entries(zones).map(([nom, p]) => `${nom} ${p[0]} ${p[1]}`).join("\n");
}

function texteVersZones(texte) {
  const zones = {};
  for (const ligne of texte.split("\n").map((l) => l.trim()).filter(Boolean)) {
    const [nom, lat, lon] = ligne.split(/\s+/);
    if (!nom || lat === undefined || lon === undefined) {
      throw new Error(`Secteur mal formé : « ${ligne} ». Attendu : nom latitude longitude.`);
    }
    zones[nom] = [Number(lat), Number(lon)];
  }
  return zones;
}

async function chargerReglages() {
  try {
    const { reglages } = await api.reglages();
    $("#r-communes").value = communesVersTexte(reglages.communes);
    $("#r-zones").value = zonesVersTexte(reglages.zones);
    $("#r-fenetre").value = reglages.fenetre_jours;
    $("#r-type").value = reglages.type_batiment ?? "";
    $("#r-surface-min").value = reglages.surface_min;
    $("#r-surface-max").value = reglages.surface_max;
    $("#r-purge").value = reglages.purge_mois;

    // Le sélecteur de secteur de l'écran Veille suit les réglages.
    const selecteur = $("#f-zone");
    const choisi = selecteur.value;
    selecteur.innerHTML = '<option value="">tous</option>' +
      Object.keys(reglages.zones).map((nom) => `<option>${echapper(nom)}</option>`).join("");
    selecteur.value = choisi;
  } catch (erreur) {
    afficherErreur("Impossible de lire les réglages.", erreur.message);
  }
}

async function enregistrerReglages() {
  masquerErreur();
  let valeurs;
  try {
    valeurs = {
      communes: texteVersCommunes($("#r-communes").value),
      zones: texteVersZones($("#r-zones").value),
      fenetre_jours: Number($("#r-fenetre").value),
      type_batiment: $("#r-type").value,
      surface_min: Number($("#r-surface-min").value),
      surface_max: Number($("#r-surface-max").value),
      purge_mois: Number($("#r-purge").value),
    };
  } catch (erreur) {
    afficherErreur(erreur.message);
    return;
  }

  try {
    await api.enregistrerReglages(valeurs);
    afficherSucces("Réglages enregistrés.");
    await chargerReglages();
    await chargerJournal();
  } catch (erreur) {
    afficherErreur("Réglages refusés.", erreur.message);
  }
}

async function chargerJournal() {
  try {
    const [{ imports }, sante] = await Promise.all([api.journalImports(), api.sante()]);

    $("#prochain-import").innerHTML = sante.prochain_import
      ? `Import automatique hebdomadaire. Prochaine exécution :
         <span class="donnee">${dateFr(sante.prochain_import)}
         à ${echapper(sante.prochain_import.slice(11, 16))}</span>.`
      : "Import automatique désactivé sur ce conteneur.";

    $("#a-propos").innerHTML =
      `Version <span class="donnee">${echapper(sante.version)}</span> · ` +
      `construite le <span class="donnee">${dateFr(sante.date_build)}</span> · ` +
      `base <span class="donnee">${echapper(sante.base)}</span>`;

    const corps = $("#journal").querySelector("tbody");
    if (!imports.length) {
      corps.innerHTML = '<tr><td colspan="5" class="message">Aucun import enregistré pour l\'instant.</td></tr>';
      return;
    }
    corps.innerHTML =
      `<tr><th>Début</th><th>Fin</th><th>Statut</th><th>Lignes</th><th>Détail</th></tr>` +
      imports.map((ligne) => `
        <tr>
          <td class="donnee">${dateFr(ligne.debut)} ${echapper(ligne.debut.slice(11, 16))}</td>
          <td class="donnee">${ligne.fin ? echapper(ligne.fin.slice(11, 16)) : "—"}</td>
          <td class="statut-${echapper(ligne.statut)}">${echapper(ligne.statut)}</td>
          <td class="donnee">${entierFr.format(ligne.lignes || 0)}</td>
          <td>${echapper(ligne.message || "")}</td>
        </tr>`).join("");
  } catch (erreur) {
    afficherErreur("Impossible de lire le journal des imports.", erreur.message);
  }
}

// --------------------------------------------------------------------
//  Navigation et carte
// --------------------------------------------------------------------

function changerVue(vue) {
  $("#vue-veille").hidden = vue !== "veille";
  $("#vue-reglages").hidden = vue !== "reglages";
  document.querySelectorAll("[data-vue]").forEach((bouton) => {
    bouton.setAttribute("aria-pressed", String(bouton.dataset.vue === vue));
  });
  if (vue === "reglages") { chargerReglages(); chargerJournal(); }
  if (vue === "veille" && etat.carte) etat.carte.redimensionner();
}

function deplierCarte() {
  const panneau = $("#panneau-carte");
  if (panneau.dataset.replie === "oui") {
    panneau.dataset.replie = "non";
    $("#bascule-carte").setAttribute("aria-expanded", "true");
    etat.carte.redimensionner();
  }
}

function initialiserCarte() {
  etat.carte = creerCarte("carte", selectionner);
  // Sur grand écran la carte est visible d'emblée ; sur téléphone elle est
  // repliée pour que la liste passe en premier.
  if (window.matchMedia("(min-width: 940px)").matches) {
    $("#panneau-carte").dataset.replie = "non";
  }
  setTimeout(() => etat.carte.redimensionner(), 60);
}

// --------------------------------------------------------------------
//  Démarrage
// --------------------------------------------------------------------

async function demarrer() {
  initialiserCarte();

  $("#rafraichir").addEventListener("click", lancerImport);
  $("#filtres").addEventListener("change", charger);
  $("#filtres").addEventListener("submit", (e) => e.preventDefault());
  $("#f-commune").addEventListener("input", debounce(charger, 400));

  $("#marquer-vus").addEventListener("click", async () => {
    try {
      const { marques } = await api.marquerVus(null);
      afficherSucces(marques ? `${marques} logement(s) marqué(s) comme vus.` : "Rien à marquer.");
      charger();
    } catch (erreur) {
      afficherErreur(erreur.message);
    }
  });

  // Filtres repliables : fermes d'emblee sur telephone, pour que la
  // premiere chose visible soit la liste des biens.
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
    const panneau = $("#panneau-carte");
    const replie = panneau.dataset.replie === "oui";
    panneau.dataset.replie = replie ? "non" : "oui";
    $("#bascule-carte").setAttribute("aria-expanded", String(replie));
    if (replie) etat.carte.redimensionner();
  });

  document.querySelectorAll("[data-vue]").forEach((bouton) => {
    bouton.addEventListener("click", () => changerVue(bouton.dataset.vue));
  });

  // Les filtres par défaut viennent des réglages : on les demande une fois,
  // puis on charge la liste avec.
  try {
    const reponse = await api.veille({});
    appliquerFiltres(reponse.filtres);
  } catch (_) { /* charger() affichera l'erreur */ }

  await chargerReglages();
  await charger();
  await reprendreSuiviEventuel();
}

function debounce(fonction, delai) {
  let minuteur;
  return (...arguments_) => {
    clearTimeout(minuteur);
    minuteur = setTimeout(() => fonction(...arguments_), delai);
  };
}

demarrer();
