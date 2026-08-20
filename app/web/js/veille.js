import { api, ErreurApi } from "./api.js";
import { creerCarte } from "./carte.js";
import {
  auTermeDeLImport, lancerImport, rafraichirSiPerime, reprendreSuiviEventuel,
} from "./import.js";
import { ouvrirFiche } from "./fiche.js";
import { initialiserIdentification } from "./identifier.js";
import { auChangement, changerVue } from "./navigation.js";
import {
  $, afficherErreur, afficherSucces, anciennete, dateFr, echapper, entierFr,
  etiquetteHtml, liensExternes, masquerErreur, mesure, nombreFr,
} from "./format.js";

const etat = {
  filtres: {},
  resultats: [],
  selection: null,
  carte: null,
  sondage: null,      // identifiant du minuteur de suivi d'import
};

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

// --------------------------------------------------------------------
//  Écran Veille
// --------------------------------------------------------------------

function lireFiltres() {
  const formulaire = $("#filtres");
  const etiquette = formulaire.etiquettes.value;
  return {
    fenetre_jours: formulaire.fenetre_jours.value,
    // Le code INSEE plutôt que le nom : l'ADEME écrit la même commune de
    // plusieurs façons, et lui seul identifie sans ambiguïté.
    code_insee: formulaire.code_insee.value,
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

  // Les réglages autorisent n'importe quelle fenêtre (45 jours par
  // exemple). Si elle ne figure pas dans la liste déroulante, on l'y
  // ajoute : sans cela le sélecteur resterait vide, et l'utilisateur
  // ne verrait pas quel filtre s'applique.
  const fenetre = String(filtres.fenetre_jours ?? 120);
  const choix = formulaire.fenetre_jours;
  if (![...choix.options].some((option) => option.value === fenetre)) {
    choix.add(new Option(`${fenetre} jours`, fenetre), 0);
  }
  choix.value = fenetre;
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
              surface. Un secteur peut aussi n'avoir simplement aucun
              diagnostic récent : il ne s'établit qu'environ 1,6 DPE par jour
              sur l'ensemble du 40200, toutes communes et tous types
              confondus.</p>
         </div>`;
    return;
  }

  liste.innerHTML = resultats.map(gabaritReleve).join("");

  liste.querySelectorAll("[data-fiche]").forEach((bouton) => {
    bouton.addEventListener("click", (evenement) => {
      evenement.stopPropagation();
      ouvrirFiche({ n_dpe: bouton.dataset.fiche });
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

/**
 * Charge la liste. `recherche` distingue une vraie recherche — ouverture de
 * l'application, changement de filtre — d'un simple rechargement après
 * import : seule la première peut déclencher une moisson (CDC §4).
 */
async function charger({ recherche = false } = {}) {
  masquerErreur();
  etat.filtres = lireFiltres();
  $("#export-csv").href = api.urlExport(etat.filtres);

  // Lancé sans attendre : les données déjà en cache s'affichent tout de
  // suite, la moisson tourne derrière et rappellera charger() en finissant.
  if (recherche) rafraichirSiPerime();

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

/**
 * Remplit les listes de communes à partir de ce que le cache contient
 * réellement — plutôt que de faire deviner une orthographe.
 */
async function chargerCommunes() {
  try {
    const { communes, zones } = await api.communes();
    const selecteur = $("#f-commune");
    const choisi = selecteur.value;
    selecteur.innerHTML =
      '<option value="">toutes les communes</option>' +
      communes.map((commune) =>
        `<option value="${echapper(commune.code_insee)}">` +
        `${echapper(commune.nom)} (${entierFr.format(commune.dpe)})</option>`).join("");
    selecteur.value = choisi;

    // Le sous-titre dit ce qui est réellement surveillé : « Mimizan et
    // communes voisines » était écrit en dur et devenait faux dès qu'on
    // ajoutait un autre code postal.
    const sousTitre = $("#sous-titre");
    if (communes.length === 0) {
      sousTitre.textContent = "DPE récents";
    } else if (communes.length <= 3) {
      sousTitre.textContent = "DPE récents · " +
        communes.map((c) => c.nom).join(", ");
    } else {
      sousTitre.textContent = `DPE récents · ${communes[0].nom} ` +
        `et ${communes.length - 1} communes voisines`;
    }
    // Le filtre par secteur ne s'affiche que s'il a de quoi filtrer : les
    // secteurs sont propres à une commune, et disparaissent dès qu'on
    // surveille un autre territoire.
    const champSecteur = $("#f-zone").closest(".champ");
    const selecteurZone = $("#f-zone");
    if (!zones || zones.length === 0) {
      champSecteur.hidden = true;
      selecteurZone.value = "";
    } else {
      champSecteur.hidden = false;
      const zoneChoisie = selecteurZone.value;
      selecteurZone.innerHTML = '<option value="">tous</option>' +
        zones.map((zone) => `<option>${echapper(zone)}</option>`).join("");
      selecteurZone.value = zoneChoisie;
    }

    return communes;
  } catch (_) {
    return [];      // la liste reste sur « toutes les communes »
  }
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
    $("#r-zones-insee").value = reglages.zones_code_insee ?? "";

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
      zones_code_insee: $("#r-zones-insee").value.trim(),
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

/** Version déployée, affichée en permanence dans le bandeau. */
async function afficherVersion() {
  try {
    const sante = await api.sante();
    const boite = $("#version");

    if (!sante.version || sante.version === "dev") {
      boite.textContent = "version locale";
      boite.title = "Construite hors CI — pas de numéro de version";
      return;
    }

    // BUILD_VERSION porte l'empreinte complète du commit : sept caractères
    // suffisent à l'identifier, et tiennent dans le bandeau.
    const abrege = sante.version.slice(0, 7);
    const date = new Date(sante.date_build);
    const horodatage = Number.isNaN(date.getTime())
      ? ""
      : " · " + date.toLocaleString("fr-FR", {
          day: "2-digit", month: "2-digit", year: "numeric",
          hour: "2-digit", minute: "2-digit",
        });

    boite.textContent = abrege + horodatage;
    boite.title = `Version ${sante.version}\nConstruite le ${sante.date_build}`;
  } catch (_) { /* le bandeau reste vide, ce n'est pas bloquant */ }
}

async function chargerJournal() {
  try {
    // Ce que les codes postaux surveillés couvrent réellement : le 40200
    // ne se limite pas à Mimizan, et rien ne le disait.
    const { communes } = await api.communes();
    $("#communes-couvertes").innerHTML = communes.length
      ? "Actuellement en cache : " + communes.map((commune) =>
          `<span class="donnee">${echapper(commune.nom)}</span> ` +
          `(${entierFr.format(commune.dpe)} DPE, INSEE ${echapper(commune.code_insee)})`
        ).join(" · ")
      : "Aucune commune en cache : lancez un import depuis l'écran Veille.";
  } catch (_) { /* section facultative */ }

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
  $("#filtres").addEventListener("change", () => charger({ recherche: true }));
  $("#filtres").addEventListener("submit", (e) => e.preventDefault());

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

  // Ce qu'il faut rafraîchir quand un écran redevient visible.
  // Quand une moisson aboutit, l'écran se remet à jour tout seul.
  // Une moisson peut faire apparaître une commune jusque-là absente.
  auTermeDeLImport(() => { chargerCommunes(); charger(); });

  auChangement("reglages", () => { chargerReglages(); chargerJournal(); });
  auChangement("veille", () => { if (etat.carte) etat.carte.redimensionner(); });

  initialiserIdentification();

  // Les filtres par défaut viennent des réglages : on les demande une fois,
  // puis on charge la liste avec.
  try {
    const reponse = await api.veille({});
    appliquerFiltres(reponse.filtres);
  } catch (_) { /* charger() affichera l'erreur */ }

  await chargerReglages();
  await chargerCommunes();
  afficherVersion();
  // L'ouverture de l'application compte comme une recherche : c'est le
  // moment où l'on veut des données du jour.
  await charger({ recherche: true });
  await reprendreSuiviEventuel();
}

demarrer();
