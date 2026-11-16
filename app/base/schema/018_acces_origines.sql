-- =====================================================================
--  018_acces_origines.sql — Les adresses ou l'application est ouverte
-- =====================================================================
--  Le lien qui remplace un mot de passe oublie doit ramener a
--  l'application. Or elle ne connait pas sa propre adresse : elle la
--  lisait dans la requete de celui qui demandait le lien — n'importe qui,
--  puisque cette demande se fait sans etre connecte. Une requete forgee
--  suffisait donc a faire partir, vers la boite du proprietaire, un
--  courriel authentique dont le lien menait ailleurs.
--
--  On retient desormais les adresses d'ou le proprietaire s'est REELLEMENT
--  servi de l'application, mot de passe a l'appui. Le lien ne part plus
--  que vers l'une d'elles (voir metier/acces.py).
-- =====================================================================

CREATE TABLE IF NOT EXISTS acces_origine (
    origine  TEXT PRIMARY KEY,           -- « https://immo.exemple.fr »
    vue_le   TEXT NOT NULL
);
