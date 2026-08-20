// ====================================================================
//  identifier.js — F2 : retrouver un bien depuis les chiffres d'une annonce.
//
//  L'écran affiche TOUJOURS trois choses, dans cet ordre :
//    1. l'entonnoir — combien de logements passent chaque critère seul,
//       puis en cumulé ;
//    2. le diagnostic, quand l'entonnoir se ferme ;
//    3. le classement complet, dont rien n'a été éliminé.
//
//  C'est l'exigence centrale du CDC F2 : ne jamais éliminer sans expliquer.
// ====================================================================

import { api } from "./api.js";
import { ouvrirFiche } from "./fiche.js";
import { auTermeDeLImport } from "./import.js";
import { communeCourante, surCommunePrete } from "./parcours.js";
import {
  $, afficherErreur, echapper, entierFr, etiquetteHtml, liensExternes,
  masquerErreur, mesure, nombreFr,
} from "./format.js";

function lireFormulaire() {
  const valeur = (identifiant) => {
    const brut = $(identifiant).value.trim();
    return brut === "" ? null : Number(brut.replace(",", "."));
  };
  return {
    criteres: {
      surface: valeur("#i-surface"),
      conso_ep: valeur("#i-conso-ep"),
      conso_ef: valeur("#i-conso-ef"),
      ges: valeur("#i-ges"),
      etiquette_dpe: $("#i-etiquette-dpe").value,
      etiquette_ges: $("#i-etiquette-ges").value,
    },
    tolerances: {
      surface: valeur("#i-tol-surface") ?? undefined,
      conso: valeur("#i-tol-conso") ?? undefined,
      ges: valeur("#i-tol-ges") ?? undefined,
    },
    filtres: {
      // La commune vient du parcours : on l'a choisie avant d'arriver ici.
      code_insee: communeCourante()?.code_insee ?? "",
      type_batiment: $("#i-type").value,
    },
  };
}

/** L'entonnoir : une ligne par critère, avec la barre du cumul. */
function dessinerEntonnoir(reponse) {
  const { entonnoir, examines } = reponse;
  if (!entonnoir.length) {
    $("#entonnoir").innerHTML = "";
    return;
  }

  const lignes = entonnoir.map((etape) => {
    // Échelle logarithmique : un cumul de 1 sur 4 000 doit rester visible.
    // En proportion directe, la barre ferait moins d'un pixel et la lecture
    // de l'entonnoir — son objet même — serait perdue.
    const part = examines
      ? Math.max(2, (Math.log1p(etape.cumules) / Math.log1p(examines)) * 100)
      : 0;
    const vise = etape.tolerance
      ? `${nombreFr.format(etape.attendu)} ${etape.unite} ± ${nombreFr.format(etape.tolerance)}`
      : echapper(etape.attendu);
    // Un critère que la base renseigne peu ne prouve pas grand-chose.
    const rare = etape.renseignes < examines / 2;
    return `
      <tr>
        <td>${echapper(etape.libelle)}</td>
        <td class="donnee">${vise}</td>
        <td class="donnee">${entierFr.format(etape.seuls)}</td>
        <td class="donnee ${etape.cumules === 0 ? "cumul-vide" : ""}">${entierFr.format(etape.cumules)}</td>
        <td class="barre-cellule">
          <span class="barre" style="width:${part}%"></span>
        </td>
        <td class="donnee ${rare ? "rare" : ""}" title="Logements pour lesquels la base renseigne ce critère">
          ${entierFr.format(etape.renseignes)}
        </td>
      </tr>`;
  }).join("");

  $("#entonnoir").innerHTML = `
    <h2>Entonnoir</h2>
    <p class="explication">
      ${entierFr.format(examines)} logements examinés. « Seul » compte ceux qui
      satisfont le critère pris isolément, « cumulé » ceux qui satisfont aussi
      tous les critères précédents. Un cumul qui tombe à zéro désigne le chiffre
      de l'annonce à suspecter.
    </p>
    <div class="cadre-defilant"><table class="entonnoir">
      <tr>
        <th>Critère</th><th>Visé</th><th>Seul</th><th>Cumulé</th><th></th>
        <th>Renseigné</th>
      </tr>
      ${lignes}
    </table></div>`;
}

