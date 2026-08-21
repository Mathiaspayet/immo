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

## État — lots 1, 2 et 3 livrés

| Fonction | État |
|---|---|
| **F1** Veille des DPE récents | livrée |
| **F2** Identifier un bien depuis une annonce | livrée |
| **F4** Fiche bien, chronologie, remplacements | livrée |
| Historique des ventes (DVF) | livré |
| Carte d'exploration, parcelles colorées | livrée |
| Import ADEME des trois bases, avec cache et journal | livré |
| Import quotidien automatique | livré |
| Alerte courriel des nouveaux DPE (F6) | livré |
| Écran Réglages, export CSV | livrés |
| **F3** Recherche cadastrale | livrée |
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

### Ce que fait la recherche cadastrale (F3)

On cherche un terrain : telle surface de parcelle, telle emprise bâtie au
sol. Repère utile — une maison de 120 m² habitables de plain-pied occupe
environ 120 m² au sol&nbsp;; la même sur deux niveaux, 60 à 70 m².

Et surtout le croisement que demande le CDC : **une parcelle au bon gabarit
qui porte en plus un diagnostic récent**. Les deux signaux sont
indépendants, leur rencontre ne l'est pas. Sur Launaguet :

```
4 304 parcelles au cadastre
1 228   au gabarit  (terrain 400–2 000 m², emprise 60–250 m²)
  223     portant un DPE
   16       dont le DPE date de moins de 120 jours
```

Ces seize-là sont les candidats. Ils s'affichent en liste et sur la carte,
contour à l'encre, en ambre quand le diagnostic est frais.

Le rattachement des bâtiments aux parcelles passe par un **index spatial en
grille** : comparer chaque bâtiment à chaque parcelle serait 11 444 × 14 395
= 165 millions de tests d'appartenance pour la seule commune de Mimizan. La
commune est donc découpée en cases de 110 m, et un bâtiment ne se compare
qu'aux parcelles de sa case. Résultat mesuré sur Launaguet : 6 905 bâtiments
rattachés en 6 secondes, **10 orphelins** (0,14 %).

Les DPE sont rattachés à leur parcelle par la même mécanique, une fois pour
toutes à l'import — 2 560 sur 2 878 pour Launaguet, les autres n'ayant pas
de position exploitable.

### Ce que fait la fiche (F4)

Chronologie de tous les DPE connus pour une adresse, les trois bases
confondues, et remontée de la chaîne des remplacements.

Le point délicat : **un DPE remplacé est retiré de la base active de
l'ADEME**. Le chercher par son numéro échoue, et une recherche plein texte
ramène alors les DPE qui le *citent* — pas lui. L'application ne fait donc
jamais de repli silencieux : soit le numéro est vérifié, soit elle écrit
que le diagnostic n'est plus accessible.

Le signal « encore publié » se lit en comparant `revu_le` à la dernière
moisson **de la commune du bien** — les deux portent le même horodatage,
l'import les écrivant dans la même transaction. Le repère doit être par
commune : moissonner Launaguet ne dit rien de Mimizan, dont les lignes
n'ont pas été revues à cette occasion.

**Combien de logements une adresse couvre-t-elle ?** Le nombre de
diagnostics ne le dit pas : une maison vendue deux fois en porte deux, un
immeuble aussi. Ce qui les sépare est la *simultanéité* — on ne
rediagnostique pas le même logement le même jour, mais on diagnostique un
immeuble d'un coup. On retient donc le plus grand nombre de diagnostics
partageant une même date. Sur Mimizan, des 552 adresses portant plusieurs
DPE, la règle en requalifie 328 en maison revisitée et maintient 224
adresses réellement multiples — 4 diagnostics le même jour rue des
Pinsons, 2 avenue de Woolsack.

### La carte d'exploration

On parcourt la commune sur photo aérienne IGN, parcellaire en surimpression,
chaque parcelle colorée selon ce qu'on en sait :

| | |
|---|---|
| **Ambre** | un DPE **et** une vente connus |
| **Vert** | un DPE seul |
| **Bleu** | une vente seule |
| **Pâle** | rien encore |

