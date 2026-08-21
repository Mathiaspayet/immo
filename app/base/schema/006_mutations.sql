-- =====================================================================
--  006_mutations.sql — L'historique des ventes (DVF)
-- =====================================================================
--  Deux tables, parce qu'une mutation porte souvent sur PLUSIEURS
--  parcelles : maison, jardin attenant, garage. Tout mettre dans une
--  seule table repeterait la valeur fonciere autant de fois qu'il y a de
--  parcelles, et la moindre somme annoncerait un prix multiplie.
--
--  C'est exactement le piege du fichier source, ou `valeur_fonciere` se
--  repete a l'identique sur chaque ligne : une vente a 400 000 EUR sur
--  quatre lignes en annonce 1 600 000 si on additionne. Sur Mimizan,
--  1 118 mutations sur 2 054 tiennent sur plusieurs lignes — le cas est
--  majoritaire, pas marginal.
-- =====================================================================

CREATE TABLE IF NOT EXISTS mutation (
    id                TEXT PRIMARY KEY,      -- id_mutation de la source
    code_insee        TEXT NOT NULL,
    date_mutation     TEXT NOT NULL,
    nature            TEXT,
    valeur_fonciere   REAL,                  -- pour la mutation ENTIERE
    -- Agregats calcules a l'import, pour ne pas les recalculer a chaque
    -- consultation de fiche.
    nb_parcelles      INTEGER NOT NULL DEFAULT 0,
    nb_locaux         INTEGER NOT NULL DEFAULT 0,
    surface_bati_m2   REAL,
    surface_terrain_m2 REAL,
    types_locaux_json TEXT,                  -- ["Maison", "Dependance"]
    importe_le        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_mutation_commune
    ON mutation (code_insee, date_mutation);

-- Le lien vers le foncier. C'est par lui que la fiche d'un bien retrouve
-- ses ventes, sans jamais passer par l'adresse dont l'orthographe varie.
CREATE TABLE IF NOT EXISTS mutation_parcelle (
    mutation_id  TEXT NOT NULL,
    parcelle_id  TEXT NOT NULL,
    PRIMARY KEY (mutation_id, parcelle_id)
);

CREATE INDEX IF NOT EXISTS idx_mutation_parcelle_inverse
    ON mutation_parcelle (parcelle_id);
