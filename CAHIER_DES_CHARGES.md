# Cahier des charges — Veille immobilière Mimizan

**Version** 1.0 — août 2026
**Maître d'ouvrage** Mathias
**Cible de déploiement** Synology NAS, Container Manager

---

## 1. Objet

Application web privée destinée à identifier, avant leur mise en ligne sur les portails d'annonces, les maisons susceptibles d'être vendues sur Mimizan et ses communes voisines, et à qualifier un bien à partir de ses seules caractéristiques publiques.

Elle consolide en un outil unique une série de scripts en ligne de commande déjà écrits et validés, fournis dans `scripts_existants/`.

**Utilisateurs** deux personnes d'un même foyer, sur mobile et sur ordinateur.

**Ce que l'application n'est pas** ni un CRM, ni un outil de prospection de masse, ni un service destiné à des tiers. Elle est mono-foyer et non exposée publiquement.

---

## 2. Contraintes d'hébergement

| Contrainte | Exigence |
|---|---|
| Plateforme | Synology Container Manager (Docker Compose v2) |
| Architecture | Image multi-arch — vérifier `uname -m` du NAS avant build (`x86_64` ou `aarch64`) |
| Empreinte | Un seul conteneur. RAM cible < 512 Mo, image < 400 Mo |
| Persistance | Un volume monté pour la base SQLite et les exports |
| Réseau | Un seul port exposé, configurable. Aucun accès Internet entrant direct |
| Accès distant | Via le reverse proxy Synology (DSM → Portail des applications), avec HTTPS |
| Build | Doit pouvoir se construire sur le NAS lui-même, sans chaîne Node.js |

Une conséquence pratique du passage sous Linux : le problème de certificats rencontré sous Windows disparaît. Le conteneur dispose du magasin de l'OS. Inclure malgré tout `certifi` dans les dépendances par sécurité.

---

## 3. Architecture cible

```
┌──────────────────────────────────────────────┐
│  Conteneur unique                            │
│                                              │
│  FastAPI (Python 3.12)                       │
│    ├── API REST /api/*                       │
│    ├── Fichiers statiques /                  │
│    └── Planificateur APScheduler             │
│                                              │
│  SQLite  →  /data/veille.db  (volume)        │
└──────────────────────────────────────────────┘
```

**Backend** FastAPI + Uvicorn. Toute la logique métier des scripts existants est portée en modules importables, sans `input()` ni `print()`.

**Frontend** HTML + CSS moderne (custom properties, grid) + JavaScript en modules ES natifs. **Pas de React, pas de bundler.** Justification : un seul conteneur, pas d'étape de build sur le NAS, et un code que le propriétaire pourra relire lui-même. Cartographie par Leaflet, fonds IGN et OpenStreetMap.

**Base** SQLite. Le volume de données est faible (quelques dizaines de milliers de lignes) et la concurrence nulle.

**Polices et bibliothèques** auto-hébergées dans l'image, pas de CDN — l'application doit fonctionner si le NAS perd Internet, et aucune requête ne doit fuiter vers des tiers.

---

## 4. Sources de données

| Source | Usage | Accès |
|---|---|---|
| ADEME `dpe03existant` | DPE depuis juillet 2021 | API data-fair, `data.ademe.fr` |
| ADEME `dpe02neuf` | DPE logements neufs | idem |
| ADEME `dpe-france` | DPE avant juillet 2021 | idem, schéma différent |
| Cadastre Etalab | Parcelles et bâtiments | `cadastre.data.gouv.fr`, GeoJSON par commune |
| API Découpage administratif | Résolution nom de commune → code INSEE | `geo.api.gouv.fr` |
| Base Adresse Nationale | Géocodage inverse | `api-adresse.data.gouv.fr` |
| DVF | Ventes passées | `app.dvf.etalab.gouv.fr` / API Etalab |
| Panoramax | Photos de rue libres | `api.panoramax.xyz` — optionnel, couverture à vérifier |

**Règles impératives**

- Toute source est mise en cache en base. Aucun appel externe ne doit être déclenché par le simple affichage d'une page.
- Un identifiant de navigateur classique doit être envoyé : le pare-feu de l'ADEME renvoie 403 sur les agents inhabituels.
- Les noms de colonnes de l'ADEME changent entre versions. Le repérage automatique par lecture du `/schema`, déjà implémenté dans `dpe_recherche.py`, doit être conservé.
- Le filtrage sur l'API se fait par `{champ}_eq=`. Prévoir la cascade de repli déjà écrite.

---

## 5. Modules fonctionnels

### F1 — Veille des DPE récents
*Priorité 1. C'est la fonction qui justifie l'application.*

Un DPE est obligatoire avant toute mise en vente. Un diagnostic récent précède donc souvent l'annonce de plusieurs semaines.

