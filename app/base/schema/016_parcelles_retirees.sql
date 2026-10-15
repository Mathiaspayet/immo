-- =====================================================================
--  016_parcelles_retirees.sql — Les parcelles que le cadastre ne publie plus
-- =====================================================================
--  Une parcelle divisee ou fusionnee change d'identifiant : AB0180 devient
--  AB0450 et AB0451. Le cadastre se rafraichit par upsert, et l'ancienne
--  restait en base pour toujours — chevauchant ses heritieres sur la carte,
--  et captant des diagnostics au rattachement.
--
--  On ne la supprime pas pour autant : DVF cite les parcelles telles
--  qu'elles etaient au jour de la vente, et les ventes d'avant la division
--  portent l'ancien identifiant. Elle est donc RETIREE — absente de la
--  carte, de l'index et du rattachement — et sa FILIATION est notee, pour
--  que la fiche d'une heritiere montre les ventes de la parcelle d'origine.
-- =====================================================================

ALTER TABLE parcelle ADD COLUMN retiree_le TEXT;

CREATE TABLE IF NOT EXISTS parcelle_filiation (
    ancienne  TEXT NOT NULL,           -- la parcelle retiree
    nouvelle  TEXT NOT NULL,           -- une parcelle qui en est issue
    notee_le  TEXT NOT NULL,
    PRIMARY KEY (ancienne, nouvelle)
);

CREATE INDEX IF NOT EXISTS idx_filiation_nouvelle ON parcelle_filiation (nouvelle);
