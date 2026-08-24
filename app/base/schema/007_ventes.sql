-- =====================================================================
--  007_ventes.sql — Alerter sur les ventes, et cesser d'en perdre
-- =====================================================================
--  Deux corrections et une nouveaute, toutes nees du meme constat : DVF
--  n'est pas un fichier qui grandit, c'est une FENETRE GLISSANTE.
--
--  Etalab ne publie que cinq millesimes. Verifie le 24/08/2026 : 2019 et
--  2020 rendent 404 pour toutes les communes, Toulouse comprise, tandis
--  que 2021 a 2025 repondent. A la parution d'automne, 2026 entrera et
--  2021 sortira. L'import remplacait alors la commune en bloc — il aurait
--  donc EFFACE 2021 de la base au premier passage suivant, sans rien
--  dire. C'est l'inverse de ce qu'on veut : la base est le seul endroit
--  ou l'historique ancien subsiste une fois la source passee a autre
--  chose.
--
--  L'import procede desormais par mise a jour ligne a ligne. D'ou ces
--  deux colonnes, qui ne survivraient pas a un remplacement en bloc.
-- =====================================================================

-- `vu_le` date l'entree en base, `alerte_le` le signalement. Deux
-- colonnes distinctes pour la meme raison qu'au 005 : consulter ne doit
-- pas faire taire l'alerte, ni l'alerte effacer ce qui est neuf.
ALTER TABLE mutation ADD COLUMN vu_le TEXT;
ALTER TABLE mutation ADD COLUMN alerte_le TEXT;

-- L'adresse et la position viennent du fichier source, qui les porte sur
-- chaque ligne. Sans elles, un courriel d'alerte annoncerait une vente
-- sans dire OU : « 320 000 EUR, 78 m² » ne se rattache a rien. La
-- position sert en outre a poser la vente dans un secteur — bourg ou
-- plage — sans dependre du cadastre, qui peut ne pas etre charge.
ALTER TABLE mutation ADD COLUMN adresse TEXT;
ALTER TABLE mutation ADD COLUMN latitude REAL;
ALTER TABLE mutation ADD COLUMN longitude REAL;

-- Les ventes DEJA en base ne sont pas des nouveautes : elles sont
-- l'historique, importe avant que l'alerte n'existe. Sans cette ligne,
-- `alerte_le` naitrait a NULL sur les 2 054 mutations de Mimizan, et le
-- premier courriel — a la parution d'automne, dans quelques semaines —
-- les listerait toutes. C'est le meme raisonnement que la suppression du
-- premier import, applique ici au passage de version.
UPDATE mutation SET alerte_le = datetime('now') WHERE alerte_le IS NULL;

CREATE INDEX IF NOT EXISTS idx_mutation_alerte
    ON mutation (alerte_le) WHERE alerte_le IS NULL;

-- =====================================================================
--  Quand Etalab a-t-il publie ?
-- =====================================================================
--  On ne peut pas le demander : il n'y a pas d'API de version. Mais
--  chaque fichier porte un ETag et une date de derniere modification, et
--  une requete HEAD les donne sans telecharger le fichier. On garde donc
--  la signature du dernier millesime vu ; l'import complet n'est relance
--  que lorsqu'elle change.
--
--  Sans cela, il faudrait retelecharger un megaoctet de CSV chaque jour
--  pour decouvrir deux fois l'an qu'il a bouge.
-- =====================================================================
CREATE TABLE IF NOT EXISTS dvf_millesime (
    code_insee  TEXT NOT NULL,
    annee       INTEGER NOT NULL,
    signature   TEXT,               -- ETag, ou a defaut Last-Modified
    releve_le   TEXT NOT NULL,
    PRIMARY KEY (code_insee, annee)
);
