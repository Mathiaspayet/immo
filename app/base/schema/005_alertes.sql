-- =====================================================================
--  005_alertes.sql — Tracer ce qui a deja fait l'objet d'une alerte
-- =====================================================================
--  `vu_le` dit si l'ecran Veille a montre la ligne ; il ne peut pas servir
--  ici. Consulter l'ecran effacerait les alertes en attente, et recevoir
--  un courriel effacerait les badges « nouveau » — deux effets de bord que
--  personne n'attend. La colonne est donc distincte.
--
--  Elle vaut aussi garde-fou : sans elle, un envoi interrompu apres le
--  courriel mais avant la fin de l'import reexpedierait les memes biens au
--  passage suivant.
-- =====================================================================

ALTER TABLE dpe ADD COLUMN alerte_le TEXT;

-- Les candidats a l'alerte sont les lignes jamais alertees. Elles se
-- rarefient a mesure que la base se remplit : l'index evite de parcourir
-- toute la table a chaque import.
CREATE INDEX IF NOT EXISTS idx_dpe_alerte ON dpe (alerte_le) WHERE alerte_le IS NULL;
