-- ---------------------------------------------------------------------
-- 012 — Les DPE « vierges » ne portent plus de classe inventee.
--
-- Un logement ne consomme pas ZERO. Quand la consommation primaire est
-- nulle, le diagnostic n'a pas ete etabli : c'est le « DPE vierge » que
-- l'ancien regime autorisait. L'ADEME le note tantot « N » (non
-- renseigne), tantot « A » par defaut.
--
-- L'ecran affichait donc « classe A · 0 kWh/m² », presentant un logement
-- NON EVALUE comme la meilleure performance possible — et le filtre par
-- classe les ramenait parmi les A.
--
-- Mesure sur Mimizan avant correction : 1 194 vraies classes A, de 18,8 a
-- 82,8 kWh/m², aucune a zero ; et 72 diagnostics a zero, tous issus de la
-- base anterieure a juillet 2021, tous sans consommation finale ni cout
-- annuel. Trente-neuf portaient « N », trente-trois portaient « A ».
--
-- La correction ne DETRUIT rien d'utile : la ligne brute d'origine reste
-- dans `donnees_brutes_json`, et la surface, l'adresse, la date et la
-- position sont conservees. Seules disparaissent trois valeurs qui
-- n'etaient pas des mesures.
-- ---------------------------------------------------------------------

UPDATE dpe
   SET etiquette_dpe = NULL,
       etiquette_ges = NULL,
       conso_ep_m2   = NULL,
       ges_m2        = NULL
 WHERE conso_ep_m2 = 0;

-- « N » n'est pas une classe, meme quand une consommation l'accompagne.
UPDATE dpe SET etiquette_dpe = NULL WHERE etiquette_dpe = 'N';
UPDATE dpe SET etiquette_ges = NULL WHERE etiquette_ges = 'N';
