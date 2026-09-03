# Champs, filtres et tris de `/search` (API Légifrance)

Ce document couvre la **classe `/search`** : pour chaque fonds, les champs de
recherche (`typeChamp`), les filtres (`facette`), les tris (`sort`), et le
vocabulaire réellement renvoyé par l'API pour les facettes énumérables.

Les **endpoints hors `/search`**, le **schéma complet de la réponse
`/consult/juri`** et la question de la **décision attaquée** sont traités dans
le document jumeau [`api-legifrance-endpoints-et-schemas.md`](api-legifrance-endpoints-et-schemas.md).
La séparation tient au volume : la description du `/consult` occupe 35 feuilles
du classeur DILA et une centaine de clés de réponse, sans rapport avec les
facettes de recherche.

## Statut des affirmations

Deux sources sont distinguées dans tout le document.

- **[DOC]** — DILA, « Description des tris et filtres de l'API », classeur
  Open XML, mise à jour du 05/08/2024, référencé depuis
  <https://www.legifrance.gouv.fr/contenu/pied-de-page/open-data-et-api> :
  <https://www.legifrance.gouv.fr/contenu/Media/Files/pied-de-page/description-des-tris-et-filtres-de-l-api.xlsx>
  (53 feuilles : 17 de recherche, 35 de consultation, 1 de présentation).
- **[OBS]** — observation directe sur l'API de production
  `https://api.piste.gouv.fr/dila/legifrance/lf-engine-app`, **le 2026-09-02**.
  Les décomptes cités sont ceux de ce jour et bougent avec les versements.

Aucune documentation OpenAPI n'est accessible : `/v2/api-docs`, `/v3/api-docs`,
`/swagger.json`, `/openapi.json`, `/api-docs` et `/swagger-ui.html` répondent
tous HTTP 403 sur le domaine de production (OBS 2026-09-02). Le classeur DILA
est donc la seule source normative disponible.

## Forme de la requête

```json
{"fond": "JURI", "sort": "PERTINENCE", "secondSort": "ID",
 "typePagination": "DEFAUT",
 "recherche": {"pageNumber": 1, "pageSize": 10, "operateur": "ET",
   "fromAdvancedRecherche": false,
   "champs": [{"typeChamp": "ALL", "operateur": "ET",
               "criteres": [{"typeRecherche": "UN_DES_MOTS",
                             "valeur": "contrat", "operateur": "ET"}]}],
   "filtres": [ … ]}}
```

Trois formes de filtre sont admises (OBS 2026-09-02) :

| Forme | Usage |
|---|---|
| `{"facette": F, "valeurs": ["A", "B"]}` | facette plate ; plusieurs valeurs sont en OU |
| `{"facette": F, "dates": {"start": "AAAA-MM-JJ", "end": "AAAA-MM-JJ"}}` | facette de date |
| `{"facette": F, "valeurs": ["P"], "multiValeurs": {"P": ["enfant"]}}` | facette hiérarchique (parent/enfant) |

La clé `champs` est **facultative** : une requête ne comportant que `filtres`
est acceptée et renvoie l'intégralité des décisions correspondant aux filtres
(OBS 2026-09-02). C'est ce qui rend possible l'index inverse décrit dans le
document jumeau.

## Pièges vérifiés (OBS 2026-09-02)

- **`typeChamp` inapplicable : rejet silencieux.** Un `typeChamp` valide au sens
  de l'énumération mais étranger au fonds (par exemple `NOR`, `IDCC`, `VISA` ou
  `ARTICLE` sur JURI) renvoie HTTP 200 en **abandonnant le critère de
  recherche** : la requête rend alors le fonds entier (JURI 605 978,
  CETAT 570 819, CODE_DATE 31 498, soit exactement les totaux de fonds).
  Un `typeChamp` inconnu de l'énumération, lui, renvoie HTTP 400. Les listes
  par fonds ci-dessous sont donc **normatives et à faire respecter côté
  client** : l'API ne signale pas l'erreur.
