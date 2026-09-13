// ====================================================================
//  carte.js — La carte Leaflet, en regard de la liste.
//
//  Fonds IGN et OpenStreetMap (CDC 3). Leaflet est auto-heberge dans
//  l'image : aucun CDN, l'application fonctionne si le NAS perd Internet
//  — seules les tuiles manqueront alors.
// ====================================================================

// Centre d'ouverture, le temps que les marqueurs arrivent : la France, pour
// ne rien présumer du territoire surveillé. `afficher()` recadre ensuite sur
// les biens trouvés.
const FRANCE = [46.6, 2.4];

const ATTRIBUTION_IGN =
  '<a href="https://geoservices.ign.fr/">IGN-F/Géoportail</a>';

/** Le repère d'un diagnostic. Deux cartes s'en servent. */
function icone(classes) {
  return L.divIcon({
    className: "",
    html: `<div class="${classes}"></div>`,
    iconSize: [14, 14],
    iconAnchor: [7, 7],
  });
}

/**
 * Le repère d'un bien, prêt à poser sur une couche.
 *
 * Les repères ne remplacent pas les parcelles, ils s'y ajoutent — et
 * c'est ce qui compte : sur un an à Mimizan, 18 diagnostics sur 307 ne
 * sont rattachés à AUCUNE parcelle, faute d'un géocodage assez fin chez
 * l'ADEME (« Avenue des Castors », sans numéro). Une carte qui ne
 * connaîtrait que le cadastre les perdrait en silence. Leurs coordonnées,
 * elles, existent : un repère les montre.
 */
function repere(bien, surSelection) {
  const marqueur = L.marker([bien.latitude, bien.longitude], {
    icon: icone(bien.nouveau ? "marqueur marqueur-nouveau" : "marqueur"),
    keyboard: true,
    title: bien.adresse || bien.n_dpe,
  });
  marqueur.bindPopup(
    `<span class="adresse-popup">${(bien.adresse || "adresse absente")
      .replace(/</g, "&lt;")}</span>` +
      `<span class="donnee">${bien.date_etablissement || "?"} · ` +
      `${bien.surface_habitable ?? "?"} m² · ${bien.etiquette_dpe || "?"}</span>`
  );
  marqueur.on("click", () => surSelection && surSelection(bien.n_dpe));
  return marqueur;
}

function tuilesIgn(couche, format = "image/png") {
  return L.tileLayer(
    "https://data.geopf.fr/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0" +
      `&LAYER=${couche}&STYLE=normal&TILEMATRIXSET=PM&FORMAT=${format}` +
      "&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}",
    { maxZoom: 19, attribution: ATTRIBUTION_IGN }
  );
}

export function creerCarte(identifiant, surSelection) {
  const plan = tuilesIgn("GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2");
  const carte = L.map(identifiant, {
    center: FRANCE,
    zoom: 5,
    layers: [plan],
    zoomControl: true,
  });

  const fonds = {
    "Plan IGN": plan,
    "Vue aérienne": tuilesIgn("ORTHOIMAGERY.ORTHOPHOTOS", "image/jpeg"),
    OpenStreetMap: L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    }),
  };

  // Le parcellaire en superposition : c'est deja la matiere du lot 3,
  // et il rend la lecture d'une adresse beaucoup plus concrete.
  const superpositions = {
    "Parcelles cadastrales": L.tileLayer(
      "https://data.geopf.fr/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0" +
        "&LAYER=CADASTRALPARCELS.PARCELLAIRE_EXPRESS&STYLE=PCI%20vecteur" +
        "&TILEMATRIXSET=PM&FORMAT=image/png&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}",
      { maxZoom: 19, opacity: 0.7, attribution: ATTRIBUTION_IGN }
    ),
  };

  L.control.layers(fonds, superpositions, { position: "topright" }).addTo(carte);

  const couche = L.layerGroup().addTo(carte);
  const marqueurs = new Map();

  return {
    /** Place un marqueur par bien positionné et cadre la carte dessus. */
    afficher(resultats) {
      couche.clearLayers();
      marqueurs.clear();

      const points = [];
      for (const bien of resultats) {
        if (bien.latitude == null || bien.longitude == null) continue;
        const marqueur = repere(bien, surSelection);
        marqueur.addTo(couche);
        marqueurs.set(bien.n_dpe, marqueur);
        points.push([bien.latitude, bien.longitude]);
      }

      if (points.length) {
        carte.fitBounds(L.latLngBounds(points), { padding: [30, 30], maxZoom: 16 });
      }
      return points.length;
    },

    /** Met en avant un bien sélectionné dans la liste. */
    surligner(numero) {
      for (const [cle, marqueur] of marqueurs) {
        const bienNouveau = marqueur.options.icon.options.html.includes("nouveau");
        marqueur.setIcon(
          icone(
            cle === numero
              ? "marqueur marqueur-actif"
              : bienNouveau
              ? "marqueur marqueur-nouveau"
              : "marqueur"
          )
        );
      }
      const cible = marqueurs.get(numero);
      if (cible) {
        carte.panTo(cible.getLatLng());
        cible.openPopup();
      }
    },

    /** À appeler quand le conteneur change de taille (repli sur mobile). */
    redimensionner() {
      carte.invalidateSize();
    },
  };
}


