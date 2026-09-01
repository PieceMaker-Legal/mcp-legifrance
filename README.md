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
- recherche dans les codes et consultation du texte intégral d'une décision ;
- suivi BODACC par SIREN ;
- téléchargement déterministe d'une requête ;
- construction et validation d'un corpus jurisprudentiel exhaustif sans RAG,
  embeddings ni top-k.

Le serveur fournit également un dictionnaire juridique, un guide de rédaction
des conclusions, des exemples et le prompt `workflow_conclusions`.

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