- **Filtre de date mal formé : rejet silencieux.** `DATE_DECISION` et
  `DATE_DECISION_ATTAQUEE` envoyés avec `singleDate` ou `valeurs` au lieu de
  `dates` renvoient HTTP 200 sans modifier le total.
- **Plafond de pagination.** `pageSize` est écrêté à 100 (une demande de 200
  rend 100 résultats). `pageNumber × pageSize` doit rester **≤ 10 000** ; au
  delà l'API répond HTTP 503 « Une erreur est survenue dans le moteur de
  recherche ». Vérifié à exactement 10 000 sur les couples (100, 100),
  (1 000, 10), (500, 20) et (2 000, 5).
- **Index multivalué.** Une même décision peut répondre à plusieurs valeurs
  d'un même champ de date. Voir la sentinelle `2999-01-01` documentée dans le
  document jumeau.

## Fonds

`config/settings.py` déclare 8 fonds (`LEGIFRANCE_FONDS`). Le classeur en
documente 17 (voir divergences en fin de document). Les fonds effectivement
utilisés par ce serveur sont JURI, CETAT, CODE_DATE et CODE_ETAT ; les autres
sont donnés pour complétude.

### JURI — jurisprudence judiciaire

Champs de recherche [DOC] : `ALL`, `TITLE`, `ABSTRATS`, `NUM_AFFAIRE`, `TEXTE`,
`RESUMES`.
Tris [DOC] : `PERTINENCE`, `DATE_DESC`, `DATE_ASC`.

| Filtre [DOC] | Champ technique | Facette | Forme | Vocabulaire |
|---|---|---|---|---|
| Par juridiction | juridictionJudiciaire | `JURIDICTION_JUDICIAIRE` | valeurs | 3 valeurs [OBS] |
| Publication au bulletin | cassPubliBulletin | `CASSATION_TYPE_PUBLICATION_BULLETIN` | valeurs | `F`, `T` [OBS] |
| Numéro au bulletin | numeroBulletin | `NUM_BULLETIN` | valeurs | non énuméré |
| Année de publication au bulletin | anneeBulletin | `ANNEE_BULLETIN` | valeurs | non énuméré |
| Cour de cassation — nature de la décision | cassDecision | `CASSATION_NATURE_DECISION` | valeurs | 4 valeurs [OBS] |
| Cour de cassation — formation | cassFormation | `CASSATION_FORMATION` | valeurs | 18 valeurs [OBS] |
| Cour de cassation — décision attaquée | cassDecisionAttaquee | `CASSATION_DECISION_ATTAQUEE` | valeurs | 19 valeurs [OBS] |
| Cour de cassation — lieu de la décision attaquée | lieuDecision | `LIEU_DECISION` | valeurs | **plein texte**, non énuméré [OBS] |
| Cour de cassation — date de décision attaquée | dateDecisionAttaquee | `DATE_DECISION_ATTAQUEE` | dates | — |
| Juridiction d'appel — siège de la cour | siegeAppel | `APPEL_SIEGE_APPEL` | valeurs | 36 villes [OBS] |
| Premier degré — type de juridiction | premiereJuri | `PREMIER_DEGRE_TYPE_JURIDICTION` | valeurs | 61 libellés [OBS] |
| Premier degré — siège de la juridiction | siegePremierDegre | `PREMIER_DEGRE_SIEGE` | valeurs | **rend 0** [OBS] |
| Date de décision | dateDecision | `DATE_DECISION` | dates | — |
| Numéro d'affaire | numAffaire | `NUM_AFFAIRE` | valeurs | non énuméré |
| ECLI | ecli | `ECLI` | valeurs | non énuméré |

Une facette non documentée est en outre renvoyée dans les réponses JURI :
`PDC_CHECKBOX_RESTREINDRE_ARRET` (champ `restreindreArretPlanClassement`),
toujours vide (OBS 2026-09-02).

`JURIDICTION_NATURE` **n'existe pas sur JURI** : HTTP 500, y compris sous la
forme `multiValeurs` (OBS 2026-09-02).

#### Vocabulaires observés (2026-09-02)

