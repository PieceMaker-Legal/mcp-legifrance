# Endpoints et schémas de réponse (API Légifrance)

Document jumeau de [`facettes-officielles-dila.md`](facettes-officielles-dila.md),
qui couvre la classe `/search` (champs, filtres, tris, vocabulaires de facettes).
Celui-ci couvre le reste : les endpoints de consultation et de listage, le
schéma complet de la réponse `/consult/juri`, et la question de la **décision
attaquée**.

Mêmes conventions de preuve que le document jumeau : **[DOC]** pour le classeur
DILA « Description des tris et filtres de l'API » (05/08/2024), **[OBS]** pour
une observation directe sur l'API de production
`https://api.piste.gouv.fr/dila/legifrance/lf-engine-app`, datée.

## Réponse courte à la question du numéro de la décision attaquée

**Non. L'API n'expose nulle part, en donnée structurée, le numéro de la
décision attaquée.**

Le seul champ dédié est `text.decisionAttaquee`, dont le schéma complet est
`{formation: string|null, date: entier (millisecondes epoch)}`. Aucune clé de
numéro, ni au premier niveau, ni imbriquée. Vérifié sur un échantillon de 47
décisions consultées une par une (37 JURITEXT, 10 CETATEXT), toutes chambres et
plusieurs décennies (OBS 2026-09-02) : les seules sous-clés jamais rencontrées
sont `decisionAttaquee.date` (37/47 non vide) et `decisionAttaquee.formation`
(31/47 non vide).

Détail par degré (OBS 2026-09-02) :

| Degré | Échantillon | `decisionAttaquee` |
|---|---|---|
| Cour de cassation (JURI) | renseigné | `{formation: "Paris, 11 décembre 2018"-like, date réelle}` |
| Cour d'appel (JURI) | 25 arrêts | 25/25 `{formation: null, date: 32472144000000}` soit **2999-01-01** |
| Premier degré (JURI) | 25 décisions | 25/25 même sentinelle `2999-01-01` |
| Conseil d'État / CAA (CETAT) | 25 décisions | 25/25 `decisionAttaquee` nul ou absent |

Le numéro de la décision attaquée **apparaît parfois en texte libre** dans
`text.texte`, sous la forme « Selon les arrêts attaqués (Paris, 11 décembre
2018) », mais sans numéro RG dans les échantillons examinés : c'est de la prose
de motivation, pas une donnée exploitable de façon fiable.

Les autres pistes ont été inspectées et écartées (OBS 2026-09-02, mêmes 47
décisions) : `renvoi`, `visas`, `visasHtml`, `conteneurs`, `idConteneur`,
`infosComplementaires`, `infosComplementairesHtml`, `numsequence`,
`natureQualifiee`, `typeDecision` sont **toujours vides**. `liens` est
renseigné 28/47 fois et le seul `typeLien` observé est `CITATION` (avec
`sens: "source"`), qui pointe vers des textes cités, pas vers la décision
attaquée. `ancienId` (17/47) est un identifiant historique interne
(`JAX2004X10XPEX0000000011`), pas un numéro de dossier.

## Ce qui existe malgré tout : un index inverse sur la Cour de cassation

Le module `tools/decision_history.py` affirme dans sa docstring que « l'API
Légifrance n'expose aucun index inverse ». **C'est faux pour les arrêts de la
Cour de cassation.**

Trois facettes de `/search` sur le fonds JURI indexent la décision attaquée et
sont acceptées comme filtres (OBS 2026-09-02) :

- `CASSATION_DECISION_ATTAQUEE` — champ indexé `decisionAttaquee.formation.search`,
  19 valeurs énumérables (liste dans le document jumeau) ;
- `LIEU_DECISION` — recherche plein texte tokenisée en ET sur le libellé
  `decisionAttaquee.formation` ;
- `DATE_DECISION_ATTAQUEE` — intervalle de dates sur `decisionAttaquee.date`.

Combinées, et sans aucune clé `champs` (une requête purement filtrée est
acceptée), elles retrouvent les arrêts de cassation portant sur une décision
donnée :

