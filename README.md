# Veille immobilière — Mimizan

Application web privée qui repère les maisons susceptibles d'être vendues
**avant** leur mise en ligne sur les portails d'annonces.

Le principe : un DPE est obligatoire avant toute mise en vente. Un
diagnostic tout frais précède donc souvent l'annonce de plusieurs semaines,
et la base des DPE de l'ADEME est en open data **avec l'adresse**.

> À lire avant de s'emballer : un DPE récent ne signifie pas une vente. Ce
> peut être une mise en location, un audit avant travaux ou un dossier
> MaPrimeRénov'. La proportion de faux positifs est importante.

Spécification complète : [`CAHIER_DES_CHARGES.md`](CAHIER_DES_CHARGES.md).

---

## État — lots 1 et 2 livrés

| Fonction | État |
|---|---|
| **F1** Veille des DPE récents | livrée |
| **F2** Identifier un bien depuis une annonce | livrée |
| **F4** Fiche bien, chronologie, remplacements | livrée |
| Import ADEME des trois bases, avec cache et journal | livré |
| Import hebdomadaire automatique | livré |
| Écran Réglages, export CSV | livrés |
| **F3** Recherche cadastrale | lot 3 |
| **F5/F6** Suivi, notes, notifications | lot 4 |

Sur un import réel du code postal 40200 : **7 593 DPE**, des trois bases de
l'ADEME, s'étendant de mai 2013 à aujourd'hui, dont 354 portent un lien de
remplacement. La veille en retient 44 maisons de 80 à 400 m² diagnostiquées
dans les 120 derniers jours, réparties entre bourg (28) et plage (16).

### Ce que fait l'identification (F2)

On saisit les chiffres lus sur une annonce, et l'écran affiche toujours
trois choses : l'**entonnoir** (combien de logements passent chaque critère
seul, puis en cumulé), le **diagnostic** quand l'entonnoir se ferme, et le
**classement complet** dont rien n'a été éliminé.

Un essai réel le montre bien. Pour une annonce à 144 m², 216 kWh/m² ép.,
158 kWh/m² éf., 7 kg de GES, classe D/B, l'entonnoir se ferme : aucun
logement ne satisfait tout. Mais le mieux classé — 19 Avenue des Oiseaux —
colle sur les consommations, les émissions et les deux classes, et ne
s'écarte que sur la surface : 149 m² en base contre 144 annoncés. Un filtre
strict à ±3 m² aurait fait disparaître la bonne maison sans rien expliquer.

### Ce que fait la fiche (F4)

Chronologie de tous les DPE connus pour une adresse, les trois bases
confondues, et remontée de la chaîne des remplacements.

Le point délicat : **un DPE remplacé est retiré de la base active de
l'ADEME**. Le chercher par son numéro échoue, et une recherche plein texte
ramène alors les DPE qui le *citent* — pas lui. L'application ne fait donc
jamais de repli silencieux : soit le numéro est vérifié, soit elle écrit
que le diagnostic n'est plus accessible.

---

## Déploiement sur le NAS

La chaîne est entièrement automatique :

```
git push main → GitHub Actions (tests puis build)
              → ghcr.io/mathiaspayet/immo:latest
              → Watchtower sur le NAS → conteneur remplacé
```

### Première installation

```bash
# Sur le NAS, en SSH
mkdir -p /volume1/docker/veille-immo && cd /volume1/docker/veille-immo

# Récupérer docker-compose.synology.yml et .env.example depuis ce dépôt
cp .env.example .env        # puis ajuster si besoin

docker compose -f docker-compose.synology.yml up -d
```

L'application répond alors sur `http://<nas>:8020`. Le port 8000 étant déjà
pris par `gestion-locative`, celui-ci est décalé — modifiable par
`VEILLE_PORT_HOTE` dans le `.env`.

Publication en HTTPS : **DSM → Portail des applications → Proxy inversé**,
avec authentification. L'application n'a pas de gestion de comptes : elle
n'est pas destinée à être exposée telle quelle (CDC §9).

### Mises à jour

Rien à faire. Le Watchtower déjà installé pour `gestion-locative` surveille
aussi ce conteneur : il porte le même label de portée
(`com.centurylinklabs.watchtower.scope=gestion-locative`). Un push sur
`main` suffit.

Le schéma de la base se met à jour tout seul au démarrage : aucune commande
à lancer sur le NAS après une nouvelle version.

### Premier usage

La base arrive vide. Cliquer sur **Rafraîchir** en haut à droite lance le
premier import — une à deux minutes, la progression s'affiche. Ensuite,
l'import se relance tout seul chaque lundi à 7 h.

---

## Développement local

```bash
pip install -r requirements.txt
pip install pytest httpx                       # pour les tests

VEILLE_BASE=./donnees/veille.db \
  python -m uvicorn app.main:application --reload --port 8020

python -m pytest tests/ -q                     # 87 tests, aucun appel réseau
```

Ou avec Docker : `docker compose up --build`, puis <http://localhost:8020>.

Documentation interactive de l'API : `/api/documentation`.

---

## Architecture

Un seul conteneur, un seul processus : FastAPI sert l'API, l'interface et
le planificateur.