`JURIDICTION_JUDICIAIRE` : `Cour de cassation`, `Juridictions d'appel`,
`Juridictions du premier degré`.

`CASSATION_NATURE_DECISION` : `arret`, `autres_decisions`, `avis`,
`ordonnance`. Les valeurs sont en minuscules et sans accent.

`CASSATION_FORMATION` : `ASSEMBLEE_PLENIERE`, `AVIS`, `CHAMBRES_REUNIES`,
`CHAMBRE_CIVILE`, `CHAMBRE_CIVILE_1`, `CHAMBRE_CIVILE_2`, `CHAMBRE_CIVILE_3`,
`CHAMBRE_COMMERCIALE`, `CHAMBRE_CRIMINELLE`, `CHAMBRE_MIXTE`,
`CHAMBRE_SOCIALE`, `COMMISSION_REEXAMEN`, `COMMISSION_REPARATION_DETENTION`,
`COMMISSION_REVISION`, `COUR_REVISION`,
`JURIDICTION_NATIONALE_LIBERTE_CONDITIONNELLE`,
`ORDONNANCE_PREMIER_PRESIDENT`, `TRIBUNAL_CONFLIT`.

`CASSATION_DECISION_ATTAQUEE` (champ indexé `decisionAttaquee.formation.search`) :
`COMMISSION_INDEMNISATION_VICTIMES_INFRACTIONS`, `CONSEIL_PRUDHOMME`,
`COUR_APPEL`, `COUR_ASSISES`, `COUR_CASSATION`, `COUR_JUSTICE_REPUBLIQUE`,
`COUR_NATIONAL_INCAPACITE_TARIFICATION`,
`TRIBUNAL_AFFAIRES_SECURITE_SOCIALE`, `TRIBUNAL_COMMERCE`,
`TRIBUNAL_CONTENTIEUX_INCAPACITE`, `TRIBUNAL_CORRECTIONNEL`,
`TRIBUNAL_FORCES_ARMEES`, `TRIBUNAL_GRANDE_INSTANCE`, `TRIBUNAL_INSTANCE`,
`TRIBUNAL_MARITIME_COMMERCIAL`, `TRIBUNAL_PARITAIRE_BAUX_RURAUX`,
`TRIBUNAL_POLICE`, `TRIBUNAL_PREMIERE_INSTANCE`, `TRIBUNAL_SUPERIEURS_APPEL`.

`APPEL_SIEGE_APPEL` (36 valeurs) : `AGEN`, `AIX-PROVENCE`, `AMIENS`, `ANGERS`,
`BASSE-TERRE`, `BASTIA`, `BESANCON`, `BORDEAUX`, `BOURGES`, `CAEN`, `CAYENNE`,
`CHAMBERY`, `COLMAR`, `DIJON`, `DOUAI`, `FORT-DE-FRANCE`, `GRENOBLE`,
`LIMOGES`, `LYON`, `METZ`, `MONTPELLIER`, `NANCY`, `NIMES`, `NOUMEA`,
`ORLEANS`, `PAPEETE`, `PARIS`, `PAU`, `POITIERS`, `REIMS`, `RENNES`, `RIOM`,
`ROUEN`, `ST-DENIS-REUNION`, `TOULOUSE`, `VERSAILLES`.

`PREMIER_DEGRE_TYPE_JURIDICTION` (champ indexé `natureJuridiction`) renvoie 61
valeurs qui sont des **libellés français**, pas des jetons : mélange de
libellés génériques (`Conseil de prud'hommes`, `Tribunal de commerce`,
`Tribunal de grande instance`, `Tribunal d'instance`), de libellés par ville
(`Tribunal correctionnel de Nice`, `Juridiction de proximité de Lyon`,
`Tribunal des affaires de sécurité sociale de Grenoble`…) et d'un jeton isolé
`TRIBUNAL_CONFLIT`. La correspondance est **exacte**, jamais par préfixe.

#### `LIEU_DECISION` n'est pas une énumération de villes

