# Filtres officiels de l'API Légifrance (fonds utilisés par ce serveur)

Source faisant foi : DILA, « Description des tris et filtres de l'API »
(classeur Open XML, mise à jour du 05/08/2024), référencé depuis
<https://www.legifrance.gouv.fr/contenu/pied-de-page/open-data-et-api> :
<https://www.legifrance.gouv.fr/contenu/Media/Files/pied-de-page/description-des-tris-et-filtres-de-l-api.xlsx>

Ce fichier documente, pour la classe `/search`, la liste **exhaustive** des
champs de recherche (`typeChamp`) et des filtres (`facette`) par fonds.
Il est reproduit ici pour éviter de re-tester à l'aveugle des noms de facettes
inexistants (l'API répond HTTP 500 sans jamais énumérer les valeurs admises).

## JURI — jurisprudence judiciaire

Champs de recherche : `ALL`, `TITLE`, `ABSTRATS`, `NUM_AFFAIRE`, `TEXTE`, `RESUMES`.

| Filtre | Champ technique | Facette |
|---|---|---|
| Par juridiction | juridictionJudiciaire | `JURIDICTION_JUDICIAIRE` |
| Publication au bulletin | cassPubliBulletin | `CASSATION_TYPE_PUBLICATION_BULLETIN` |
| Numéro au bulletin | numeroBulletin | `NUM_BULLETIN` |
| Année de publication au bulletin | anneeBulletin | `ANNEE_BULLETIN` |
| Cour de cassation — nature de la décision | cassDecision | `CASSATION_NATURE_DECISION` |
| **Cour de cassation — formation (chambre)** | cassFormation | `CASSATION_FORMATION` |
| Cour de cassation — décision attaquée | cassDecisionAttaquee | `CASSATION_DECISION_ATTAQUEE` |
| Cour de cassation — lieu de la décision attaquée | lieuDecision | `LIEU_DECISION` |
| Cour de cassation — date de décision attaquée | dateDecisionAttaquee | `DATE_DECISION_ATTAQUEE` |
| Juridiction d'appel — siège de la cour | siegeAppel | `APPEL_SIEGE_APPEL` |
| Premier degré — type de juridiction | premiereJuri | `PREMIER_DEGRE_TYPE_JURIDICTION` |
| Premier degré — siège de la juridiction | siegePremierDegre | `PREMIER_DEGRE_SIEGE` |
| Date de décision | dateDecision | `DATE_DECISION` |
| Numéro d'affaire | numAffaire | `NUM_AFFAIRE` |
| ECLI | ecli | `ECLI` |

**Conséquence directe** : le seul filtre de chambre/formation du fonds JURI est
`CASSATION_FORMATION`, et il ne s'applique qu'à la Cour de cassation. Pour les
cours d'appel et les juridictions du premier degré, l'API n'expose que le siège
(la ville) et le type de juridiction — aucune chambre, aucune matière. La
chambre d'un arrêt d'appel n'apparaît ni dans le titre ni dans aucun champ des
résultats de `/search` ; elle n'existe qu'en texte libre (« 2o chambre ») dans
la réponse `/consult/juri` de chaque décision prise une par une.

### Ce que cela implique par degré

- **Cour de cassation** : `CASSATION_FORMATION` porte la matière (chambre civile,
  commerciale, criminelle, sociale). Filtre rendu obligatoire.
- **Cours d'appel** : ni facette de chambre, ni chambre dans les résultats.
  Vérifié sur 500 arrêts d'appel tirés de `/search` : **0** titre mentionne une
  chambre (format « Cour d'appel de Versailles, 5 février 2015, 14/06125 »).
  La chambre n'existe qu'en texte libre dans `/consult/juri`, décision par
  décision. Aucun filtrage n'est donc possible à la recherche.
- **Premier degré** : la matière est portée par le nom de la juridiction
  (prud'hommes = social, tribunal de commerce = commercial, tribunal
  correctionnel = pénal). `PREMIER_DEGRE_TYPE_JURIDICTION` est donc rendu
  obligatoire. Attention : la facette mêle libellés génériques
  (« Conseil de prud'hommes », 270 décisions) et libellés par ville
  (« Tribunal correctionnel de Nice », 1 décision), et la correspondance est
  exacte, pas par préfixe — le serveur lit les valeurs réelles de la facette
  pour la requête en cours et étend chaque famille demandée.

## CETAT — jurisprudence administrative

Champs de recherche : `ALL`, `TITLE`, `NUM_DEC`, `ABSTRATS`, `TEXTE`, `RESUMES`.

| Filtre | Champ technique | Facette |
|---|---|---|
| Nom de la juridiction | juridiction | `JURIDICTION_NATURE` |
| Date de décision | dateDecision | `DATE_DECISION` |
| Date de versement dans la base | dateVersement | `DATE_VERSEMENT` |
| Publication au recueil | publiRecueil | `PUBLICATION_RECUEIL` |
| Numéro de décision | numDecision | `NUMERO_DECISION` |
| ECLI | ecli | `ECLI` |

Aucun filtre de chambre. `JURIDICTION_NATURE` est bien renvoyée dans les
facettes des réponses (valeurs `CONSEIL_ETAT`, `COURS_APPEL` et villes filles)
mais l'API répond HTTP 500 quand on l'envoie comme filtre, quelle que soit la
valeur : le tri Conseil d'État / CAA / ville reste donc côté client (c'est ce
que fait `Search_CAA`, la ville figurant dans le titre « CAA de PARIS, 3ème
chambre, … »).

## CODE_DATE / CODE_ETAT — codes

Champs de recherche : `ALL`, `TITLE`, `TABLE`, `NUM_ARTICLE`, `ARTICLE`.

| Filtre | Facette (par date) | Facette (par état) |
|---|---|---|
| État juridique des articles | `ARTICLE_LEGAL_STATUS` | — |
| État juridique des textes | `TEXT_LEGAL_STATUS` | — |
| Date de la version | `DATE_VERSION` | — |
| Nom du code | `NOM_CODE` | `TEXT_NOM_CODE` |
| Numéro d'article | `NUM_ARTICLE` | `NUM_ARTICLE` |
