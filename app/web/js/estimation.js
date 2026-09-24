// ====================================================================
//  estimation.js — Estimer la valeur d'un bien, et garder ses estimations.
//
//  On y entre depuis une fiche — celle d'un diagnostic ou d'une parcelle,
//  donc depuis n'importe quel point de la carte — avec ce que la base sait
//  déjà du bien. L'utilisateur corrige, précise l'état du bâti, et obtient
//  une valeur, une fourchette et SURTOUT de quoi juger : chaque méthode,
//  son erreur mesurée dans le département, les ventes comparables.
//
//  Rien ne part vers une source tant qu'on n'a pas appuyé sur un bouton
//  (CDC 4) : ouvrir l'écran ne lit que la base du NAS.
// ====================================================================

import { api } from "./api.js";
import {
  $, afficherErreur, afficherSucces, dateFr, echapper, entierFr, euroFr,
  masquerErreur, nombreFr,
} from "./format.js";
import { auChangement, auRetourArriere, changerVue } from "./navigation.js";

const ecran = {
  bien: null,            // ce qu'on estime, tel que pré-rempli puis corrigé
  saisie: null,          // état, travaux, ajustement
  departement: null,     // ventes chargées, modèle appris, précision
  etats: [],             // l'échelle d'état du bâti
  resultat: null,        // la dernière estimation
  enregistree: null,     // l'identifiant, si elle a été gardée
  retour: "carte",
};

const NOMS_DEPARTEMENT_TYPE = { maison: "maisons", appartement: "appartements" };

// Ce que fait chaque méthode, en une ligne : on ne se fie pas à un chiffre
// dont on ignore d'où il vient.
const PRINCIPES = {
  comparables: "les 12 ventes du même type les plus proches, prix au m² actualisé",
  hedonique: "régression sur les ventes du département : surface, terrain, pièces, commune",
  sol_construction: "terrains à bâtir voisins + bâti à neuf moins son usure, calé sur le marché",
  boosting: "des centaines d'arbres de décision appris sur le département, nourris des prix voisins",
};