- Rafraîchissement automatique hebdomadaire, et bouton de rafraîchissement manuel.
- Filtres : commune, secteur géographique, type de bâtiment, fourchette de surface, fenêtre temporelle, classe énergétique.
- Séparation bourg / plage par rattachement au point de référence le plus proche — Mimizan-Plage n'a ni code postal ni code INSEE propre. Points de référence configurables dans l'interface.
- Une ligne par adresse, le DPE le plus récent.
- Marquage de ce qui est apparu depuis la dernière consultation.
- Code de référence : `scripts_existants/dpe_recents.py`, incluant la conversion Lambert-93 vérifiée au centimètre contre pyproj.

### F2 — Identification d'un bien depuis une annonce
*Priorité 1.*

Saisie des chiffres lus sur une annonce — surface, consommation en énergie primaire et finale, émissions, étiquettes — et restitution des logements classés par ressemblance.

- **Ne jamais éliminer sans expliquer.** Afficher l'entonnoir : nombre de logements satisfaisant chaque critère isolément, puis en cumulé. C'est ce qui permet de repérer quel chiffre de l'annonce est faux ou arrondi.
- Résultats classés par écart moyen, avec le détail critère par critère.
- Tolérances réglables dans l'interface.
- Code de référence : `scripts_existants/dpe_recherche.py`.

### F3 — Recherche cadastrale
*Priorité 2.*

Filtrage des parcelles d'une commune par surface de terrain et emprise bâtie au sol.

- Import et mise en cache du cadastre communal.
- Rattachement des bâtiments aux parcelles par index spatial en grille — l'approche naïve serait en O(n×m) et inutilisable.
- Affichage cartographique des parcelles retenues.
- Recoupement avec F1 et F2 : une adresse présente dans deux modules est un candidat quasi certain.
- Code de référence : `scripts_existants/parcelles.py`.

### F4 — Fiche bien et historique
*Priorité 2.*

- Chronologie de tous les DPE connus pour une adresse, toutes bases confondues.
- Chaîne des remplacements de DPE, avec comparaison champ par champ.
- **Attention** un DPE remplacé est retiré de la base active de l'ADEME. Le dire explicitement plutôt que de renvoyer un résultat approchant. La recherche plein texte sur un numéro ramène les DPE qui le *citent* : n'accepter un résultat que si le filtre portait sur le champ du numéro, ou si l'égalité est vérifiable.
- Code de référence : `dpe_historique.py` et `dpe_comparer.py`.

### F5 — Suivi personnel
*Priorité 2.*

- Mise en favori d'un bien, avec statut : à étudier, à visiter, visité, écarté.
- Notes libres, horodatées, attribuées à l'un des deux utilisateurs.
- Vue liste et vue carte des biens suivis.

### F6 — Notifications
*Priorité 3.*

- Appel d'un webhook Home Assistant lorsque de nouveaux DPE correspondent aux critères enregistrés.
- URL du webhook configurable, désactivable.

### F7 — Photos de rue
*Priorité 3, conditionnel.*

Planche contact de vignettes Panoramax pour une liste de biens. **À ne développer qu'après vérification de la couverture réelle de Mimizan** — ces plateformes reposent sur des contributeurs bénévoles et les lotissements résidentiels sont rarement couverts. Code de référence : `photos_rue.py`.

---

## 6. Modèle de données

```sql
commune(code_insee PK, nom, code_postal, derniere_maj_cadastre, derniere_maj_dpe)

parcelle(id PK, code_insee, section, numero, contenance_m2,
         emprise_batie_m2, nb_batiments, latitude, longitude, geometrie_json)

dpe(n_dpe PK, code_insee, adresse, latitude, longitude, zone,
    date_etablissement, surface_habitable, type_batiment,
    etiquette_dpe, etiquette_ges, conso_ep_m2, conso_ef_m2,
    ges_m2, cout_annuel, annee_construction, n_dpe_remplace,
    jeu_de_donnees, donnees_brutes_json, vu_le)

suivi(id PK, adresse, n_dpe, parcelle_id, statut, cree_le, maj_le)

note(id PK, suivi_id FK, auteur, texte, cree_le)

reglage(cle PK, valeur_json)

journal_import(id PK, source, debut, fin, lignes, statut, message)
```

Conserver le JSON brut de chaque DPE : la base ADEME compte 230 colonnes et les besoins évolueront.

---

## 7. Interface

### Direction visuelle

L'application manipule des relevés cadastraux, des références parcellaires et des mesures. Le registre visuel est celui du **document technique de l'administration foncière** — le plan, pas la brochure d'agence immobilière.

**Palette**

| Rôle | Hex |
|---|---|
| Encre — texte, tracés | `#12262B` |
| Papier — fond | `#F1F3F1` |
| Pin — accents structurels | `#2E5B4C` |
| Atlantique — interactif, liens | `#14708C` |
| Ambre — signal « nouveau » | `#D9A441` |
| Alerte | `#A33A2A` |

