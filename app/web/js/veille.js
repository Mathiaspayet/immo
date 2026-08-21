import { api, ErreurApi } from "./api.js";
import { creerCarte } from "./carte.js";
import { auTermeDeLImport, lancerImport, reprendreSuiviEventuel } from "./import.js";
import { initialiserParcelles } from "./parcelles.js";
import {
  communeCourante, dessinerContexte, initialiserParcours, surCommunePrete,
} from "./parcours.js";
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
//  Écran Réglages
// --------------------------------------------------------------------

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
 * Ajuste ce qui dépend du contenu réel du cache : le sous-titre, la barre
 * de contexte, et le filtre par secteur — qui n'a de sens que là où des
 * secteurs ont été définis.
 */
async function chargerContexte() {
  const commune = communeCourante();
  try {
    const { communes, zones } = await api.communes();
    const ici = communes.find((c) => c.code_insee === commune?.code_insee);

    $("#sous-titre").textContent = commune
      ? `DPE récents · ${commune.nom}`
      : "DPE récents";
    dessinerContexte({ dpe: ici?.dpe });

    // Les secteurs sont propres à une commune : ailleurs, plus rien n'en
    // porte et le filtre n'a rien à filtrer.
    const selecteurZone = $("#f-zone");
    const champSecteur = selecteurZone.closest(".champ");
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
    return [];
  }
}

async function chargerReglages() {
  try {
    const { reglages } = await api.reglages();
    $("#r-zones").value = zonesVersTexte(reglages.zones);
    $("#r-fenetre").value = reglages.fenetre_jours;
    $("#r-type").value = reglages.type_batiment ?? "";
    $("#r-surface-min").value = reglages.surface_min;
    $("#r-surface-max").value = reglages.surface_max;
    $("#r-purge").value = reglages.purge_mois;
    $("#r-zones-insee").value = reglages.zones_code_insee ?? "";
    $("#r-alerte-active").value = reglages.alerte_active ? "1" : "0";
    $("#r-alerte-destinataire").value = reglages.alerte_destinataire ?? "";
    // Les listes se peuplent AVANT qu'on y pose la valeur enregistrée :
    // affecter une option qui n'existe pas encore la perdrait.
    await chargerEtatAlerte(reglages.alerte_code_insee ?? "",
                            reglages.alerte_zone ?? "");
  } catch (erreur) {
    afficherErreur("Impossible de lire les réglages.", erreur.message);
  }
}

/**
 * L'état de l'alerte : ce que les Réglages ne peuvent pas dire d'eux-mêmes.
 *
 * Les identifiants SMTP vivent dans l'environnement du conteneur, pas en
 * base — le mot de passe n'a rien à faire dans une réponse d'API. L'écran
 * ne peut donc pas deviner si l'envoi est possible : le serveur le lui dit.
 */
async function chargerEtatAlerte(communeChoisie = null, zoneChoisie = null) {
  const boite = $("#alerte-etat");
  if (!boite) return;
  try {
    const etat = await api.etatAlerte();
    zonesParCommune = etat.zones_par_commune || {};
    peuplerCommunes(etat.communes || [],
                    communeChoisie ?? etat.code_insee ?? "");
    peuplerZones(zoneChoisie ?? etat.zone ?? "");
    if (!etat.smtp_configure) {
      boite.innerHTML = `Aucun serveur SMTP configuré&nbsp;: renseignez
        <span class="donnee">VEILLE_SMTP_HOTE</span> et
        <span class="donnee">VEILLE_SMTP_EXPEDITEUR</span> dans le
        <span class="donnee">.env</span> du conteneur, puis redémarrez-le.
        Rien ne peut partir d'ici tant que ce n'est pas fait.`;
      return;
    }
    const attente = etat.en_attente === 0
      ? "aucun bien en attente"
      : `${etat.en_attente} bien(s) seraient signalés au prochain import`;
    boite.innerHTML = `Envoi par <span class="donnee">${echapper(etat.smtp_hote)}</span>
      ${etat.smtp_authentifie ? "avec authentification" : "sans authentification"}
      · ${echapper(attente)}.`;
  } catch (erreur) {
    boite.textContent = "État de l'alerte indisponible.";
  }
}

