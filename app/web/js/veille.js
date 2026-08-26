import { api, ErreurApi } from "./api.js";
import { creerCarte } from "./carte.js";
import { auTermeDeLImport, lancerImport, reprendreSuiviEventuel } from "./import.js";
import { initialiserExploration } from "./exploration.js";
import { initialiserReglages, rafraichirReglages } from "./reglages.js";
import {
  communeCourante, dessinerContexte, initialiserParcours, libelleIntention,
  surCommunePrete,
} from "./parcours.js";
import { ouvrirFiche } from "./fiche.js";
import { initialiserIdentification } from "./identifier.js";
import { auChangement, changerVue, brancherHistorique } from "./navigation.js";
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
    const attente = etat.en_attente === 0
      ? "aucun bien en attente"
      : `${etat.en_attente} bien(s) seraient signalés au prochain import`;

    // QUAND le message part. Sans cela, « je n'ai rien reçu aujourd'hui »
    // reste sans réponse : on ignore l'heure du passage, et même s'il a
    // lieu sur ce conteneur.
    const p = etat.planificateur || {};
    let quand;
    if (!p.actif) {
      quand = "Import automatique <strong>désactivé</strong> sur ce conteneur"
        + "&nbsp;: rien ne partira de soi-même.";
    } else {
      const jours = p.jours === "*" ? "chaque jour" : `les jours ${p.jours}`;
      const prochaine = p.prochaine
        ? ` — prochain passage le ${dateFr(p.prochaine)}`
        : "";
      quand = `Passage ${jours} à <strong>${p.heure}h00</strong>`
        + ` (${echapper(p.fuseau || "")})${echapper(prochaine)}.`;
    }

    // Les critères qui décident d'un envoi : plus étroits qu'on ne le
    // croit, et première explication d'un silence.
    const c = etat.criteres || {};
    const criteres = `Un message ne part que pour un bien <em>neuf</em> répondant
      aux critères&nbsp;: ${echapper(c.type_batiment || "tous types")},
      de ${entierFr.format(c.surface_min || 0)} à ${entierFr.format(c.surface_max || 0)}&nbsp;m²,
      diagnostiqué dans les ${entierFr.format(c.fenetre_jours || 0)} derniers jours.
      Sans nouveauté, rien ne part — c'est le cas la plupart des jours.`;

    // Le « quand » ne dépend pas du « comment » : l'horaire s'affiche même
    // sans serveur d'envoi, sans quoi une configuration incomplète cachait
    // l'information qu'on venait justement chercher.
    const envoi = etat.smtp_configure
      ? `<p>Envoi par <span class="donnee">${echapper(etat.smtp_hote)}</span>
         ${etat.smtp_authentifie ? "avec authentification" : "sans authentification"}
         · ${echapper(attente)}.</p>`
      : `<p class="message message-erreur">Aucun serveur d'envoi
         configuré&nbsp;: renseignez le serveur SMTP et l'adresse
         d'expédition ci-dessous. Rien ne peut partir tant que ce n'est
         pas fait.</p>`;

    boite.innerHTML = `${envoi}<p>${quand}</p><p>${criteres}</p>`;
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

/**
 * Le serveur d'envoi tel qu'il est saisi — ou rien, si on ne le saisit pas.
 *
 * Les champs ne sont remplis que lorsqu'on ouvre « Modifier ». Les lire
 * alors qu'ils dorment vides enverrait un brouillon vide, qui écraserait
 * la configuration enregistrée le temps du contrôle : celui-ci
 * annoncerait « serveur absent » pour une configuration parfaitement
 * valide en base.
 *
 * On ne renvoie donc un brouillon QUE si la zone est ouverte. Fermée,
 * c'est ce qui est enregistré qu'on éprouve — et c'est bien ce qu'on veut
 * savoir.
 */
