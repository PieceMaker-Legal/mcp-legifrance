# MCP Légifrance

Serveur MCP autonome donnant accès aux sources juridiques officielles
françaises via les API Légifrance/PISTE et BODACC. Il expose un transport stdio
pour les clients MCP et un adaptateur HTTP local optionnel lié exclusivement à
`127.0.0.1`.

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

On peut aussi fournir directement ces variables dans l'environnement, ou
définir `LEGIFRANCE_ENV_FILE=/chemin/absolu/.env`. La découverte MCP fonctionne
sans identifiants ; seuls les appels réseau les exigent.

## Outils exposés

- recherche jurisprudentielle : Cour de cassation, cours d'appel, Conseil
  d'État, CAA et première instance ;
- recherche dans les codes à une date de vigueur donnée, consultation du texte
  intégral d'un article identifié et consultation du texte intégral d'une décision ;
- reconstitution du fil procédural d'une décision (appel, pourvoi, cassation,
  arrêt de renvoi, pourvoi suivant), dans l'ordre judiciaire comme
  administratif, chaque maillon portant sa preuve et son degré de certitude,
  assortie du relevé des décisions qui citent la décision de départ — chacune
  retenue seulement si son texte reprend littéralement le numéro cité ;
- suivi BODACC par SIREN ;
- recherche en temps réel dans le lexique juridique officiel de justice.fr
  avec l'outil `dictionnaire_juridique` ;
- téléchargement déterministe d'une requête ;
- construction et validation d'un corpus jurisprudentiel exhaustif sans RAG,
  embeddings ni top-k.

Le serveur fournit également un dictionnaire juridique.

## Syntaxe des recherches

Les outils `Search_Cour_Cassation`, `Search_Cour_Appel`,
`Search_Conseil_Etat`, `Search_CAA`, `Search_Code`
et `Build_Research_Corpus` partagent la même syntaxe :

- les guillemets délimitent une expression exacte : `"faute grave"` ;
- `ET` exige les deux côtés et est prioritaire sur `OU` ;
- les parenthèses modifient le regroupement : `(A OU B) ET C` ;
- les références telles que `L. 1235-3` et `L1235-3` sont normalisées ;
- sans opérateur explicite, les mots non entre guillemets sont reliés par `ET`.

Exemple :

```text
("faute grave" OU "faute lourde") ET licenciement
```

`Search_Premiere_Instance` reconnaît la même syntaxe, mais relie par `OU` les
mots non entre guillemets lorsqu'aucun opérateur n'est explicite, afin d'élargir
ce corpus limité. Utiliser `ET` explicitement lorsqu'un cumul est requis.

L'ancien alias interne `recherche_jurisprudence` a été supprimé. Utiliser les
outils spécialisés ci-dessus, qui appliquent les filtres propres à chaque fonds
et rendent leurs limites explicites.

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