```json
{"fond": "JURI", "sort": "PERTINENCE", "secondSort": "ID",
 "typePagination": "DEFAUT",
 "recherche": {"pageNumber": 1, "pageSize": 100, "operateur": "ET",
   "fromAdvancedRecherche": false,
   "filtres": [
     {"facette": "CASSATION_DECISION_ATTAQUEE", "valeurs": ["COUR_APPEL"]},
     {"facette": "LIEU_DECISION", "valeurs": ["PARIS"]},
     {"facette": "DATE_DECISION_ATTAQUEE",
      "dates": {"start": "2018-12-11", "end": "2018-12-11"}}]}}
```

Résultat (OBS 2026-09-02) : 11 décisions exactement. Les 11 ont été consultées
une par une : **11/11** ont `decisionAttaquee.formation` contenant « Paris » et
`decisionAttaquee.date` au 11 décembre 2018. Aucun faux positif.

Cette recette ne vaut que pour les arrêts de la Cour de cassation : les arrêts
d'appel et les décisions du premier degré ont tous la sentinelle `2999-01-01`
et une `formation` nulle, donc rien à indexer.

### Piège : la sentinelle `2999-01-01` et l'index multivalué

`DATE_DECISION_ATTAQUEE` sur l'intervalle `2999-01-01`…`2999-01-01` renvoie
516 751 décisions (OBS 2026-09-02). Or la même décision (NUM_AFFAIRE
19-12.025) répond **à la fois** à sa date réelle 2018-12-11 et à la sentinelle
2999-01-01 — mais pas à une date fausse (2017 rend 0). Le champ est donc
multivalué côté index.

Les intervalles réels étroits restent exacts et additifs : la somme des totaux
année par année de 2000 à 2019 fait 224 396, exactement le total de la requête
sur l'intervalle unique 2000-2019.

**Règle opérationnelle** : ne jamais laisser une borne `end` atteindre 2999,
sous peine de ramener un demi-million de décisions sans rapport.

## Schéma de la réponse `/consult/juri`

`POST /consult/juri {"textId": "JURITEXT…"}` ou `{"textId": "CETATEXT…"}`.
Réponse : `{executionTime: int, dereferenced: bool, text: {…}}`.

`text` compte **126 clés** (OBS 2026-09-02, échantillon de 47 décisions,
47 appels réussis, 0 échec). La grande majorité est toujours vide : le DTO est
partagé avec les autres fonds. Clés effectivement renseignées au moins une fois
sur l'échantillon :

| Clé | Renseignée | Type |
|---|---|---|
| `id`, `titre`, `titreLong`, `texte`, `texteHtml` | 47/47 | str |
| `nature`, `formation`, `juridiction`, `natureJuridiction`, `origine` | 47/47 | str |
| `publicationRecueil` | 47/47 | str |
| `dateTexte`, `dateTexteComputed`, `relevantDate` | 47/47 | int (ms epoch) |
| `refInjection`, `idTechInjection` | 47/47 | str |
| `sommaire` (`id`, `resumePrincipal`, `autreResume`, `abstrats`) | 47/47 | liste |
| `titrages`, `titragesKey` | 40/47 | liste |
| `decisionAttaquee` (`date`, `formation`) | 37/47 | dict |
| `numeroAffaire` | 37/47 | liste |
| `juridictionJudiciaire`, `provenance`, `typePublicationBulletin` | 37/47 | str |
| `citationJpHtml` | 36/47 | str |
| `president` | 34/47 | str |
| `avocats`, `natureNumero`, `num`, `solution` | 32/47 | str |
| `citationJp` | 29/47 | str |
| `liens` (`typeLien`, `sens`, `title`) | 28/47 | liste |
| `rapporteur` | 26/47 | str |
| `ecli` | 21/47 | str |
| `ancienId` | 17/47 | str |
| `avocatGl` | 16/47 | str |
| `numeroPublicationBulletin`, `originePubli` | 12/47 | str |
| `dateVersement` | 10/47 | int |
| `annePublicationBulletin`, `commissaire` | 9/47 | str |
| `siegeAppel` | 6/47 | str |