function lireServeurAffiche() {
  const zone = document.querySelector("[data-reglage='envoi'] .reglage-edition");
  if (!zone || zone.hidden) return null;
  return {
    hote: $("#r-smtp-hote").value.trim(),
    port: Number($("#r-smtp-port").value) || 587,
    ssl: $("#r-smtp-ssl").value === "1",
    expediteur: $("#r-smtp-expediteur").value.trim(),
    utilisateur: $("#r-smtp-utilisateur").value.trim(),
    // Les puces veulent dire « celui déjà enregistré » : l'écran ne peut
    // pas relire le mot de passe, il ne peut donc pas le renvoyer.
    motdepasse: $("#r-smtp-motdepasse").value,
  };
}

const ETATS_ESSAI = {
  ok:        { marque: "✓", classe: "etape-ok" },
  echec:     { marque: "✕", classe: "etape-echec" },
  attention: { marque: "!", classe: "etape-attention" },
  ignoree:   { marque: "–", classe: "etape-ignoree" },
};

/**
 * Le compte rendu du contrôle, étape par étape.
 *
 * « Ça ne marche pas » ne se débogue pas : il faut savoir OÙ cela
 * s'arrête. La connexion a-t-elle abouti ? Le serveur a-t-il annoncé
 * STARTTLS ? L'authentification est-elle passée ? Chaque réponse écarte
 * une moitié des causes possibles.
 */