Contrairement à ce que son nom suggère, `LIEU_DECISION` est une **recherche
plein texte tokenisée en ET sur tout le libellé** `decisionAttaquee.formation`
(OBS 2026-09-02) :

| Valeur envoyée | Total | Nature des résultats |
|---|---|---|
| `prud'hommes` | 21 888 | tous « Conseil de Prud'hommes de … » |
| `tribunal commerce nice` | 43 | tous « Tribunal de commerce de Nice » |
| `assises` | 5 521 | toutes « Cour d'assises de … » |
| `DE` | 420 456 | mot vide très fréquent |
| `PARIS VERSAILLES` | 5 | conjonction ET des deux jetons |

Plusieurs entrées dans `valeurs` sont en OU (100 012 + 28 515 = 128 522,
somme exacte). La comparaison est insensible à la casse et à la ponctuation.
Cette facette **n'est pas renvoyée dans le bloc `facets`** : son vocabulaire
n'est pas découvrable par l'API.

`DATE_DECISION_ATTAQUEE` n'est pas non plus renvoyée dans `facets`.
`CASSATION_DECISION_ATTAQUEE`, elle, l'est.

### CETAT — jurisprudence administrative

Champs de recherche [DOC] : `ALL`, `TITLE`, `NUM_DEC`, `ABSTRATS`, `TEXTE`,
`RESUMES`.
Tris [DOC] : `PERTINENCE`, `DATE_DESC`, `DATE_ASC`.

| Filtre [DOC] | Champ technique | Facette | Forme |
|---|---|---|---|
| Nom de la juridiction | juridiction | `JURIDICTION_NATURE` | **`multiValeurs` obligatoire** [OBS] |
| Date de décision | dateDecision | `DATE_DECISION` | dates |
| Date de versement dans la base | dateVersement | `DATE_VERSEMENT` | dates |
| Publication au recueil | publiRecueil | `PUBLICATION_RECUEIL` | valeurs (`PUBLIE`, `NON_PUBLIE`) |
| Numéro de décision | numDecision | `NUMERO_DECISION` | valeurs |
| ECLI | ecli | `ECLI` | valeurs |

Facette non documentée renvoyée en plus : `pdcRestreindreArret`
(champ `restreindreArretPlanClassement`), toujours vide (OBS 2026-09-02).

#### `JURIDICTION_NATURE` est filtrable, contrairement à ce qui était écrit

La version précédente de ce document affirmait que « l'API répond HTTP 500
quand on l'envoie comme filtre, quelle que soit la valeur ». **C'est faux** :
la cause n'est pas la facette mais la forme du filtre. Huit formes ont été
essayées sur CETAT le 2026-09-02 :

| Forme envoyée | Réponse |
|---|---|
| `{"facette":"JURIDICTION_NATURE","valeurs":["CONSEIL_ETAT"]}` | HTTP 500 |
| `{"facette":"JURIDICTION_NATURE","valeur":"CONSEIL_ETAT"}` | HTTP 500 |
| `{"facette":"JURIDICTION_NATURE","valeurs":["COURS_APPEL"]}` | HTTP 500 |
| idem + `"criteres":[]` | HTTP 500 |
| `"valeurs":["Paris"]` (valeur fille seule) | HTTP 500 |
| idem + `"childs":[]` | HTTP 500 |
| idem + `"childs":["Paris"]` | HTTP 500 |
| `{"facette":"JURIDICTION_NATURE","valeurs":["COURS_APPEL"],"multiValeurs":{"COURS_APPEL":["Paris"]}}` | **HTTP 200, 58 964** |

`JURIDICTION_NATURE` est une facette **hiérarchique** et exige donc la clé
`multiValeurs`, où chaque clé est une valeur parente citée dans `valeurs` et
chaque liste énumère les valeurs filles retenues (liste vide = tout le parent).
Contrôles de cohérence (OBS 2026-09-02) :

