// -*- coding: utf-8 -*-
/**
 * exploration.js — L'écran de la carte, et la liste des DPE récents.
 *
 * On parcourt la commune sur photo aérienne, chaque parcelle colorée selon
 * ce qu'on en sait : un diagnostic, une vente, les deux, ou rien encore.
 * C'est le croisement qui informe — une parcelle vendue sans diagnostic
 * récent et une parcelle diagnostiquée sans vente ne racontent pas la même
 * histoire.
 *
 * LA LISTE ET LA CARTE SONT LE MÊME ÉCRAN. C'étaient deux parcours
 * distincts — « Les DPE récents » et « Explorer la carte » — qui montraient
 * la même commune sans jamais se rejoindre. Ils n'en font plus qu'un : la
 * carte seule tant qu'on explore, la liste à côté dès qu'on demande une
 * fenêtre de diagnostics récents.
 *
 * Les deux se complètent, et ce n'est pas un confort. Les parcelles ne
 * portent que les DPE rattachés au cadastre ; sur un an à Mimizan, 18 sur
 * 307 ne le sont pas — l'ADEME ne les a pas géocodés assez finement. La
 * liste et les repères, eux, travaillent sur les coordonnées : rien ne
 * disparaît en silence.
 *
 * Deux contraintes gouvernent la partie cartographique :
 *
 *   - le volume. Les 11 444 parcelles de Mimizan pèsent 3,8 Mo. On ne
 *     charge donc que le cadre affiché, et on prévient quand il en reste
 *     au-delà plutôt que d'en tracer une bouillie ;
 *   - le zoom. En dessous d'un certain niveau, les parcelles sont trop
 *     petites pour se distinguer et trop nombreuses pour se charger : la
 *     carte le dit au lieu de peiner en silence. Les repères des
 *     diagnostics, eux, restent visibles à toute échelle.
 */

import { api, ErreurApi } from "./api.js";
import { creerCarteExploration, etatParcelle } from "./carte.js";
import {
  $, afficherErreur, afficherSucces, anciennete, dateFr, echapper, entierFr,
  etiquetteHtml, liensExternes, masquerErreur, mesure, nombreFr,
} from "./format.js";
import { ouvrirFiche } from "./fiche.js";
import { auTermeDeLImport } from "./import.js";
import { auChangement } from "./navigation.js";
import { communeCourante, dessinerContexte, surCommunePrete } from "./parcours.js";

// En dessous, une commune entière tient à l'écran : des milliers de
// parcelles de quelques pixels, illisibles et lourdes à charger.
const ZOOM_MINIMAL = 15;

// On charge PLUS LARGE que ce qu'on montre : un déplacement qui reste
// dans cette marge ne demande rien du tout, et c'est ce qui enlève la
// sensation de rechargement à chaque geste.
//
// La valeur n'est pas choisie à l'œil. Mesuré à la densité de Mimizan,
// sur huit petits déplacements de 150 px :
//
//     marge 0,00 : 7 requêtes / 8 gestes
//     marge 0,25 : 3 requêtes / 8 gestes
//     marge 0,30 : 2 requêtes / 8 gestes
//     marge 0,60 : réponse TRONQUÉE, donc jamais réutilisable
//
// Elle a un prix, mesuré lui aussi : un cadre plus large fait plus de
// contours à poser quand un chargement a bien lieu. Sur un processeur
// bridé six fois, le travail cumulé passe de ~110 ms à ~500 ms sur une
// série de onze gestes — mais il est payé UNE fois par chargement, et il
// y a cinq fois moins de chargements. La cadence d'affichage, elle, reste
// à 17 ms par image dans les deux cas.
const MARGE = 0.3;

let carte = null;
let derniereRequete = 0;
let communeCadree = null;