/**
 * Les quatre états d'une parcelle sur la carte d'exploration.
 *
 * C'est le CROISEMENT qui informe, pas chaque fait pris seul : une
 * parcelle vendue sans diagnostic récent et une parcelle diagnostiquée
 * sans vente ne racontent pas la même histoire. Le jaune, le plus visible
 * des trois, est donc réservé aux deux à la fois.
 *
 * Trois teintes seulement portent de l'information : « rien de connu »
 * est une absence, pas une catégorie, et se contente d'un voile blanc.
 *
 * LES VALEURS NE SONT PAS CHOISIES À L'ŒIL. Une carte est un cas « toutes
 * paires » — n'importe quelles deux parcelles peuvent se toucher — et le
 * fond est une photo, donc l'opacité mélange chaque teinte au paysage.
 * Le couple (teinte, opacité) a été retenu en composant chaque état sur
 * trois fonds réels du littoral landais — pinède #4a5a3f, teinte moyenne
 * #7d7a6a, sable #d8cbb0 — puis en mesurant la séparation obtenue.
 *
 * Résultat : séparation en vision normale ≥ 22,1 (plancher 15) et sous
 * daltonisme ≥ 9,7 (cible 8), sur les trois fonds. Le jeu précédent —
 * vert et bleu sombres à 45 % — tombait à 10,5 en vision normale : deux
 * couleurs que l'œil ne distinguait pas, ce qui se voyait à l'usage.
 *
 * L'opacité compte autant que la teinte : à 45 % la photo l'emporte et
 * les états se rejoignent. Il faut 65 % pour franchir le plancher, d'où
 * les 70 % retenus. « Les deux » monte à 92 % — c'est l'état le plus rare
 * (10 parcelles sur 550) et celui qu'on cherche.
 *
 * Chaque contour porte un liseré blanc plein : sur une photo, une teinte
 * seule disparaît contre une toiture claire ou dans l'ombre d'un arbre.
 */
export const ETATS_PARCELLE = {
  deux:  { libelle: "DPE et vente",  couleur: "#EDA100", remplissage: 0.92 },
  dpe:   { libelle: "DPE seul",      couleur: "#008300", remplissage: 0.70 },
  vente: { libelle: "Vente seule",   couleur: "#2A78D6", remplissage: 0.70 },
  rien:  { libelle: "Rien de connu", couleur: "#FFFFFF", remplissage: 0.12 },
};

/**
 * L'état d'une parcelle, selon les couches DEMANDÉES.
 *
 * Décocher « Ventes » ne masque pas seulement les parcelles bleues : une
 * parcelle « les deux » redevient « DPE seul », car c'est bien ce qu'on
 * en sait une fois les ventes mises de côté. Sans cela, la couleur la
 * plus visible de la carte — celle du croisement — répondrait encore à
 * une question qu'on vient de retirer.
 */
export function etatParcelle(parcelle, couches = {}) {
  const avecDpe = couches.dpe !== false;
  const avecVentes = couches.ventes !== false;
  const dpe = avecDpe && Number(parcelle.dpe) > 0;
  const vente = avecVentes && Number(parcelle.ventes) > 0;
  if (dpe && vente) return "deux";
  if (dpe) return "dpe";
  if (vente) return "vente";
  return "rien";
}

/** Tous ses diagnostics sont-ils situés par approche, et non par appartenance ? */
export function parcelleApprochee(parcelle) {
  const total = Number(parcelle.dpe) || 0;
  return total > 0 && (Number(parcelle.dpe_approche) || 0) >= total;
}


