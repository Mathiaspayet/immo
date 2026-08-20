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

/** Transforme un objet de filtres en paramètres d'URL. */
export function versParametres(filtres) {
  const parametres = new URLSearchParams();
  for (const [cle, valeur] of Object.entries(filtres)) {
    if (valeur === "" || valeur === null || valeur === undefined) continue;
    if (Array.isArray(valeur)) {
      valeur.filter(Boolean).forEach((v) => parametres.append(cle, v));
    } else if (typeof valeur === "boolean") {
      if (valeur) parametres.set(cle, "true");
    } else {
      parametres.set(cle, valeur);
    }
  }
  return parametres;
}

export const api = {
  sante: () => demander("/api/sante"),

  veille: (filtres) => demander(`/api/veille?${versParametres(filtres)}`),

  urlExport: (filtres) => `/api/veille/export.csv?${versParametres(filtres)}`,

  marquerVus: (numeros = null) =>
    demander("/api/veille/vus", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ numeros }),
    }),

  lancerImport: () => demander("/api/import", { method: "POST" }),

  statutImport: () => demander("/api/import/statut"),

  journalImports: () => demander("/api/import/journal"),

  reglages: () => demander("/api/reglages"),

  enregistrerReglages: (valeurs) =>
    demander("/api/reglages", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(valeurs),
    }),
};