L'ambre — la couleur du signal « nouveau » ailleurs dans l'application — est
réservée au croisement, parce que c'est lui qui informe : une parcelle
vendue sans diagnostic récent et une parcelle diagnostiquée sans vente ne
racontent pas la même histoire.

**Un clic ouvre la fiche, directement.** Les deux chemins y mènent : quand
la parcelle porte un diagnostic, c'est la fiche du bien avec sa
chronologie ; sinon c'est celle de la parcelle — contour, voisinage, bâti,
et ses ventes s'il y en a. Le second cas est de loin le plus fréquent, 468
parcelles sur 550 dans une vue courante, et sans lui la carte mènerait à
une impasse presque partout.

La boîte de recherche accepte indifféremment une adresse ou une référence
cadastrale — distinguer les deux champs obligerait à savoir lequel remplir.
Elle accepte aussi les deux écritures du numéro : la base le garde sans
zéros de remplissage (`AT148`) là où l'identifiant affiché sur la fiche les
porte (`AT0148`).

**Deux contraintes gouvernent cet écran.** Le volume d'abord : les 11 444
parcelles de Mimizan pèsent 3,8 Mo, et les envoyer d'un bloc rendrait la
carte inutilisable sur téléphone. On ne charge donc que le cadre affiché —
602 parcelles pour un quartier de 700 m, 375 Ko, 24 ms — et quand il en
reste au-delà, l'écran le dit plutôt que d'en tracer une bouillie. Les
parcelles renseignées passent d'ailleurs en premier : tronquer ne doit pas
faire disparaître celles qui portent l'information.

L'échelle ensuite : en dessous du zoom 15, une commune entière tient à
l'écran et ses parcelles font quelques pixels. La carte demande alors de
zoomer, au lieu de peiner en silence.

### L'historique des ventes (DVF)

La fiche montre les ventes connues du bien, tirées des **demandes de
valeurs foncières** publiées par la DGFiP dans la version géocodée
d'Etalab. Le rattachement passe par la **parcelle**, jamais par l'adresse :
DVF et le cadastre partagent `id_parcelle`, là où l'orthographe d'une
adresse varie d'une base à l'autre. Les DPE y étant déjà rattachés, la
jointure est directe.

Mesures sur Mimizan, cinq millésimes (2021-2025) :

| | |
|---|---|
| Lignes DVF téléchargées | 4 116 |
| Ventes distinctes | 2 054 |
| Parcelles citées, retrouvées au cadastre | 1 730 sur 1 821 — **95 %** |
| DPE rattachés à une parcelle | 2 555 |
| …dont une vente connue | 788 — **30 %** |

**Le piège du fichier source, et la raison des deux tables.** Une mutation
porte souvent sur plusieurs parcelles et plusieurs locaux — maison, jardin,
garage. `valeur_fonciere` vaut alors pour l'ensemble et **se répète à
l'identique sur chaque ligne**. Additionner les lignes d'une vente à
400 000 € en annonce 1 600 000. Ce n'est pas un cas marginal : 1 118 des
2 054 mutations de Mimizan tiennent sur plusieurs lignes. Le montant est
donc lu une seule fois par mutation, et les parcelles vivent dans une table
de liaison.

Même prudence sur le **prix au m²**, qui n'est affiché que si la vente
porte sur un seul local et une seule parcelle. Sinon on rapporterait le
prix d'une maison, d'un garage et d'un terrain à la seule surface bâtie —
un chiffre faux, et flatteur. La fiche écrit alors pourquoi elle se tait.

Deux limites de la source, annoncées sur la fiche : elle ne couvre que les
cinq derniers millésimes publiés, et **jamais l'Alsace-Moselle (57, 67, 68)
ni Mayotte**, qui tiennent leur propre livre foncier.

---

## Déploiement sur le NAS

La chaîne est entièrement automatique :

```
git push main → GitHub Actions (tests puis build)
              → ghcr.io/mathiaspayet/immo:latest
              → Watchtower sur le NAS → conteneur remplacé
```

### Première installation — sans SSH, depuis DSM

**Container Manager → Projet → Créer**