/** Secteurs disponibles par commune, tenus à jour par `chargerEtatAlerte`. */
let zonesParCommune = {};

function peuplerCommunes(communes, choisie) {
  const liste = $("#r-alerte-commune");
  liste.innerHTML = '<option value="">toutes les communes</option>'
    + communes.map((c) => `<option value="${echapper(c.code_insee)}">`
        + `${echapper(c.nom)} (${entierFr.format(c.dpe)} DPE)</option>`).join("");
  liste.value = choisie || "";
}

/**
 * Les secteurs de la commune retenue, et d'elle seule.
 *
 * Proposer « plage » à qui surveille Launaguet ne remonterait jamais rien :
 * les secteurs sont propres à une commune. Sans commune choisie, aucun
 * secteur n'a de sens non plus — la liste se vide et se désactive.
 */
function peuplerZones(choisie) {
  const liste = $("#r-alerte-zone");
  const commune = $("#r-alerte-commune").value;
  const zones = commune ? (zonesParCommune[commune] || []) : [];
  liste.innerHTML = '<option value="">tous les secteurs</option>'
    + zones.map((z) => `<option value="${echapper(z)}">${echapper(z)}</option>`).join("");
  liste.disabled = zones.length === 0;
  liste.value = zones.includes(choisie) ? choisie : "";
}

/** Un message de contrôle, pour ne pas découvrir un mot de passe faux au
 *  premier bien manqué. */
async function envoyerEssaiAlerte() {
  const bouton = $("#essai-alerte");
  const libelle = bouton.textContent.trim();
  masquerErreur();
  bouton.disabled = true;
  bouton.textContent = "Envoi…";
  try {
    const r = await api.essaiAlerte($("#r-alerte-destinataire").value.trim());
    afficherSucces(`Message de contrôle envoyé à ${r.destinataire}.`);
  } catch (erreur) {
    afficherErreur("Le message de contrôle n'est pas parti.", erreur.message);
  } finally {
    bouton.disabled = false;
    bouton.textContent = libelle;
  }
}

async function enregistrerReglages() {
  masquerErreur();
  let valeurs;
  try {
    valeurs = {
      zones: texteVersZones($("#r-zones").value),
      fenetre_jours: Number($("#r-fenetre").value),
      type_batiment: $("#r-type").value,
      surface_min: Number($("#r-surface-min").value),
      surface_max: Number($("#r-surface-max").value),
      purge_mois: Number($("#r-purge").value),
      zones_code_insee: $("#r-zones-insee").value.trim(),
      alerte_active: $("#r-alerte-active").value === "1",
      alerte_destinataire: $("#r-alerte-destinataire").value.trim(),
      alerte_code_insee: $("#r-alerte-commune").value.trim(),
      alerte_zone: $("#r-alerte-zone").value.trim(),
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

  $("#filtres").addEventListener("change", () => charger());
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

  $("#forcer-import").addEventListener("click", lancerImport);

  // Ce bouton n'a jamais été branché depuis le lot 1 : les réglages
  // s'affichaient, se modifiaient à l'écran, et rien n'était enregistré.
  $("#enregistrer-reglages").addEventListener("click", enregistrerReglages);
  $("#essai-alerte").addEventListener("click", envoyerEssaiAlerte);
  $("#r-alerte-commune").addEventListener("change", () => peuplerZones(""));

  // Ce qu'il faut rafraîchir quand un écran redevient visible.
  // Quand une moisson aboutit, l'écran se remet à jour tout seul.
  // Une moisson qui aboutit change ce qu'il y a à montrer.
  auTermeDeLImport(() => { chargerContexte(); charger(); });

  // Le parcours nous prévient quand une commune est choisie et prête.
  surCommunePrete(() => { chargerContexte(); charger(); });

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
  afficherVersion();

  // Le parcours prend la main : accueil, puis commune, puis résultats.
  initialiserParcelles();
  initialiserParcours();
  await reprendreSuiviEventuel();
}

demarrer();