- CAA Paris seule : 58 964, exactement le décompte `childs` de Paris ;
- CAA Paris + Lyon : 107 567 = 58 964 + 48 603, somme exacte ;
- `COURS_APPEL` avec liste vide : 388 595 (toutes les CAA) ;
- `CONSEIL_ETAT` avec liste vide : 173 809 ;
- `CONSEIL_ETAT` + `COURS_APPEL` : 562 404 ;
- `TRIBUNAL_ADMINISTATIF` / `Paris` : 760 ;
- parent inconnu ou enfant inconnu : HTTP 200 et **0 résultat** (pas d'erreur).

Valeurs parentes observées : `CONSEIL_ETAT`, `COURS_APPEL`,
`TRIBUNAL_ADMINISTATIF` (orthographe de l'API, sans le second « r »),
`TRIBUNAL_CONFLIT`, `COURS_DE_DISCIPLINE`, `COURS_APPEL_FINANCIERE`,
`COURS_COMPTES`, `CHAMBRES_COMPTES` (ces trois dernières à 0 sur CETAT).
Enfants de `COURS_APPEL` : Bordeaux, Douai, Lyon, Marseille, Nancy, Nantes,
Paris, Toulouse, Versailles. Enfants de `TRIBUNAL_ADMINISTATIF` : 42 villes,
la plupart à 0.

Ajouter `multiValeurs` à une facette **plate** est sans effet et sans erreur :
`CASSATION_FORMATION` / `CHAMBRE_SOCIALE` rend 142 754 avec ou sans
(OBS 2026-09-02).

**Conséquence pour `Search_CAA`** : le tri par ville peut passer côté serveur.

### JUFI — juridictions financières

Champs [DOC] : `ALL`, `TITLE`, `NUM_DEC`, `ABSTRATS`, `TEXTE`.
Tris [DOC] : `PERTINENCE`, `DATE_DESC`, `DATE_ASC`.
Filtres [DOC] : `PUBLICATION_RECUEIL` (publiRecueil), `JURIDICTION_NATURE`
(juridiction), `DATE_DECISION` (dateDecision), `NUMERO_DECISION` (numDecision).

`JURIDICTION_NATURE` y est également hiérarchique : HTTP 500 en forme plate,
HTTP 200 avec `multiValeurs` (`COURS_COMPTES` : 1 656, OBS 2026-09-02).

### CODE_DATE / CODE_ETAT — codes

Champs [DOC] : `ALL`, `TITLE`, `TABLE`, `NUM_ARTICLE`, `ARTICLE` (identiques
dans les deux variantes).

| Filtre [DOC] | Facette (par date) | Facette (par état) |
|---|---|---|
| État juridique des articles | — | `ARTICLE_LEGAL_STATUS` |
| État juridique des textes | — | `TEXT_LEGAL_STATUS` |
| Date de la version | `DATE_VERSION` | — |
| Nom du code | `NOM_CODE` | `TEXT_NOM_CODE` |
| Numéro d'article | `NUM_ARTICLE` | `NUM_ARTICLE` |

`typePagination: "ARTICLE"` est requis pour obtenir les articles plutôt que les
textes (c'est ce que force `search_code` dans `tools/legifrance_client.py`).

### CONSTIT — Conseil constitutionnel

Champs [DOC] : `ALL`, `TITLE`, `NUM_DEC`, `TEXTE`.
Tris [DOC] : `PERTINENCE`, `DATE_DESC`, `DATE_ASC`.
Filtres [DOC] : `NATURE_CONSTIT` (natureConstit), `NATURE_NORME_AUTRE`
(natureNormeAutre), `SOLUTION_CONSTIT` (solutionConstit), `TITRE_DEFEREE`
(titreLoi), `NUM_LOI` (numLoi), `DATE_LOI` (dateLoi), `TYPE_DECISION`
(natureElection), `SOLUTION_ELECT` (solutionElect), `NATURE_AUTRE`
(natureAutre), `SOLUTION_AUTRE` (solutionAutre), `DATE_DECISION`
(dateDecision), `NUMERO_DECISION` (numDecision), `NOR` (nor).

### JORF — Journal officiel

Champs [DOC] : `ALL`, `TITLE`, `NOR`, `NUM`, `NUM_ARTICLE`, `ARTICLE`, `VISA`,
`NOTICE`, `VISA_NOTICE`, `TRAVAUX_PREP`, `SIGNATURE`, `NOTA`.
Tris [DOC] : `PERTINENCE`, `SIGNATURE_DATE_DESC`, `SIGNATURE_DATE_ASC`,
`PUBLICATION_DATE_DESC`, `PUBLICATION_DATE_ASC`.
Filtres [DOC] : `NATURE` (nature), `DATE_SIGNATURE` (dateSignature),
`DATE_PUBLICATION` (datePublication), `MINISTERE` (ministere), `EMETTEUR`
(emetteur), `NOR` (nor), `NUM_TEXTE` (num), `NUM_ARTICLE` (numArticle),
`DECORATION` (decoration), `DELEGATION` (delegation).
La facette `EMETTEUR` renvoie plusieurs dizaines d'autorités en libellé majuscule
non accentué (OBS 2026-09-02).

### LODA — lois, ordonnances, décrets, arrêtés

Champs [DOC] : mêmes 12 champs que JORF, dans les deux variantes date/état.
Tris [DOC] : `PERTINENCE`, `PUBLICATION_DATE_DESC`, `PUBLICATION_DATE_ASC`,
`SIGNATURE_DATE_DESC`, `SIGNATURE_DATE_ASC`.
Filtres [DOC] : `NATURE`/`TEXT_NATURE`, `DATE_SIGNATURE`/`TEXT_DATE_SIGNATURE`,
`DATE_PUBLICATION`/`TEXT_DATE_PUBLICATION`, `ARTICLE_LEGAL_STATUS` (état seul),
`TEXT_LEGAL_STATUS` (état seul), `NOR`, `NUM_TEXTE`, `NUM_ARTICLE`,
`DATE_VERSION` (date seule).

### CIRC — circulaires

Champs [DOC] : `ALL`, `TITLE`, `NOR`, `RESUME_CIRC`, `TEXTE_REF`.
Tris [DOC] : `PERTINENCE`, `SIGNATURE_DATE_DESC`, `SIGNATURE_DATE_ASC`,
`PUBLI_DATE_DESC`, `PUBLI_DATE_ASC`.
Filtres [DOC] : `DATE_MEL` (dateMEL), `DATE_SIGNATURE`, `DATE_MEA` (dateMEA),
`OPPOSABILITE`, `DOMAINE`, `MIN_DEPOSANT`, `MIN_CONCERNE`, `MOTS_CLEFS`,
`NUMERO_INTERNE`, `NOR`, `REF_PUBLI`.

### KALI — conventions collectives

Champs [DOC] : `ALL`, `TITLE`, `IDCC`, `MOTS_CLES`, `ARTICLE`.
Tris [DOC] : `PERTINENCE`, `MODIFICATION_DATE_DESC`, `SIGNATURE_DATE_DESC`,
`SIGNATURE_DATE_ASC`.
Filtres [DOC] : `LEGAL_STATUS`, `ARTICLE_LEGAL_STATUS`, `ACTIVITE`,
`ARTICLE_QUESTION_USUELLE`, `DATE_SIGNATURE`, `DATE_PUBLICATION`,
`NATURE_TEXTE_CITE`, `NUM_TEXTE_CITE`, `DATE_PUBLI_TEXTE_CITE`,
`NOM_CODE_CITE`, `NUM_ARTICLE_CODE_CITE`, `IDCC`, `NOR`, `CODE_NAF_OU_APE`,
`NUMERO_BO`, `ARTICLE_NUMERO`.

### ACCO — accords d'entreprise

Champs [DOC] : `ALL`, `TITLE`, `RAISON_SOCIALE`, `IDCC`.
Tris [DOC] : `PERTINENCE`, `DATE_DESC`, `DATE_ASC`.
Filtres [DOC] : `THEME`, `SIGNATAIRE`, `DATE_SIGNATURE`, `ACTIVITE_PRINCIPALE`,
`CODE_APE`, `IDCC`, `VILLE`, `CODE_POSTAL`, `DATE_DIFFUSION`,
`SIRET_RAISON_SOCIALE`.

### CNIL

Champs [DOC] : `ALL`, `TITLE`, `NOR`, `TEXTE`, `NUM_DELIB`.
Tris [DOC] : `PERTINENCE`, `DATE_DECISION_DESC`, `DATE_DECISION_ASC`.
Filtres [DOC] : `TYPE` (facetteNature), `NATURE_DELIB` (facetteNatureDelib),
`DATE_DELIB` (timeInterval), `NUMERO_DELIB` (numeroDelib), `NOR` (nor).

### ALL — recherche transverse

Champs [DOC] : `ALL`, `TITLE`. Filtre unique [DOC] : `FOND` (origine).
Valeurs observées de `FOND` (OBS 2026-09-02) : `ACCO`, `CETAT`, `CIRC`, `CNIL`,
`CODE`, `CONSTIT`, `JORF`, `JUFI`, `JURI`, `KALI`, `LEGI`.

### Fonds sans champ de recherche documenté

Le classeur ne décrit pour eux que des filtres et des tris.

| Fonds | Filtres [DOC] | Tris [DOC] |
|---|---|---|
| BOCC | `INTERVAL_PUBLICATION`, `IDCC` | `BOCC_SORT_DESC`, `BOCC_SORT_ASC` |
| debatsParlementaires | `DATE_PUBLICATION`, `TYPE_DE_PUBLICATION` | `DEBAT_PARLEMENTAIRE_DESC/ASC`, `ID_ASC`, `ID_DESC` |
| questionsEcritesParlementaires | `DATE_PUBLICATION`, `TYPE_PARLEMENT` | `QUESTION_ECRITE_PARLEMENTAIRE_DESC/ASC`, `ID_ASC`, `ID_DESC` |
| docAdmin | `YEARS` (facetteYearPubli) | — |

## Divergences entre le classeur et le dépôt

Relevées le 2026-09-02, non corrigées dans le code à ce stade.

1. **`APPEL_SIEGE_APPEL` incomplet.** L'énumération de
   `config/mcp_definitions.py` (ligne 99) compte 35 villes ; la facette en
   renvoie 36. **`CAYENNE` manque.**
2. **`PREMIER_DEGRE_TYPE_JURIDICTION` inventé.** L'énumération du dépôt utilise
   des jetons majuscules (`TRIBUNAL_JUDICIAIRE`, `CONSEIL_PRUDHOMMES`,
   `TRIBUNAL_CORRECTIONNEL`…) alors que la facette renvoie 61 **libellés
   français** en correspondance exacte. Les jetons ne peuvent pas matcher tels
   quels.
3. **`LEGIFRANCE_FONDS` incomplet.** `config/settings.py` déclare 8 fonds ; le
   classeur en documente 17.
4. **`JURIDICTION_NATURE` déclarée infiltrable.** Corrigé ci-dessus : elle est
   filtrable via `multiValeurs`.
5. **`PREMIER_DEGRE_SIEGE` documentée mais inerte.** Acceptée (HTTP 200), elle
   renvoie 0 pour toutes les valeurs essayées (OBS 2026-09-02). Non tranché :
   il n'a pas été possible d'en découvrir le vocabulaire, la facette n'étant
   pas renvoyée dans `facets`.

## Points restés non tranchés

- Vocabulaire admis de `LIEU_DECISION`, `DATE_DECISION_ATTAQUEE`,
  `NUM_BULLETIN`, `ANNEE_BULLETIN`, `PREMIER_DEGRE_SIEGE` : ces facettes ne
  sont pas renvoyées dans `facets` et l'API n'énumère pas les valeurs admises.
- Comportement des fonds BOCC, debatsParlementaires,
  questionsEcritesParlementaires et docAdmin : non sondés, faute d'emploi dans
  ce serveur.
- Sémantique exacte de `PDC_CHECKBOX_RESTREINDRE_ARRET` /
  `pdcRestreindreArret` : facette toujours vide, non documentée au classeur.
