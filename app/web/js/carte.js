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
