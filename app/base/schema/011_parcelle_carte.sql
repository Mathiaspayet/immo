-- ---------------------------------------------------------------------
-- 011 — La parcelle d'affichage, indexee.
--
-- La carte joint les diagnostics a leur parcelle EXACTE ou, a defaut, a
-- leur parcelle approchee. Ecrit tel quel — `coalesce(d.parcelle_id,
-- d.parcelle_approchee) = p.id` — le predicat n'est pas indexable, et
-- SQLite abandonne alors les DEUX index : celui des diagnostics, mais
-- aussi celui du cadre de la carte. Le plan passait de
--
--     SEARCH p USING INDEX idx_parcelle_cadre
--     SEARCH d USING INDEX idx_dpe_parcelle
--
-- a deux SCAN complets, soit 11 444 parcelles x 4 382 diagnostics pour un
-- seul rafraichissement. La coloration, instantanee jusque-la, mettait
-- plusieurs secondes a chaque changement de filtre.
--
-- Une colonne GENEREE porte le meme calcul, et s'indexe. VIRTUAL et non
-- STORED : SQLite refuse d'ajouter une colonne generee STORED par ALTER
-- TABLE, et l'index suffit — c'est lui qui materialise la valeur.
-- ---------------------------------------------------------------------

ALTER TABLE dpe ADD COLUMN parcelle_carte TEXT
    GENERATED ALWAYS AS (coalesce(parcelle_id, parcelle_approchee)) VIRTUAL;

CREATE INDEX IF NOT EXISTS idx_dpe_parcelle_carte ON dpe(parcelle_carte);