const LIBELLES_ETATS = {
  bon: "bon", assez_bon: "assez bon", passable: "passable", mediocre: "médiocre",
  mauvais: "mauvais", travaux: "travaux chiffrés",
};
const pourcent = new Intl.NumberFormat("fr-FR", { style: "percent", maximumFractionDigits: 1 });
const pourcentEntier = new Intl.NumberFormat("fr-FR", { style: "percent", maximumFractionDigits: 0 });
const coefficient = new Intl.NumberFormat("fr-FR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

/**
 * Une valeur estimée se lit au millier d'euros près : afficher 346 440 €
 * prêterait au calcul une précision qu'il n'a pas — il se trompe
 * couramment de 10 à 20 %.
 */
function arrondi(valeur) {
  if (valeur == null) return null;
  const pas = valeur >= 100000 ? 1000 : 500;
  return Math.round(valeur / pas) * pas;
}

const euros = (valeur) => (valeur == null ? "—" : euroFr.format(arrondi(valeur)));

// --------------------------------------------------------------------
//  Entrées
// --------------------------------------------------------------------

/** Ouvre l'estimation d'un bien, depuis sa fiche. */
export async function ouvrirEstimation({ n_dpe = null, parcelle_id = null,
                                         retour = null, sansHistorique = false } = {}) {
  masquerErreur();
  ecran.retour = retour || ecran.retour || "carte";
  if (!sansHistorique) changerVue("estimation", { n_dpe, parcelle_id, retour: ecran.retour });
  $("#estimation-contenu").innerHTML =
    '<p class="message message-travail">Lecture de ce que l\'on sait du bien…</p>';

  let reponse;
  try {
    reponse = await api.bienAEstimer({ n_dpe, parcelle_id });
  } catch (erreur) {
    $("#estimation-contenu").innerHTML = "";
    afficherErreur("Impossible de préparer l'estimation.", erreur.message);
    return;
  }
  Object.assign(ecran, {
    bien: reponse.bien, departement: reponse.departement, etats: reponse.etats,
    saisie: { etat: "assez_bon", travaux: 0, ajustement: 0, raison: "" },
    resultat: null, enregistree: null,
  });
  dessiner();
}

/** Rouvre une estimation enregistrée : ce qui avait été saisi, et le résultat d'alors. */
export async function ouvrirEstimationEnregistree(ident, { sansHistorique = false } = {}) {
  masquerErreur();
  ecran.retour = "estimations";
  if (!sansHistorique) changerVue("estimation", { estimation: ident, retour: "estimations" });
  $("#estimation-contenu").innerHTML =
    '<p class="message message-travail">Lecture de l\'estimation…</p>';

  let gardee;
  let etats;
  try {
    [gardee, etats] = await Promise.all([api.estimationEnregistree(ident), api.etatsDuBati()]);
  } catch (erreur) {
    $("#estimation-contenu").innerHTML = "";
    afficherErreur("Impossible de rouvrir cette estimation.", erreur.message);
    return;
  }
  const resultat = gardee.resultat;
  let departement = null;
  try {
    departement = await api.etatDepartement(resultat.departement);
  } catch (_) { /* l'écran se contente du résultat gardé */ }
  Object.assign(ecran, {
    bien: { ...resultat.bien, adresse: gardee.adresse, commune: gardee.commune,
            n_dpe: gardee.n_dpe, parcelle_id: gardee.parcelle_id,
            pieces: resultat.bien.pieces_estimees ? null : resultat.bien.pieces,
            terrain_m2: resultat.bien.terrain_estime ? null : resultat.bien.terrain_m2 },
    saisie: { etat: "assez_bon", travaux: 0, ajustement: 0, raison: "", ...gardee.saisie },
    departement, etats: etats.etats, resultat, enregistree: gardee,
  });
  dessiner();
}

// --------------------------------------------------------------------
//  L'écran
// --------------------------------------------------------------------

function titreDuBien(bien) {
  if (bien.adresse) return bien.adresse;
  if (bien.parcelle_id) return `Parcelle ${bien.parcelle_id.slice(-6)}`;
  return "Bien sans adresse";
}

function dessiner() {
  const bien = ecran.bien;
  const gardee = ecran.enregistree;
  $("#estimation-contenu").innerHTML = `
    <div class="fiche-barre">
      <button type="button" class="bouton bouton-retour" id="estimation-retour">← Retour</button>
    </div>
    <header class="estimation-tete">
      <p class="surtitre">${gardee
        ? `Estimation enregistrée le ${dateFr(gardee.cree_le)}` : "Estimer ce bien"}</p>
      <h1>${echapper(titreDuBien(bien))}</h1>
      <p class="explication">
        ${echapper(bien.commune || "")}
        ${bien.parcelle_id ? ` · parcelle <span class="donnee">${echapper(bien.parcelle_id)}</span>` : ""}
        ${bien.sources?.length ? ` · pré-rempli d'après ${echapper(libelleSources(bien.sources))}` : ""}
      </p>
    </header>
    <div id="estimation-departement">${blocDepartement()}</div>
    ${formulaire()}
    <div id="estimation-resultat">${ecran.resultat ? blocResultat(ecran.resultat) : ""}</div>`;

  $("#estimation-retour").addEventListener("click", revenir);
  brancherDepartement();
  brancherFormulaire();
  brancherResultat();
}

function libelleSources(sources) {
  const noms = { diagnostic: "le diagnostic", vente: "la dernière vente", parcelle: "le cadastre" };
  return sources.map((s) => noms[s] || s).join(", ");
}

function revenir() {
  if (history.state && history.state.vue === "estimation") history.back();
  else changerVue(ecran.retour || "carte");
}

// --------------------------------------------------------------------
//  Le département : prêt, ou à préparer
// --------------------------------------------------------------------

function blocDepartement() {
  const dep = ecran.departement;
  if (!dep) {
    return `<p class="message message-erreur">Commune du bien inconnue : l'estimation
      ne peut pas trouver ses ventes de référence.</p>`;
  }
  if (dep.indisponible) {
    return `<p class="message message-erreur">${echapper(dep.indisponible)}
      Aucune estimation n'est possible ici.</p>`;
  }
  if (!dep.pret) {
    return `
      <div class="estimation-preparer">
        <h2>Première estimation dans ce département</h2>
        <p class="explication">
          L'estimation apprend sur les ventes de tout le département
          ${echapper(dep.departement)}&nbsp;: cinq ans de ventes DVF (un fichier
          public par an, de 1 à 14&nbsp;Mo), dont elle tire ses références, puis
          elle mesure sa propre précision sur la dernière année. Comptez une à
          deux minutes, une seule fois&nbsp;: ensuite tout se calcule sur le NAS,
          et les ventes se mettent à jour d'elles-mêmes à chaque parution.
        </p>
        <p><button type="button" class="bouton bouton-principal" id="preparer-departement">
          Charger les ventes du département
        </button></p>
        <p class="message message-travail" id="preparation-etat" hidden></p>
      </div>`;
  }
  const precision = Object.entries(dep.precision || {}).map(([type, p]) =>
    `${NOMS_DEPARTEMENT_TYPE[type] || type} ${nombreFr.format(p.erreur_mediane)}&nbsp;%`).join(", ");
  return `
    <p class="explication estimation-modele">
      Références&nbsp;: ${entierFr.format(dep.ventes || 0)} ventes du département
      ${echapper(dep.departement)}, du ${dateFr(dep.periode?.[0])} au ${dateFr(dep.periode?.[1])}
      · erreur médiane mesurée sur la dernière année&nbsp;: ${precision || "—"}.
    </p>`;
}

