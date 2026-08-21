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
  const couchePolygones = L.layerGroup().addTo(carte);
  const marqueurs = new Map();

  function icone(classes) {
    return L.divIcon({
      className: "",
      html: `<div class="${classes}"></div>`,
      iconSize: [14, 14],
      iconAnchor: [7, 7],
    });
  }

  return {
    /** Place un marqueur par bien positionné et cadre la carte dessus. */
    afficher(resultats) {
      couche.clearLayers();
      marqueurs.clear();

      const points = [];
      for (const bien of resultats) {
        if (bien.latitude == null || bien.longitude == null) continue;
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

    /**
     * Trace les parcelles retenues. Le contour à l'encre sur fond clair,
     * comme sur un plan cadastral ; l'ambre signale celles qui portent un
     * diagnostic récent — le croisement qui compte.
     */
    afficherParcelles(resultats) {
      couchePolygones.clearLayers();
      const points = [];

      for (const parcelle of resultats) {
        if (!parcelle.geometrie) continue;
        const recente = Boolean(parcelle.dpe_recent);
        const forme = L.geoJSON(parcelle.geometrie, {
          style: {
            color: recente ? "#B9862C" : "#12262B",
            weight: recente ? 2 : 1,
            fillColor: recente ? "#D9A441" : "#2E5B4C",
            fillOpacity: recente ? 0.35 : 0.12,
          },
        });
        const reference = `${parcelle.section ?? ""}${parcelle.numero ?? ""}`;
        forme.bindPopup(
          `<span class="adresse-popup">${(parcelle.adresses?.[0] || "Parcelle " + reference)
            .replace(/</g, "&lt;")}</span>` +
          `<span class="donnee">terrain ${Math.round(parcelle.contenance_m2 ?? 0)} m² · ` +
          `bâti ${Math.round(parcelle.emprise_batie_m2 ?? 0)} m²` +
          (parcelle.dpe ? ` · ${parcelle.dpe} DPE` : "") + "</span>"
        );
        forme.on("click", () => surSelection && surSelection(parcelle.id));
        forme.addTo(couchePolygones);
        if (parcelle.latitude != null) points.push([parcelle.latitude, parcelle.longitude]);
      }

      if (points.length) {
        carte.fitBounds(L.latLngBounds(points), { padding: [30, 30], maxZoom: 17 });
      }
      return points.length;
    },

    /** Met en avant une parcelle choisie dans la liste. */
    centrerSur(latitude, longitude) {
      if (latitude == null || longitude == null) return;
      carte.setView([latitude, longitude], Math.max(carte.getZoom(), 17));
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
 * sans vente ne racontent pas la même histoire. L'ambre — la couleur du
 * signal « nouveau » ailleurs dans l'application — est donc réservée aux
 * deux à la fois.
 *
 * Les teintes sont posées sur photo aérienne : chaque contour porte un
 * liseré blanc, sans quoi il disparaîtrait sur une toiture claire ou dans
 * l'ombre d'un arbre.
 */
export const ETATS_PARCELLE = {
  deux:  { libelle: "DPE et vente", couleur: "#D9A441", remplissage: 0.55 },
  dpe:   { libelle: "DPE seul",     couleur: "#2E5B4C", remplissage: 0.45 },
  vente: { libelle: "Vente seule",  couleur: "#14708C", remplissage: 0.45 },
  rien:  { libelle: "Rien de connu", couleur: "#F1F3F1", remplissage: 0.10 },
};

export function etatParcelle(parcelle) {
  const dpe = Number(parcelle.dpe) > 0;
  const vente = Number(parcelle.ventes) > 0;
  if (dpe && vente) return "deux";
  if (dpe) return "dpe";
  if (vente) return "vente";
  return "rien";
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
export function creerCarteExploration(identifiant, { surDeplacement, surParcelle }) {
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
  let dernierTrace = null;

  // Le déplacement est continu, le rechargement ne doit pas l'être : on
  // attend que la main se pose. Sans cela, un simple glissement lancerait
  // dix requêtes dont neuf seraient périmées à l'arrivée.
  let minuterie = null;
  carte.on("moveend", () => {
    clearTimeout(minuterie);
    minuterie = setTimeout(() => surDeplacement && surDeplacement(), 250);
  });

  return {
    /** Le cadre affiché, dans l'ordre attendu par l'API. */
    cadre() {
      const b = carte.getBounds();
      return [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()].join(",");
    },

    zoom() { return carte.getZoom(); },

    /** Trace les parcelles reçues, chacune selon son état. */
    dessiner(parcelles) {
      couche.clearLayers();
      for (const parcelle of parcelles) {
        if (!parcelle.geometrie) continue;
        const etat = ETATS_PARCELLE[etatParcelle(parcelle)];
        const forme = L.geoJSON(parcelle.geometrie, {
          style: {
            color: "#FFFFFF",
            weight: 1.2,
            opacity: 0.9,
            fillColor: etat.couleur,
            fillOpacity: etat.remplissage,
            lineJoin: "round",
          },
        });
        forme.on("click", () => surParcelle && surParcelle(parcelle, forme));
        forme.addTo(couche);
      }
      return parcelles.length;
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
