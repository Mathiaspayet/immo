-- =====================================================================
--  001_socle.sql — Tables du lot 1 (veille des DPE)
-- =====================================================================
--  Le modele suit la section 6 du cahier des charges. Les tables des
--  lots suivants (parcelle, suivi, note) seront ajoutees par de nouvelles
--  migrations, pas en modifiant ce fichier : il a deja ete applique sur
--  le NAS et ne doit plus changer.
--
--  Les dates sont stockees en texte ISO (AAAA-MM-JJ, ou horodatage
--  complet) : c'est le format que SQLite sait comparer et trier
--  directement, sans conversion.
-- =====================================================================

CREATE TABLE IF NOT EXISTS commune (
    code_insee            TEXT PRIMARY KEY,
    nom                   TEXT NOT NULL,
    code_postal           TEXT,
    derniere_maj_cadastre TEXT,   -- lot 3
    derniere_maj_dpe      TEXT
);

-- ---------------------------------------------------------------------
--  Les DPE. Un enregistrement par numero de DPE, quel que soit le jeu
--  de donnees ADEME d'origine (existant, neuf, avant juillet 2021).
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS dpe (
    n_dpe               TEXT PRIMARY KEY,
    code_insee          TEXT,
    code_postal         TEXT,
    commune             TEXT,
    adresse             TEXT,
    latitude            REAL,
    longitude           REAL,
    -- Rattachement bourg / plage : Mimizan-Plage n'a ni code postal ni
    -- code INSEE propre, on la separe donc par la geographie (CDC F1).
    zone                TEXT,
    distance_zone_m     INTEGER,
    date_etablissement  TEXT,
    surface_habitable   REAL,
    type_batiment       TEXT,
    etiquette_dpe       TEXT,
    etiquette_ges       TEXT,
    conso_ep_m2         REAL,     -- energie primaire  (ADEME : "ep")
    conso_ef_m2         REAL,     -- energie finale    (ADEME : "ef")
    ges_m2              REAL,
    cout_annuel         REAL,
    annee_construction  INTEGER,
    n_dpe_remplace      TEXT,
    jeu_de_donnees      TEXT NOT NULL,
    -- La base ADEME compte plus de 200 colonnes et les besoins evolueront :
    -- on conserve la ligne brute telle que l'API l'a renvoyee (CDC 6).
    donnees_brutes_json TEXT,
    -- Ajouts par rapport au CDC : sans date de premiere apparition, on ne
    -- peut pas dire ce qui est nouveau depuis la derniere consultation.
    importe_le          TEXT NOT NULL,
    vu_le               TEXT
);

CREATE INDEX IF NOT EXISTS idx_dpe_date    ON dpe (date_etablissement DESC);
CREATE INDEX IF NOT EXISTS idx_dpe_commune ON dpe (code_postal, commune);
CREATE INDEX IF NOT EXISTS idx_dpe_adresse ON dpe (adresse);
CREATE INDEX IF NOT EXISTS idx_dpe_vu      ON dpe (vu_le);

-- ---------------------------------------------------------------------
--  Reglages metier : communes surveillees, points de reference des
--  secteurs, filtres par defaut, webhook. Une cle, une valeur JSON.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS reglage (
    cle        TEXT PRIMARY KEY,
    valeur_json TEXT NOT NULL,
    maj_le     TEXT
);

-- ---------------------------------------------------------------------
--  Trace de chaque import (CDC 8). Consultable dans les reglages :
--  un import qui echoue en silence est un import qu'on ne repare jamais.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS journal_import (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    source  TEXT NOT NULL,
    debut   TEXT NOT NULL,
    fin     TEXT,
    lignes  INTEGER DEFAULT 0,
    ajouts  INTEGER DEFAULT 0,
    statut  TEXT NOT NULL,          -- en_cours | succes | echec
    message TEXT
);

CREATE INDEX IF NOT EXISTS idx_journal_debut ON journal_import (debut DESC);