function brancherDepartement() {
  const bouton = $("#preparer-departement");
  if (!bouton) return;
  bouton.addEventListener("click", async () => {
    bouton.disabled = true;
    masquerErreur();
    try {
      await api.preparerDepartement(ecran.departement.departement);
    } catch (erreur) {
      // 409 : une préparation tourne déjà — on la suit plutôt que d'échouer.
      if (!/déjà|deja/i.test(erreur.message)) {
        bouton.disabled = false;
        afficherErreur("La préparation n'a pas pu démarrer.", erreur.message);
        return;
      }
    }
    suivrePreparation();
  });
}

async function suivrePreparation() {
  const boite = $("#preparation-etat");
  let etat;
  try {
    etat = await api.etatPreparation();
  } catch (erreur) {
    setTimeout(suivrePreparation, 3000);
    return;
  }
  if (boite) {
    boite.hidden = false;
    boite.innerHTML = `${echapper(etat.etape || "préparation")}…<span class="jauge"><span></span></span>`;
  }
  if (etat.en_cours) {
    setTimeout(suivrePreparation, 1500);
    return;
  }
  if (etat.erreur) {
    if (boite) boite.hidden = true;
    const bouton = $("#preparer-departement");
    if (bouton) bouton.disabled = false;
    afficherErreur("Les ventes du département n'ont pas pu être chargées.", etat.erreur);
    return;
  }
  try {
    ecran.departement = await api.etatDepartement(ecran.departement.departement);
  } catch (erreur) {
    afficherErreur("Préparation terminée, mais son état n'a pas pu être relu.", erreur.message);
    return;
  }
  if (ecran.departement.pret) afficherSucces("Département prêt : vous pouvez estimer.");
  // On garde ce qui a déjà été saisi dans le formulaire.
  lireFormulaire();
  dessiner();
}

// --------------------------------------------------------------------
//  Le formulaire
// --------------------------------------------------------------------

function champNombre(id, libelle, valeur, { min = 0, max = null, pas = 1, aide = "", unite = "" } = {}) {
  return `
    <div class="champ">
      <label for="${id}">${libelle}${unite ? ` (${unite})` : ""}</label>
      <input type="number" id="${id}" inputmode="decimal" min="${min}"
             ${max != null ? `max="${max}"` : ""} step="${pas}"
             value="${valeur != null && valeur !== "" ? echapper(String(valeur)) : ""}">
      ${aide ? `<p class="aide">${aide}</p>` : ""}
    </div>`;
}

