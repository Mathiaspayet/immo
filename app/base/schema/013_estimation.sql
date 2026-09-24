-- =====================================================================
--  013_estimation.sql — Estimer la valeur d'un bien
-- =====================================================================
--  L'estimation apprend sur les ventes de TOUT un departement, pas de la
--  seule commune suivie : l'etude l'a montre, un departement est l'echelle
--  ou les methodes sont les plus justes (un modele regional ne fait pas
--  mieux, meme pour la Creuse), et une commune seule est trop maigre.
--
--  Ces ventes ne remplacent pas la table `mutation` : celle-ci garde
--  l'historique exact d'une parcelle, lots et dependances compris, pour la
--  fiche et l'alerte. Celles-ci sont NETTOYEES pour apprendre — une ligne
--  par vente d'UN logement, dont le prix designe sans ambiguite un bien.
-- =====================================================================

CREATE TABLE IF NOT EXISTS vente_reference (
    departement   TEXT NOT NULL,
    id_mutation   TEXT NOT NULL,
    code_insee    TEXT NOT NULL,
    date_vente    TEXT NOT NULL,
    trimestre     TEXT NOT NULL,            -- « 2025-Q3 »
    type          TEXT NOT NULL,            -- maison | appartement
    prix          REAL NOT NULL,
    surface       REAL NOT NULL,            -- surface reelle batie (DGFiP)
    pieces        INTEGER,
    terrain_m2    REAL NOT NULL DEFAULT 0,
    dependances   INTEGER NOT NULL DEFAULT 0,
    vefa          INTEGER NOT NULL DEFAULT 0,
    latitude      REAL NOT NULL,
    longitude     REAL NOT NULL,
    parcelle_id   TEXT,
    adresse       TEXT,
    PRIMARY KEY (departement, id_mutation)
);
CREATE INDEX IF NOT EXISTS idx_vente_ref_type     ON vente_reference (departement, type);
CREATE INDEX IF NOT EXISTS idx_vente_ref_parcelle ON vente_reference (parcelle_id);

-- Les terrains a batir vendus nus : la valeur du sol, pour la methode
-- sol + construction.
CREATE TABLE IF NOT EXISTS terrain_reference (
    departement   TEXT NOT NULL,
    id_mutation   TEXT NOT NULL,
    code_insee    TEXT NOT NULL,
    date_vente    TEXT NOT NULL,
    trimestre     TEXT NOT NULL,
    prix          REAL NOT NULL,
    terrain_m2    REAL NOT NULL,
    latitude      REAL NOT NULL,
    longitude     REAL NOT NULL,
    PRIMARY KEY (departement, id_mutation)
);

-- Ce qui a ete importe, et de quelle publication : c'est ce qui permet de
-- savoir, par quelques requetes HEAD, qu'un nouveau millesime est paru.
CREATE TABLE IF NOT EXISTS departement_reference (
    departement      TEXT PRIMARY KEY,
    importe_le       TEXT NOT NULL,
    signatures_json  TEXT NOT NULL,
    ventes           INTEGER NOT NULL,
    terrains         INTEGER NOT NULL,
    premiere_vente   TEXT,
    derniere_vente   TEXT
);

-- Le modele appris pour un departement : indice, coefficients, et surtout
-- sa PRECISION MESUREE sur la derniere annee — c'est elle qui donne la
-- fourchette et le niveau de fiabilite affiches.
CREATE TABLE IF NOT EXISTS modele_estimation (
    departement   TEXT PRIMARY KEY,
    entraine_le   TEXT NOT NULL,
    modele_json   TEXT NOT NULL
);

-- Les estimations enregistrees. Garder ce qu'on a estime, avec ce qu'on a
-- saisi, permet de le comparer au prix reel quand la vente parait dans
-- DVF — et de verifier sur ses propres biens l'echelle d'etat, que rien
-- d'autre ne permet de calibrer.
CREATE TABLE IF NOT EXISTS estimation (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    cree_le         TEXT NOT NULL,
    departement     TEXT,
    code_insee      TEXT,
    parcelle_id     TEXT,
    n_dpe           TEXT,
    adresse         TEXT,
    type            TEXT NOT NULL,
    surface         REAL NOT NULL,
    terrain_m2      REAL,
    latitude        REAL,
    longitude       REAL,
    saisie_json     TEXT NOT NULL,
    valeur          REAL NOT NULL,
    bas             REAL,
    haut            REAL,
    resultat_json   TEXT NOT NULL,
    -- La vente reelle, quand DVF la publie ensuite.
    vente_id_mutation TEXT,
    vente_date        TEXT,
    vente_prix        REAL,
    rapproche_le      TEXT
);
CREATE INDEX IF NOT EXISTS idx_estimation_parcelle ON estimation (parcelle_id);

-- L'indice Notaires-Insee des logements anciens, en cache. Il ne sert
-- qu'a projeter l'estimation sur les mois que DVF ne couvre pas encore.
CREATE TABLE IF NOT EXISTS indice_officiel (
    zone        TEXT NOT NULL,
    type        TEXT NOT NULL,            -- maison | appartement
    trimestre   TEXT NOT NULL,
    indice      REAL NOT NULL,
    PRIMARY KEY (zone, type, trimestre)
);

-- La carte des loyers (ANIL) : un loyer d'annonce par commune et par type,
-- pour afficher le rendement brut qu'un prix implique.
CREATE TABLE IF NOT EXISTS loyer_commune (
    code_insee  TEXT NOT NULL,
    type        TEXT NOT NULL,
    loyer_m2    REAL NOT NULL,
    bas_m2      REAL,
    haut_m2     REAL,
    millesime   TEXT,
    PRIMARY KEY (code_insee, type)
);

-- Quand chaque source annexe a ete relue pour la derniere fois.
CREATE TABLE IF NOT EXISTS source_maj (
    source   TEXT PRIMARY KEY,
    maj_le   TEXT NOT NULL,
    detail   TEXT
);
