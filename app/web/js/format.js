// ====================================================================
//  format.js — Mise en forme et retours d'état, partagés par les écrans.
// ====================================================================

export const $ = (selecteur) => document.querySelector(selecteur);

export const nombreFr = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 1 });
export const entierFr = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 0 });

/** Les prix se lisent sans centimes : à ce niveau, ils sont du bruit. */
export const euroFr = new Intl.NumberFormat("fr-FR", {
  style: "currency", currency: "EUR", maximumFractionDigits: 0,
});

export function dateFr(iso) {
  if (!iso) return "—";
  const [a, m, j] = String(iso).slice(0, 10).split("-");
  return j && m && a ? `${j}/${m}/${a}` : iso;
}

export function anciennete(jours) {
  if (jours == null) return "";
  if (jours === 0) return "aujourd'hui";
  if (jours === 1) return "hier";
  if (jours < 31) return `il y a ${jours} j`;
  const mois = Math.round(jours / 30.44);
  if (mois < 24) return `il y a ${mois} mois`;
  return `il y a ${Math.round(mois / 12)} ans`;
}

export function echapper(texte) {
  const boite = document.createElement("span");
  boite.textContent = texte ?? "";
  return boite.innerHTML;
}

/** Une mesure : valeur en chasse fixe, ou tiret explicite si absente. */
export function mesure(libelle, valeur, unite = "", format = nombreFr) {
  const absent = valeur === null || valeur === undefined || valeur === "";
  const affiche = absent ? "—" : `${format.format(valeur)}${unite ? " " + unite : ""}`;
  return `<div><dt>${libelle}</dt><dd class="${absent ? "absent" : ""}">${affiche}</dd></div>`;
}

export function etiquetteHtml(classe) {
  const lettre = String(classe || "").trim().toUpperCase();
  if (!lettre) return '<span class="absent">—</span>';
  return `<span class="etiquette etiquette-${lettre}" title="Classe ${lettre}">${lettre}</span>`;
}

/** Liens vers la vue satellite, Street View et le Géoportail (CDC §7). */
export function liensExternes(bien) {
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
    <a href="${geoportail}" target="_blank" rel="noopener">Géoportail</a>`;
}

// --------------------------------------------------------------------
//  Bandeaux d'état
// --------------------------------------------------------------------

export function afficherErreur(message, detail = "") {
  const boite = $("#erreur");
  boite.innerHTML = echapper(message) + (detail ? `<span class="detail">${echapper(detail)}</span>` : "");
  boite.hidden = false;
  boite.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

export function masquerErreur() { $("#erreur").hidden = true; }

export function afficherSucces(message) {
  const boite = $("#succes");
  boite.textContent = message;
  boite.hidden = false;
  setTimeout(() => { boite.hidden = true; }, 8000);
}

export function afficherTravail(message, avecJauge = true) {
  const boite = $("#progression");
  boite.innerHTML = echapper(message) + (avecJauge ? '<span class="jauge"><span></span></span>' : "");
  boite.hidden = false;
}

export function masquerTravail() { $("#progression").hidden = true; }

export function debounce(fonction, delai) {
  let minuteur;
  return (...arguments_) => {
    clearTimeout(minuteur);
    minuteur = setTimeout(() => fonction(...arguments_), delai);
  };
}
