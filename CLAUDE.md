# Claude Code — MCP Légifrance

Lire et respecter `AGENTS.md` avant toute intervention. Ce projet est un
serveur MCP Python autonome sur stdio : stdout est réservé au JSON-RPC et tous
les logs vont sur stderr.

## Configuration locale

Sur cette machine, le fichier d'environnement propre au MCP se trouve dans
`/Users/tsardet/.config/mcp-legifrance/.env`. Pour les appels Légifrance en
direct, définir `LEGIFRANCE_ENV_FILE` avec ce chemin absolu. Ne jamais afficher,
recopier ni journaliser le contenu de ce fichier.

## Recherches

Utiliser uniquement les outils publics spécialisés :

- `Search_Cour_Cassation`, `Search_Cour_Appel` ;
- `Search_Conseil_Etat`, `Search_CAA` ;
- `Search_Premiere_Instance`, `Search_Code` ;
- `Download_Query_Results`, `Build_Research_Corpus`.

L'ancien alias générique `recherche_jurisprudence` a été supprimé et ne doit
pas être restauré.

Syntaxe commune :

- `"faute grave"` impose une expression exacte ;
- `ET` est prioritaire sur `OU` ;
- `(A OU B) ET C` impose le regroupement voulu ;
- sans opérateur explicite, les mots non entre guillemets sont reliés par `ET` ;
- `Search_Premiere_Instance` est l'unique exception et utilise alors `OU` ;
- les références comme `L. 1235-3` sont normalisées automatiquement.

Exemple recommandé :

```text
("faute grave" OU "faute lourde") ET licenciement
```

Pour un corpus exhaustif, conserver chaque échec et chaque troncature dans la
télémétrie. Aucun score lexical ne doit retirer une décision des lots ou de la
validation.

## Vérification

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_*.py'
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
  | PYTHONDONTWRITEBYTECODE=1 python3 mcp_stdio_server.py
```

Les tests doivent rester hors réseau. Ne jamais écrire de secrets, jetons,
corpus téléchargés, logs ou rapports juridiques dans Git.
