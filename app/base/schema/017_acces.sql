-- =====================================================================
--  017_acces.sql — Le mot de passe de l'application
-- =====================================================================
--  Un seul mot de passe, pas de compte : l'application n'a qu'un
--  utilisateur. Il se choisit, ou se remplace, par un lien envoye par
--  courriel — le seul moyen de prouver qu'on est le proprietaire quand on
--  n'a encore rien a taper.
--
--  Aucune de ces tables ne garde de secret en clair : le mot de passe est
--  derive par scrypt, et les jetons comme les sessions ne sont conserves
--  que par leur empreinte SHA-256. Une copie de la base — les sauvegardes
--  en font chaque jour — n'ouvre donc pas l'application.
-- =====================================================================

CREATE TABLE IF NOT EXISTS acces (
    id          INTEGER PRIMARY KEY CHECK (id = 1),   -- une seule ligne
    empreinte   TEXT NOT NULL,                        -- scrypt, sel compris
    defini_le   TEXT NOT NULL
);

-- Les liens envoyes. Chacun ne sert qu'une fois, et pas au-dela de sa
-- date d'expiration ; les plus recents disent aussi si l'on en demande
-- trop souvent.
CREATE TABLE IF NOT EXISTS acces_jeton (
    empreinte   TEXT PRIMARY KEY,
    cree_le     TEXT NOT NULL,
    expire_le   TEXT NOT NULL,
    utilise_le  TEXT
);

-- Les navigateurs connectes.
CREATE TABLE IF NOT EXISTS acces_session (
    empreinte   TEXT PRIMARY KEY,
    cree_le     TEXT NOT NULL,
    vu_le       TEXT NOT NULL,
    expire_le   TEXT NOT NULL,
    appareil    TEXT
);
