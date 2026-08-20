-- =====================================================================
--  004_batiments.sql — Les batiments, pour l'extrait cadastral
-- =====================================================================
--  L'import du lot 3 ne gardait que l'agregat : emprise totale et nombre
--  de batiments par parcelle. La fiche d'un bien demande de les DESSINER,
--  et avec les parcelles voisines : il faut donc leurs contours.
--
--  Le cout est modeste — 1,5 Mo pour Launaguet, 2,9 Mo pour Mimizan.
-- =====================================================================

CREATE TABLE IF NOT EXISTS batiment (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    code_insee    TEXT NOT NULL,
    parcelle_id   TEXT,                  -- NULL si sur aucune parcelle connue
    -- Le cadastre distingue le bati « dur » du bati « leger » : un abri de
    -- jardin ne se lit pas comme une maison.
    type          TEXT,
    surface_m2    REAL,
    lat_min       REAL,
    lat_max       REAL,
    lon_min       REAL,
    lon_max       REAL,
    geometrie_json TEXT NOT NULL,
    importe_le    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_batiment_commune  ON batiment (code_insee);
CREATE INDEX IF NOT EXISTS idx_batiment_parcelle ON batiment (parcelle_id);
-- Retrouver ce qui tombe dans un cadre : on preselectionne par la latitude,
-- puis on affine sur la longitude.
CREATE INDEX IF NOT EXISTS idx_batiment_boite    ON batiment (code_insee, lat_min, lat_max);
CREATE INDEX IF NOT EXISTS idx_parcelle_cadre    ON parcelle (code_insee, lat_min, lat_max);