function gabaritCandidat(bien, rang) {
  const detail = Object.entries(bien.ecarts || {}).map(([critere, ecart]) => {
    if (typeof ecart === "boolean") {
      return `<span class="ecart ${ecart ? "ecart-bon" : "ecart-mauvais"}">
                ${echapper(critere.replace("etiquette_", "classe "))} ${ecart ? "✓" : "✗"}
              </span>`;
    }
    if (ecart === null) {
      return `<span class="ecart ecart-absent">${echapper(critere)} non renseigné</span>`;
    }
    const classe = ecart <= 1 ? "ecart-bon" : ecart <= 3 ? "ecart-moyen" : "ecart-mauvais";
    return `<span class="ecart ${classe}">${echapper(critere)} ${nombreFr.format(ecart)}×</span>`;
  }).join("");

  return `
  <article class="releve candidat">
    <div class="releve-tete">
      <span class="rang donnee">${rang}</span>
      <span class="score donnee">écart moyen ${bien.ecart_moyen ?? "—"}</span>
      ${bien.zone ? `<span class="secteur">${echapper(bien.zone)}</span>` : ""}
      <span>${echapper(bien.date_etablissement || "")}</span>
    </div>
    <h3 class="adresse">${echapper(bien.adresse || "Adresse absente de la base")}</h3>
    <dl class="mesures">
      ${mesure("surface", bien.surface_habitable, "m²")}
      <div><dt>classe</dt><dd>${etiquetteHtml(bien.etiquette_dpe)}</dd></div>
      <div><dt>classe GES</dt><dd>${etiquetteHtml(bien.etiquette_ges)}</dd></div>
      ${mesure("énergie ép.", bien.conso_ep_m2, "kWh/m²", entierFr)}
      ${mesure("énergie éf.", bien.conso_ef_m2, "kWh/m²", entierFr)}
      ${mesure("GES", bien.ges_m2, "kg/m²", nombreFr)}
    </dl>
    <div class="ecarts">${detail}</div>
    <div class="liens">
      <button type="button" class="bouton-lien" data-fiche="${echapper(bien.n_dpe)}">Fiche du bien</button>
      ${liensExternes(bien)}
      <span class="reference donnee">${echapper(bien.n_dpe)}</span>
    </div>
  </article>`;
}

function dessinerResultats(reponse) {
  const boite = $("#resultats-identification");

  if (reponse.diagnostic) {
    $("#diagnostic-identification").innerHTML =
      `<p class="message message-travail">${echapper(reponse.diagnostic)}</p>`;
  } else {
    $("#diagnostic-identification").innerHTML = "";
  }

  if (!reponse.resultats.length) {
    boite.innerHTML = `
      <div class="vide">
        <h3>Rien à classer</h3>
        <p>Aucun logement du périmètre ne renseigne les critères saisis.
           Élargissez la commune, ou saisissez un autre chiffre de l'annonce.</p>
      </div>`;
    return;
  }

  boite.innerHTML =
    `<h2>Classement</h2>
     <p class="explication">
       ${entierFr.format(reponse.classes)} logements classés par écart moyen,
       exprimé en nombre de tolérances. Aucun n'a été éliminé : le bon candidat
       peut se trouver sous un écart supérieur à 1 si l'annonce arrondit.
     </p>` +
    reponse.resultats.map((bien, index) => gabaritCandidat(bien, index + 1)).join("");

  boite.querySelectorAll("[data-fiche]").forEach((bouton) => {
    bouton.addEventListener("click", () => ouvrirFiche({ n_dpe: bouton.dataset.fiche }));
  });
}

let derniereRecherche = null;

async function chercher() {
  masquerErreur();
  const corps = lireFormulaire();
  derniereRecherche = corps;
  const bouton = $("#i-chercher");
  bouton.disabled = true;
  bouton.textContent = "Recherche…";

  try {
    const reponse = await api.identifier(corps);
    dessinerEntonnoir(reponse);
    dessinerResultats(reponse);
  } catch (erreur) {
    afficherErreur("La recherche a échoué.", erreur.message);
  } finally {
    bouton.disabled = false;
    bouton.textContent = "Chercher";
  }
}

export function initialiserIdentification() {
  // Une moisson qui aboutit pendant qu'on consulte le classement le rend
  // caduc : on le rejoue, mais seulement si une recherche a déjà eu lieu.
  auTermeDeLImport(() => { if (derniereRecherche) chercher(); });

  $("#formulaire-identification").addEventListener("submit", (evenement) => {
    evenement.preventDefault();
    chercher();
  });
  $("#i-effacer").addEventListener("click", () => {
    $("#formulaire-identification").reset();
    $("#entonnoir").innerHTML = "";
    $("#diagnostic-identification").innerHTML = "";
    $("#resultats-identification").innerHTML = "";
  });

  // Les tolérances par défaut viennent des réglages.
  api.reglages().then(({ reglages }) => {
    $("#i-tol-surface").placeholder = reglages.tolerances.surface;
    $("#i-tol-conso").placeholder = reglages.tolerances.conso;
    $("#i-tol-ges").placeholder = reglages.tolerances.ges;
  }).catch(() => { /* les tolérances du serveur s'appliqueront */ });

  // Changer de commune vide le classement précédent : il portait sur
  // d'autres logements.
  surCommunePrete(() => {
    derniereRecherche = null;
    $("#entonnoir").innerHTML = "";
    $("#diagnostic-identification").innerHTML = "";
    $("#resultats-identification").innerHTML = "";
  });
}
