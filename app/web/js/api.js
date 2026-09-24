// ====================================================================
//  api.js — Le seul endroit qui parle au serveur.
//
//  Toutes les erreurs sont traduites en un message affichable tel quel :
//  le CDC 7 demande de dire ce qui s'est passe et quoi faire, jamais un
//  simple « une erreur est survenue ».
// ====================================================================

export class ErreurApi extends Error {}

async function demander(url, options = {}) {
  let reponse;
  try {
    reponse = await fetch(url, options);
  } catch (erreur) {
    throw new ErreurApi(
      "Le serveur ne répond pas. Vérifiez que le conteneur est démarré, " +
      "puis rechargez la page."
    );
  }

  if (!reponse.ok) {
    let detail = "";
    try {
      const corps = await reponse.json();
      detail = corps.detail || corps.message || "";
      if (Array.isArray(detail)) detail = detail.map((e) => e.msg || e).join(" · ");
    } catch (_) { /* le corps n'etait pas du JSON */ }
    throw new ErreurApi(detail || `Le serveur a répondu ${reponse.status}.`);
  }

  if (reponse.status === 204) return null;
  return reponse.json();
}

/**
 * Transforme un objet de filtres en paramètres d'URL.
 *
 * Un booléen FAUX s'écrit, il ne s'omet pas. L'omettre revenait à laisser
 * le serveur décider, ce qui va très bien tant que sa valeur par défaut
 * est « faux » — et casse dès qu'elle ne l'est pas. `defauts: false` dit
 * « prends mes critères au pied de la lettre » : omis, il valait son
 * contraire, et la liste se remettait à appliquer les réglages que la
 * carte ignorait.
 */
export function versParametres(filtres) {
  const parametres = new URLSearchParams();
  for (const [cle, valeur] of Object.entries(filtres)) {
    if (valeur === "" || valeur === null || valeur === undefined) continue;
    if (Array.isArray(valeur)) {
      valeur.filter(Boolean).forEach((v) => parametres.append(cle, v));
    } else if (typeof valeur === "boolean") {
      parametres.set(cle, valeur ? "true" : "false");
    } else {
      parametres.set(cle, valeur);
    }
  }
  return parametres;
}

