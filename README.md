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

## État — lot 1 livré

| Fonction | État |
|---|---|
| **F1** Veille des DPE récents | livrée |
| Import ADEME avec cache et journal | livré |
| Import hebdomadaire automatique | livré |
| Écran Réglages | livré |
| Export CSV | livré |
| **F2** Identifier un bien depuis une annonce | lot 2 |
| **F3** Recherche cadastrale | lot 3 |
| **F4** Fiche bien et historique | lot 2 |
| **F5/F6** Suivi, notes, notifications | lot 4 |

Sur un import réel du code postal 40200 : **2 881 DPE récupérés**, dont 44
maisons de 80 à 400 m² diagnostiquées dans les 120 derniers jours,
réparties entre bourg (28) et plage (16).

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

python -m pytest tests/ -q                     # 52 tests, aucun appel réseau
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
├── sources/         API externes : ADEME, geo.api.gouv.fr
├── metier/          logique portée des scripts d'origine
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

**La purge supprimera des données utiles au lot 2.** Le CDC §9 impose de ne
rien conserver au-delà de 24 mois, et le réglage l'applique au cache des
DPE : sur 2 881 lignes téléchargées, 1 830 sont supprimées aussitôt. C'est
sans effet sur la veille, qui regarde les derniers mois. Mais la fonction
F2 — identifier un bien depuis une annonce — a besoin de toute la
profondeur de la base, une annonce pouvant citer un DPE de 2022. Il faudra
porter `purge_mois` à 60 (l'écran Réglages) avant d'attaquer le lot 2.

**Le conteneur tourne en root**, comme `gestion-locative`. C'est ce qui
évite les refus d'écriture sur le volume monté. L'application n'étant pas
exposée publiquement, le compromis est assumé.

**Mimizan-Plage n'a pas de code administratif propre** — ni code postal ni
code INSEE distinct du bourg. La séparation se fait par la distance au
point de référence le plus proche, réglable dans l'écran Réglages.
