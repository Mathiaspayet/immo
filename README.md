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
| Vue de rue sur la fiche (option) | livrée |
| Carte d'exploration, parcelles colorées | livrée |
| Import ADEME des trois bases, avec cache et journal | livré |
| Import quotidien automatique | livré |
| Alerte courriel des nouveaux DPE (F6) | livré |
| Écran Réglages, export CSV | livrés |
| **F3** Cadastre, croisement avec les DPE | livrée |
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

**Chaque critère est facultatif, séparément.** Une annonce ne donne souvent
que l'énergie primaire et le GES ; ils suffisent. Le formulaire les demande
donc en premier, sous leur propre titre, et range le reste sous « si
l'annonce les donne » — un champ vide est ignoré, il n'écarte rien. Mesure
sur Mimizan, pour une maison à 89 kWh/m² ép. et 3 kg de GES :

```
4 343 logements en cache
   65   passent l'énergie primaire  (± 5)
   45     passent aussi le GES      (± 1,5)
```

Le premier du classement est alors la bonne maison, écart moyen nul. Seul
le formulaire entièrement vide est refusé : sans un chiffre à comparer, le
classement rendrait la base dans son ordre, ce qui ressemble à un résultat
sans en être un.

Un essai réel le montre bien. Pour une annonce à 144 m², 216 kWh/m² ép.,
158 kWh/m² éf., 7 kg de GES, classe D/B, l'entonnoir se ferme : aucun
logement ne satisfait tout. Mais le mieux classé — 19 Avenue des Oiseaux —
colle sur les consommations, les émissions et les deux classes, et ne
s'écarte que sur la surface : 149 m² en base contre 144 annoncés. Un filtre
strict à ±3 m² aurait fait disparaître la bonne maison sans rien expliquer.

### Ce que fait le cadastre (F3)

Le croisement que demande le CDC — **une parcelle qui porte à la fois un
diagnostic et une vente** — se lit désormais sur la carte d'exploration,
qui a remplacé l'écran de recherche par filtres. Cet écran proposait de
filtrer par surface de terrain et emprise bâtie, avec un export CSV ; il a
été retiré, la carte répondant à la même question de façon plus directe. Le
filtrage par gabarit est la seule capacité perdue au passage.

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

| État | Teinte | Opacité |
|---|---|---|
| un DPE **et** une vente | jaune `#EDA100` | 92 % |
| un DPE seul | vert `#008300` | 70 % |
| une vente seule | bleu `#2A78D6` | 70 % |
| rien encore | voile blanc | 12 % |

Le jaune, le plus visible des trois, est réservé au croisement : c'est lui
qui informe, une parcelle vendue sans diagnostic récent et une parcelle
diagnostiquée sans vente ne racontant pas la même histoire.

**Ces valeurs ne sont pas choisies à l'œil.** Une carte est un cas « toutes
paires » — n'importe quelles deux parcelles peuvent se toucher — et le fond
est une photographie, donc l'opacité mélange chaque teinte au paysage. Le
couple (teinte, opacité) a été retenu en composant chaque état sur trois
fonds réels du littoral landais — pinède `#4a5a3f`, teinte moyenne
`#7d7a6a`, sable `#d8cbb0` — puis en mesurant la séparation obtenue.

| | Séparation en vision normale | Sous daltonisme |
|---|---|---|
| Premier jeu (vert et bleu sombres, 45 %) | **10,5** | 10,1 |
| Jeu retenu | **22,1** | 9,7 |
| Seuil | 15 | 8 |

Le premier jeu échouait au plancher : deux couleurs que l'œil ne
distinguait pas — ce qui se voyait à l'usage. L'opacité compte autant que
la teinte : à 45 % la photo l'emporte et les états se rejoignent ; il faut
65 % pour franchir le plancher, d'où les 70 % retenus. Le jaune monte à
92 % parce que c'est l'état le plus rare — 10 parcelles sur 550 — et celui
qu'on cherche. Chaque contour porte enfin un liseré blanc plein : sur une
photo, une teinte seule disparaît contre une toiture claire ou dans l'ombre
d'un arbre.

Sur l'écran **Les DPE récents**, un repère mène lui aussi à la fiche du
bien — c'est là qu'on allait de toute façon. Le sens inverse est conservé :
cliquer une ligne de la liste la situe sur la carte sans quitter l'écran.

**Sur la carte d'exploration, un clic ouvre la fiche, directement.** Les deux chemins y mènent : quand
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

### La vue de rue

La fiche affiche le cliché de rue du bien, **si une clé d'API Google est
renseignée**. Sans clé, elle garde son simple lien et rien n'est transmis :
c'est le comportement par défaut.