export const api = {
  sante: () => demander("/api/sante"),

  communes: () => demander("/api/communes"),

  chercherCommunes: (q) => demander(`/api/communes/recherche?${versParametres({ q })}`),

  /** Quelle commune se trouve à cette position, et l'a-t-on déjà ? */
  communeIci: (latitude, longitude) =>
    demander(`/api/communes/ici?${versParametres({ latitude, longitude })}`),

  /** Rend une commune consultable : la moissonne si elle manque ou date. */
  preparerCommune: (codeInsee, besoin = "dpe") =>
    demander(`/api/communes/${encodeURIComponent(codeInsee)}/preparer` +
             `?${versParametres({ besoin })}`, { method: "POST" }),

  veille: (filtres) => demander(`/api/veille?${versParametres(filtres)}`),

  urlExport: (filtres) => `/api/veille/export.csv?${versParametres(filtres)}`,

  marquerVus: (numeros = null) =>
    demander("/api/veille/vus", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ numeros }),
    }),

  lancerImport: () => demander("/api/import", { method: "POST" }),

  ageImport: () => demander("/api/import/age"),

  statutImport: () => demander("/api/import/statut"),

  journalImports: () => demander("/api/import/journal"),

  identifier: (corps) =>
    demander("/api/identification", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(corps),
    }),


  /** Parcelle, voisines et bâtiments : de quoi dessiner un extrait. */
  extraitCadastral: (n_dpe) =>
    demander(`/api/parcelles/extrait?${versParametres({ n_dpe })}`),

  fiche: (parametres) => demander(`/api/fiche?${versParametres(parametres)}`),

  chaine: (n_dpe) => demander(`/api/fiche/chaine?${versParametres({ n_dpe })}`),

  comparer: (recent, ancien) =>
    demander(`/api/fiche/comparer?${versParametres({ recent, ancien })}`),

  reglages: () => demander("/api/reglages"),

  enregistrerReglages: (valeurs) =>
    demander("/api/reglages", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(valeurs),
    }),

  // Les critères voyagent avec le cadre : c'est le serveur qui décide ce
  // qui compte comme « DPE », afin que la carte et la liste répondent à
  // la même question. `etiquettes` part en une seule valeur séparée par
  // des virgules, comme l'attend la route.
  parcellesCarte: (code_insee, bbox, limite, filtres, geometries = true) => {
    const parametres = new URLSearchParams({ code_insee, bbox });
    if (limite) parametres.set("limite", limite);
    for (const cle of ["fenetre_jours", "zone", "type_batiment",
                       "surface_min", "surface_max"]) {
      const valeur = filtres?.[cle];
      if (valeur !== "" && valeur !== null && valeur !== undefined) {
        parametres.set(cle, valeur);
      }
    }
    const etiquettes = (filtres?.etiquettes || []).filter(Boolean);
    if (etiquettes.length) parametres.set("etiquettes", etiquettes.join(","));
    if (filtres?.seulement_nouveaux) parametres.set("seulement_nouveaux", "true");
    // Aux zooms larges la carte pose des marques, pas des contours : les
    // géométries ne servent alors à rien et pèsent les trois quarts de la
    // réponse — 1 538 Ko contre 406 sur Mimizan entière.
    if (!geometries) parametres.set("geometries", "false");
    return demander(`/api/parcelles/carte?${parametres}`);
  },

  chercherSurCarte: (code_insee, q) =>
    demander(`/api/parcelles/chercher?code_insee=${encodeURIComponent(code_insee)}`
      + `&q=${encodeURIComponent(q)}`),

  /** Quelle parcelle se trouve sous ce point de la carte ? */
  parcelleALaPosition: (code_insee, latitude, longitude) =>
    demander(`/api/parcelles/a-la-position?${versParametres(
      { code_insee, latitude, longitude })}`),

  ficheParcelle: (parcelle_id) =>
    demander(`/api/parcelles/fiche-parcelle?parcelle_id=${encodeURIComponent(parcelle_id)}`),

  ventes: (n_dpe) =>
    demander(`/api/parcelles/ventes?n_dpe=${encodeURIComponent(n_dpe)}`),

  etatAlerte: () => demander("/api/alertes"),

  // Ce que chaque passage a donné, envoyé ou non : la seule
  // réponse consultable à « je n'ai rien reçu ce matin ».
  journalAlerte: () => demander("/api/alertes/journal"),

  // `smtp` porte la configuration affichée, pas celle enregistrée : le
  // contrôle éprouve ce qu'on voit à l'écran.
  essaiAlerte: (destinataire, smtp) =>
    demander("/api/alertes/essai", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...(destinataire ? { destinataire } : {}),
                             ...(smtp ? { smtp } : {}) }),
    }),

  profondeurVentes: (code_insee) =>
    demander("/api/import/ventes/profondeur"
      + (code_insee ? `?code_insee=${encodeURIComponent(code_insee)}` : "")),

  // Répond à la fin : le fichier est départemental, l'attente de l'ordre
  // de la minute, et c'est un geste qu'on ne fait qu'une fois.
  etatSauvegardes: () => demander("/api/import/sauvegardes"),

  sauvegarderMaintenant: () =>
    demander("/api/import/sauvegardes", { method: "POST" }),

  // --- Estimation -------------------------------------------------
  /** Ce que la base sait du bien, et l'état de son département. Ne sort pas du NAS. */
  bienAEstimer: ({ n_dpe, parcelle_id }) =>
    demander(`/api/estimation/bien?${versParametres({ n_dpe, parcelle_id })}`),

  etatDepartement: (departement) =>
    demander(`/api/estimation/departement/${encodeURIComponent(departement)}`),

  /** Charge les ventes du département et apprend : répond aussitôt, on suit ensuite. */
  preparerDepartement: (departement) =>
    demander(`/api/estimation/preparer?${versParametres({ departement })}`, { method: "POST" }),

  etatPreparation: () => demander("/api/estimation/preparation"),

  etatsDuBati: () => demander("/api/estimation/etats"),

  estimer: (corps) =>
    demander("/api/estimation", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(corps),
    }),

  estimationsEnregistrees: () => demander("/api/estimation/enregistrees"),

  estimationEnregistree: (ident) =>
    demander(`/api/estimation/enregistrees/${encodeURIComponent(ident)}`),

  supprimerEstimation: (ident) =>
    demander(`/api/estimation/enregistrees/${encodeURIComponent(ident)}`, { method: "DELETE" }),

  // Sans rien, le serveur prend la commune surveillée. Sinon une autre
  // commune, ou tout un département.
  reprendreArchive: ({ code_insee, dep } = {}) =>
    demander("/api/import/ventes/archive"
      + (dep ? `?dep=${encodeURIComponent(dep)}`
             : code_insee ? `?code_insee=${encodeURIComponent(code_insee)}` : ""),
      { method: "POST" }),
};