// L'etat de l'ecran. `etat` tout court etait deja pris par la ligne
// d'etat de la carte, plus bas.
const ecran = {
  filtres: {},
  resultats: [],
  selection: null,
  couches: { dpe: true, ventes: true, vides: true },
  // La liste repliee ne se recharge pas ; on note qu'elle a vieilli.
  listeAJour: false,
  // La derniere reponse du serveur, pour redessiner sans la redemander.
  dernieresParcelles: null,
  // Le cadre effectivement charge, et a quel zoom : tant que la vue reste
  // dedans, il n'y a rien a redemander.
  cadreCharge: null,
  zoomCharge: null,
  // Un cadre tronque est INCOMPLET : s'y fier ferait manquer des
  // parcelles au premier deplacement. On redemande alors toujours.
  chargeComplet: false,
};

// ====================================================================
//  La liste des DPE récents
//
//  Elle n'apparaît que si on la demande : choisir une fenêtre, c'est
//  dire « montre-moi ce qui vient d'être diagnostiqué ». Tant qu'aucune
//  n'est choisie, l'écran reste ce qu'il était — une carte, en grand.
// ====================================================================

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
      ${bien.logements > 1
        ? `<span class="pastille pastille-lot" title="Même adresse, même surface : `
          + `l'ADEME ne permet pas de les distinguer.">`
          + `${entierFr.format(bien.logements)} logements identiques</span>`
        : ""}
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

/**
 * Souligne les critères POSÉS, pour qu'on voie ce que la carte montre.
 *
 * « toutes dates » et « 30 derniers jours » se ressemblent trop dans un
 * menu déroulant : sans marque, on ne sait pas d'un coup d'œil si la
 * carte répond à une question ou montre tout.
 */
function marquerLesFiltres() {
  const formulaire = $("#filtres");
  for (const champ of formulaire.querySelectorAll("select, input[type=number]")) {
    const pose = String(champ.value || "").trim() !== "";
    champ.dataset.pose = pose ? "oui" : "non";
  }
}

/** Un critère est-il posé ? Sert à dire à l'écran ce qu'il montre. */
function filtreActif() {
  const f = ecran.filtres;
  return Boolean(f.fenetre_jours || f.zone || f.type_batiment
                 || f.surface_min || f.surface_max
                 || (f.etiquettes || []).length || f.seulement_nouveaux);
}

