-- =====================================================================
--  002_lot2.sql — Qualification (F2 identification, F4 fiche et historique)
-- =====================================================================
--  Contrairement au 001, ce fichier n'est pas rejouable tel quel :
--  SQLite ne connait pas ALTER TABLE ... ADD COLUMN IF NOT EXISTS. C'est
--  le suivi des migrations (table `migration`) qui garantit une seule
--  execution.
-- =====================================================================

-- ---------------------------------------------------------------------
--  Date de derniere presence dans la source.
--
--  `importe_le` dit quand un DPE est apparu chez nous et ne bouge plus.
--  `revu_le` est rafraichi a chaque import ou la ligne est encore servie
--  par l'ADEME. L'ecart entre les deux porte une information que rien
--  d'autre ne donne : un DPE remplace est RETIRE de la base active de
--  l'ADEME (CDC F4). Cesser de le revoir est donc le signal de son
--  remplacement, et notre cache en conserve la trace alors que l'API ne
--  le sert plus.
-- ---------------------------------------------------------------------
ALTER TABLE dpe ADD COLUMN revu_le TEXT;
UPDATE dpe SET revu_le = importe_le WHERE revu_le IS NULL;

CREATE INDEX IF NOT EXISTS idx_dpe_revu     ON dpe (revu_le);
CREATE INDEX IF NOT EXISTS idx_dpe_remplace ON dpe (n_dpe_remplace);
CREATE INDEX IF NOT EXISTS idx_dpe_jeu      ON dpe (jeu_de_donnees);

-- Regroupement par adresse pour la chronologie (F4) : l'index doit porter
-- la meme expression que la requete, sinon il n'est jamais utilise.
CREATE INDEX IF NOT EXISTS idx_dpe_adresse_norm ON dpe (lower(trim(adresse)));

-- Criteres d'identification (F2) : la recherche compare surtout ces
-- quatre grandeurs sur l'ensemble d'une commune.
CREATE INDEX IF NOT EXISTS idx_dpe_criteres ON dpe (surface_habitable, conso_ep_m2);