- chemin : `/docker/veille-immo` (créer le dossier)
- source : *Créer docker-compose.yml*
- coller le contenu de [`docker-compose.synology.yml`](docker-compose.synology.yml)
- Suivant jusqu'à Terminer

Container Manager télécharge l'image lui-même. Le fichier fonctionne sans
`.env` à côté : chaque réglage y porte une valeur par défaut.

> **L'onglet « Registre » ne trouvera pas cette image.** Sa recherche
> interroge Docker Hub, et GitHub Container Registry n'expose aucune API de
> recherche : le champ restera vide même après avoir ajouté `ghcr.io` comme
> registre. Ce n'est pas une limite du NAS. Le passage par un projet, comme
> ci-dessus, télécharge l'image sans difficulté — le nom complet y est écrit
> en toutes lettres.

### Ou en SSH, si vous préférez

```bash
mkdir -p /volume1/docker/veille-immo && cd /volume1/docker/veille-immo
# y déposer docker-compose.synology.yml, et un .env si vous voulez
# changer un réglage (voir .env.example)
docker compose -f docker-compose.synology.yml up -d
```

L'application répond alors sur `http://<nas>:8020`. Le port 8000 étant déjà
pris par `gestion-locative`, celui-ci est décalé — modifiable par
`VEILLE_PORT_HOTE` dans un `.env`.

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

python -m pytest tests/ -q                     # 116 tests, aucun appel réseau
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
├── planificateur.py APScheduler — import quotidien, puis alerte
├── base/            SQLite : connexion, migrations SQL, réglages
├── sources/         API externes : ADEME (3 bases), geo.api.gouv.fr
├── metier/          logique portée des scripts d'origine
│   ├── veille.py            F1 — les DPE récents, dédoublonnés
│   ├── identification.py    F2 — l'entonnoir et le classement
│   ├── fiche.py             F4 — chronologie, remplacements, comparaison
│   ├── mutations.py         Ventes DVF, rattachées par la parcelle
│   └── (carte : parcelles.pour_carte + chercher_sur_carte)
│   ├── geometrie.py         surfaces, appartenance, index spatial en grille
│   └── parcelles.py         F3 — cadastre et croisement avec les DPE
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

### L'extrait cadastral

L'en-tête de la fiche d'un bien est le seul endroit où le CDC autorise de
l'audace : le polygone de la parcelle tracé à l'encre sur une trame fine, la
référence cadastrale en chasse fixe dans l'angle, les mesures alignées en
colonne. Il porte aussi une barre d'échelle et une rose des vents, et un
repère rouge marque la position du diagnostic dans la parcelle.

Une parcelle tracée seule ne se lit pas : rien ne dit si ces 549 m² sont un
mouchoir de poche en centre-bourg ou une parcelle ordinaire. L'extrait
montre donc **le voisinage** — les parcelles limitrophes en trait fin, la
parcelle du bien en trait plein — et **le bâti dessiné par-dessus**, hachuré
pour le bâti léger. Le cadastre distingue en effet le dur du léger, et
l'écart est net : à Launaguet, 129 m² de médiane pour le premier contre
10 m² pour le second — une maison ne se confond pas avec un abri de jardin.
Le cadre retenu est la parcelle plus 35 m de marge ; sur une parcelle
courante de Launaguet cela donne 104 × 107 m, 15 voisines et 22 bâtiments.

Ces contours sont désormais conservés en base (table `batiment`, 1,5 Mo pour
Launaguet, 2,9 Mo pour Mimizan). Un cadastre importé avant ce changement n'a
que des parcelles, et c'est le manque le plus trompeur de l'application : le
dessin paraît complet — parcelle et voisines s'y tracent — mais aucun bâti
n'apparaît, sans que rien ne l'explique. Une commune de forêt et de labours
n'ayant elle non plus aucun bâti, la table vide ne suffit pas à conclure ; on
compare donc au nombre de bâtiments que l'import précédent avait déjà compté
par parcelle. S'il est positif alors que les contours manquent, l'extrait le
signale et propose de le compléter — un import du seul cadastre, les DPE
restant en place.