/**
 * La carte d'exploration : photo aérienne, parcellaire, et nos parcelles
 * colorées par-dessus.
 *
 * Elle diffère de `creerCarte` sur un point qui change tout : elle expose
 * son cadre et prévient quand il bouge. C'est ce qui permet de ne charger
 * que les parcelles visibles — les 11 444 de Mimizan pèsent 3,8 Mo, et les
 * envoyer d'un bloc rendrait la carte inutilisable sur téléphone.
 */
/**
 * Ce qui a empêché de savoir où l'on est. `motif` sert à choisir le
 * message : refuser la permission et servir la page en clair ne se
 * corrigent pas du tout de la même façon.
 */
export class ErreurPosition extends Error {
  constructor(message, motif) {
    super(message);
    this.name = "ErreurPosition";
    this.motif = motif;
  }
}

/**
 * La position du téléphone, une fois.
 *
 * LE CONTEXTE SÉCURISÉ EST VÉRIFIÉ D'ABORD, et ce n'est pas une
 * précaution théorique : servie en http:// depuis le NAS, la page verrait
 * `navigator.geolocation` exister puis échouer en « permission refusée »,
 * et on chercherait le problème du mauvais côté. Le navigateur réserve la
 * géolocalisation aux origines sûres — https:// ou localhost.
 *
 * `maximumAge` accepte une position d'une demi-minute : se localiser deux
 * fois de suite ne doit pas rallumer le GPS.
 */
export function positionGps({ delai = 15000 } = {}) {
  return new Promise((resoudre, rejeter) => {
    if (typeof window !== "undefined" && window.isSecureContext === false) {
      rejeter(new ErreurPosition(
        "La géolocalisation demande une connexion sécurisée (https://). "
        + "Cette page est servie en clair : le navigateur la refuse.",
        "non-securise"));
      return;
    }
    if (!navigator.geolocation) {
      rejeter(new ErreurPosition(
        "Ce navigateur ne sait pas donner de position.", "absent"));
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (position) => resoudre({
        latitude: position.coords.latitude,
        longitude: position.coords.longitude,
        precision: position.coords.accuracy,
      }),
      (erreur) => {
        const motifs = {
          1: ["Position refusée. Autorisez la localisation pour ce site dans "
              + "les réglages du navigateur.", "refuse"],
          2: ["Position indisponible : le téléphone n'a pas réussi à se situer.",
              "indisponible"],
          3: ["Le téléphone a mis trop de temps à se situer. Réessayez à "
              + "découvert.", "trop-long"],
        };
        const [message, motif] = motifs[erreur?.code]
          || ["Position introuvable.", "inconnu"];
        rejeter(new ErreurPosition(message, motif));
      },
      { enableHighAccuracy: true, timeout: delai, maximumAge: 30000 });
  });
}