C'est un **écart assumé au CDC §9** — « aucune donnée transmise à un
service tiers hors des API publiques listées en section 4 » — puisque
consulter une fiche envoie les coordonnées du bien à Google. Le choix a été
fait faute d'alternative couvrante, et la mesure est nette : sur
**Panoramax**, l'équivalent ouvert de l'IGN, on compte 89 prises de vue
dans les 200 m à Launaguet mais **zéro dans le bourg de Mimizan**. Sur un
échantillon de 60 adresses de Mimizan, 13 % seulement avaient une vue à
moins de 40 m, issue d'une campagne isolée de 2019.

Deux précautions limitent la portée de l'écart :

- **L'image passe par le NAS.** Le navigateur n'appelle jamais Google — ce
  qui préserve la règle du §3, aucune requête de la page vers un tiers — et
  la clé ne quitte pas le serveur. Vérifié : la fiche n'émet de requêtes
  que vers `data.geopf.fr`.
- **La clé est un secret**, au même titre que le mot de passe SMTP : elle
  vit dans `SECRETS`, l'API ne renvoie que des puces, et un test verrouille
  qu'elle n'apparaît nulle part dans les réponses.

Deux détails qui font la qualité du résultat. Le **catalogue est interrogé
avant l'image** : cette consultation est gratuite, elle dit si une vue
existe — ce qui évite de payer un cliché absent et de l'afficher en
rectangle gris — et elle donne la position réelle de la prise de vue. On en
déduit alors **vers où tourner l'objectif** : la caméra est sur la voie, le
bien est de côté, et sans ce cap on reçoit ce que le véhicule avait devant
lui, c'est-à-dire la route. Le cliché obtenu est enfin **gardé sur disque**,
une même fiche se consultant plusieurs fois et chaque image se facturant.

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

#### DVF est une fenêtre glissante, pas un fichier qui grandit

C'est le fait dont tout le reste découle, et il est facile à manquer.
Etalab ne publie que **cinq millésimes**, et les fait glisser. Vérifié le
24 août 2026 :

| Millésime | Mimizan | Toulouse |
|---|---|---|
| 2019, 2020 | 404 | 404 |
| 2021 → 2025 | servis | servis |
| 2026 | 404 | 404 |

La publication en ligne datait du **18 mai 2026** et s'arrêtait au
**30 décembre 2025** : huit mois d'angle mort. C'est structurel — une vente
signée chez le notaire met plusieurs mois à devenir publique — et il faut
le savoir avant de conclure qu'un bien n'a jamais changé de mains.

**La liste des millésimes se calcule, elle ne s'écrit pas.** Elle était
figée à `(2021, …, 2025)`. À la parution d'automne 2026, l'application
aurait ignoré le millésime neuf — et sans rien dire : un millésime absent
est traité comme une commune sans vente cette année-là, ce qui est le cas
légitime le plus fréquent. L'historique se serait arrêté à fin 2025 en
paraissant complet. `millesimes()` part donc de l'année courante et demande
un millésime de plus que la fenêtre n'en contient : c'est ce millésime en
trop qui capte la nouveauté le jour où elle paraît.