À droite du dessin, **une vue satellite au cadrage identique**. C'est le
même rectangle géographique, aux mêmes proportions, avec le contour de la
parcelle reporté dessus — de sorte que l'œil passe de l'un à l'autre sans
recalage. Les deux vues sont côte à côte au-delà de 1 120 px de large, et
l'une sous l'autre en dessous.

Les degrés n'étant pas isotropes, le contour est projeté en mètres avant
d'être dessiné — sans quoi une parcelle carrée apparaîtrait en rectangle.
Tant que le cadastre de la commune n'est pas chargé, l'extrait retombe sur
le repère de position et l'écrit.

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
| `cadastre.data.gouv.fr` | parcelles et bâtiments | import du cadastre |

Aucune autre. Ni CDN, ni police distante, ni mesure d'audience.

---

## Fraîcheur des données

Trois horloges se succèdent, et la plus lente est celle de l'application,
pas celle de l'ADEME.

| Étape | Délai mesuré |
|---|---|
| Établissement du DPE → réception par l'ADEME | médiane **0 jour** ; 79 % le jour même, 97 % sous une semaine |
| Publication dans le jeu de données ouvert | **quotidienne** |
| Import dans l'application | à la consultation d'une commune si elle date de plus de 24 h, et **quotidien** (7 h) pour tout le registre |

Le cache est donc au pire **24 heures** derrière la source dès lors que
l'application est consultée, et 7 jours si elle ne l'est pas du tout. Mesures faites en août 2026 sur
1 000 DPE du 40200, en comparant `date_etablissement_dpe` et
`date_reception_dpe`.

Un écran vide ne signifie pas que la base a pris du retard : il ne
s'établit qu'environ **1,6 DPE par jour** sur tout le 40200, toutes
communes et tous types confondus. Un filtre étroit sur quelques jours peut
légitimement ne rien retourner.

**Le rafraîchissement se joue commune par commune**, au moment où on la
consulte. Jamais moissonnée : on la moissonne, il n'y a rien à montrer
autrement. Moissonnée mais périmée : on affiche le cache tout de suite et on
rafraîchit derrière. À jour : rien. Le déclencheur est le choix d'une
commune, jamais le simple affichage d'un écran — ce que le CDC §4 interdit.
Le seuil se règle par `rafraichir_apres_heures` ; `0` coupe le
rafraîchissement, pas la première moisson.

Pour forcer en plus un import quotidien planifié, une variable suffit —
syntaxe cron, `*` valant « tous les jours » :

```yaml
VEILLE_IMPORT_JOUR: "*"
```

Rien ne devient obsolète en vieillissant, et par défaut **rien n'est
supprimé** : la purge est réglée sur « jamais ».

## Le parcours

L'application pose une question à la fois.

```
  Accueil                 Commune                   Résultats
  ┌──────────────┐        ┌──────────────┐          ┌──────────────┐
  │ DPE récents  │───────▶│  « laun… »   │─────────▶│  24 relevés  │
  │ Identifier   │        │  Launaguet   │  moisson │  + carte     │
  └──────────────┘        └──────────────┘  si besoin└──────────────┘
```

**L'intention d'abord** : regarder les diagnostics récents, ou retrouver un
bien depuis les chiffres d'une annonce.

**La commune ensuite**, cherchée par son nom — n'importe laquelle en France.
Celles déjà consultées sont proposées en un clic ; les autres portent la
mention « à télécharger ».

**Les résultats enfin.** Si la commune n'est pas en cache, l'application va
chercher ses diagnostics et le dit ; si elle y est mais date de plus de
24 h, elle affiche immédiatement ce qu'elle a et rafraîchit derrière.

Rien ne se déclare à l'avance. Le registre des communes se remplit à mesure
qu'on les consulte, et c'est lui que le rafraîchissement quotidien
parcourt. L'écran Réglages ne garde que ce qui relève vraiment d'un choix :
secteurs, filtres par défaut, tolérances, rétention.

### La commune est l'unité de travail