function formulaire() {
  const b = ecran.bien;
  const s = ecran.saisie;
  const pret = ecran.departement?.pret;
  const etats = ecran.etats.map((e) => `
    <label class="etat-choix">
      <input type="radio" name="etat" value="${e.cle}" ${s.etat === e.cle ? "checked" : ""}>
      <span class="etat-libelle">${echapper(e.libelle)}</span>
      <span class="etat-effet donnee">${e.effet > 0 ? "+" : ""}${e.effet}&nbsp;%</span>
    </label>`).join("");

  return `
    <form class="estimation-formulaire" id="estimation-formulaire" novalidate>
      <section>
        <h2>Le bien</h2>
        <div class="types-bien" role="radiogroup" aria-label="Type de bien">
          ${["maison", "appartement"].map((type) => `
            <label class="type-choix">
              <input type="radio" name="type" value="${type}" ${b.type === type ? "checked" : ""}>
              <span>${type === "maison" ? "Maison" : "Appartement"}</span>
            </label>`).join("")}
        </div>
        <div class="grille-champs">
          ${champNombre("e-surface", "Surface habitable", b.surface, { min: 9, unite: "m²" })}
          ${champNombre("e-pieces", "Pièces principales", b.pieces, { min: 1, max: 30,
            aide: "Si vous ne le savez pas, laissez vide." })}
          <div id="e-bloc-terrain">
            ${champNombre("e-terrain", "Terrain", b.terrain_m2 != null ? Math.round(b.terrain_m2) : null,
              { unite: "m²", aide: "Le terrain vendu avec la maison." })}
          </div>
          ${champNombre("e-annee", "Année de construction", b.annee_construction,
            { min: 1500, max: 2100, aide: "Sert à la vétusté du bâti." })}
        </div>
        <div class="cases-bien">
          <div class="champ case">
            <input type="checkbox" id="e-dependance" ${b.dependances ? "checked" : ""}>
            <label for="e-dependance">Garage ou dépendance vendu avec</label>
          </div>
          <div class="champ case">
            <input type="checkbox" id="e-neuf" ${b.neuf ? "checked" : ""}>
            <label for="e-neuf">Neuf (vente en l'état futur d'achèvement)</label>
          </div>
        </div>
        ${b.etiquette_dpe ? `<p class="aide">Classe énergie ${echapper(b.etiquette_dpe)} :
          elle n'entre pas dans le calcul. Mesuré sur 833 maisons du Born, le DPE
          n'améliore pas la précision — son effet est déjà dans l'âge et le secteur.</p>` : ""}
      </section>

      <section>
        <h2>L'état du bâti</h2>
        <p class="explication">
          Ce que rien, dans les données publiques, ne mesure — et la première
          source d'erreur d'une estimation. L'échelle est celle du coefficient
          d'entretien de l'administration fiscale&nbsp;; l'estimation
          représente un bien en état d'usage courant («&nbsp;assez bon&nbsp;»).
        </p>
        <fieldset class="etats" id="e-etats" ${s.travaux > 0 ? "disabled" : ""}>
          <legend class="visuellement-cache">État du bâti</legend>
          ${etats}
        </fieldset>
        <div class="grille-champs">
          <div class="champ">
            <label for="e-travaux">Ou bien&nbsp;: travaux à prévoir (€)</label>
            <input type="number" id="e-travaux" inputmode="decimal" min="0" step="1000"
                   value="${s.travaux ? echapper(String(s.travaux)) : ""}">
            <p class="aide">Si vous les avez chiffrés&nbsp;: leur coût est retranché d'un
              bien en état d'usage courant, et l'état ci-dessus ne s'applique plus.</p>
          </div>
        </div>
      </section>

      <section>
        <h2>Votre appréciation</h2>
        <p class="explication">
          Une vue, une piscine, une nuisance&nbsp;: ce que vous savez et que les
          données ignorent. L'ajustement est borné à 30&nbsp;% et reste affiché
          à part, avec sa raison.
        </p>
        <div class="grille-champs">
          ${champNombre("e-ajustement", "Ajustement", s.ajustement || null,
            { min: -30, max: 30, pas: 1, unite: "%" })}
          <div class="champ">
            <label for="e-raison">Raison</label>
            <input type="text" id="e-raison" maxlength="120" value="${echapper(s.raison || "")}"
                   placeholder="vue sur le lac, piscine…">
          </div>
        </div>
      </section>

      <p class="estimation-actions">
        <button type="submit" class="bouton bouton-principal" id="estimer" ${pret ? "" : "disabled"}>
          Estimer
        </button>
        ${pret ? "" : '<span class="aide">Chargez d\'abord les ventes du département.</span>'}
      </p>
    </form>`;
}

function valeurNombre(id) {
  const champ = $(`#${id}`);
  if (!champ || champ.value === "") return null;
  const nombre = Number(champ.value.replace(",", "."));
  return Number.isFinite(nombre) ? nombre : null;
}

/** Relit le formulaire dans `ecran` — pour estimer, ou pour le redessiner sans rien perdre. */
function lireFormulaire() {
  const formulaire = $("#estimation-formulaire");
  if (!formulaire) return;
  const type = formulaire.querySelector('input[name="type"]:checked')?.value || null;
  const etat = formulaire.querySelector('input[name="etat"]:checked')?.value || "assez_bon";
  Object.assign(ecran.bien, {
    type,
    surface: valeurNombre("e-surface"),
    pieces: valeurNombre("e-pieces"),
    terrain_m2: type === "maison" ? valeurNombre("e-terrain") : null,
    annee_construction: valeurNombre("e-annee"),
    dependances: $("#e-dependance").checked ? 1 : 0,
    neuf: $("#e-neuf").checked,
  });
  ecran.saisie = {
    etat,
    travaux: valeurNombre("e-travaux") || 0,
    ajustement: valeurNombre("e-ajustement") || 0,
    raison: $("#e-raison").value.trim(),
  };
}

function ajusterFormulaire() {
  const type = $("#estimation-formulaire")?.querySelector('input[name="type"]:checked')?.value;
  // Le terrain d'un appartement est celui de la copropriété : il ne dit rien du lot.
  $("#e-bloc-terrain").hidden = type === "appartement";
  $("#e-etats").disabled = (valeurNombre("e-travaux") || 0) > 0;
}

function brancherFormulaire() {
  const formulaire = $("#estimation-formulaire");
  formulaire.addEventListener("change", ajusterFormulaire);
  $("#e-travaux").addEventListener("input", ajusterFormulaire);
  formulaire.addEventListener("submit", (evenement) => {
    evenement.preventDefault();
    estimer(false);
  });
  ajusterFormulaire();
}

function corpsDeLaDemande(enregistrer) {
  const b = ecran.bien;
  return {
    bien: {
      type: b.type, surface: b.surface, pieces: b.pieces, terrain_m2: b.terrain_m2,
      annee_construction: b.annee_construction, dependances: b.dependances, neuf: b.neuf,
      latitude: b.latitude, longitude: b.longitude, code_insee: b.code_insee,
      parcelle_id: b.parcelle_id, n_dpe: b.n_dpe, adresse: b.adresse,
    },
    saisie: ecran.saisie,
    enregistrer,
  };
}

