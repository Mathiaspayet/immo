-- =====================================================================
--  014_boosting.sql — Le gradient boosting, et les ventes retrouvees
-- =====================================================================
--  Un modele par departement et par type de bien. A part du reste du
--  modele : quelques centaines de Ko compresses, qu'il est inutile de
--  relire a chaque estimation pour savoir si le modele a change.
-- =====================================================================

CREATE TABLE IF NOT EXISTS modele_boosting (
    departement  TEXT NOT NULL,
    type         TEXT NOT NULL,            -- maison | appartement
    modele       BLOB NOT NULL,            -- texte LightGBM, compresse (zlib)
    PRIMARY KEY (departement, type)
);

-- Retrouver vite, apres chaque import, les estimations dont la vente
-- vient de paraitre.
CREATE INDEX IF NOT EXISTS idx_estimation_attente
    ON estimation (departement, vente_id_mutation);