Un code postal en couvre presque toujours plusieurs — cinq pour le 40200,
sept pour le 31140 — et on n'en veut qu'une. Les trois bases de l'ADEME se
filtrent donc par **code INSEE**, le seul identifiant commun aux deux
générations de schémas. Launaguet seule représente 2 878 DPE, contre 15 910
pour tout son code postal.

C'est aussi le seul filtre fiable : l'ADEME écrit la même commune
`Sainte-Eulalie-en-Born`, `STE EULALIE EN BORN` ou `SAINTE-EULALIE-EN-BORN`
selon les lignes, et aucune recherche par nom ne les rattrape toutes. Les
codes INSEE, eux, sont renseignés sur 100 % des lignes.

### Les secteurs sont propres à une commune

Le découpage bourg / plage n'a de sens que là où ses points de référence ont
été placés. Sans restriction, un logement d'Aureilhan se verrait étiqueter
« bourg » au seul motif que c'est le repère le plus proche — et aucun seuil
de distance ne sépare proprement les deux : Mimizan s'étend jusqu'à 4 083 m
de ses repères, Aureilhan commence à 2 076 m.

Le réglage `zones_code_insee` dit donc à quelle commune les secteurs
s'appliquent (`40184`, Mimizan, par défaut ; vide = partout). Quand aucun
logement en cache ne porte de secteur, le filtre correspondant disparaît de
l'écran.

## Points à connaître

**La purge est désactivée, et ne porte pas sur la date du diagnostic.**
Le CDC §9 demande de ne rien conserver au-delà de 24 mois, sans préciser
24 mois à compter de quoi. Les deux lectures possibles n'ont pas le même
effet, mesuré sur Mimizan (4 343 DPE) :

| Critère | Supprimés | Conservés |
|---|---|---|
| Date d'établissement du diagnostic | 2 770 | 1 573 |
| `revu_le`, dernière fois que l'ADEME a servi la ligne | 0 | 4 343 |

Purger sur la date d'établissement rendrait le lot 2 impossible : la
chronologie F4 remonte à 2013, et une annonce peut citer un DPE de 2022
(640 diagnostics cette année-là à Mimizan). Le critère retenu est donc
`revu_le`.

Le délai, lui, est réglé sur **0 — ne jamais purger**, l'exigence exprimée
étant de garder le maximum d'historique. Ce que la valeur de 24 mois aurait
détruit n'est pas anodin : un DPE que l'ADEME retire de sa base cesse
d'être revu, et notre cache en devient l'unique trace — celle-là même que
la chronologie F4 exploite.

Ces deux choix sont des écarts assumés au texte du CDC §9. Le délai se
change dans l'écran Réglages, sans redéploiement ; le critère est dans le
code. À noter que la clause du CDC répond aussi à un souci de protection
des données (§9 : « leur agrégation constitue un traitement de données
personnelles ») : conserver sans limite l'affaiblit, sur un usage qui reste
strictement privé et non exposé.

**L'alerte part par courriel, pas par webhook.** Le CDC §9 écrit « aucun
envoi automatique de courrier », et F6 prévoyait un appel de webhook Home
Assistant. Le courriel a été demandé explicitement : c'est un écart assumé,
au même titre que la purge.

Elle suit l'import quotidien (CDC §8) et reprend **les critères enregistrés
dans les Réglages** — fenêtre, type de bien, surfaces — pour que ce qu'on
reçoit soit ce que l'écran Veille montre, sans second jeu de règles à tenir
à jour.

S'y ajoute un **périmètre propre à l'alerte** : une commune, et au besoin un
de ses secteurs. Sans commune retenue, l'alerte porterait sur tout le
registre, et chaque commune explorée viendrait s'y ajouter — on finirait par
recevoir des biens de territoires qu'on ne cherche plus. Les deux listes se
peuplent depuis la base : les communes réellement consultées, avec leur
nombre de DPE, et les secteurs **de la commune retenue** seulement. Un
secteur appartient à une commune : proposer « plage » à qui surveille
Launaguet ne remonterait jamais rien, aussi la liste se vide-t-elle et se
désactive.

Trois garde-fous, parce qu'un courriel de trop est déjà parti :