```
app/
├── main.py          assemblage FastAPI, migrations au démarrage
├── config.py        variables d'environnement (chemins, port, fuseau)
├── planificateur.py APScheduler — import hebdomadaire
├── base/            SQLite : connexion, migrations SQL, réglages
├── sources/         API externes : ADEME (3 bases), geo.api.gouv.fr
├── metier/          logique portée des scripts d'origine
│   ├── veille.py            F1 — les DPE récents, dédoublonnés
│   ├── identification.py    F2 — l'entonnoir et le classement
│   └── fiche.py             F4 — chronologie, remplacements, comparaison
├── api/             routes HTTP — ne font que traduire en JSON
└── web/             interface : HTML, CSS, modules ES natifs
```

Trois principes structurants :

**Aucun appel externe à l'affichage.** `api/` ne connaît que la base.
L'import est un traitement séparé, tracé dans `journal_import`.

**Import transactionnel.** Tout est téléchargé et transformé avant la
moindre écriture. Un échec ne laisse jamais la base à moitié remplie.

**Pas d'outil de construction.** Le frontend est en modules ES natifs,
Leaflet et les trois polices sont auto-hébergés dans l'image. Le fichier
que vous lisez est celui que le navigateur exécute, et l'application
fonctionne si le NAS perd Internet — seules les tuiles manqueront.

### Ce qui vient des scripts d'origine

Les scripts validés contre les API réelles sont conservés dans
[`scripts_existants/`](scripts_existants/). Trois correctifs non évidents
en ont été repris, chacun couvert par un test :

**Découverte des noms de colonnes.** L'ADEME renomme ses colonnes entre
versions. Le code lit le schéma publié par l'API et retrouve chaque champ
par mots-clés. Ce n'est pas théorique : `n_dpe` est devenu `numero_dpe`, et
`n_dpe_remplace` est devenu `numero_dpe_remplace`. Le repérage automatique
a absorbé les deux sans modification.

**Correspondance exacte quand il le faut.** `date_derniere_modification_dpe`
contient littéralement la séquence `n_dpe` : une recherche par sous-chaîne
prendrait cette date pour le numéro de DPE. En cas d'égalité de mots-clés,
c'est la clé la plus courte qui gagne — c'est ce qui distingue
`cout_total_5_usages` (le total) de `cout_total_5_usages_energie_n1` (le
coût d'une seule énergie).

**Cascade de syntaxes de requête.** Le filtrage passe par `_eq`, `_in`, `qs`
ou la recherche plein texte selon la configuration du serveur. Les quatre
sont essayées dans l'ordre. Un identifiant de navigateur classique est
envoyé : le pare-feu de l'ADEME renvoie 403 aux agents inhabituels.

La conversion Lambert-93 → WGS84 est reprise telle quelle, sans `pyproj`
(qui pèserait une quinzaine de mégaoctets). Elle est vérifiée par
aller-retour au centimètre sur cinq villes.

### Un défaut corrigé au passage : INSEE contre code postal

La base d'avant juillet 2021 (`dpe-france`) est d'une autre génération :
22 colonnes au lieu de 230, et **aucune colonne de code postal**. Son seul
repère communal est `code_insee_commune_actualise`, qui attend un code
INSEE.

Lui passer un code postal ne provoque aucune erreur : l'API répond
normalement, avec les logements de la commune dont le code INSEE vaut ce
nombre. Interroger `dpe-france` avec « 40200 » renvoyait ainsi **98
logements de Moustey** (INSEE 40200) au lieu des **1 338 de Mimizan**
(INSEE 40184). L'import résout donc les codes INSEE via `geo.api.gouv.fr`
avant d'interroger cette base, et refuse de se rabattre sur le code postal
si le référentiel est indisponible.

Même famille de piège, attrapé avant d'écrire en base : sur cette même
base, le concept « commune » tombait sur `code_insee_commune_actualise`,
qui contient le mot *commune* — le code INSEE se serait retrouvé enregistré
comme nom de commune.

---

## Requêtes sortantes

Le CDC §4 liste les sources autorisées. Deux domaines s'y ajoutent, sans
lesquels la cartographie exigée au §3 ne peut pas fonctionner :

| Domaine | Usage | Quand |
|---|---|---|
| `data.ademe.fr` | DPE | import seulement |
| `geo.api.gouv.fr` | code INSEE des communes | import seulement |
| `data.geopf.fr` | fonds de plan et parcellaire IGN | affichage de la carte |
| `tile.openstreetmap.org` | fond OpenStreetMap | affichage de la carte |

Aucune autre. Ni CDN, ni police distante, ni mesure d'audience.

---

## Points à connaître

**La purge ne porte plus sur la date du diagnostic.** Le CDC §9 demande de
ne rien conserver au-delà de 24 mois. Appliquée à la date d'établissement,
cette règle rendait le lot 2 impossible : la chronologie F4 remonte à 2013,
et une annonce peut citer un DPE de 2022. La purge porte donc sur `revu_le`
— la dernière fois que l'ADEME a servi la ligne. La règle garde son sens,
rien n'est conservé sans être rafraîchi, et elle rend même un service à
F4 : un DPE remplacé disparaît de la base active de l'ADEME, notre cache en
garde la trace 24 mois de plus. C'est un écart assumé au texte du CDC,
signalé ici pour que la décision reste la vôtre.

**Le conteneur tourne en root**, comme `gestion-locative`. C'est ce qui
évite les refus d'écriture sur le volume monté. L'application n'étant pas
exposée publiquement, le compromis est assumé.

**Mimizan-Plage n'a pas de code administratif propre** — ni code postal ni
code INSEE distinct du bourg. La séparation se fait par la distance au
point de référence le plus proche, réglable dans l'écran Réglages.