export function creerCarteExploration(identifiant,
                                      { surDeplacement, surParcelle, surBien }) {
  const aerienne = tuilesIgn("ORTHOIMAGERY.ORTHOPHOTOS", "image/jpeg");
  const carte = L.map(identifiant, {
    center: FRANCE,
    zoom: 6,
    layers: [aerienne],
    zoomControl: true,
  });

  const parcellaire = L.tileLayer(
    "https://data.geopf.fr/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0" +
      "&LAYER=CADASTRALPARCELS.PARCELLAIRE_EXPRESS&STYLE=PCI%20vecteur" +
      "&TILEMATRIXSET=PM&FORMAT=image/png&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}",
    { maxZoom: 19, opacity: 0.6, attribution: ATTRIBUTION_IGN }
  ).addTo(carte);

  L.control.layers(
    {
      "Vue aérienne": aerienne,
      "Plan IGN": tuilesIgn("GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2"),
      OpenStreetMap: L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19,
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      }),
    },
    { "Parcellaire IGN": parcellaire },
    { position: "topright" }
  ).addTo(carte);

  const couche = L.layerGroup().addTo(carte);
  // Les repères des diagnostics vivent SUR une couche à part, ajoutée
  // après celle des parcelles : un rechargement du cadastre ne doit pas
  // les effacer, et ils doivent rester au-dessus des contours.
  const coucheBiens = L.layerGroup().addTo(carte);
  // La position de l'utilisateur vit encore ailleurs : elle ne doit être
  // effacée ni par un rechargement du cadastre, ni par un changement de
  // filtre. On s'y repère pendant qu'on explore.
  const couchePosition = L.layerGroup().addTo(carte);
  const marqueurs = new Map();
  // Les contours déjà posés, par identifiant de parcelle. C'est la clef de
  // la fluidité : on ne rebâtit pas, on ajuste.
  const contours = new Map();
  let dernierTrace = null;

  // Le déplacement est continu, le rechargement ne doit pas l'être : on
  // attend que la main se pose. Sans cela, un simple glissement lancerait
  // dix requêtes dont neuf seraient périmées à l'arrivée.
  let minuterie = null;
  carte.on("moveend", () => {
    clearTimeout(minuterie);
    minuterie = setTimeout(() => surDeplacement && surDeplacement(), 160);
  });

  function styleDe(parcelle, couches) {
    const etat = ETATS_PARCELLE[etatParcelle(parcelle, couches)];
    const approchee = parcelleApprochee(parcelle)
      && etatParcelle(parcelle, couches) !== "rien";
    return {
      color: "#FFFFFF",
      weight: approchee ? 2.5 : 1.5,
      opacity: 1,
      dashArray: approchee ? "4 3" : null,
      fillColor: etat.couleur,
      fillOpacity: etat.remplissage,
      lineJoin: "round",
    };
  }

  /** Deux styles se valent-ils ? Restyler coûte ; ne rien faire, non. */
  function memeStyle(a, b) {
    return a && b && a.fillColor === b.fillColor && a.weight === b.weight
      && a.fillOpacity === b.fillOpacity && a.dashArray === b.dashArray;
  }

  return {
    /**
     * Le cadre affiché, dans l'ordre attendu par l'API.
     *
     * `marge` l'ÉLARGIT : on charge plus large que ce qu'on montre, de
     * sorte qu'un petit déplacement retombe dans ce qui est déjà là et ne
     * demande rien. 0,6 veut dire 60 % de la largeur de part et d'autre.
     */
    cadre(marge = 0) {
      const b = carte.getBounds().pad(marge);
      return [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()].join(",");
    },

    /** Le cadre visible est-il entièrement compris dans celui-ci ? */
    cadreContient(bbox) {
      if (!bbox) return false;
      const [o, s, e, n] = String(bbox).split(",").map(Number);
      if ([o, s, e, n].some(Number.isNaN)) return false;
      return L.latLngBounds([s, o], [n, e]).contains(carte.getBounds());
    },

    zoom() { return carte.getZoom(); },

    /**
     * Met la carte À JOUR — elle ne la refait pas.
     *
     * C'est toute la différence entre un déplacement fluide et une
     * sensation de rechargement. L'ancienne version vidait la couche puis
     * reconstruisait mille contours : l'écran se vidait un instant, et
     * chaque parcelle encore à l'écran était jetée puis recréée à
     * l'identique.
     *
     * Ici, trois gestes seulement : on ajoute ce qui arrive, on retire ce
     * qui est parti, et on ne restyle que ce qui a changé de couleur. Une
     * parcelle qui reste à l'écran n'est jamais touchée — et rien ne
     * clignote.
     *
     * `couches` dit ce qu'on regarde — les DPE, les ventes, ou les deux.
     * Une parcelle dont tous les diagnostics sont situés PAR APPROCHE
     * porte un contour tireté : la couleur dit ce qu'on sait, le tireté
     * dit à quel point on en est sûr.
     */
    dessiner(parcelles, couches = {}) {
      const vues = new Set();

      for (const parcelle of parcelles) {
        if (!parcelle.geometrie) continue;
        vues.add(parcelle.id);
        const style = styleDe(parcelle, couches);
        const connu = contours.get(parcelle.id);

        if (connu) {
          // Déjà à l'écran : on ne la retrace pas. Au plus, on la repeint.
          if (!memeStyle(connu.style, style)) {
            connu.forme.setStyle(style);
            connu.style = style;
          }
          connu.parcelle = parcelle;
          continue;
        }

        const forme = L.geoJSON(parcelle.geometrie, { style });
        const entree = { forme, style, parcelle };
        // Le clic lit l'entrée, jamais la parcelle capturée à la création :
        // les comptes changent avec les filtres, la forme non.
        forme.on("click", () => surParcelle && surParcelle(entree.parcelle));
        forme.addTo(couche);
        contours.set(parcelle.id, entree);
      }

      for (const [identifiant, entree] of contours) {
        if (vues.has(identifiant)) continue;
        couche.removeLayer(entree.forme);
        contours.delete(identifiant);
      }
      return parcelles.length;
    },

    /** Tout retirer — au changement de commune, ou sous le seuil de zoom. */
    effacerParcelles() {
      couche.clearLayers();
      contours.clear();
    },

    /**
     * Les diagnostics qu'aucune parcelle ne porte, posés en losange.
     *
     * Une forme DIFFÉRENTE, pas une couleur de plus : ce qui les sépare
     * des autres n'est pas ce qu'on en sait, c'est qu'on ne sait pas OÙ
     * ils sont exactement. Les adresses sans numéro de rue sont géocodées
     * au milieu de la voie ; les attribuer à l'une des parcelles qui la
     * bordent serait inventer.
     */
    poserPoints(points, surBienChoisi) {
      coucheBiens.clearLayers();
      marqueurs.clear();
      for (const bien of points || []) {
        if (bien.latitude == null || bien.longitude == null) continue;
        const marqueur = L.marker([bien.latitude, bien.longitude], {
          icon: L.divIcon({
            className: "",
            html: '<div class="losange" title="diagnostic sans parcelle"></div>',
            iconSize: [16, 16],
            iconAnchor: [8, 8],
          }),
          keyboard: true,
          title: `${bien.adresse || bien.n_dpe} — sans parcelle`,
        });
        marqueur.bindPopup(
          `<span class="adresse-popup">${(bien.adresse || "adresse absente")
            .replace(/</g, "&lt;")}</span>` +
          `<span class="donnee">${bien.date_etablissement || "?"} · ` +
          `${bien.surface_habitable ?? "?"} m² · ${bien.etiquette_dpe || "?"}</span>` +
          '<span class="donnee">aucune parcelle : adresse trop imprécise</span>');
        marqueur.on("click", () =>
          (surBienChoisi || surBien) && (surBienChoisi || surBien)(bien.n_dpe));
        marqueur.addTo(coucheBiens);
        marqueurs.set(bien.n_dpe, marqueur);
      }
      return (points || []).length;
    },

    /** Met une parcelle en avant, et l'amène à l'écran. */
    surligner(parcelle) {
      if (dernierTrace) { couche.removeLayer(dernierTrace); dernierTrace = null; }
      if (!parcelle?.geometrie) return;
      dernierTrace = L.geoJSON(parcelle.geometrie, {
        style: { color: "#A33A2A", weight: 3, fillOpacity: 0, lineJoin: "round" },
      }).addTo(couche);
      carte.fitBounds(dernierTrace.getBounds(), { padding: [60, 60], maxZoom: 19 });
    },

    /** Met en avant le bien choisi dans la liste. */
    surlignerBien(numero) {
      for (const [cle, marqueur] of marqueurs) {
        const nouveau = marqueur.options.icon.options.html.includes("nouveau");
        marqueur.setIcon(icone(
          cle === numero ? "marqueur marqueur-actif"
            : nouveau ? "marqueur marqueur-nouveau" : "marqueur"));
      }
      const cible = marqueurs.get(numero);
      if (!cible) return false;
      carte.panTo(cible.getLatLng());
      cible.openPopup();
      return true;
    },

    allerA(latitude, longitude, zoom = 18) {
      if (latitude == null || longitude == null) return;
      carte.setView([latitude, longitude], zoom);
    },

    /**
     * Amène la carte sur une commune, à une échelle où elle sert.
     *
     * Cadrer la commune entière n'est pas ce qu'on veut : Mimizan fait 7 km
     * de large, ce qui place la carte sous le seuil d'affichage des
     * parcelles — on arriverait sur une photo vide et un message. On se
     * pose donc au centre, à une échelle de quartier, quitte à laisser
     * dézoomer ensuite.
     */
    cadrerSur(bornes, zoom = 16) {
      const latitude = (bornes.lat_min + bornes.lat_max) / 2;
      const longitude = (bornes.lon_min + bornes.lon_max) / 2;
      carte.setView([latitude, longitude], zoom);
    },

    /**
     * Pose « vous êtes ici » et amène la carte dessus.
     *
     * Le cercle n'est pas un ornement : sous les arbres ou en ville, le
     * GPS d'un téléphone donne cinquante mètres, et une punaise seule
     * laisserait croire à une précision qu'on n'a pas. Le zoom suit la
     * même logique — on ne cadre pas à la parcelle une position connue à
     * cent mètres près.
     */
    maPosition({ latitude, longitude, precision }) {
      couchePosition.clearLayers();
      if (latitude == null || longitude == null) return;
      const rayon = Number(precision) || 0;
      if (rayon > 0) {
        L.circle([latitude, longitude], {
          radius: rayon, color: "#14708C", weight: 1,
          fillColor: "#14708C", fillOpacity: 0.12,
        }).addTo(couchePosition);
      }
      L.marker([latitude, longitude], {
        icon: L.divIcon({
          className: "",
          html: '<div class="ma-position" title="Votre position"></div>',
          iconSize: [18, 18], iconAnchor: [9, 9],
        }),
        keyboard: true, title: "Votre position",
      }).addTo(couchePosition);

      const zoom = rayon > 200 ? 15 : rayon > 60 ? 16 : 18;
      carte.setView([latitude, longitude], zoom);
    },

    /** Retire « vous êtes ici » — changement de commune, par exemple. */
    oublierMaPosition() { couchePosition.clearLayers(); },

    redimensionner() { carte.invalidateSize(); },
  };
}