function dessinerEssai(resultat) {
  const etapes = (resultat.etapes || []).map((e) => {
    const etat = ETATS_ESSAI[e.etat] || ETATS_ESSAI.ignoree;
    return `
      <li class="etape ${etat.classe}">
        <span class="etape-marque" aria-hidden="true">${etat.marque}</span>
        <span class="etape-nom">${echapper(e.nom)}</span>
        <span class="etape-detail donnee">${echapper(e.detail || "")}</span>
        <span class="etape-duree donnee">${entierFr.format(e.ms)} ms</span>
      </li>`;
  }).join("");

  $("#essai-titre").textContent = resultat.envoye
    ? "Le message est parti" : "Le message n'est pas parti";

  $("#essai-corps").innerHTML = `
    <p class="${resultat.envoye ? "message message-succes" : "message message-erreur"}">
      ${resultat.envoye
        ? `Envoyé à <span class="donnee">${echapper(resultat.destinataire)}</span>.
           S'il n'arrive pas, regardez les indésirables&nbsp;: le serveur, lui,
           l'a accepté.`
        : echapper(resultat.message || "Échec sans message.")}
    </p>
    ${resultat.envoye && resultat.brouillon ? `
      <p class="explication piste">
        <strong>À faire&nbsp;:</strong> ce contrôle a éprouvé la
        configuration <em>affichée</em>, qui n'est pas encore enregistrée.
        Cliquez sur <strong>Enregistrer</strong> pour que l'alerte s'en
        serve.
      </p>` : ""}
    <ol class="etapes">${etapes}</ol>
    ${resultat.conseil
      ? `<p class="explication piste"><strong>Piste&nbsp;:</strong>
           ${echapper(resultat.conseil)}</p>`
      : ""}`;
}

/** Un message de contrôle, pour ne pas découvrir un mot de passe faux au
 *  premier bien manqué. */
async function envoyerEssaiAlerte() {
  const bouton = $("#essai-alerte");
  const libelle = bouton.textContent.trim();
  const dialogue = $("#dialogue-essai");
  masquerErreur();
  bouton.disabled = true;
  bouton.textContent = "Envoi…";
  $("#essai-titre").textContent = "Contrôle en cours…";
  $("#essai-corps").innerHTML =
    '<p class="message message-travail">Connexion au serveur d\'envoi…'
    + '<span class="jauge"><span></span></span></p>';
  if (!dialogue.open) dialogue.showModal();

  try {
    // Zone d'envoi ouverte : on éprouve ce qui est affiché, car remplir
    // les champs puis contrôler sans enregistrer est le geste naturel.
    // Zone fermée : rien à lire, on éprouve ce qui est enregistré.
    const brouillon = lireServeurAffiche();
    const destinataire = $("#r-alerte-destinataire").value.trim() || null;
    const resultat = await api.essaiAlerte(destinataire, brouillon);
    dessinerEssai({ ...resultat, brouillon: Boolean(brouillon) });
  } catch (erreur) {
    // Un échec d'envoi revient en 200 avec sa trace ; arriver ici veut
    // dire que l'application elle-même n'a pas répondu.
    $("#essai-titre").textContent = "Le contrôle n'a pas pu être lancé";
    $("#essai-corps").innerHTML =
      `<p class="message message-erreur">${echapper(erreur.message)}</p>`;
  } finally {
    bouton.disabled = false;
    bouton.textContent = libelle;
    chargerEtatAlerte();
  }
}


/** Version déployée, affichée en permanence dans le bandeau. */
// ---------------------------------------------------------------------
//  Historique des ventes : ce que la base garde au-delà de la source
// ---------------------------------------------------------------------

/** La profondeur d'historique conservée, et jusqu'où la source va. */
async function chargerProfondeurVentes() {
  const liste = $("#profondeur-ventes");
  if (!liste) return;
  try {
    // La commune vient du serveur, qui la lit dans les réglages : les
    // champs de l'écran sont masqués et vides tant qu'on n'a pas cliqué
    // sur « Modifier ».
    const p = await api.profondeurVentes();
    if (!p.ventes) {
      liste.innerHTML = "<dt>Ventes conservées</dt>"
        + "<dd>aucune — lancez d'abord un import</dd>";
      return;
    }
    // Ce que la base garde en plus de ce que la source sert encore : la
    // seule mesure qui dise si l'archive a servi à quelque chose.
    const plusAncien = Number(String(p.depuis).slice(0, 4));
    const premierServi = Math.min(...p.millesimes_source);
    const gagnees = p.par_annee
      .filter((a) => Number(a.annee) < premierServi)
      .reduce((total, a) => total + a.ventes, 0);

    // Sur quoi porte le bouton. Le département n'est jamais choisi : il
    // vient des deux premiers chiffres du code INSEE de la commune
    // surveillée. Sans l'écrire, on déclenche 34 Mo de téléchargement
    // sans savoir lequel.
    const porte = p.commune
      ? `${p.commune_nom || "commune"} (${p.commune})`
        + ` — archive du département ${p.departement}`
      : "aucune commune surveillée";

    liste.innerHTML = [
      ["Commune surveillée", porte],
      ["Ventes conservées", entierFr.format(p.ventes)],
      ["Historique", `du ${p.depuis} au ${p.jusqu_a}`],
      ["Millésimes servis par la source", p.millesimes_source.join(", ")],
      ["Conservées au-delà de la source", gagnees
        ? `${entierFr.format(gagnees)} vente(s), depuis ${plusAncien}`
        : "aucune pour l'instant"],
    ].map(([cle, valeur]) => `<dt>${cle}</dt><dd>${echapper(valeur)}</dd>`).join("");
  } catch (erreur) {
    liste.innerHTML = "<dt>Ventes conservées</dt><dd>indisponible</dd>";
  }
}

/** Montre le champ qu'appelle la portée choisie, et l'avertissement. */
function ajusterPorteeArchive() {
  const portee = $("#archive-portee").value;
  $("#archive-champ-commune").hidden = portee !== "commune";
  $("#archive-champ-departement").hidden = portee !== "departement";
  // Un département entier change la taille de la base : le dire avant,
  // pas après.
  $("#archive-avertissement").hidden = portee !== "departement";

  // Le résumé au-dessus dit ce que la base CONTIENT ; cette ligne dit ce
  // que le bouton VA FAIRE. Les confondre laissait croire que la reprise
  // porterait sur la commune surveillée même après avoir choisi un
  // département.
  const annonce = {
    surveillee: "Reprendra la commune surveillée, ci-dessus.",
    commune: "Reprendra la commune indiquée, quelle qu'elle soit.",
    departement: "Reprendra <strong>toutes</strong> les communes du "
                 + "département indiqué.",
  }[portee];
  $("#archive-etat").innerHTML = `<p class="message">${annonce}</p>`;
}

/** Ce que l'écran demande : rien, une commune, ou un département. */
async function cibleArchive() {
  const portee = $("#archive-portee").value;
  if (portee === "departement") {
    const dep = $("#archive-departement").value.trim();
    return dep ? { dep } : { erreur: "Indiquez un numéro de département." };
  }
  if (portee !== "commune") return {};

  const saisie = $("#archive-commune").value.trim();
  if (!saisie) return { erreur: "Indiquez une commune." };

  // Le champ accepte le code, ou le nom seul. Le datalist propose
  // « Mimizan (40184) » ; si le code est là, il tranche.
  const code = (saisie.match(/\b(\d{5})\b/) || [])[1];
  if (code) return { code_insee: code };

  // Sinon on résout le nom : exiger un choix dans la liste alors que le
  // nom suffit à trancher serait une contrainte gratuite.
  try {
    const reponse = await api.chercherCommunes(saisie);
    const trouvees = reponse.communes || [];
    if (trouvees.length === 1) return { code_insee: trouvees[0].code_insee };
    if (trouvees.length === 0) {
      return { erreur: `Aucune commune ne correspond à « ${saisie} ».` };
    }
    return { erreur: `Plusieurs communes correspondent à « ${saisie} » : `
                     + trouvees.slice(0, 4).map((c) => `${c.nom} (${c.code_insee})`)
                         .join(", ") + ". Précisez." };
  } catch (erreur) {
    return { erreur: "Recherche de commune indisponible — saisissez le "
                     + "code INSEE à cinq chiffres." };
  }
}

async function proposerCommunesArchive() {
  const saisie = $("#archive-commune").value.trim();
  if (saisie.length < 2) return;
  try {
    const reponse = await api.chercherCommunes(saisie);
    $("#archive-communes").innerHTML = (reponse.communes || [])
      .map((c) => `<option value="${echapper(c.nom)} (${c.code_insee})"></option>`)
      .join("");
  } catch (_) { /* la saisie directe du code reste possible */ }
}

async function reprendreArchiveVentes() {
  const bouton = $("#reprendre-archive");
  const etat = $("#archive-etat");
  const cible = await cibleArchive();
  if (cible.erreur) {
    etat.innerHTML = `<p class="message message-erreur">${echapper(cible.erreur)}</p>`;
    return;
  }
  bouton.disabled = true;
  const libelle = bouton.textContent;
  bouton.textContent = "Reprise…";
  etat.innerHTML = '<p class="message message-travail">Lecture de l\'archive '
    + 'départementale — 34 Mo, quelques dizaines de secondes.'
    + (cible.dep ? ' Tout le département : comptez une minute de plus.' : '')
    + '<span class="jauge"><span></span></span></p>';
  try {
    const r = await api.reprendreArchive(cible);
    etat.innerHTML = `<p class="message message-succes">${r.message}</p>`;
    await chargerProfondeurVentes();
  } catch (erreur) {
    etat.innerHTML =
      `<p class="message message-erreur">${erreur.message || erreur}</p>`;
  } finally {
    bouton.disabled = false;
    bouton.textContent = libelle;
  }
}

// ---------------------------------------------------------------------
//  Sauvegardes
// ---------------------------------------------------------------------

function poids(octets) {
  if (!octets) return "0 Mo";
  return `${(octets / 1e6).toFixed(1)} Mo`;
}

async function chargerEtatSauvegardes() {
  const liste = $("#etat-sauvegardes");
  if (!liste) return;
  try {
    const e = await api.etatSauvegardes();
    const rangs = e.copies
      ? [["Dernière", `${dateFr(e.derniere)} · il y a ${e.age_heures} h`],
         ["Copies conservées", `${e.copies} — depuis ${dateFr(e.depuis)}`],
         ["Place occupée", poids(e.octets)],
         ["Dossier", e.dossier]]
      : [["Copies conservées", "aucune pour l'instant"],
         ["Dossier", e.dossier]];
    liste.innerHTML = rangs
      .map(([cle, valeur]) => `<dt>${cle}</dt><dd>${echapper(valeur)}</dd>`)
      .join("");
    // L'alerte se voit ici plutôt qu'au moment de restaurer.
    $("#sauvegarde-etat").innerHTML = e.alerte
      ? `<p class="message message-erreur">${echapper(e.alerte)}</p>` : "";
  } catch (_) {
    liste.innerHTML = "<dt>Sauvegardes</dt><dd>indisponible</dd>";
  }
}

async function sauvegarderMaintenant() {
  const bouton = $("#sauvegarder-maintenant");
  const etat = $("#sauvegarde-etat");
  bouton.disabled = true;
  const libelle = bouton.textContent;
  bouton.textContent = "Copie…";
  etat.innerHTML = '<p class="message message-travail">Copie et vérification…'
    + '<span class="jauge"><span></span></span></p>';
  try {
    const r = await api.sauvegarderMaintenant();
    etat.innerHTML = `<p class="message message-succes">`
      + `${echapper(r.fichier)} — ${poids(r.octets)}, vérifiée`
      + (r.retirees.length ? ` · ${r.retirees.length} ancienne(s) retirée(s)` : "")
      + `</p>`;
    await chargerEtatSauvegardes();
  } catch (erreur) {
    etat.innerHTML =
      `<p class="message message-erreur">${echapper(erreur.message || String(erreur))}</p>`;
  } finally {
    bouton.disabled = false;
    bouton.textContent = libelle;
  }
}

// ---------------------------------------------------------------------
//  Journal des passages de l'alerte
// ---------------------------------------------------------------------

// Ce que chaque raison veut dire, en clair. Le code interne ne se lit pas,
// et c'est justement cette ligne qu'on vient chercher.
const RAISONS = {
  envoyee: ["succes", "Message envoyé"],
  rien_de_neuf: ["neutre", "Rien de neuf — aucun bien ne répondait aux critères"],
  desactivee: ["attention", "Alerte désactivée dans les réglages"],
  ventes_desactivees: ["attention", "Alerte sur les ventes désactivée"],
  sans_destinataire: ["attention", "Aucun destinataire enregistré"],
  echec_envoi: ["erreur", "Envoi refusé par le serveur"],
};

async function chargerJournalAlerte() {
  const boite = $("#journal-alerte");
  if (!boite) return;
  try {
    const { tentatives } = await api.journalAlerte();
    if (!tentatives.length) {
      boite.innerHTML = `<p class="message">Aucun passage enregistré pour
        l'instant. Le premier aura lieu au prochain import automatique.</p>`;
      return;
    }
    boite.innerHTML = `<table class="tableau-journal">
      <tr><th>Quand</th><th>Sujet</th><th>Résultat</th></tr>
      ${tentatives.map((t) => {
        const [etat, libelle] = RAISONS[t.raison] || ["neutre", t.raison];
        const detail = t.envoye && t.biens
          ? ` — ${entierFr.format(t.biens)} bien(s)`
          : (t.message ? ` — ${echapper(t.message)}` : "");
        return `<tr>
          <td style="white-space:nowrap">${echapper(dateFr(t.quand))}</td>
          <td>${t.sujet === "ventes" ? "ventes" : "DPE"}</td>
          <td class="etat-${etat}">${echapper(libelle)}${detail}</td>
        </tr>`;
      }).join("")}
    </table>`;
  } catch (erreur) {
    boite.innerHTML = `<p class="message">Journal des alertes indisponible.</p>`;
  }
}

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