async function estimer(enregistrer) {
  masquerErreur();
  if (!enregistrer) lireFormulaire();
  const b = ecran.bien;
  if (!b.type) {
    afficherErreur("Indiquez s'il s'agit d'une maison ou d'un appartement.");
    return;
  }
  if (!b.surface || b.surface < 9) {
    afficherErreur("Indiquez la surface habitable (9 m² au moins).");
    return;
  }
  const bouton = enregistrer ? $("#enregistrer-estimation") : $("#estimer");
  if (bouton) bouton.disabled = true;
  if (!enregistrer) {
    $("#estimation-resultat").innerHTML =
      '<p class="message message-travail">Calcul en cours…<span class="jauge"><span></span></span></p>';
  }
  let resultat;
  try {
    resultat = await api.estimer(corpsDeLaDemande(enregistrer));
  } catch (erreur) {
    if (bouton) bouton.disabled = false;
    if (!enregistrer) $("#estimation-resultat").innerHTML = "";
    afficherErreur(enregistrer ? "L'estimation n'a pas pu être enregistrée."
                               : "L'estimation n'a pas abouti.", erreur.message);
    return;
  }
  ecran.resultat = resultat;
  if (enregistrer) {
    ecran.enregistree = { id: resultat.id, cree_le: new Date().toISOString() };
    afficherSucces("Estimation enregistrée : elle sera comparée au prix réel si la vente paraît.");
  } else {
    ecran.enregistree = null;
  }
  if (bouton) bouton.disabled = false;
  $("#estimation-resultat").innerHTML = blocResultat(resultat);
  brancherResultat();
  if (!enregistrer) {
    $("#estimation-resultat").scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

// --------------------------------------------------------------------
//  Le résultat
// --------------------------------------------------------------------

function blocResultat(r) {
  return `
    ${blocVerdict(r)}
    ${blocConstruction(r)}
    ${blocDecomposition(r)}
    ${blocRendement(r)}
    ${blocComparables(r)}
    ${blocPrecision(r)}
    <section>
      <h2>Ce que l'estimation ne sait pas</h2>
      <ul class="explication liste-lecture">
        ${r.ne_sait_pas.map((phrase) => `<li>${echapper(phrase)}</li>`).join("")}
      </ul>
    </section>`;
}

function blocVerdict(r) {
  const niveau = r.fiabilite?.niveau || "faible";
  const gardee = ecran.enregistree;
  return `
    <section class="estimation-verdict">
      <p class="surtitre">Valeur estimée${r.projection
        ? ` — marché du ${libelleTrimestre(r.projection.jusqu_a)}` : ""}</p>
      <p class="estimation-valeur donnee">${euros(r.valeur)}</p>
      <p class="estimation-fourchette">
        8 chances sur 10 entre <strong class="donnee">${euros(r.bas)}</strong>
        et <strong class="donnee">${euros(r.haut)}</strong>
      </p>
      <p><span class="fiabilite fiabilite-${echapper(niveau)}">Fiabilité ${echapper(niveau)}</span></p>
      <ul class="explication liste-raisons">
        ${(r.fiabilite?.raisons || []).map((raison) => `<li>${echapper(raison)}</li>`).join("")}
      </ul>
      <p class="estimation-actions">
        ${gardee?.id
          ? `<span class="pastille">enregistrée</span>`
          : `<button type="button" class="bouton" id="enregistrer-estimation">
               Enregistrer cette estimation</button>`}
      </p>
    </section>`;
}

function libelleTrimestre(code) {
  const [annee, t] = String(code || "").split("-Q");
  if (!t) return code || "";
  return `${t === "1" ? "1er" : `${t}e`} trimestre ${annee}`;
}

function ligne(libelle, valeur, detail = "", classe = "") {
  return `<tr class="${classe}"><th scope="row">${libelle}</th>
    <td class="donnee">${valeur}</td><td class="detail">${detail}</td></tr>`;
}

function blocConstruction(r) {
  const lignes = [];
  for (const m of r.methodes) {
    lignes.push(ligne(`${echapper(m.libelle)}<span class="methode-principe">${
      echapper(PRINCIPES[m.cle] || "")}</span>`, euros(m.valeur),
      m.erreur_mediane != null
        ? `erreur médiane mesurée&nbsp;: ${nombreFr.format(m.erreur_mediane)}&nbsp;%` : ""));
  }
  lignes.push(ligne("Croisement des méthodes", euros(r.croisement),
    "moyenne géométrique : chaque méthode se trompe différemment, leurs erreurs se compensent en partie",
    "ligne-somme"));
  if (r.historique) {
    const h = r.historique;
    const memeBien = r.bien.type === "maison" ? "Ce bien a été vendu"
      : "Un appartement de même surface, sur la même parcelle, a été vendu";
    lignes.push(ligne("Historique du bien", euros(h.valeur),
      `${memeBien} ${euroFr.format(h.prix)} le ${dateFr(h.date)}&nbsp;; au niveau actuel du
       marché ${euroFr.format(arrondi(h.reindexe))}, plus ${pourcent.format(h.plus_value)} — ce
       que gagnent en moyenne les biens revendus du département (travaux).
       Pèse ${pourcentEntier.format(h.poids)} du calcul.`));
    lignes.push(ligne("Valeur de marché", euros(r.marche), "", "ligne-somme"));
  }
  if (r.projection) {
    const p = r.projection;
    const evolution = p.facteur - 1;
    lignes.push(ligne("Évolution récente du marché",
      `${evolution >= 0 ? "+" : ""}${pourcent.format(evolution)}`,
      `indice Notaires-Insee (${echapper(p.zone_libelle)}), de la fin des ventes
       connues (${libelleTrimestre(p.depuis)}) au ${libelleTrimestre(p.jusqu_a)}`));
  }
  for (const a of r.ajustements) {
    const effet = a.montant != null ? euroFr.format(a.montant)
      : `${a.facteur >= 1 ? "+" : ""}${pourcent.format(a.facteur - 1)}`;
    lignes.push(ligne("Ajustement", effet, echapper(a.libelle)));
  }
  lignes.push(ligne("Valeur estimée", euros(r.valeur), "", "ligne-somme ligne-finale"));

  return `
    <section>
      <h2>Comment ce chiffre est construit</h2>
      <p class="explication">
        Plusieurs méthodes, chacune avec l'erreur qu'elle a réellement commise
        dans ce département sur la dernière année — l'application refait le
        calcul sur les ventes d'avant, et le compare aux prix obtenus.
      </p>
      <div class="cadre-defilant"><table class="estimation-calcul"><tbody>
        ${lignes.join("")}
      </tbody></table></div>
    </section>`;
}

function blocDecomposition(r) {
  const d = r.decomposition;
  if (!d) return "";
  const total = d.terrain + d.bati;
  const usure = d.vetuste_source === "annee"
    ? `Usure du bâti&nbsp;: 1,2&nbsp;% par an depuis la construction, plafonnée à 60&nbsp;%.`
    : `Année de construction inconnue&nbsp;: usure d'une maison typique du secteur.`;
  return `
    <section>
      <h2>Terrain et bâti</h2>
      <p class="explication">
        La méthode «&nbsp;sol + construction&nbsp;»&nbsp;: le prix des terrains à
        bâtir vendus autour (les plus proches à ${entierFr.format(d.distance_terrains_m)}&nbsp;m en
        médiane), plus le coût de reconstruction du bâti diminué de son usure,
        le tout calé sur les prix réels du département.
      </p>
      <dl class="mesures mesures-colonne estimation-decomposition">
        <div><dt>terrain</dt><dd class="donnee">${euros(d.terrain)}
          <span class="part">${pourcentEntier.format(d.terrain / total)}</span></dd></div>
        <div><dt>bâti</dt><dd class="donnee">${euros(d.bati)}
          <span class="part">${pourcentEntier.format(d.bati / total)}</span></dd></div>
        <div><dt>coût à neuf</dt><dd class="donnee">${entierFr.format(d.cout_m2)} €/m²</dd></div>
        <div><dt>usure</dt><dd class="donnee">${pourcentEntier.format(d.vetuste)}</dd></div>
        <div><dt>calage sur le marché</dt><dd class="donnee">× ${coefficient.format(d.coefficient_marche)}</dd></div>
      </dl>
      <p class="aide">${usure} Le calage rapporte la valeur technique aux prix
        réellement payés pour les maisons du département.</p>
    </section>`;
}

function blocRendement(r) {
  const rendement = r.rendement;
  if (!rendement) return "";
  return `
    <section>
      <h2>Rendement locatif</h2>
      <p>
        Loué au loyer d'annonce de la commune
        (<span class="donnee">${nombreFr.format(rendement.loyer_m2)}&nbsp;€/m²</span> charges
        comprises, carte des loyers ${echapper(rendement.millesime)}), ce bien rapporterait
        environ <span class="donnee">${euroFr.format(Math.round(rendement.loyer_annuel / 100) * 100)}</span> par an,
        soit un rendement brut de <strong class="donnee">${pourcent.format(rendement.brut)}</strong>
        à ce prix.
      </p>
      <p class="explication">
        Un repère, pas une méthode d'estimation&nbsp;: un seul loyer par commune
        ne distingue ni l'état ni l'emplacement, et là où la location
        saisonnière fait le marché il ne dit presque rien.
      </p>
    </section>`;
}

function blocComparables(r) {
  if (!r.comparables?.length) return "";
  const lignes = r.comparables.map((c) => `
    <tr>
      <td class="donnee">${dateFr(c.date)}</td>
      <td>${echapper(c.adresse || "—")}</td>
      <td class="donnee">${entierFr.format(c.surface)}&nbsp;m²</td>
      ${r.bien.type === "maison"
        ? `<td class="donnee">${c.terrain_m2 ? entierFr.format(c.terrain_m2) + "&nbsp;m²" : "—"}</td>` : ""}
      <td class="donnee">${c.pieces || "—"}</td>
      <td class="donnee">${euroFr.format(c.prix)}</td>
      <td class="donnee">${euroFr.format(Math.round(c.prix_actuel / c.surface))}&nbsp;/m²</td>
      <td class="donnee">${c.distance_m < 1000
        ? `${entierFr.format(Math.round(c.distance_m / 10) * 10)}&nbsp;m`
        : `${nombreFr.format(c.distance_m / 1000)}&nbsp;km`}</td>
    </tr>`).join("");
  return `
    <section>
      <h2>Les ventes comparables</h2>
      <p class="explication">
        Les ${entierFr.format(r.comparables.length)} ventes du même type les plus
        proches. Le prix au m² est ramené au niveau actuel du marché&nbsp;; la
        méthode en prend la médiane, en donnant plus de poids aux plus proches
        et à celles de surface voisine.
      </p>
      <div class="cadre-defilant"><table class="estimation-comparables">
        <thead><tr><th>Date</th><th>Adresse</th><th>Surface</th>
          ${r.bien.type === "maison" ? "<th>Terrain</th>" : ""}
          <th>Pièces</th><th>Prix</th><th>€/m² actuel</th><th>Distance</th></tr></thead>
        <tbody>${lignes}</tbody>
      </table></div>
    </section>`;
}

function blocPrecision(r) {
  const p = r.precision;
  if (!p) return "";
  const general = r.precision_generale;
  const dejaVendu = r.historique && general && p !== general && p.n !== general.n;
  return `
    <section>
      <h2>Précision mesurée</h2>
      <p class="explication">
        Sur ${entierFr.format(p.n)} ventes de la dernière année${dejaVendu
          ? " de biens déjà vendus auparavant" : ""}, estimées sans connaître
        leur prix&nbsp;: la moitié à moins de
        <strong>${nombreFr.format(p.erreur_mediane)}&nbsp;%</strong> du prix réel,
        ${entierFr.format(p.a10)}&nbsp;% à moins de 10&nbsp;%,
        ${entierFr.format(p.a20)}&nbsp;% à moins de 20&nbsp;%.
        La fourchette affichée vient de ces erreurs réelles.
        ${dejaVendu ? `Pour un bien jamais vendu, l'erreur médiane est de
          ${nombreFr.format(general.erreur_mediane)}&nbsp;%.` : ""}
      </p>
      <p class="explication">
        Références&nbsp;: ${entierFr.format(r.donnees.ventes || 0)} ventes, du
        ${dateFr(r.donnees.periode?.[0])} au ${dateFr(r.donnees.periode?.[1])} · modèle
        du ${dateFr(r.modele_du)}.
      </p>
    </section>`;
}

function brancherResultat() {
  const bouton = $("#enregistrer-estimation");
  if (bouton) bouton.addEventListener("click", () => estimer(true));
}

// --------------------------------------------------------------------
//  Mes estimations
// --------------------------------------------------------------------

/** La liste se recharge d'elle-même quand l'écran devient visible (voir la mise en route). */
export function ouvrirMesEstimations() {
  masquerErreur();
  changerVue("estimations");
}

async function chargerMesEstimations() {
  const zone = $("#estimations-liste");
  zone.innerHTML = '<p class="message message-travail">Chargement…</p>';
  let reponse;
  try {
    reponse = await api.estimationsEnregistrees();
  } catch (erreur) {
    zone.innerHTML = "";
    afficherErreur("Impossible de lire les estimations enregistrées.", erreur.message);
    return;
  }
  const liste = reponse.estimations;
  $("#estimations-bilan").innerHTML = blocBilan(reponse.bilan);
  if (!liste.length) {
    zone.innerHTML = `
      <div class="vide">
        <h3>Aucune estimation enregistrée</h3>
        <p>Ouvrez la carte, touchez une parcelle ou un diagnostic, puis
           «&nbsp;Estimer ce bien&nbsp;».</p>
      </div>`;
    return;
  }
  zone.innerHTML = `
    <ul class="ventes">${liste.map((e) => `
      <li class="vente">
        <div class="vente-date donnee">${dateFr(e.cree_le)}</div>
        <div class="vente-corps">
          <div class="vente-tete">
            <span class="vente-prix donnee">${euros(e.valeur)}</span>
            <span class="pastille">${echapper(e.type)}</span>
            ${e.vente_prix ? `<span class="pastille pastille-vendu">vendu ${echapper(
              euroFr.format(e.vente_prix))} le ${dateFr(e.vente_date)} · ${ecartSigne(
              e.vente_prix / e.valeur - 1)}</span>` : ""}
            <button type="button" class="bouton-lien" data-ouvrir-estimation="${e.id}">Ouvrir</button>
            <button type="button" class="bouton-lien" data-supprimer-estimation="${e.id}">Supprimer</button>
          </div>
          <p class="explication">
            ${echapper(e.adresse || (e.parcelle_id ? `parcelle ${e.parcelle_id}` : "sans adresse"))}
            ${e.commune && !(e.adresse || "").includes(e.commune) ? ` · ${echapper(e.commune)}` : ""}
            · ${entierFr.format(e.surface)}&nbsp;m²${e.terrain_m2 ? ` · terrain ${entierFr.format(e.terrain_m2)}&nbsp;m²` : ""}
            · entre ${euros(e.bas)} et ${euros(e.haut)}
          </p>
        </div>
      </li>`).join("")}
    </ul>`;
  zone.querySelectorAll("[data-ouvrir-estimation]").forEach((bouton) => {
    bouton.addEventListener("click", () =>
      ouvrirEstimationEnregistree(Number(bouton.dataset.ouvrirEstimation)));
  });
  zone.querySelectorAll("[data-supprimer-estimation]").forEach((bouton) => {
    bouton.addEventListener("click", async () => {
      if (!confirm("Supprimer cette estimation ?")) return;
      try {
        await api.supprimerEstimation(Number(bouton.dataset.supprimerEstimation));
      } catch (erreur) {
        afficherErreur("La suppression a échoué.", erreur.message);
        return;
      }
      chargerMesEstimations();
    });
  });
}

function ecartSigne(ecart) {
  return `${ecart >= 0 ? "+" : ""}${pourcentEntier.format(ecart)}`;
}

/**
 * Le bilan : vos estimations face aux prix réellement payés, quand DVF
 * les publie. C'est la seule mesure de VOTRE usage — l'état que vous
 * saisissez, les ajustements que vous faites —, que rien d'autre ne
 * calibre.
 */
function blocBilan(bilan) {
  if (!bilan || !bilan.estimations) return "";
  if (!bilan.vendues) {
    return `<p class="explication">
      Aucun des biens estimés n'est encore paru vendu dans DVF. La publication
      a six mois de retard&nbsp;; à chaque parution, l'application cherche la
      vente de chacun, et ce bilan dira ce que valaient vos estimations.</p>`;
  }
  const etats = Object.entries(bilan.par_etat || {}).map(([cle, e]) =>
    `<li><span class="donnee">${ecartSigne(e.ecart_median / 100)}</span> pour
       l'état «&nbsp;${echapper(LIBELLES_ETATS[cle] || cle)}&nbsp;» (${entierFr.format(e.n)}
       vente${e.n > 1 ? "s" : ""})</li>`).join("");
  return `
    <div class="estimations-bilan">
      <p>
        <strong>${entierFr.format(bilan.vendues)}</strong> bien${bilan.vendues > 1 ? "s" : ""}
        vendu${bilan.vendues > 1 ? "s" : ""} depuis leur estimation, sur
        ${entierFr.format(bilan.estimations)} estimé${bilan.estimations > 1 ? "s" : ""}&nbsp;:
        erreur médiane <strong class="donnee">${nombreFr.format(bilan.erreur_mediane)}&nbsp;%</strong>${
        bilan.dans_la_fourchette != null ? `, ${entierFr.format(bilan.dans_la_fourchette)}&nbsp;% dans
        la fourchette annoncée` : ""}.
      </p>
      <p class="explication">Écart médian entre le prix payé et l'estimation, selon l'état
        que vous aviez saisi — positif, le bien s'est vendu plus cher qu'estimé&nbsp;:</p>
      <ul class="liste-raisons">${etats}</ul>
    </div>`;
}

// --------------------------------------------------------------------
//  Mise en route
// --------------------------------------------------------------------

export function initialiserEstimation() {
  document.querySelectorAll("[data-mes-estimations]").forEach((bouton) => {
    bouton.addEventListener("click", () => ouvrirMesEstimations());
  });
  $("#estimations-retour")?.addEventListener("click", () => {
    if (history.state && history.state.vue === "estimations") history.back();
    else changerVue("accueil");
  });
  auChangement("estimations", () => { chargerMesEstimations(); });
  // Le retour arrière ramène sur une estimation : il faut savoir laquelle.
  auRetourArriere("estimation", (etat) => {
    if (etat.estimation) ouvrirEstimationEnregistree(etat.estimation, { sansHistorique: true });
    else ouvrirEstimation({ ...etat, sansHistorique: true });
  });
}
