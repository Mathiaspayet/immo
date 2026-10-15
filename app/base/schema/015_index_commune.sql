-- =====================================================================
--  015_index_commune.sql — Les diagnostics d'une commune, par date
-- =====================================================================
--  Tous les ecrans filtrent par code INSEE — la veille, ses compteurs,
--  les secteurs, l'alerte, le rattachement au cadastre —, et aucun index
--  ne le portait : celui de 001 croise code postal et nom de commune, que
--  plus rien n'interroge depuis que la commune se designe par son code.
--  Mesure sur 21 000 diagnostics : les compteurs de la veille passent de
--  9 a 2 ms. L'ecart grandit avec la base, et un NAS calcule moins vite
--  qu'un poste de travail.
-- =====================================================================

CREATE INDEX IF NOT EXISTS idx_dpe_insee_date ON dpe (code_insee, date_etablissement);