**L'import ne remplace plus la commune en bloc.** Le défaut était plus
grave que le précédent, et de même nature : quand 2026 entrera, 2021
sortira, et un `DELETE` par commune l'aurait **effacé de la base** au
passage suivant. Or la base est alors le seul endroit où ce millésime
subsiste encore. L'écriture se fait donc ligne à ligne, en `ON CONFLICT DO
UPDATE`. Une vente déjà connue est corrigée dans ses données mais garde son
`alerte_le` — sans quoi chaque republication semestrielle re-signalerait
tout le millésime corrigé comme neuf.

#### `id_mutation` n'est pas une clef

Le fait le plus contre-intuitif de cette source, et celui qui coûte le plus
cher si on l'ignore. `id_mutation` est un **numéro d'ordre attribué par la
chaîne de publication**, pas un identifiant de la vente.

Mesure sur Mimizan, millésime 2021 : la version géocodée d'Etalab et la
compilation départementale décrivent les **mêmes 574 ventes** et n'ont que
**15 identifiants en commun**. Pire, le numéro `2021-693984` désigne une
vente à 175 000 € sur neuf parcelles chez l'un, et une vente à 113 700 €
sur une parcelle chez l'autre.

L'écriture se faisant en `ON CONFLICT(id) DO UPDATE`, une republication
renumérotée aurait fait deux dégâts d'un coup : les anciennes lignes
seraient restées en base sans plus rien désigner, et **toutes** les ventes
du millésime auraient paru neuves — le courriel d'alerte en aurait annoncé
des centaines. Je n'ai pas pu prouver qu'Etalab renumérote : ses deux
publications en ligne sont identiques au bit près, ETag compris. Mais la
compilation prouve que rien ne l'en empêche.

Une vente se reconnaît donc à ce qui lui appartient — **date, montant,
parcelles** — et non au numéro de qui la publie. Vérifié : l'empreinte
reconnaît 574 des 574 ventes de 2021 d'une source à l'autre. Trois paires
sur les 2 054 partagent date, montant et parcelles, `numero_disposition`
compris : indiscernables par tout ce que la source publie, elles sont
distinguées par un rang.

#### Reprendre l'historique que la source ne sert plus

Cinq ans est la limite de la source, pas d'Etalab : le jeu officiel de la
DGFiP n'offre lui aussi que 2021-2025. Aucune requête ne la contourne.

Reste ce que d'autres ont archivé pendant que c'était servi. Une
compilation départementale publiée sur data.gouv.fr couvre 2018-2022 ; pour
Mimizan elle rend **1 222 ventes** de 2018, 2019 et 2020. Le bouton
« Reprendre l'historique ancien » des Réglages la lit une fois.

| | avant | après |
|---|---|---|
| Ventes conservées | 2 054 | **3 276** |
| Historique | 2021-01-05 → 2025-12-30 | **2018-01-04** → 2025-12-30 |

Trois choses rendent la reprise sûre, et sont testées : les 1 022 ventes
que les deux sources ont en commun sont reconnues par leur empreinte et non
dupliquées ; rien n'est signalé par courriel, puisque c'est de l'histoire
et non une actualité ; et l'import courant suivant ne détruit pas ce que
geo-dvf ne sert plus.

**Le département n'est jamais choisi : il se déduit.** La reprise part de
la commune surveillée, lue dans les Réglages ; les deux premiers chiffres
de son code INSEE donnent le département — trois outre-mer, sans quoi 97402
chercherait un département « 97 » qui n'existe pas. L'adresse du fichier
est ensuite demandée au catalogue de data.gouv.fr, dont les ressources
s'intitulent « 40 - Landes ».

```
bouton  →  commune_surveillee()   → réglages : alerte_code_insee = 40184
        →  departement("40184")   → "40"
        →  catalogue data.gouv.fr → ressource « 40 - Landes »
        →  34 Mo lus au fil de l'eau, on ne garde que code_commune = 40184
