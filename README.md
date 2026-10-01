# MCP Légifrance

Serveur MCP autonome donnant accès aux sources juridiques officielles
françaises via les API Légifrance et Judilibre (PISTE) et BODACC. Il expose un
transport stdio pour les clients MCP.

Ce dépôt est extrait de PieceMaker avec son historique. Il ne dépend pas de
l'installateur, du serveur ou des dossiers utilisateurs de PieceMaker.

## Installation dans Claude Code

```sh
claude plugin marketplace add PieceMaker-Legal/mcp-legifrance
claude plugin install piecemaker@mcp-legifrance
```

Le plugin conserve volontairement l'identifiant `piecemaker` afin de préserver
le namespace historique `mcp__plugin_piecemaker_legifrance` utilisé par les
agents PieceMaker. Au premier lancement, `scripts/launcher.py` crée un venv
privé dans le cache du plugin et installe les dépendances. Toute sortie de cette
préparation est envoyée sur stderr afin de ne jamais corrompre le protocole MCP.

## Configuration

Créer `~/.config/mcp-legifrance/.env` avec des permissions réservées à
l'utilisateur :

```dotenv
LEGIFRANCE_CLIENT_ID=...
LEGIFRANCE_CLIENT_SECRET=...
LEGIFRANCE_ENV=production
```

Les mêmes identifiants servent à Judilibre : l'application PISTE doit être
abonnée à l'API Légifrance et à l'API Judilibre. Sans abonnement Judilibre, la
recherche continue sur Légifrance seul et le signale.

On peut aussi fournir directement ces variables dans l'environnement, ou
définir `LEGIFRANCE_ENV_FILE=/chemin/absolu/.env`. La découverte MCP fonctionne
sans identifiants ; seuls les appels réseau les exigent.

## Outils exposés

- recherche jurisprudentielle unique (`Search_Jurisprudence`) : Cour de
  cassation, cours d'appel, première instance, Conseil d'État et CAA, dans
  Légifrance et Judilibre à la fois, avec les mêmes filtres (matière et
  publication en cassation, villes des cours d'appel et des CAA, familles du
  premier degré, recueil Lebon, dates) et la même requête booléenne. Les
  décisions présentes dans les deux bases (même juridiction, même date, même
  numéro) ne sont listées qu'une fois. Légifrance n'ayant plus de décisions
  de cours d'appel depuis 2023 ni de première instance depuis 2024, Judilibre
  les fournit ; il couvre la Cour de cassation, les cours d'appel, les
  tribunaux judiciaires et de commerce ;
- recherche dans les codes à une date de vigueur donnée, consultation du texte
  intégral d'un article identifié et consultation du texte intégral d'une décision ;
- historique procédural strict d'une décision, établi sur la seule métadonnée
  officielle « décision attaquée » — jamais sur une citation —, assorti du
  relevé séparé des décisions qui citent la décision de départ, chacune retenue
  seulement si son texte reprend littéralement son numéro. Le fonds CETAT ne
  renseignant pas cette métadonnée, l'historique d'une décision administrative
  est vide par construction, et l'outil le déclare ;
- suivi BODACC par SIREN ;
- recherche en temps réel dans le lexique juridique officiel de justice.fr
  avec l'outil `dictionnaire_juridique` ;
- construction et validation d'un corpus jurisprudentiel exhaustif sans RAG,
  embeddings ni top-k, collecté par le même moteur et avec les mêmes filtres
  que `Search_Jurisprudence`.

Le serveur fournit également un lexique de l’API Légifrance.

## Syntaxe des recherches

`Search_Jurisprudence`, `Search_Code` et `Build_Research_Corpus` partagent la
même syntaxe :

- les guillemets délimitent une expression exacte : `"faute grave"` ;
- `ET` exige les deux côtés et est prioritaire sur `OU` ;
- les parenthèses modifient le regroupement : `(A OU B) ET C` ;
- les références telles que `L. 1235-3` et `L1235-3` sont normalisées ;
- sans opérateur explicite, les mots non entre guillemets sont reliés par `ET`.

Exemple :

```text
("faute grave" OU "faute lourde") ET licenciement
```

En première instance, sans `ET` ni `OU` explicite, les mots non entre
guillemets sont reliés par `OU` afin d'élargir ce corpus limité. Utiliser `ET`
explicitement lorsqu'un cumul est requis.

La requête est mise sous forme normale disjonctive : chaque branche `OU` est
une suite de termes reliés par `ET`. Légifrance reçoit toutes les branches en
un seul appel. Judilibre reçoit une requête par branche, chaque mot étant
obligatoire (`+mot`, élisions retirées) et chaque article cherché sous ses
deux écritures (`+"L. 1235-3"` et `+L1235-3`). Judilibre ne garantissant pas
l'adjacence des mots, une expression exacte de plusieurs mots est vérifiée sur
le texte intégral de chaque décision trouvée seulement dans Judilibre ; les
décisions qui ne la contiennent pas sont écartées et comptées.

Au-delà de 500 résultats cumulés (Légifrance + Judilibre, avant fusion), la
recherche est refusée. `consulter_decision` lit indifféremment un identifiant
Légifrance (`JURITEXT…`, `CETATEXT…`) ou Judilibre (24 caractères
hexadécimaux).

## Développement

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -p 'test_*.py'
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
  | PYTHONDONTWRITEBYTECODE=1 .venv/bin/python mcp_stdio_server.py
```

Les tests sont hors réseau. Ne jamais versionner `.env`, jetons, corpus
téléchargés, journaux ou rapports juridiques générés.
