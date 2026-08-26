-- =====================================================================
--  009_journal_alerte.sql — Garder trace de CHAQUE tentative d'alerte
-- =====================================================================
--  « Je n'ai rien recu ce matin » n'avait aucune reponse consultable.
--  L'issue de chaque alerte — envoyee, rien de neuf, desactivee, serveur
--  injoignable — partait au journal du conteneur et nulle part ailleurs.
--  Sur un NAS, ce journal n'est pas lisible sans SSH.
--
--  Le journal des imports ne suffisait pas : il dit que la moisson a
--  reussi, ce qui est vrai meme les jours ou aucun courriel ne part. Les
--  deux evenements sont distincts et leurs silences ont des causes
--  differentes.
--
--  Une ligne par passage, meme quand rien ne part : c'est justement le
--  cas qu'on cherche a expliquer. Sans trace du silence, on ne peut pas
--  distinguer « il n'y avait rien a dire » de « le passage n'a pas eu
--  lieu ».
-- =====================================================================

CREATE TABLE IF NOT EXISTS journal_alerte (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    quand        TEXT NOT NULL,
    sujet        TEXT NOT NULL,          -- 'dpe' | 'ventes'
    envoye       INTEGER NOT NULL,       -- 0 | 1
    raison       TEXT NOT NULL,          -- envoyee | rien_de_neuf | desactivee…
    biens        INTEGER NOT NULL DEFAULT 0,
    destinataire TEXT,
    message      TEXT                    -- le detail d'un echec
);

CREATE INDEX IF NOT EXISTS idx_journal_alerte_quand
    ON journal_alerte (quand DESC);
