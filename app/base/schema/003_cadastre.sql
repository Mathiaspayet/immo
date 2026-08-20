-- =====================================================================
--  003_cadastre.sql — Parcelles cadastrales (F3)
-- =====================================================================
--  Source : cadastre Etalab, GeoJSON par commune. La `contenance` est la
--  surface officielle du terrain, telle que le cadastre la publie — on ne
--  la recalcule pas. L'emprise batie, elle, se deduit des batiments
--  rattaches a la parcelle.
-- =====================================================================

CREATE TABLE IF NOT EXISTS parcelle (
    id              TEXT PRIMARY KEY,      -- identifiant cadastral complet
    code_insee      TEXT NOT NULL,
    prefixe         TEXT,
    section         TEXT,
    numero          TEXT,

    contenance_m2   REAL,                  -- surface du terrain, officielle
    emprise_batie_m2 REAL,                 -- somme des batiments rattaches
    nb_batiments    INTEGER DEFAULT 0,

    -- Centre et boite englobante : le centre situe la parcelle, la boite
    -- permet de la retrouver sans deserialiser sa geometrie.
    latitude        REAL,
    longitude       REAL,
    lat_min         REAL,
    lat_max         REAL,
    lon_min         REAL,
    lon_max         REAL,

    -- Le contour, pour la carte et pour l'extrait de la fiche.
    geometrie_json  TEXT,

    importe_le      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_parcelle_commune  ON parcelle (code_insee);
CREATE INDEX IF NOT EXISTS idx_parcelle_criteres ON parcelle (code_insee, contenance_m2, emprise_batie_m2);
-- Retrouver la parcelle qui contient un point : on presele par la boite
-- englobante avant de tester le contour, bien plus couteux.
CREATE INDEX IF NOT EXISTS idx_parcelle_boite    ON parcelle (lat_min, lat_max);

-- ---------------------------------------------------------------------
--  Recoupement F1/F2 x F3 (CDC F3) : « une adresse presente dans deux
--  modules est un candidat quasi certain ». On rattache donc chaque DPE a
--  la parcelle qui le contient, une fois pour toutes a l'import du
--  cadastre — le faire a chaque requete couterait un lancer de rayon par
--  DPE et par parcelle.
-- ---------------------------------------------------------------------
ALTER TABLE dpe ADD COLUMN parcelle_id TEXT;
CREATE INDEX IF NOT EXISTS idx_dpe_parcelle ON dpe (parcelle_id);
