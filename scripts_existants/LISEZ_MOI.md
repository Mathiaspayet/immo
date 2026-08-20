# Scripts existants — état et enseignements

Ces huit scripts ont été écrits, exécutés et corrigés contre les API réelles.
Chacun porte des correctifs obtenus par essais successifs. Ils constituent la
référence fonctionnelle du cahier des charges.

| Fichier | Rôle | À reprendre impérativement |
|---|---|---|
| `dpe_recents.py` | Veille des DPE récents (F1) | Conversion Lambert-93 → WGS84, vérifiée au centimètre contre pyproj. Rattachement bourg/plage par point de référence le plus proche. Déduplication par adresse. |
| `dpe_recherche.py` | Identification d'un bien (F2) | Lecture du schéma de l'API pour retrouver les noms de colonnes. Analyse en entonnoir plutôt qu'élimination silencieuse. Cascade de syntaxes de requête. |
| `dpe_historique.py` | Chronologie des DPE (F4) | Gestion des deux générations de schémas ADEME, très différentes. Sélection des seules colonnes utiles. |
| `dpe_comparer.py` | Comparaison de deux DPE (F4) | Deux niveaux de confiance selon que le filtre porte ou non sur le champ recherché. Exclusion des champs techniques `_*` du moteur de recherche. |
| `parcelles.py` | Recherche cadastrale (F3) | Index spatial en grille. Formule des lacets pour les surfaces. Lancer de rayon pour l'appartenance d'un point à un polygone. Chemins relatifs au script. |
| `photos_rue.py` | Photos de rue (F7) | Non validé : couverture Panoramax de Mimizan à vérifier avant tout développement. |
| `ouvrir_liens.py` | Ouverture par lots | Devient inutile une fois l'interface web en place. |
| `diagnostic.py` | Diagnostic SSL | Spécifique à Windows. Sans objet dans un conteneur Linux. |

## Pièges déjà rencontrés, à ne pas réintroduire

**Recherche par sous-chaîne trop permissive.** `date_derniere_modification_dpe`
contient littéralement la séquence `n_dpe`. Prévoir une correspondance exacte
quand c'est nécessaire.

**Repli silencieux.** Une version de `dpe_comparer.py` renvoyait « le premier
résultat venu » quand la recherche exacte échouait. Résultat : deux fois le même
enregistrement présenté comme deux DPE distincts. Un échec franc vaut mieux
qu'un résultat faux mais crédible.

**Champs du moteur de recherche.** Les clés commençant par `_` (`_score`, `_id`)
sont ajoutées par data-fair et ne font pas partie des données.

**Nomenclature ADEME.** L'énergie primaire s'écrit `ep`, la finale `ef` — jamais
« primaire » ni « finale ». Et `emission_ges_5_usages` est un total annuel, à ne
pas confondre avec `emission_ges_5_usages_par_m2`.

**Absence de retour visuel.** Un téléchargement silencieux de plusieurs milliers
de lignes est indiscernable d'un plantage. Toute opération longue doit afficher
sa progression.