- **Un bien n'est signalé qu'une fois** (colonne `alerte_le`, migration 005).
  Sans elle, chaque import quotidien réexpédierait les mêmes biens.
- **Découvrir une commune ne déclenche rien.** Son parc entier paraît neuf —
  4 343 DPE pour Mimizan. La suppression du premier import est donc par
  commune, et non globale comme celle du badge « nouveau » : une pastille de
  trop se ferme d'un clic, un courriel de trop est déjà parti.
- **Un échec d'envoi ne consomme pas les biens.** Ils restent candidats pour
  le lendemain : une alerte en retard vaut mieux qu'une alerte perdue. Et un
  serveur injoignable n'annule jamais une moisson réussie.

**Le serveur d'envoi se règle dans l'écran**, et nulle part ailleurs :
changer d'adresse ne doit pas demander une session SSH sur le NAS et un
redémarrage. Il n'y a qu'une source, la table des réglages — pas de
variables d'environnement en parallèle, donc pas d'ambiguïté sur l'origine
d'un réglage qui ne prendrait pas effet.

Le mot de passe devient donc le seul secret que porte la table des
réglages — que l'API sert telle quelle. Il est pour cette raison inscrit
dans `SECRETS`, et `tous()` le **masque par défaut** : il faut demander
`avec_secrets=True` pour l'obtenir, ce que seul l'envoi fait. L'écran reçoit
huit puces et un drapeau disant qu'un mot de passe existe, jamais sa valeur.
Reposter le masque le conserve — sans quoi enregistrer un autre champ de la
même page l'aurait remplacé par des puces, et l'alerte aurait cessé de
partir sans que rien ne l'explique. Vider le champ l'efface.

Avec un mot de passe renseigné, l'envoi est **refusé** si le serveur
n'annonce pas STARTTLS — il partirait en clair ; choisir alors « SSL direct »
et le port 465.

Le bouton **Envoyer un message de contrôle** des Réglages éprouve la
configuration sans attendre qu'un DPE paraisse : sans lui, on ne saurait
qu'un mot de passe est faux qu'au premier bien manqué.

**Les fichiers de l'interface se revalident à chaque chargement.** Starlette
pose un ETag et un `Last-Modified`, mais aucun `Cache-Control` : sans
consigne, le navigateur applique sa propre heuristique et peut réutiliser un
fichier **sans rien demander**. Après une mise à jour par Watchtower, un
`index.html` neuf s'est ainsi retrouvé à côté d'un `veille.js` d'une version
précédente — les champs de l'écran existaient, le code qui les remplit non,
et le symptôme était une liste déroulante vide et un message obsolète.

`Cache-Control: no-cache` corrige cela, et ne veut pas dire « ne garde
rien » : le navigateur garde le fichier mais demande à chaque fois s'il a
changé. L'ETag rend la réponse vide — 304, sans corps — quand ce n'est pas
le cas. Sur un réseau local, le coût est nul. Un cache long serait légitime
pour des fichiers portant une empreinte dans leur nom ; aucun n'en porte
ici, l'interface n'ayant pas d'étape de construction (CDC §3).

**Le conteneur tourne en root**, comme `gestion-locative`. C'est ce qui
évite les refus d'écriture sur le volume monté. L'application n'étant pas
exposée publiquement, le compromis est assumé.

**La version déployée est affichée en permanence** dans le bandeau, sous le
titre : empreinte courte du commit et date de construction. C'est ce qu'on
vient vérifier après un passage de Watchtower. L'infobulle donne l'empreinte
complète.

**Les positions aberrantes sont écartées.** L'ADEME sert des `_geopoint`
hors de France — 39 lignes du 40200 portaient la latitude −5,98, en plein
golfe de Guinée. Sans garde-fou, elles se voyaient attribuer un secteur et
piquaient un marqueur au hasard sur la carte. Elles sont désormais
déclarées sans position.

**Mimizan-Plage n'a pas de code administratif propre** — ni code postal ni
code INSEE distinct du bourg. La séparation se fait par la distance au
point de référence le plus proche, réglable dans l'écran Réglages.