Les 69 clés restantes sont **vides sur la totalité de l'échantillon**, dont
celles qui auraient pu porter la décision attaquée : `renvoi`, `visas`,
`visasHtml`, `conteneurs`, `idConteneur`, `infosComplementaires`,
`infosComplementairesHtml`, `numsequence`, `natureQualifiee`, `typeDecision`,
`typeTexte`, `demandeur`, `motsCles`, `nota`, `notice`, `observations`,
`resume`, `travauxPreparatoires`, `dossiersLegislatifs`, `signataires`,
`emetteur`, `ministere`, `etat`, `version`, `cid`, `idEli`, `idEliAlias`,
`nor`, `numJo`, `dateJo`, `datePubli`, `lienJo`, `pagePdf`, `urlCC`, etc.

Dans `liens[]`, seules `typeLien`, `sens` et `title` sont systématiquement
présentes quand le lien existe ; `id`, `numTexte`, `natureTexte`,
`dateSignaTexte`, `datePubliTexte` n'apparaissent qu'une fois sur 47, et
`cidTexte`, `norTexte`, `num` jamais.

`siegeAppel` n'est renseigné que 6 fois sur 47 : il ne peut pas servir de
discriminant fiable côté consultation.

## Inventaire des endpoints

Sondés le 2026-09-02 en POST avec une charge utile plausible. Un code 200
signifie que l'endpoint existe et a répondu ; un 400/500 sur un identifiant
d'essai ne prouve pas son inexistence.

### `/consult/*`

| Endpoint | Statut | Clés de premier niveau |
|---|---|---|
| `/consult/juri` | 200 | `executionTime`, `dereferenced`, `text` |
| `/consult/getArticle` | 200 | `executionTime`, `dereferenced`, `article` |
| `/consult/getArticleByCid` | 200 | `executionTime`, `listArticle` |
| `/consult/getArticleWithIdAndNum` | 200 | `executionTime`, `dereferenced`, `article` |
| `/consult/getArticleWithIdEliOrAlias` | 200 | `executionTime`, `dereferenced`, `article` |
| `/consult/getSectionByCid` | 200 | `executionTime`, `listSection` |
| `/consult/code/tableMatieres` | 200 | `executionTime`, `dereferenced`, `id`, `idConteneur`, `cid`, `title`, … |
| `/consult/legi/tableMatieres` | 200 | idem |
| `/consult/legiPart` | 200 | idem |
| `/consult/lawDecree` | 200 | idem |
| `/consult/jorf` | 200 | idem |
| `/consult/jorfCont` | 200 | `executionTime`, `items`, `totalNbResult` |
| `/consult/kaliArticle`, `/consult/kaliSection`, `/consult/kaliText` | 200 | idem tableMatieres |
| `/consult/kaliCont` | 200 | `executionTime`, `id`, `titre`, `numeroTexte`, `num`, `nature`, … |
| `/consult/acco` | 200 | `executionTime`, `dereferenced`, `acco` |
| `/consult/circulaire` | 200 | `executionTime`, `dereferenced`, `circulaire` |
| `/consult/cnil` | 200 | `executionTime`, `dereferenced`, `text` |
| `/consult/debat` | 200 | `executionTime`, `dereferenced`, `debat` |
| `/consult/dossierLegislatif` | 200 | `executionTime`, `dereferenced`, `dossierLegislatif` |
| `/consult/relatedLinksArticle` | 200 | `executionTime`, `liensCite`, `liensCitePar` |
| `/consult/concordanceLinksArticle` | 200 | `executionTime`, `oldTexts`, `newTexts` |
| `/consult/sameNumArticle` | 200 | `executionTime`, `oldTexts`, `newTexts` |
| `/consult/getTables` | 200 | `executionTime`, `tables`, `totalNbResult` |
| `/consult/lastNJo` | 200 | `executionTime`, `containers`, `totalNbResult` |
| `/consult/getJuriWithAncienId` | 200 | `executionTime`, `dereferenced`, `text` |
| `/consult/getCnilWithAncienId` | 200 | idem |
| `/consult/getCodeWithAncienId` | 200 | idem tableMatieres |
| `/consult/getJoWithNor` | 200 | idem tableMatieres |
| `/consult/eliAndAliasRedirectionTexte` | 200 | idem tableMatieres |
| `/consult/getBoccTextPdfMetadata` | 200 | `bocc`, `displaySize`, `pathToFile`, `title`, … |
| `/consult/code` | 500 | sur l'identifiant d'essai |
| `/consult/getJuriPlanClassement` | 500 | sur l'identifiant d'essai |
| `/consult/kaliContIdcc` | 500 | sur l'identifiant d'essai |
| `/consult/jorfPart` | 400 | charge utile d'essai invalide |
| `/consult/textesRecents` | 403 | non autorisé pour ce compte |