**Typographie**

- Titres : *Space Grotesk*, employée avec retenue.
- Texte courant : *Public Sans*.
- **Données : *IBM Plex Mono*.** Toutes les références cadastrales, numéros de DPE, surfaces et consommations sont en chasse fixe. C'est ce qui donne à l'interface son caractère de document de relevé, et cela rend les colonnes de chiffres réellement comparables à l'œil.

**Élément signature**

La fiche d'un bien reprend la forme d'un extrait cadastral : le polygone de la parcelle tracé à l'encre sur une trame fine, la référence en chasse fixe dans l'angle, les mesures alignées en colonne. C'est le seul endroit où l'on dépense de l'audace ; tout le reste reste sobre.

**À éviter** le fond crème avec serif contrasté et accent terracotta, le fond quasi noir avec accent vert acide, la mise en page pseudo-journal à filets. Ces trois directions sont des réflexes, pas des choix.

### Écrans

1. **Veille** — liste des DPE récents, tri par date, badge ambre sur les nouveautés depuis la dernière visite. Carte en regard. Écran d'accueil.
2. **Identifier un bien** — formulaire de saisie des chiffres d'annonce, entonnoir de filtrage, résultats classés.
3. **Recherche cadastrale** — filtres de surface, carte, tableau.
4. **Fiche bien** — caractéristiques, chronologie des DPE, parcelle, liens externes, notes.
5. **Suivi** — les biens mis en favori, par statut.
6. **Réglages** — communes surveillées, points de référence des secteurs, tolérances, webhook, rafraîchissement manuel.

### Exigences transverses

- Utilisable au doigt : la consultation se fera souvent en mobilité, devant une maison.
- Tout tableau exportable en CSV.
- Chaque bien porte des liens directs vers la vue satellite, Street View et le Géoportail.
- États vides et erreurs explicites : dire ce qui s'est passé et quoi faire, jamais un simple « aucun résultat ».
- Toute opération longue affiche sa progression. Les scripts existants ont montré qu'un écran figé sans retour est ingérable.
- Accessibilité : focus clavier visible, contrastes AA, `prefers-reduced-motion` respecté.

---

## 8. Traitements planifiés

| Tâche | Fréquence |
|---|---|
| Import des DPE des communes surveillées | hebdomadaire |
| Détection des nouveautés et notification | à la suite de l'import |
| Rafraîchissement du cadastre | mensuel |

Chaque exécution est tracée dans `journal_import` et consultable dans les réglages. Un échec ne doit jamais laisser la base dans un état partiel : import en transaction.

---

## 9. Sécurité et conformité

- **Aucune exposition publique.** Accès par le reverse proxy Synology, protégé par authentification.
- Les données manipulées sont publiques, mais leur agrégation constitue un traitement de données personnelles. L'usage reste strictement privé, dans le cadre de la recherche d'une résidence pour le foyer.
- Aucune fonction d'export en masse à destination de tiers, aucun envoi automatique de courrier, aucune API publique.
- Purge : suppression des données de veille de plus de 24 mois.
- Aucune donnée transmise à un service tiers hors des API publiques listées en section 4.

---

## 10. Hors périmètre

- Recherche inversée de façade à partir d'une photo. Aucun service ne le permet pour une maison ordinaire, et l'indexation locale d'un corpus d'images est un projet distinct à l'issue incertaine.
- Noms des propriétaires. Aucune base ouverte n'existe ; la procédure de l'article L107 A du Livre des procédures fiscales est manuelle et plafonnée à 25 parcelles par semaine.
- Successions à venir. Aucune donnée ne les recense avant leur ouverture.

---

## 11. Lots de livraison

**Lot 1 — socle** Conteneur, FastAPI, SQLite, import ADEME avec cache, écran Veille (F1). *L'application doit être utile dès ce lot.*

**Lot 2 — qualification** F2 identification, F4 fiche et historique.

**Lot 3 — cadastre** F3, avec import du cadastre et cartographie.

**Lot 4 — usage à deux** F5 suivi et notes, F6 notifications.

**Lot 5 — conditionnel** F7 photos de rue, si la couverture Panoramax le justifie.

---

## 12. Recette

L'application est réputée conforme lorsque :

1. Elle démarre par `docker compose up -d` sur le NAS et répond sur son port.
2. Un redémarrage du conteneur préserve base, réglages et suivi.
3. L'import hebdomadaire s'exécute seul et se trace dans le journal.
4. La saisie des chiffres d'une annonce connue fait ressortir le bon logement dans les cinq premiers résultats.
5. L'entonnoir de F2 permet d'identifier quel critère élimine les candidats.
6. Un DPE remplacé introuvable est signalé comme tel, sans résultat approchant.
7. L'interface est utilisable d'une main sur un téléphone.
8. Aucune requête sortante vers un domaine hors de la liste de la section 4.