/**
 * Vue satellite d'un extrait cadastral, cadrée exactement comme le dessin
 * qui l'accompagne.
 *
 * `zoomSnap: 0` autorise un niveau de zoom fractionnaire : sans lui,
 * Leaflet se cale sur un zoom entier et le cadrage ne correspond plus à
 * celui de l'extrait — c'est justement la comparaison qui est demandée.
 */
export function creerVueSatellite(identifiant, bornes) {
  const conteneur = document.getElementById(identifiant);
  const carte = L.map(identifiant, {
    zoomSnap: 0,
    zoomControl: false,
    attributionControl: false,
    dragging: false,
    scrollWheelZoom: false,
    doubleClickZoom: false,
    touchZoom: false,
    keyboard: false,
  });

  tuilesIgn("ORTHOIMAGERY.ORTHOPHOTOS", "image/jpeg").addTo(carte);
  carte.fitBounds([[bornes.lat_min, bornes.lon_min],
                   [bornes.lat_max, bornes.lon_max]], { padding: [0, 0] });

  const vue = {
    /**
     * Reporte le contour de la parcelle sur la photo.
     *
     * Deux traits superposés : un sombre et large dessous, un clair et fin
     * dessus. C'est la solution cartographique classique — un trait d'une
     * seule couleur disparaît selon ce qu'il survole, toiture claire ou
     * ombre d'arbre.
     */
    tracer(geometrie, options = {}) {
      if (!geometrie) return;
      const dessiner = (couleur, epaisseur) =>
        L.geoJSON(geometrie, {
          style: { color: couleur, weight: epaisseur, fillOpacity: 0,
                   lineJoin: "round" },
        }).addTo(carte);
      dessiner(options.gaine || "#12262B", (options.epaisseur || 2) + 2.5);
      dessiner(options.couleur || "#FFFFFF", options.epaisseur || 2);
    },
    redimensionner() {
      carte.invalidateSize();
      carte.fitBounds([[bornes.lat_min, bornes.lon_min],
                       [bornes.lat_max, bornes.lon_max]], { padding: [0, 0] });
    },

    // Les deux méthodes qui suivent servent à vérifier que le dessin et la
    // photo montrent bien le même rectangle — c'est tout l'intérêt de les
    // mettre côte à côte, et rien dans le rendu ne le prouve à l'œil.
    // Mesurer le tracé par `getBoundingClientRect` ne marche pas : sous la
    // pile de transformations de Leaflet, il ne rend pas la position écran.

    /** Où tombe une coordonnée dans le conteneur, en pixels. */
    pointDe(longitude, latitude) {
      const p = carte.latLngToContainerPoint([latitude, longitude]);
      return { x: p.x, y: p.y };
    },

    /** Ce que la vue montre réellement — sert à vérifier le cadrage. */
    bornesAffichees() {
      const b = carte.getBounds();
      return { lon_min: b.getWest(), lon_max: b.getEast(),
               lat_min: b.getSouth(), lat_max: b.getNorth() };
    },

    detruire() { carte.remove(); },
  };

  // Comme Leaflet marque ses conteneurs, on rattache la vue au sien : elle
  // reste ainsi mesurable et destructible depuis l'extérieur.
  conteneur._vueSatellite = vue;
  return vue;
}