`/consult/relatedLinksArticle` est le seul endpoint de graphe de liens
observé, et il porte sur les **articles**, pas sur les décisions : il ne fournit
pas de chaînage procédural.

### Autres classes

| Endpoint | Statut | Clés |
|---|---|---|
| `/search` | 200 | `executionTime`, `totalResultNumber`, `results`, `facets`, … |
| `/suggest` | 200 | `executionTime`, `totalResultNumber`, `results` |
| `/chrono/textCid` | 200 | `executionTime`, `regroupements`, `datePublication` |
| `/list/loda` | 200 | `executionTime`, `results`, `natures`, `legalStatus`, `totalResultNumber` |
| `/list/conventions` | 200 | `executionTime`, `results`, `moteCles`, `legalStatus`, `typeTexte`, … |
| `/list/bodmr` | 200 | `executionTime`, `years`, `results`, `totalResultNumber`, … |
| `/list/code` | 503 | moteur indisponible au moment du sondage |
| `/list/dossiersLegislatifs` | 400 | charge utile d'essai invalide |
| `/consult/ping`, `/search/ping`, `/list/ping` | 405 | méthode non autorisée en POST |

Les `ping` répondent **HTTP 500 en GET** et **405 en POST** (OBS 2026-09-02) :
la découverte de routes par GET est donc inexploitable, un 500 ne distinguant
pas une route absente d'une route présente mal appelée.

## Conséquences pour ce serveur

1. **`tools/decision_history.py`** — la prémisse « aucun index inverse » de sa
   docstring est fausse pour la Cour de cassation. La recherche par nom de
   juridiction et rapprochement approximatif peut être remplacée, pour le lien
   appel → cassation, par le triplet
   `CASSATION_DECISION_ATTAQUEE` + `LIEU_DECISION` + `DATE_DECISION_ATTAQUEE`,
   qui est exact. Elle reste nécessaire pour le lien premier degré → appel, que
   l'API n'indexe pas.
2. **`Search_CAA`** — le tri par ville peut passer côté serveur via
   `JURIDICTION_NATURE` en forme `multiValeurs` (voir le document jumeau), au
   lieu du filtrage côté client sur le titre.
3. **Validation des `typeChamp`** — l'API acceptant silencieusement un
   `typeChamp` étranger au fonds en abandonnant le critère, la liste par fonds
   du document jumeau doit être appliquée côté client.
4. **Pagination** — plafonner `pageNumber × pageSize` à 10 000 et `pageSize` à
   100, sous peine de HTTP 503.

## Points restés non tranchés

- **Numéro de la décision attaquée en texte libre** : il n'a pas été établi
  avec quelle régularité un numéro RG figure dans `text.texte`. Sur les
  échantillons examinés, la mention se limite à la ville et à la date. Aucune
  extraction fiable ne peut être fondée là-dessus sans une campagne dédiée.
- **`typeLien`** : seul `CITATION` a été observé sur 47 décisions. Il n'est pas
  exclu que d'autres valeurs existent sur des décisions non échantillonnées ;
  la liste des `typeLien` admis n'est documentée nulle part.
- **`/consult/getJuriPlanClassement`** : répond 500 sur les identifiants
  essayés ; sa charge utile correcte n'a pas été trouvée, et son intérêt
  éventuel pour le chaînage procédural reste inconnu.
- **`/consult/textesRecents`** : 403, hors périmètre du compte utilisé.
- **Sandbox** : les observations n'ont porté que sur la production. Le
  comportement de l'environnement sandbox n'a pas été vérifié.