// Les jours d'un cron, en francais. `*` veut dire tous les jours ; sinon
// APScheduler accepte « mon », « mon-fri », « 0 », « mon,thu »…
const JOURS_FR = {
  mon: "lundi", tue: "mardi", wed: "mercredi", thu: "jeudi",
  fri: "vendredi", sat: "samedi", sun: "dimanche",
  0: "lundi", 1: "mardi", 2: "mercredi", 3: "jeudi",
  4: "vendredi", 5: "samedi", 6: "dimanche",
};

/** « chaque jour », « chaque lundi », « du lundi au vendredi »… */
function rythmeImport(jours) {
  const brut = String(jours ?? "*").trim().toLowerCase();
  if (!brut || brut === "*") return "chaque jour";
  const intervalle = brut.match(/^([a-z0-9]+)-([a-z0-9]+)$/);
  if (intervalle && JOURS_FR[intervalle[1]] && JOURS_FR[intervalle[2]]) {
    return `du ${JOURS_FR[intervalle[1]]} au ${JOURS_FR[intervalle[2]]}`;
  }
  const listes = brut.split(",").map((j) => JOURS_FR[j.trim()]).filter(Boolean);
  if (listes.length === 1) return `chaque ${listes[0]}`;
  if (listes.length > 1) return `les ${listes.join(", ")}`;
  return `selon la règle « ${brut} »`;
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

    // Le rythme vient du serveur : l'écran annonçait « hebdomadaire »
    // quelle que soit la configuration. C'est justement cette ligne
    // qu'on vient lire quand aucun courriel n'est arrivé.
    $("#prochain-import").innerHTML = sante.prochain_import
      ? `Import automatique <span class="donnee">${echapper(
           rythmeImport(sante.import_jours))} à ${echapper(
           String(sante.import_heure ?? "?"))}h00</span>
         (${echapper(sante.import_fuseau || "")}). Prochaine exécution :
         <span class="donnee">${dateFr(sante.prochain_import)}
         à ${echapper(sante.prochain_import.slice(11, 16))}</span>.
         <span class="detail">Les alertes par courriel ne partent qu'à ce
         passage&nbsp;: consulter une commune rafraîchit la base, mais
         n'envoie rien.</span>`
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
  // Un clic sur un repère ouvre la fiche du bien, comme sur la carte
  // d'exploration : c'est là qu'on allait de toute façon. Le sens inverse
  // — cliquer une ligne pour la situer sur la carte — reste inchangé.
  etat.carte = creerCarte("carte", (numero) =>
    ouvrirFiche({ n_dpe: numero, retour: "veille" }));
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
  $("#essai-alerte").addEventListener("click", envoyerEssaiAlerte);
  $("#essai-fermer").addEventListener("click", () => $("#dialogue-essai").close());
  $("#essai-relancer").addEventListener("click", envoyerEssaiAlerte);
  $("#r-alerte-commune").addEventListener("change", () => peuplerZones(""));

  // Ce qu'il faut rafraîchir quand un écran redevient visible.
  // Quand une moisson aboutit, l'écran se remet à jour tout seul.
  // Une moisson qui aboutit change ce qu'il y a à montrer.
  auTermeDeLImport(() => { chargerContexte(); charger(); });

  // Le parcours nous prévient quand une commune est choisie et prête.
  surCommunePrete(() => { chargerContexte(); charger(); });

  auChangement("reglages", () => {
    rafraichirReglages().catch(() => {});
    chargerEtatAlerte();
    chargerJournal();
  });
  auChangement("veille", () => { if (etat.carte) etat.carte.redimensionner(); });

  initialiserIdentification();

  // Les filtres par défaut viennent des réglages : on les demande une fois,
  // puis on charge la liste avec.
  try {
    const reponse = await api.veille({});
    appliquerFiltres(reponse.filtres);
  } catch (_) { /* charger() affichera l'erreur */ }

  await rafraichirReglages().catch(() => {});
  afficherVersion();

  // Le parcours prend la main : accueil, puis commune, puis résultats.
  initialiserExploration();
  // Les réglages se rechargent après un enregistrement : les filtres
  // par défaut et l'état de l'alerte en dépendent.
  initialiserReglages(() => {
    chargerEtatAlerte(); chargerJournal(); chargerProfondeurVentes();
    chargerJournalAlerte();
  });
  chargerProfondeurVentes();
  chargerJournalAlerte();
  chargerEtatSauvegardes();
  $("#reprendre-archive")?.addEventListener("click", reprendreArchiveVentes);
  $("#archive-portee")?.addEventListener("change", ajusterPorteeArchive);
  $("#archive-commune")?.addEventListener("input", proposerCommunesArchive);
  ajusterPorteeArchive();
  $("#sauvegarder-maintenant")?.addEventListener("click", sauvegarderMaintenant);
  initialiserParcours();
  brancherHistorique();
  await reprendreSuiviEventuel();
}

demarrer();