```

Rien de tout cela n'était visible, et c'était un défaut : on déclenchait
34 Mo de téléchargement sans savoir lequel, et rien ne permettait de
vérifier après coup que la reprise avait porté là où on le croyait.
L'écran annonce donc sa cible **avant** — « Mimizan (40184) — archive du
département 40 » — et le compte rendu nomme la ressource effectivement
lue.

#### Une commune, ou tout un département

Le fichier téléchargé est départemental dans les deux cas — il n'existe
qu'à cette maille. Prendre le département entier ne coûte donc **pas un
téléchargement de plus**, seulement les lignes conservées. Mesure sur les
Landes :

| | commune (Mimizan) | département entier |
|---|---|---|
| Lignes lues | 3 867 | 184 878 |
| Communes | 1 | 327 |
| Ventes | 2 244 | 69 699 |
| Durée d'import | < 1 s | **9 s** |
| Taille de la base | ~7 Mo | **38 Mo** |

C'est ce chiffre de 9 s qui autorise l'appel synchrone : le téléchargement
des 34 Mo domine largement.

**L'écriture reste commune par commune.** Tout ce qui tient l'import droit
raisonne par commune — la reconnaissance des ventes déjà connues par
empreinte, la suppression du premier import, le comptage des
rattachements. Un import global les fausserait tous en silence.

**Mais une vente n'est jamais coupée en deux.** 510 des 69 699 ventes des
Landes portent sur plusieurs communes : des parcelles limitrophes vendues
ensemble — 40271 et 40272, 40280 et 40281. Répartir les *lignes* par
commune les scinderait, et comme l'écriture refait les rattachements à
neuf, la seconde commune effacerait les parcelles de la première. Mesuré :
**4 450 rattachements perdus**. Le regroupement se fait donc par vente
d'abord, chaque vente étant rangée entière dans la commune de sa première
ligne. Vérifié sur le département réel : 138 148 rattachements contre
133 609 avec le découpage naïf, et les 510 ventes à cheval conservent
leurs parcelles des deux côtés.

**Trois issues distinctes**, parce qu'elles n'appellent pas la même
réaction : une saisie fautive rend **400**, un département que la
compilation ne couvre pas rend **404**, une panne de data.gouv.fr rend
**502**. Les confondre enverrait chercher le problème au mauvais endroit.
Préciser une commune *et* un département est refusé plutôt qu'arbitré :
taire l'un des deux ferait croire qu'on a repris une commune alors qu'on
aurait pris 327.

La compilation est **figée** (mai 2023) et n'est donc pas guettée : on la
lit une fois, le courant continue de venir de geo-dvf. Si elle disparaissait
de data.gouv.fr, le bouton échouerait avec un message — ce qui est déjà
repris resterait en base.

### L'alerte sur les ventes

Le pendant de l'alerte DPE, sur le **même périmètre** — commune et secteur.
Un second jeu de critères aurait fini par diverger sans qu'on s'en
aperçoive ; on croirait surveiller la même chose des deux côtés.

Deux différences tiennent à la nature de la source.

**On guette la publication, pas la donnée.** Un DPE paraît en continu ; DVF
paraît deux fois l'an, par blocs. Une requête `HEAD` quotidienne compare
l'`ETag` de chaque millésime à celui du dernier passage, et l'import
complet ne part que lorsqu'il a bougé. Télécharger le CSV chaque jour pour
découvrir deux fois l'an qu'il a changé donnerait le même résultat au prix
de trois cent soixante-trois téléchargements inutiles. Le premier relevé ne
déclenche rien : sans point de comparaison, tout paraîtrait neuf.

**Le secteur se calcule à l'envoi, pas à l'import.** Le DPE porte sa zone
en colonne. Une vente la déduit de la position que DVF pose sur chaque
ligne, au moment de l'alerte. C'est volontaire : les repères de secteur
sont modifiables dans les Réglages, et une colonne figée dirait « plage »
pour une vente que les repères actuels rangent au bourg. Une vente sans
position n'est jamais rangée dans un secteur — la taire vaut mieux que l'y
mettre au hasard.

**La profondeur d'historique est affichée.** Elle ne se devine pas : la
source n'offre que cinq ans, la base en garde davantage à mesure que les
millésimes en sortent, et rien d'autre ne dirait où l'on en est. L'écran
Réglages montre donc combien de ventes sont conservées, sur quelle période,
quels millésimes la source sert encore, et **combien sont gardées au-delà** —
la seule mesure qui dise si la reprise a servi à quelque chose.

**La commune surveillée se lit dans les réglages, jamais à l'écran.** Les
champs dorment masqués et vides tant qu'on n'a pas cliqué sur « Modifier » :
les lire rendait la chaîne vide, et « Reprendre l'historique » visait alors
toutes les communes ou aucune. C'est le serveur qui tranche désormais. Le
même piège avait déjà fait échouer le contrôle d'envoi — troisième fois que
cette structure d'écran le tend.

**Le passage de version ne transforme pas l'archive en nouveautés.** Les
2 054 ventes déjà en base ont été importées avant que l'alerte n'existe :
`alerte_le` y naîtrait à `NULL`, et le premier courriel les aurait toutes
listées. La migration les marque comme déjà signalées — même raisonnement
que la suppression du premier import, appliqué au changement de version.
Un test rejoue ce chemin pour de bon, sur une base montée jusqu'au 006
puis migrée : il ne s'emprunte qu'une fois par base, et ne casserait pas un
test au passage — il enverrait un courriel absurde le jour de la parution.

---

## Sauvegardes

**Ce que contient cette base ne se retélécharge pas.** DVF ne se consulte
que sur cinq ans ; à chaque parution d'automne, le millésime le plus ancien
quitte la source et ne subsiste plus qu'ici. Les DPE ne sont pas purgés. La
sauvegarde n'est donc pas une précaution d'usage, c'est la seule chose qui
sépare cet historique de sa disparition.

Une copie datée est écrite **après chaque import**, dans
`VEILLE_SAUVEGARDES` (`/sauvegardes` sur le NAS).

**La copie est vérifiée avant de compter.** `quick_check` relit toutes les
pages, et les lignes de `dpe`, `mutation`, `parcelle` et `reglage` sont
recomptées dans la copie. Une copie qui ne se vérifie pas est jetée et ne
remplace rien : sauvegarder une base abîmée puis faire tourner la rotation
est la façon classique de tout perdre en croyant se protéger.

**Elle est publiée de façon atomique.** L'écriture se fait dans un fichier
`.partiel` à côté, et le nom définitif n'apparaît qu'une fois la
vérification passée. Sans cela, deux sauvegardes dans la même minute
portaient le même nom — et une seconde qui échoue avait déjà écrasé la
première. C'est un test qui l'a trouvé, pas une relecture.

**Chaque sauvegarde tient en un seul fichier.** `backup()` reproduit le
mode WAL de la source, et la copie traînait un `-wal` et un `-shm`
orphelins. Un `PRAGMA journal_mode = DELETE` replie tout dedans : c'est ce
qu'on glisse sur une clé, ce qu'Hyper Backup emporte, et ce qu'on rouvrira
sans se demander quels fichiers vont ensemble.

**La rotation garde le récent et l'ancien** : les sept derniers jours, puis
une par mois sur douze mois, puis une par an sans limite. Ne garder que les
dernières copies serait un piège — une corruption passe rarement inaperçue
le jour même, et s'il faut trois semaines pour la remarquer, sept jours de
rétention n'ont plus rien à offrir. Mesuré : quatre ans de copies
quotidiennes se réduisent à **23 fichiers**, soit environ 700 Mo pour une
base de 30 Mo.

### Restaurer

Trois gestes, sans outil :

```bash
docker compose stop veille                       # 1. arrêter
cp /volume1/veille-sauvegardes/veille-2026-08-24-0700.db    /var/lib/docker/volumes/veille-donnees/_data/veille.db
docker compose start veille                      # 3. redémarrer
```

Un test rejoue exactement cette procédure : il peuple une base, la
sauvegarde, **efface la base vivante**, restaure par simple copie, et
vérifie que les données sont là, que la base est de nouveau *écrivable*, et
que les migrations ne rejouent rien. Une sauvegarde qui ne se restaure pas
ne sert à rien, et on ne l'apprend qu'au pire moment.

### Ce que cela ne protège pas

Les copies vivent sur le même NAS. Elles couvrent l'effacement accidentel,
une corruption de la base, une mise à jour qui tourne mal. **Elles ne
couvrent pas la panne du disque** — pour cela il faut qu'elles sortent du
NAS, et c'est le travail d'Hyper Backup.

C'est la raison du montage en **dossier partagé** plutôt qu'en volume
Docker : Hyper Backup sauvegarde des dossiers partagés, tandis qu'un volume
Docker vit dans `/var/lib/docker` et lui échappe le plus souvent. Le dossier
est aussi visible depuis DSM, donc consultable et copiable sans ligne de
commande.

Rien ne part vers un tiers (CDC 9) : tout reste sur le NAS.

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
│   └── sauvegarde.py        copies datées, vérifiées, tournantes
├── sources/         API externes : ADEME (3 bases), geo.api.gouv.fr
│   ├── ban.py               géocodage des DPE que l'ADEME n'a pas placés
│   ├── dvf.py               ventes, cinq millésimes glissants
│   ├── dvf_archive.py       les millésimes que la source ne sert plus
├── metier/          logique portée des scripts d'origine
│   ├── veille.py            F1 — les DPE récents, dédoublonnés
│   ├── identification.py    F2 — l'entonnoir et le classement
│   ├── fiche.py             F4 — chronologie, remplacements, comparaison
│   ├── mutations.py         Ventes DVF, rattachées par la parcelle
│   ├── alertes.py           F6 — l'alerte sur les DPE nouvellement parus
│   ├── alerte_ventes.py     l'alerte sur les ventes nouvellement publiées
│   └── (carte : parcelles.pour_carte + chercher_sur_carte)
│   ├── geometrie.py         surfaces, appartenance, index spatial en grille
│   ├── parcelles.py         F3 — cadastre, extrait, carte
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

### Un DPE sur vingt manquait à l'appel

L'import interroge l'ADEME par **code INSEE** — c'est le seul repérage
fiable, et un code postal couvre plusieurs communes (le 40200 en couvre
cinq). Mais environ **5 % des DPE n'ont aucun code INSEE** : le géocodage
de l'ADEME a échoué sur eux, et ils étaient donc invisibles.

Mesure sur Mimizan, le 24 août 2026 :

| | |
|---|---|
| DPE récupérés | 2 023 |
| DPE sans code INSEE, donc manqués | **102** — 4,8 % |
| …dont **maisons** | **48** |
| …dont maisons de 2025-2026 | **46 sur 48** |

Ce ne sont pas des miettes anciennes : quarante-six maisons diagnostiquées
en dix-huit mois, dans la commune surveillée.

**Ces lignes ne sont pas douteuses — leur adresse est bavarde.** Le motif
saute aux yeux :

```
« 5 rue Bremontier - Résidence Cap Océan - Apt 317 »
```

Ni la résidence ni le numéro d'appartement ne figurent dans un référentiel
d'adresses. Coupé après le nom de voie, ce qui reste se géocode sans peine.

L'application les récupère donc par leur code postal — le seul repérage
géographique qui leur reste — nettoie l'adresse, et la fait géocoder par la
**Base Adresse Nationale** (déjà déclarée au CDC §4, jusque-là inutilisée).
Réparée, la ligne redevient ordinaire : elle a sa position, donc son
secteur, sa parcelle et son historique de ventes.

**Le code INSEE que rend la BAN sert de garde-fou.** C'est lui qui décide
si la ligne appartient vraiment à la commune : sans ce contrôle, réparer
les orphelins de Mimizan y ferait entrer ceux d'Aureilhan, les deux
partageant le 40200. Un test le vérifie, et échoue si le contrôle saute.

Deux garde-fous de plus. Un **score minimum de 0,55** : les bonnes
correspondances mesurées sortent entre 0,70 et 0,96, une rue mal reconnue
à 0,40. Et la réparation **ne peut jamais faire échouer un import** — c'est
un complément, pas une condition ; une panne de la BAN priverait sinon la
veille de sa moisson quotidienne.

Import réel de Mimizan avant / après : **4 343 → 4 448 DPE**, les 105
nouveaux tous positionnés et rangés dans un secteur.

#### Les positions aberrantes, réparées par la même mécanique

Cas voisin, traité par le même chemin : des DPE que l'ADEME rattache bien
à la commune mais **sans position exploitable**. Ils étaient en base, donc
cherchables par critères — mais sans secteur, sans parcelle et sans
historique de ventes, donc absents de la carte et des alertes par secteur.

Le diagnostic sur Mimizan a séparé deux populations que rien ne
distinguait à l'écran :

| Origine | Nombre | Adresse à la source | Réparable |
|---|---|---|---|
| base « existant » | 21 | oui — « 18 Avenue des Oiseaux » | **oui** |
| base « ancien » (avant 07/2021) | 84 | aucune, `geo_score = 0` | non |

Les 21 premières portent toutes le **même** `_geopoint` :
`-5.98, -1.36` — en plein Atlantique. C'est le Lambert-93 (0,0) converti,
et leur `statut_geocodage` annonce pourtant « adresse géocodée ban à
l'adresse ». Le filtre des positions aberrantes les écartait à juste
titre ; il ne restait qu'à leur rendre la bonne.

Les 84 autres sont irréparables : la base d'avant juillet 2021 ne porte
aucune adresse pour elles. Il n'y a rien à géocoder, et aucune requête ne
part — un test le vérifie.

Résultat mesuré : **105 → 85** lignes sans position, les 20 réparées
reprenant leur secteur (13 plage, 7 bourg). Le vingt-et-unième cas échoue
sur « 80 Chemin des parcs-Quartier Archus Nord » : le tiret y est collé,
comme dans « Saint-Julien » ou « 5-7 », et le desserrer casserait ces
cas-là. Compromis assumé, à un enregistrement près.

L'adresse **brute** est désormais demandée à chaque import, pas seulement
pour les orphelines : c'est le seul recours quand l'adresse normalisée est
vide ou que la position est fausse.

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

**Il éprouve ce qu'on est en train de regarder.** Zone d'envoi ouverte, il
éprouve les champs affichés : le geste naturel est de les remplir puis de
cliquer sur « contrôle », et tester la table *enregistrée* — vide tant
qu'on n'a pas cliqué sur Enregistrer — faisait accuser une absence que
l'utilisateur voyait pourtant remplie à l'écran. Zone fermée, il éprouve la
configuration enregistrée, la seule qui existe alors.

Cette distinction n'est pas un détail : depuis que les champs dorment
masqués tant qu'on n'a pas cliqué sur « Modifier », les lire sans condition
envoyait un brouillon **vide** qui masquait la configuration enregistrée le
temps du contrôle — celui-ci annonçait « serveur absent » pour une
configuration parfaitement valide. Le brouillon n'est donc lu que si la
zone est ouverte, et le rappel d'enregistrer n'apparaît que dans ce cas :
sinon il n'y a rien à enregistrer. Le contrôle n'écrit jamais en base.

#### L'horaire d'import se règle à l'écran, pas dans l'environnement

Le rythme de la veille est un **choix de comportement**. Il vit donc en base,
dans la table `reglage`, comme les secteurs, les filtres et le serveur
d'envoi — et se modifie depuis l'écran Réglages. L'environnement du
conteneur ne porte plus que ce qui relève du **déploiement** :
`VEILLE_PLANIFICATEUR` (ce conteneur exécute-t-il des tâches planifiées ?
un poste de développement dit non), `TZ`, les chemins et le port.

Il n'en a pas toujours été ainsi, et le prix a été payé — voir le piège
ci-dessous. Trois conséquences valent d'être notées :

**Une variable gravée dans un conteneur existant est désormais inerte.**
Un `VEILLE_IMPORT_JOUR=mon` hérité d'un ancien déploiement n'a plus aucun
effet ; l'horaire vient de la base. Corriger un conteneur mal configuré ne
demande donc plus de le recréer — un test le vérifie en posant les deux
variables et en constatant qu'elles sont ignorées.

**Le changement prend effet immédiatement.** L'API replanifie le travail
d'APScheduler à l'enregistrement. Sans cela il n'agirait qu'au prochain
redémarrage, et l'écran annoncerait la nouvelle heure pendant que le
planificateur suivrait l'ancienne — exactement le désaccord que tout ceci
vient supprimer. Un test l'éprouve de bout en bout, et échoue si l'appel à
`replanifier()` disparaît.

**Un cron invalide est refusé à l'écriture.** Il ne se verrait sinon qu'au
démarrage suivant, quand le planificateur refuserait de partir.

#### Un défaut du compose survit à toutes les mises à jour

Le piège qui a causé la confusion, et il n'est pas évident. Le compose
déclarait chaque variable avec **son propre défaut** — `${VEILLE_IMPORT_JOUR:-*}`
— qui dupliquait celui de `config.py`. Or :

1. Docker substitue la valeur **à la création du conteneur**, ce qui la
   grave dedans comme une variable bien réelle ;
2. Watchtower remplace l'**image** mais conserve l'**environnement** du
   conteneur existant ;
3. le défaut du compose survit donc à toutes les mises à jour, et se met à
   diverger du code dès qu'on le change.

C'est exactement ce qui s'est produit. Le compose posait `mon` le 20 août
à 9 h ; le code est passé à `*` le même soir à 22 h. Le conteneur déployé
entre-temps est resté **hebdomadaire pendant des semaines** — l'écran
annonçant « chaque jour » d'après le code pendant que le planificateur
suivait le `mon` gravé dans le conteneur. Aucune des deux moitiés ne
mentait seule ; c'est leur désaccord qui trompait.

Le compose passe désormais une chaîne **vide** quand rien n'est choisi, et
`config.py` traite le vide comme une absence. Une seule source de vérité,
qui suit les mises à jour d'image ; un `.env` posé à côté continue de
primer. Un test relit le compose et échoue si un défaut y est réintroduit —
la panne ne se verrait sinon qu'à l'usage, des semaines plus tard.

Conséquence pratique : **changer le compose ne suffit pas** sur un
conteneur déjà créé. Il faut le recréer (`docker compose up -d
--force-recreate`) pour que le nouvel environnement s'applique.

`TZ` garde son défaut : elle est lue par le système autant que par
l'application, et vide elle vaudrait UTC — l'import de 7 h partirait à 9 h
en été. `VEILLE_SAUVEGARDES` aussi : elle désigne un point de montage
déclaré dans le compose, que le code ne peut pas connaître.

**Le rythme affiché est le rythme réel.** L'écran annonçait « Import
automatique hebdomadaire » — une chaîne écrite en dur, vraie par hasard sur
un déploiement hebdomadaire et fausse sur tous les autres. Le journal du
conteneur disait « import quotidien » au même moment. Or le rythme se règle
par `VEILLE_IMPORT_JOUR`, dont la valeur par défaut (`*`, chaque jour) n'est
pas forcément celle du `.env` déployé.

C'est la ligne qu'on vient lire quand aucun courriel n'est arrivé, et elle
mentait. `/api/sante` sert donc les jours, l'heure et le fuseau ; l'écran
traduit le cron en français — « chaque lundi », « du lundi au vendredi »,
« les lundi, jeudi ».

Elle rappelle aussi ce qui n'allait pas de soi : **les alertes ne partent
qu'au passage planifié**. Consulter une commune rafraîchit la base — le
journal des imports le montre — mais n'envoie rien. Un import manuel qui
ramène cent nouveaux DPE ne déclenche donc aucun courriel ; ils attendent le
passage suivant.

**Chaque passage laisse une trace, même muet.** C'est le complément
indispensable du précédent : savoir que le passage a lieu à 7 h ne dit pas
ce qu'il a donné. L'issue de chaque tentative — envoyée, rien de neuf,
désactivée, serveur injoignable — partait au journal du conteneur et nulle
part ailleurs. Sur un NAS, ce journal n'est pas lisible sans SSH, et « je
n'ai rien reçu ce matin » restait donc sans réponse consultable.

Le journal des imports ne suffisait pas : il dit que la moisson a réussi,
ce qui est vrai **même les jours où aucun courriel ne part**. Les deux
événements sont distincts, et leurs silences ont des causes différentes.

Une ligne est donc écrite à chaque passage, y compris quand rien ne part —
c'est justement le cas qu'on cherche à expliquer. Sans trace du silence,
« je n'ai rien reçu » ne se distingue pas de « le passage n'a pas eu lieu ».
Les raisons sont affichées en clair, et leur couleur dit s'il y a quelque
chose à corriger :

| Ce qu'on lit | Ce que ça veut dire |
|---|---|
| Message envoyé — 3 bien(s) | tout va bien |
| Rien de neuf | aucun bien ne répondait aux critères — le cas le plus fréquent |
| Alerte désactivée | un réglage à changer |
| Aucun destinataire enregistré | l'adresse n'a jamais été enregistrée |
| Envoi refusé par le serveur | avec le message exact du serveur |

Le journal est un **témoin, jamais une condition** : une écriture
impossible ne doit pas empêcher un courriel de partir. Un test le vérifie.

**L'écran dit QUAND l'alerte part, et à quelles conditions.** « Je n'ai
rien reçu aujourd'hui » restait sans réponse : rien n'indiquait l'heure du
passage, ni s'il avait seulement lieu sur ce conteneur, ni ce qui décide
d'un envoi. `prochaine_execution()` existait dans le planificateur mais
n'était exposée nulle part.

La zone Alerte affiche donc le passage — chaque jour à 7 h, fuseau compris,
avec la date du prochain — et rappelle les critères, qui sont plus étroits
qu'on ne le croit : **maisons seules**, 80 à 400 m², diagnostiquées dans les
120 derniers jours. Sur Mimizan cela représente environ quinze biens par
mois, et ils arrivent par paquets — l'ADEME publie avec deux à trois
semaines de retard, pas au fil de l'eau. **Plusieurs jours sans courriel
sont donc normaux**, et c'est ce que l'écran dit maintenant.

L'horaire s'affiche même sans serveur d'envoi configuré : le « quand » ne
dépend pas du « comment », et une configuration incomplète cachait
justement l'information qu'on venait chercher.

Il ne répond pas par oui ou non. « Ça ne marche pas » ne se débogue pas :
il faut savoir **où** cela s'arrête. Une boîte de dialogue montre donc la
trace, étape par étape — configuration, connexion, chiffrement,
authentification, envoi — chacune datée, car un délai d'attente se
reconnaît à sa durée. Chaque étape franchie écarte une moitié des causes
possibles.

L'échec revient en 200, pas en erreur : c'est le *résultat* de l'appel, pas
une erreur de l'appel, et un code d'erreur priverait l'écran de la trace.
Le mot de passe n'y figure jamais — elle est faite pour être affichée.

La boîte est posée **hors** de toute zone de réglage. Enfermée dans un bloc
d'édition — masqué tant qu'on n'édite pas — `showModal()` réussissait sans
que rien ne paraisse : `hidden` sur un ancêtre l'emporte. Le symptôme n'est
pas une erreur mais une absence, et l'écran semblait figé, le bouton restant
sur « Envoi… » derrière une boîte modale invisible qui bloquait le reste de
la page.
Quand la cause est reconnaissable, une piste concrète accompagne le
diagnostic : un port qui ne répond pas, un STARTTLS demandé sur un port
SSL, des identifiants refusés faute d'accès POP3/IMAP activé chez le
fournisseur.

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

**Le retour arrière du téléphone remonte le parcours.** L'application tient
en une seule page&nbsp;: sans rien faire, le geste habituel — glisser depuis
le bord, ou le bouton matériel — quittait le site depuis une fiche. Chaque
écran laisse donc une entrée dans l'historique, et celle d'une fiche porte
*quel* bien elle montrait, faute de quoi y revenir afficherait une fiche
vide. Le bouton « Retour » de la fiche fait le même geste plutôt que
d'empiler une étape de plus.

Le bouton est en tête, et collé sous le bandeau : sur téléphone une fiche
fait plusieurs écrans de haut, et le chercher en bas obligeait à parcourir
tout ce qu'on venait de lire.

**La hauteur du bandeau est mesurée, pas supposée.** `--bandeau-hauteur`
est une hauteur *minimale* de 60 px ; sur téléphone le bandeau se replie et
atteint 105 px. Les éléments qui se collent dessous s'y cachaient à moitié.
Un `ResizeObserver` publie la hauteur réelle dans `--bandeau-reel`, que
suivent les règles collantes — aucune constante ne peut prévoir un repli.

**L'écran des Réglages montre ce qui est enregistré, pas des champs de
saisie.** Il présentait des champs déjà remplis, et rien ne distinguait une
valeur venue de la base de celle qu'on venait de taper. Pire : un unique
bouton « Enregistrer », posé au milieu de la page dans « Filtres par
défaut », enregistrait *toutes* les zones — y compris celles situées en
dessous, dont on ne voyait pas qu'elles étaient concernées.

Chaque zone affiche donc maintenant ses valeurs enregistrées, en lecture
seule. « Modifier » ouvre les champs — sur un fond distinct, parce qu'on
est alors dans un état où rien n'est acquis — « Enregistrer » n'écrit que
cette zone-là, et « Annuler » referme sans rien changer. Le même défaut
avait déjà produit une confusion sur le contrôle d'envoi, qui éprouvait la
table pendant que l'écran montrait autre chose.

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
