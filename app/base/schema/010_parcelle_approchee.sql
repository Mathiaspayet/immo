-- ---------------------------------------------------------------------
-- 010 — La parcelle APPROCHEE d'un diagnostic.
--
-- `parcelle_id` ne se remplit que par appartenance stricte : le point du
-- diagnostic tombe dans le contour. C'est la bonne regle, et elle laisse
-- des orphelins — l'ADEME geocode souvent sur la CHAUSSEE, devant la
-- maison. Mesure faite sur Mimizan, sur un an : 19 diagnostics sur 307
-- n'appartiennent a aucune parcelle, mais 15 d'entre eux en ont une a
-- moins de 6 metres, sans rivale a moins de 3 metres de plus.
--
-- Ces 15-la meritent d'etre montres a leur place sur la carte. Pas dans
-- `parcelle_id` pour autant : la fiche d'un bien y lit l'historique des
-- VENTES de sa parcelle, et une parcelle approchee y ferait entrer les
-- ventes du voisin. Deux colonnes, deux usages, aucune confusion.
--
-- `distance_parcelle_m` garde la mesure : c'est elle qui autorise l'ecran
-- a dire « position approchee » plutot que de faire passer une estimation
-- pour un fait.
-- ---------------------------------------------------------------------

ALTER TABLE dpe ADD COLUMN parcelle_approchee TEXT;
ALTER TABLE dpe ADD COLUMN distance_parcelle_m REAL;

CREATE INDEX IF NOT EXISTS idx_dpe_parcelle_approchee
    ON dpe(parcelle_approchee);
