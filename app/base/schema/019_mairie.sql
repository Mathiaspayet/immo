-- =====================================================================
--  019_mairie.sql — La mairie de chaque commune
-- =====================================================================
--  La carte s'ouvrait au milieu du rectangle des diagnostics connus :
--  sur une commune etendue — Mimizan va de l'ocean aux landes, sur dix
--  kilometres —, ce milieu tombe en pleine pinede, loin du bourg comme de
--  la plage. La mairie, elle, est la ou l'on vit.
--
--  Sa position vient du referentiel de l'Etat (geo.api.gouv.fr), lu a la
--  moisson et garde ici : ouvrir la carte ne fait partir aucune requete
--  (CDC 4). Vide tant qu'aucune moisson ne l'a lue ; la carte retombe
--  alors sur l'ancien cadrage.
-- =====================================================================

ALTER TABLE commune ADD COLUMN mairie_latitude REAL;
ALTER TABLE commune ADD COLUMN mairie_longitude REAL;
