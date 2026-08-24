-- =====================================================================
--  008_empreinte.sql — Reconnaitre une vente sans le numero du publieur
-- =====================================================================
--  `id_mutation` n'est PAS une clef durable. C'est un numero d'ordre
--  attribue par la chaine de publication, et deux chaines differentes
--  numerotent differemment les memes ventes.
--
--  Mesure sur Mimizan, 2021 : la version geocodee d'Etalab et la
--  compilation departementale decrivent les MEMES 574 ventes, et n'ont
--  que 15 identifiants en commun. Pire, l'identifiant « 2021-693984 »
--  designe une vente a 175 000 EUR sur neuf parcelles d'un cote, et une
--  vente a 113 700 EUR sur une parcelle de l'autre.
--
--  L'import ecrit par `ON CONFLICT(id) DO UPDATE`. Si une republication
--  renumerotait, deux choses arriveraient d'un coup : les anciennes
--  lignes resteraient en base sans plus rien designer, et TOUTES les
--  ventes du millesime paraitraient neuves — le courriel d'alerte en
--  annoncerait des centaines. Je n'ai pas pu prouver qu'Etalab
--  renumerote (ses deux publications en ligne sont identiques au bit
--  pres), mais la compilation prouve que rien ne l'en empeche.
--
--  D'ou une empreinte tiree de la vente elle-meme — date, montant,
--  parcelles — et non du numero de qui la publie. Verifiee : elle
--  reconnait 574 des 574 ventes de 2021 d'une source a l'autre.
-- =====================================================================

ALTER TABLE mutation ADD COLUMN empreinte TEXT;

-- Pas d'index UNIQUE : trois paires de ventes sur les 2 054 de Mimizan
-- partagent date, montant ET parcelles — indiscernables par tout ce que
-- la source publie, `numero_disposition` compris. Elles sont donc
-- distinguees par un rang, et l'index sert la recherche, pas la
-- contrainte.
CREATE INDEX IF NOT EXISTS idx_mutation_empreinte
    ON mutation (code_insee, empreinte);