function lireFiltres() {
  const formulaire = $("#filtres");
  const etiquette = formulaire.etiquettes.value;
  return {
    // Les critères de l'écran, et EUX SEULS : sans ce drapeau, le serveur
    // complète ce qui manque par les réglages enregistrés, et la liste se
    // met à répondre à une autre question que la carte.
    defauts: false,
    // Le voile des parcelles sans information : demandé ou non.
    sans_info: $("#c-vides").checked,
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

/**
 * Rend disponible la fenêtre exacte des réglages, sans la choisir.
 *
 * L'écran s'ouvre sur la carte STANDARD — toutes dates, DPE et ventes :
 * c'est la vue d'ensemble, et elle ne doit rien présumer. Mais les
 * réglages autorisent n'importe quelle fenêtre (45 jours par exemple) ;
 * si elle manque au menu, on l'y ajoute, pour que le périmètre exact du
 * courriel d'alerte soit à un clic.
 */
function appliquerFiltres(filtres) {
  const formulaire = $("#filtres");

  // Les réglages autorisent n'importe quelle fenêtre (45 jours par
  // exemple). Si elle ne figure pas dans la liste déroulante, on l'y
  // ajoute : sans cela l'utilisateur ne pourrait pas retrouver d'un clic
  // le périmètre exact de son alerte.
  const fenetre = String(filtres.fenetre_jours ?? 120);
  const choix = formulaire.fenetre_jours;
  if (![...choix.options].some((option) => option.value === fenetre)) {
    // À sa place dans l'ordre des durées, et non ajoutée en queue : un
    // menu où « 120 jours » suit « 2 ans » se lit mal, et donne à croire
    // à un choix à part.
    const suivante = [...choix.options].find(
      (option) => option.value !== "" && Number(option.value) > Number(fenetre));
    choix.add(new Option(`${fenetre} jours`, fenetre), suivante ?? null);
  }
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
           <p>Aucun DPE n'a encore été importé. Lancez un premier import depuis
              les <strong>Réglages</strong>, bouton « Forcer une moisson
              maintenant » : il télécharge les diagnostics des communes
              surveillées, ce qui prend une à deux minutes.</p>
         </div>`
      : `<div class="vide">
           <h3>Aucun logement ne correspond à ces filtres</h3>
           <p>La base contient ${resume.total_base} DPE. Élargissez la fenêtre
              temporelle, ou desserrez les bornes de surface. Un secteur peut
              aussi n'avoir simplement aucun diagnostic récent : il ne
              s'établit qu'environ 1,6 DPE par jour sur l'ensemble du 40200,
              toutes communes et tous types confondus.</p>
         </div>`;
    return;
  }

  liste.innerHTML = resultats.map(gabaritReleve).join("");

  liste.querySelectorAll("[data-fiche]").forEach((bouton) => {
    bouton.addEventListener("click", (evenement) => {
      evenement.stopPropagation();
      ouvrirFiche({ n_dpe: bouton.dataset.fiche, retour: "carte" });
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

/**
 * Une ligne choisie s'allume, et la carte va la chercher.
 *
 * Elle s'y rend par les COORDONNÉES du diagnostic : qu'il soit porté par
 * une parcelle, rapproché de l'une d'elles ou posé seul en losange, le
 * point existe toujours. Un surlignage de losange, quand c'en est un.
 */
function selectionner(numero) {
  ecran.selection = numero;
  document.querySelectorAll(".releve").forEach((element) => {
    element.setAttribute("aria-current",
                         element.dataset.dpe === numero ? "true" : "false");
  });
  const bien = ecran.resultats.find((b) => b.n_dpe === numero);
  if (!bien) return;
  if (!carte?.surlignerBien(numero)) {
    carte?.allerA(bien.latitude, bien.longitude);
  }
}

/**
 * Remplit la liste des secteurs.
 *
 * Elle ne l'a JAMAIS été : le menu « Secteur » n'a proposé que « tous »
 * depuis qu'il existe, alors que les secteurs sont comptés juste à côté,
 * dans la ligne de compteurs (« bourg 96 · plage 82 »). Un filtre qui ne
 * peut rien filtrer vaut moins que pas de filtre : il se désactive
 * maintenant tout seul quand la commune n'en porte aucun.
 */
function peuplerSecteurs(zones) {
  const liste = $("#f-zone");
  const choisi = liste.value;
  liste.innerHTML = '<option value="">tous</option>'
    + (zones || []).map((z) =>
        `<option value="${echapper(z)}">${echapper(z)}</option>`).join("");
  liste.disabled = !(zones || []).length;
  liste.value = (zones || []).includes(choisi) ? choisi : "";
}

/** Rafraîchit la barre de contexte : la commune, et son nombre de DPE. */
async function chargerContexte() {
  const commune = communeCourante();
  if (!commune) return;
  try {
    const reponse = await api.communes();
    const trouvee = (reponse.communes || []).find(
      (c) => c.code_insee === commune.code_insee);
    peuplerSecteurs(reponse.zones);
    dessinerContexte(trouvee ? { dpe: trouvee.dpe } : {});
  } catch (_) {
    // Le compte est un agrément : sans lui la barre reste juste, elle
    // annonce seulement la commune.
    dessinerContexte();
  }
}

/**
 * Charge la liste de détail, rangée sous la carte.
 *
 * Elle ne commande plus rien : la carte garde sa taille et sa position,
 * quel que soit le filtre. Un écran qui se réorganise à chaque case
 * cochée fait perdre l'endroit qu'on regardait — c'était le défaut de la
 * première version, et il rendait la carte standard inatteignable une
 * fois un filtre posé.
 */
async function chargerListe() {
  // Repliée, elle ne coûte rien : ni requête, ni cinq cents articles
  // construits dans le vide. C'est ce qui rendait chaque changement de
  // filtre lent — la carte se recolorait en quelques millisecondes, puis
  // attendait une liste que personne ne regardait.
  if (!$("#detail-liste").open) {
    ecran.listeAJour = false;
    // Le titre ne doit pas garder le compte d'un filtre abandonné : il
    // redevient une invitation, pas une affirmation.
    $("#resume-liste").textContent = "Voir le détail des diagnostics affichés";
    return;
  }
  ecran.listeAJour = true;

  masquerErreur();
  let reponse;
  try {
    reponse = await api.veille(ecran.filtres);
  } catch (erreur) {
    afficherErreur(
      erreur instanceof ErreurApi ? erreur.message : "Impossible de charger la liste.",
      erreur instanceof ErreurApi ? "" : String(erreur));
    return;
  }

  ecran.resultats = reponse.resultats;
  dessinerCompteurs(reponse.resume);
  dessinerListe(reponse.resultats, reponse.resume);
  $("#resume-liste").textContent = filtreActif()
    ? `Voir le détail des ${entierFr.format(reponse.resume.total)} diagnostic(s) retenu(s)`
    : `Voir le détail des diagnostics de la commune `
      + `(${entierFr.format(reponse.resume.total)})`;
}

/**
 * Amène la carte sur la commune, la première fois seulement.
 *
 * Le parcours ne retient de la commune que son code et son nom — ils
 * viennent des attributs du bouton cliqué. On va donc chercher son étendue
 * au registre, qui la tient des positions des DPE.
 *
 * « La première fois seulement » compte : revenir sur la carte après avoir
 * ouvert une fiche doit retrouver l'endroit qu'on regardait, pas repartir
 * du centre du bourg.
 */
async function cadrerSurLaCommune() {
  const commune = communeCourante();
  if (!commune || communeCadree === commune.code_insee) return;
  try {
    const { communes } = await api.communes();
    const trouvee = communes.find((c) => c.code_insee === commune.code_insee);
    if (trouvee?.cadre) {
      communeCadree = commune.code_insee;
      carte.cadrerSur(trouvee.cadre);
    }
  } catch (_) { /* on reste où on est : ce n'est pas bloquant */ }
}

function etat(message) {
  $("#carte-etat").innerHTML = message;
}

/**
 * Charge et trace les parcelles du cadre courant, selon les critères.
 *
 * C'est ICI que les filtres agissent : la requête emporte les critères,
 * et le serveur ne compte comme « DPE » que les diagnostics qui y
 * répondent. La carte se recolore donc sur place — même cadre, même
 * échelle, même position — au lieu d'ouvrir un autre écran à côté.
 */
async function rafraichir({ force = false } = {}) {
  const commune = communeCourante();
  if (!commune) {
    etat("Choisissez une commune pour commencer.");
    return;
  }
  if (carte.zoom() < ZOOM_MINIMAL) {
    // On oublie la dernière réponse : elle décrit un cadre qu'on ne
    // montre plus, et une bascule de couche la repeindrait telle quelle.
    oublierLeCadre();
    carte.effacerParcelles();
    carte.poserPoints([]);
    etat("Zoomez pour voir les parcelles&nbsp;: à cette échelle, elles sont " +
         "trop nombreuses et trop petites pour être lisibles.");
    return;
  }

  // Le déplacement qui ne demande rien. Tant que la vue reste dans ce qui
  // est déjà chargé, au même zoom, il n'y a rien à aller chercher : les
  // contours sont là, on ne les touche pas. C'est ce cas-là qui doit être
  // le plus fréquent, et c'est lui qui rend la navigation fluide.
  if (!force && ecran.chargeComplet
      && carte.zoom() === ecran.zoomCharge
      && carte.cadreContient(ecran.cadreCharge)) {
    return;
  }

  // Un déplacement rapide peut lancer plusieurs requêtes ; seule la
  // dernière compte. Sans ce numéro d'ordre, une réponse tardive
  // écraserait l'affichage d'un cadre qu'on a déjà quitté.
  const rang = ++derniereRequete;
  const cadre = carte.cadre(MARGE);
  // La carte GARDE ce qu'elle montre pendant le chargement : la vider
  // d'abord, ou annoncer « Chargement… » à sa place, donnait justement
  // l'impression d'un rechargement. Un discret témoin suffit, et
  // seulement si l'attente se voit.
  const temoin = setTimeout(() => attendre(true), 400);

  let reponse;
  let cadreRetenu = cadre;
  try {
    reponse = await api.parcellesCarte(commune.code_insee, cadre,
                                       null, ecran.filtres);
    // Une réponse tronquée SUR DES PARCELLES RENSEIGNÉES a dépensé son
    // plafond sur la marge autant que sur le visible : de l'information
    // manque sous les yeux. On redemande alors le cadre nu.
    //
    // La distinction est capitale. Les parcelles renseignées passent en
    // tête, donc le plafond ne mord d'ordinaire que sur le VOILE des
    // parcelles sans information — un manque sans conséquence. Traiter
    // les deux pareil, comme je l'ai fait d'abord, revenait à redemander
    // deux fois à chaque geste et à désactiver tout le cache : sur un
    // écran large, 1 549 parcelles pour un plafond de 1 600, donc tronqué
    // presque toujours.
    if (reponse.tronque_utile) {
      cadreRetenu = carte.cadre();
      reponse = await api.parcellesCarte(commune.code_insee, cadreRetenu,
                                         null, ecran.filtres);
    }
  } catch (erreur) {
    clearTimeout(temoin);
    if (rang !== derniereRequete) return;
    attendre(false);
    oublierLeCadre();
    afficherErreur("Les parcelles n'ont pas pu être chargées.", erreur.message);
    return;
  }
  clearTimeout(temoin);
  if (rang !== derniereRequete) return;
  attendre(false);

  masquerErreur();
  ecran.dernieresParcelles = reponse;
  ecran.cadreCharge = cadreRetenu;
  ecran.zoomCharge = carte.zoom();
  // Un cadre amputé d'informations ne peut pas servir à décider qu'un
  // déplacement est inutile. Un voile incomplet, si : rien ne s'y cache.
  ecran.chargeComplet = !reponse.tronque_utile;
  peindre(reponse);
}

/** Le cadre chargé n'est plus fiable : la prochaine vue le redemandera. */
function oublierLeCadre() {
  ecran.dernieresParcelles = null;
  ecran.cadreCharge = null;
  ecran.zoomCharge = null;
  ecran.chargeComplet = false;
}

// Ce qu'on laisse voir sous la carte : de quoi comprendre qu'il y a
// quelque chose en dessous, sans amputer la carte pour autant.
const GOUTTIERE = 10;
const HAUTEUR_MINIMALE = 320;

/**
 * Donne à la carte toute la hauteur restante de la fenêtre.
 *
 * La hauteur était calculée à l'aveugle en CSS —
 * `clamp(380px, 100vh - 320px, 760px)` — avec deux défauts. Les 320 px
 * de bandeau et de filtres étaient DEVINÉS : la rangée de filtres passe
 * à la ligne selon la largeur, et le compte tombait faux dès qu'elle le
 * faisait. Et le plafond de 760 px arrêtait la carte en pleine fenêtre
 * sur un grand écran, laissant du vide sous elle.
 *
 * On mesure donc, et on remesure à chaque changement de largeur : la
 * hauteur des filtres dépend de leur repli, qu'aucune constante ne peut
 * prévoir.
 */
function ajusterHauteurCarte() {
  const boite = $("#carte-exploration");
  if (!boite || $("#vue-carte").hidden) return;
  // Position dans le DOCUMENT, et non dans la fenêtre : la mesure reste
  // juste même si la page est défilée au moment où on la prend.
  const haut = boite.getBoundingClientRect().top + window.scrollY;
  const hauteur = Math.max(HAUTEUR_MINIMALE,
                           window.innerHeight - haut - GOUTTIERE);
  const pose = `${Math.round(hauteur)}px`;
  if (boite.style.height === pose) return;   // rien à faire, rien à agiter
  boite.style.height = pose;
  carte?.redimensionner();
}

/** Un témoin discret, sans toucher à ce que la carte montre déjà. */
function attendre(encours) {
  $("#carte-exploration").dataset.attente = encours ? "oui" : "non";
}

/**
 * Redessine à partir de la dernière réponse, sans rien redemander.
 *
 * Cocher ou décocher une couche ne change pas les DONNÉES : les mêmes
 * parcelles, les mêmes comptes, lus autrement. Repasser par le serveur
 * pour cela ajoutait un aller-retour à un geste qui doit être instantané.
 */
function peindre(reponse) {
  const parcelles = reponse.parcelles || [];
  carte.dessiner(parcelles, ecran.couches);
  // Les losanges ne concernent que les diagnostics : décocher « DPE » les
  // retire avec le reste.
  carte.poserPoints(ecran.couches.dpe ? reponse.points : []);

  const compte = (cle) =>
    parcelles.filter((p) => etatParcelle(p, ecran.couches) === cle).length;
  const morceaux = [`${entierFr.format(parcelles.length)} parcelle(s)`];
  if (ecran.couches.dpe && ecran.couches.ventes) {
    morceaux.push(`${entierFr.format(compte("deux"))} avec DPE et vente`);
  }
  if (ecran.couches.dpe) {
    morceaux.push(`${entierFr.format(compte("dpe"))} DPE seul`);
    const orphelins = (reponse.points || []).length;
    if (orphelins) morceaux.push(`${entierFr.format(orphelins)} sans parcelle`);
  }
  if (ecran.couches.ventes) {
    morceaux.push(`${entierFr.format(compte("vente"))} vente seule`);
  }
  if (ecran.couches.dpe && reponse.points_tronques) {
    morceaux.push("<strong>et d'autres sans parcelle</strong>");
  }

  const resume = morceaux.join(" · ")
    + (filtreActif() ? " — <strong>filtré</strong>" : "");

  // Deux manques bien différents, qu'il serait malhonnête de confondre.
  // Le plafond mord d'abord sur les parcelles dont on ne sait RIEN : la
  // carte reste alors complète sur ce qui compte. Il ne mange les
  // renseignées qu'à très grande échelle, et là il faut le dire.
  let avertissement = "";
  if (reponse.tronque_utile) {
    avertissement = ". <strong>Des parcelles renseignées manquent</strong>"
      + "&nbsp;: zoomez pour toutes les voir.";
  } else if (reponse.tronque) {
    avertissement = ". Le voile des parcelles sans information n'est pas"
      + " complet à cette échelle&nbsp;; les renseignées, elles, y sont toutes.";
  }
  etat(resume + avertissement);
}

/**
 * Un clic sur une parcelle ouvre sa fiche, directement.
 *
 * La bulle intermédiaire n'apportait rien : elle répétait ce que la
 * couleur disait déjà, et imposait un second clic pour arriver là où on
 * allait de toute façon.
 *
 * Les deux chemins mènent à une fiche. Quand la parcelle porte un
 * diagnostic, c'est la fiche du bien, avec sa chronologie ; sinon c'est
 * celle de la parcelle — contour, voisinage, bâti, ventes. Le second cas
 * est de loin le plus fréquent sur la carte.
 */
function ouvrir(parcelle) {
  if (parcelle.n_dpe) {
    ouvrirFiche({ n_dpe: parcelle.n_dpe, retour: "carte" });
  } else {
    ouvrirFiche({ parcelle_id: parcelle.id, retour: "carte" });
  }
}

// --------------------------------------------------------------------
//  Recherche : une adresse, ou une référence cadastrale
// --------------------------------------------------------------------

let minuterieRecherche = null;

async function suggerer() {
  const boite = $("#carte-suggestions");
  const texte = $("#carte-adresse").value.trim();
  const commune = communeCourante();
  if (texte.length < 2 || !commune) {
    boite.hidden = true;
    return;
  }

  let resultats;
  try {
    resultats = (await api.chercherSurCarte(commune.code_insee, texte)).resultats;
  } catch (_) {
    boite.hidden = true;
    return;
  }
  if (!resultats.length) {
    boite.innerHTML = '<li class="suggestion-vide">Aucun résultat dans cette commune.</li>';
    boite.hidden = false;
    return;
  }

  boite.innerHTML = resultats.map((r, index) => `
    <li>
      <button type="button" data-suggestion="${index}">
        <span>${echapper(r.libelle)}</span>
        <span class="donnee">${r.type === "parcelle" ? "parcelle"
          : `${entierFr.format(r.diagnostics || 0)} DPE`}</span>
      </button>
    </li>`).join("");
  boite.hidden = false;
  boite.querySelectorAll("[data-suggestion]").forEach((bouton) => {
    bouton.addEventListener("click", () => {
      const choix = resultats[Number(bouton.dataset.suggestion)];
      boite.hidden = true;
      $("#carte-adresse").value = choix.libelle;
      $("#dialogue-adresse").close();
      carte.allerA(choix.latitude, choix.longitude);
    });
  });
}

export async function initialiserExploration() {
  carte = creerCarteExploration("carte-exploration", {
    surDeplacement: rafraichir,
    surParcelle: ouvrir,
    // Un clic sur un repère ouvre la fiche du bien, comme un clic sur une
    // parcelle : c'est là qu'on allait de toute façon.
    surBien: (numero) => ouvrirFiche({ n_dpe: numero, retour: "carte" }),
  });

  // Leaflet mesure son conteneur à la création : l'écran étant masqué à ce
  // moment-là, il calcule une taille nulle. Il faut le prévenir.
  auChangement("carte", async () => {
    ajusterHauteurCarte();
    carte.redimensionner();
    await cadrerSurLaCommune();
    rafraichir();
  });

  // La hauteur se remesure quand la fenêtre change, et quand la rangée de
  // filtres se replie ou se déplie — c'est elle qui décale la carte.
  window.addEventListener("resize", ajusterHauteurCarte);
  if (typeof ResizeObserver === "function") {
    const observateur = new ResizeObserver(ajusterHauteurCarte);
    observateur.observe($("#filtres"));
    observateur.observe($("#carte-etat"));
  }
  ajusterHauteurCarte();

  surCommunePrete(async () => {
    chargerContexte();
    // Une autre commune, d'autres parcelles : ce qui est tracé n'a plus
    // cours, et le cadre chargé non plus.
    carte.effacerParcelles();
    oublierLeCadre();
    if ($("#vue-carte").hidden) return;
    await cadrerSurLaCommune();
    rafraichir({ force: true });
    chargerListe();
  });
  auTermeDeLImport(() => {
    chargerContexte();
    oublierLeCadre();
    if ($("#vue-carte").hidden) return;
    rafraichir({ force: true });
    chargerListe();
  });

  // La recherche d'adresse tenait une rangée entière en permanence, pour
  // un usage occasionnel. Elle est derrière un bouton.
  $("#ouvrir-adresse").addEventListener("click", () => {
    $("#dialogue-adresse").showModal();
    $("#carte-adresse").focus();
  });
  $("#adresse-fermer").addEventListener("click", () => $("#dialogue-adresse").close());
  $("#carte-adresse").addEventListener("input", () => {
    clearTimeout(minuterieRecherche);
    minuterieRecherche = setTimeout(suggerer, 220);
  });

  // Le geste central : un critère change, la CARTE se recolore. La liste
  // de détail suit, mais c'est la carte qui répond.
  $("#filtres").addEventListener("change", (evenement) => {
    marquerLesFiltres();
    const couches = { dpe: $("#c-dpe").checked, ventes: $("#c-ventes").checked,
                      vides: $("#c-vides").checked };
    // « DPE » et « Ventes » se relisent sur place ; « Le reste » change ce
    // que le serveur envoie, et demande donc un aller-retour.
    const seulementLesCouches =
      evenement.target === $("#c-dpe") || evenement.target === $("#c-ventes");
    ecran.couches = couches;

    // Une couche seule : on repeint ce qu'on a déjà. Rien à redemander.
    if (seulementLesCouches && ecran.dernieresParcelles) {
      peindre(ecran.dernieresParcelles);
      return;
    }

    ecran.filtres = lireFiltres();
    // L'export suit les critères même quand la liste est repliée : le
    // fichier doit contenir ce que la carte montre.
    $("#export-csv").href = api.urlExport(ecran.filtres);
    // Les comptes changent : le cadre déjà chargé ne répond plus à la
    // question posée, si large soit-il.
    rafraichir({ force: true });
    chargerListe();
  });

  // Ouvrir le détail, c'est demander la liste. On ne la recharge que si
  // les critères ont bougé depuis la dernière fois.
  $("#detail-liste").addEventListener("toggle", () => {
    if ($("#detail-liste").open && !ecran.listeAJour) chargerListe();
  });
  $("#filtres").addEventListener("submit", (e) => e.preventDefault());

  // Revenir à la carte standard doit tenir en un geste — c'est ce qui
  // manquait le plus : une fois un filtre posé, plus rien ne ramenait à
  // la vue d'ensemble.
  $("#tout-effacer").addEventListener("click", () => {
    const formulaire = $("#filtres");
    formulaire.reset();
    $("#c-dpe").checked = true;
    $("#c-ventes").checked = true;
    formulaire.dispatchEvent(new Event("change", { bubbles: true }));
  });
  // Un chiffre saisi au clavier ne declenche « change » qu'a la sortie du
  // champ : la marque, elle, doit suivre la frappe.
  $("#filtres").addEventListener("input", marquerLesFiltres);

  $("#marquer-vus").addEventListener("click", async () => {
    try {
      const { marques } = await api.marquerVus(null);
      afficherSucces(marques ? `${marques} logement(s) marqué(s) comme vus.`
                             : "Rien à marquer.");
      chargerListe();
    } catch (erreur) {
      afficherErreur(erreur.message);
    }
  });

  // Filtres repliables, fermés d'emblée sur téléphone : la première chose
  // visible doit être la carte.
  const surTelephone = window.matchMedia("(max-width: 700px)");
  const replierFiltres = (replie) => {
    $("#filtres").dataset.replie = replie ? "oui" : "non";
    $("#bascule-filtres").setAttribute("aria-expanded", String(!replie));
    ajusterHauteurCarte();
  };
  replierFiltres(surTelephone.matches);
  surTelephone.addEventListener("change", (e) => replierFiltres(e.matches));
  $("#bascule-filtres").addEventListener("click", () => {
    replierFiltres($("#filtres").dataset.replie === "non");
  });

  // Les réglages autorisent n'importe quelle fenêtre (45 jours par
  // exemple) : on l'ajoute au menu si elle y manque, pour que le
  // périmètre exact du courriel d'alerte soit à un clic. Rien n'est
  // sélectionné pour autant — l'écran s'ouvre sur la carte standard.
  try {
    appliquerFiltres((await api.veille({})).filtres);
  } catch (_) { /* le menu reste celui de la page */ }
  marquerLesFiltres();
}
