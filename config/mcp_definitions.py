#/config/mcp_definitions.py 
#! MCP SERVEUR LOCAL
"""Définition des outils MCP disponibles"""

MCP_TOOLS = [
# ============================================================================
    # OUTILS RECHERCHE JURISPRUDENCE - VERSION OPTIMISÉE
    # ============================================================================
    {
        "name": "Search_Cour_Cassation",
        "description": "Recherche ciblée dans la jurisprudence de la COUR DE CASSATION avec parsing intelligent de la query.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": """Mots-clés avec opérateurs logiques et recherche par article visé.

SYNTAXE SUPPORTÉE:
1. Mots simples: "faute grave licenciement" → cherche les 3 mots (ET automatique)
2. Opérateur ET: "faute" ET "employeur" → les 2 mots obligatoires
3. Opérateur OU: "faute" OU "employeur" → au moins un des 2 mots
4. Expression exacte: "faute de l'employeur" → phrase exacte (avec guillemets)
5. Référence article: "L. 1235-3" ou "L1235-3" → décisions citant cet article (normalisé automatiquement)
6. Mixte: "faute grave" ET "L. 1235-3" → combine mots-clés et article
7. Multiple: FAUTE ET Employeur ET LICENCIEMENT → les 3 mots obligatoires

EXEMPLES CONCRETS:
✅ "faute grave licenciement" → mots-clés simples
✅ "faute" ET "employeur" → opérateur ET
✅ "L. 1235-3" → article du Code du travail (indemnité licenciement)
✅ "L. 1235-3" ET "faute grave" → article + contexte
✅ "L. 1234-1" OU "L. 1234-5" → plusieurs articles
✅ "clause de non-concurrence" → expression exacte
✅ "L.2262-14" → article conventions collectives (point facultatif)

NOTE: Les références d'articles (L.1234-1, R.1234-2, D.1234-3) sont automatiquement normalisées.
Le système parse automatiquement et optimise la requête."""
                },
                "matiere": {
                    "type": "string",
                    "enum": ["TOUTES", "CIVIL", "COMMERCIAL", "PENAL", "SOCIAL"],
                    "default": "TOUTES",
                    "description": "Matière juridique: CIVIL (contrats, famille, immobilier), COMMERCIAL (sociétés), PENAL (criminel), SOCIAL (travail)"
                },
                "CASSATION_TYPE_PUBLICATION_BULLETIN": {
                    "type": "string",
                    "enum": ["TOUS", "PUBLIE", "INEDIT"],
                    "default": "TOUS",
                    "description": "PUBLIE = arrêts de principe uniquement"
                },
                "date_debut": {
                    "type": "string",
                    "description": "Date début YYYY-MM-DD (défaut: 5 ans en arrière)"
                },
                "date_fin": {
                    "type": "string",
                    "description": "Date fin YYYY-MM-DD (défaut: aujourd'hui)"
                },
                "page_size": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 10
                },
                "page_number": {
                    "type": "integer",
                    "minimum": 1,
                    "default": 1
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "Search_Cour_Appel",
        "description": "Recherche dans la jurisprudence des COURS D'APPEL avec parsing intelligent. Volume important: bien cibler avec ville + dates.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": """Mots-clés avec opérateurs logiques et recherche par article visé.

Syntaxe identique à Search_Cour_Cassation:
- Mots simples → ET automatique
- "mot1" ET "mot2" → opérateur ET explicite
- "mot1" OU "mot2" → opérateur OU explicite
- "expression exacte" → entre guillemets
- "L. 1235-3" ou "L1235-3" → décisions citant cet article (normalisé auto)
- Mixte: "divorce" ET "L. 229" → mots-clés + article

Exemples: "divorce prestation compensatoire", "L. 229" ET "prestation", "L. 373-2-9"."""
                },
                "APPEL_SIEGE_APPEL": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["PARIS", "VERSAILLES", "LYON", "AIX-PROVENCE", "TOULOUSE", "BORDEAUX", "RENNES", "DOUAI", "MONTPELLIER", "ROUEN", "NANCY", "DIJON", "GRENOBLE", "ANGERS", "ORLEANS", "AMIENS", "METZ", "NIMES", "LIMOGES", "CAEN", "REIMS", "BOURGES", "POITIERS", "RIOM", "PAU", "BESANCON", "AGEN", "COLMAR", "BASTIA", "CHAMBERY", "BASSE-TERRE", "FORT-DE-FRANCE", "ST-DENIS-REUNION", "NOUMEA", "PAPEETE"]
                    },
                    "description": "Cour(s) d'appel ciblée(s) par ville"
                },
                "date_debut": {
                    "type": "string",
                    "description": "Date début YYYY-MM-DD (défaut: 3 ans)"
                },
                "date_fin": {
                    "type": "string",
                    "description": "Date fin YYYY-MM-DD"
                },
                "page_size": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 15
                },
                "page_number": {
                    "type": "integer",
                    "minimum": 1,
                    "default": 1
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "Search_Conseil_Etat",
        "description": "Recherche ciblée dans la jurisprudence du CONSEIL D'ÉTAT avec parsing intelligent de la query.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": """Mots-clés avec opérateurs logiques et recherche par article visé.

SYNTAXE SUPPORTÉE:
1. Mots simples: "responsabilité hospitalière" → cherche les 2 mots (ET automatique)
2. Opérateur ET: "responsabilité" ET "faute" → les 2 mots obligatoires
3. Opérateur OU: "responsabilité" OU "faute" → au moins un des 2 mots
4. Expression exacte: "responsabilité sans faute" → phrase exacte (avec guillemets)
5. Référence article: "L. 1235-3" → décisions citant cet article (normalisé automatiquement)
6. Mixte: "responsabilité" ET "L. 1142-1" → combine mots-clés et article

EXEMPLES CONCRETS:
✅ "responsabilité hospitalière" → mots-clés simples
✅ "responsabilité" ET "établissement public" → opérateur ET
✅ "L. 1142-1" → article du Code de la santé publique
✅ "annulation acte administratif" → contexte administratif
✅ "principe égalité" OU "principe neutralité" → plusieurs principes

NOTE: Les références d'articles sont automatiquement normalisées."""
                },
                "PUBLICATION_RECUEIL": {
                    "type": "string",
                    "enum": ["TOUS", "PUBLIE", "NON_PUBLIE"],
                    "default": "TOUS",
                    "description": "PUBLIE = décisions publiées au recueil Lebon uniquement"
                },
                "date_debut": {
                    "type": "string",
                    "description": "Date début YYYY-MM-DD (défaut: 5 ans en arrière)"
                },
                "date_fin": {
                    "type": "string",
                    "description": "Date fin YYYY-MM-DD (défaut: aujourd'hui)"
                },
                "page_size": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 10
                },
                "page_number": {
                    "type": "integer",
                    "minimum": 1,
                    "default": 1
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "Search_CAA",
        "description": "Recherche dans la jurisprudence des COURS ADMINISTRATIVES D'APPEL avec parsing intelligent. Permet de filtrer par ville de la CAA.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": """Mots-clés avec opérateurs logiques et recherche par article visé.

Syntaxe identique à Search_Conseil_Etat:
- Mots simples → ET automatique
- "mot1" ET "mot2" → opérateur ET explicite
- "mot1" OU "mot2" → opérateur OU explicite
- "expression exacte" → entre guillemets
- "L. 1235-3" ou "L1235-3" → décisions citant cet article (normalisé auto)
- Mixte: "urbanisme" ET "L. 123-1" → mots-clés + article

Exemples: "permis de construire", "L. 421-6" ET "urbanisme", "refus titre séjour"."""
                },
                "CAA_VILLE": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["PARIS", "VERSAILLES", "LYON", "MARSEILLE", "BORDEAUX", "NANTES", "NANCY", "DOUAI", "TOULOUSE"]
                    },
                    "description": "Cour(s) administrative(s) d'appel ciblée(s) par ville"
                },
                "PUBLICATION_RECUEIL": {
                    "type": "string",
                    "enum": ["TOUS", "PUBLIE", "NON_PUBLIE"],
                    "default": "TOUS",
                    "description": "PUBLIE = décisions publiées au recueil Lebon uniquement"
                },
                "date_debut": {
                    "type": "string",
                    "description": "Date début YYYY-MM-DD (défaut: 3 ans)"
                },
                "date_fin": {
                    "type": "string",
                    "description": "Date fin YYYY-MM-DD"
                },
                "page_size": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 15
                },
                "page_number": {
                    "type": "integer",
                    "minimum": 1,
                    "default": 1
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "Search_Premiere_Instance",
        "description": "Recherche dans la jurisprudence des JURIDICTIONS DE PREMIÈRE INSTANCE. Volume très limité dans la base (~50 décisions). Query automatiquement optimisée (opérateur OU, au moins un mot - car volume faible).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": """Mots-clés avec opérateurs logiques et recherche par article visé.

SYNTAXE SUPPORTÉE:
1. Mots simples: "divorce pension alimentaire" → cherche avec OU (au moins un mot)
2. Opérateur ET: "divorce" ET "pension" → les 2 mots obligatoires
3. Opérateur OU: "divorce" OU "séparation" → au moins un des 2 mots
4. Expression exacte: "pension alimentaire" → phrase exacte (avec guillemets)
5. Référence article: "L. 1235-3" ou "L1235-3" → décisions citant cet article (normalisé auto)
6. Combinaisons: "divorce" ET "pension alimentaire" ET "L. 229" → mixte

EXEMPLES:
- "licenciement" → décisions contenant au moins ce mot
- "L. 1235-3" → décisions citant cet article du Code du travail
- "L. 1235-3" ET "faute grave" → article + contexte
- "divorce" ET "pension" → décisions avec les 2 mots
- "clause de non-concurrence" → expression exacte
- "prud'hommes" ET "rappel salaire" → termes combinés

NOTE: Volume très faible en première instance (~50 décisions totales), opérateur OU par défaut sauf si ET/OU explicite dans la query.
Les références d'articles (L., R., D.) sont automatiquement normalisées."""
                },
                "PREMIER_DEGRE_TYPE_JURIDICTION": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["Tribunal de grande instance", "Tribunal judiciaire de Paris", "Conseil de prud'hommes", "Chambre de l'application des peines du TSA de St Pierre"]
                    },
                    "description": "Type de juridiction de première instance"
                },
                "date_debut": {
                    "type": "string",
                    "description": "Date début YYYY-MM-DD"
                },
                "date_fin": {
                    "type": "string",
                    "description": "Date fin YYYY-MM-DD"
                },
                "page_size": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 20
                },
                "page_number": {
                    "type": "integer",
                    "minimum": 1,
                    "default": 1
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "Search_Code",
        "description": "Recherche INTELLIGENTE dans les codes juridiques français (Code du travail, Code civil, etc.) avec parsing automatique des références d'articles et opérateurs logiques.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": """Recherche avec détection automatique du format.

FORMATS SUPPORTÉS:

1. RÉFÉRENCE D'ARTICLE EXACTE:
   - "L. 1234-1" ou "L.1234-1" ou "L 1234-1" ou "L1234-1"
   - "R. 2242-1" (articles réglementaires)
   - "D. 1234-56" (articles décrets)
   → Recherche exacte dans NUM_ARTICLE (normalisé automatiquement)

2. MOTS-CLÉS SIMPLES:
   - "licenciement économique" → cherche les 2 mots (ET automatique)
   - "faute grave" → cherche les 2 mots

3. OPÉRATEUR ET EXPLICITE:
   - "licenciement" ET "motif économique" → les 2 termes obligatoires

4. OPÉRATEUR OU EXPLICITE:
   - "démission" OU "rupture conventionnelle" → au moins un des termes

5. EXPRESSION EXACTE (guillemets):
   - "clause de non-concurrence" → phrase exacte
   - "faute lourde de l'employeur" → expression exacte

6. COMBINAISONS:
   - "L1234-1 ET indemnité" → article + mot-clé
   - "Code du travail" ET "licenciement" ET "économique"

EXEMPLES CONCRETS:
- "L1235-3" → trouve l'article L. 1235-3 (indemnité licenciement)
- "licenciement pour motif économique" → articles sur ce sujet
- "clause de mobilité" → expression exacte
- "préavis" ET "démission" → articles contenant les 2 mots
- "rupture" OU "résiliation" → articles avec l'un ou l'autre

NOTE: Incluez le nom du code dans la query pour cibler un code spécifique (ex: "752 code de procédure civile")."""
                },
                "date": {
                    "type": "string",
                    "description": "Date de vigueur souhaitée au format YYYY-MM-DD (ex: '2020-01-15'). Par défaut, seuls les articles EN VIGUEUR aujourd'hui sont recherchés. Utilisez ce paramètre pour obtenir la version d'un article valable à une date passée."
                },
                "sort": {
                    "type": "string",
                    "enum": ["PERTINENCE", "DATE_VERSION_ASC", "DATE_VERSION_DESC"],
                    "default": "PERTINENCE",
                    "description": "Tri des résultats"
                },
                "page_size": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "default": 10,
                    "description": "Nombre de résultats par page"
                },
                "page_number": {
                    "type": "integer",
                    "minimum": 1,
                    "default": 1,
                    "description": "Numéro de page"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "consulter_article",
        "description": "Consulte le texte intégral et les informations de vigueur d'une version précise d'article à partir de son identifiant officiel Légifrance LEGIARTI.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "article_id": {
                    "type": "string",
                    "pattern": "^LEGIARTI[0-9]+$",
                    "description": "Identifiant technique officiel de la version d'article, par exemple LEGIARTI000036762052. Cet identifiant est fourni par Search_Code."
                }
            },
            "required": ["article_id"]
        }
    },
        {
            "name": "consulter_decision",
            "description": "Get Jurisprudence content with Legifrance API & return result with link https://www.legifrance.gouv.fr/juri/id/{text_id}",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "text_id": {
                        "type": "string",
                        "description": "Should be in format : 'JURITEXT000006949246')"
                    }
                },
                "required": ["text_id"]
            }
        },
    # ============================================================================
    # TOOL 4 : TRACKING (BODACC)
    # ============================================================================
    {
        "name": "Tracking_BODACC",
        "description": "Search French BODACC for company situation with its SIREN number(procédure collective)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "siren": {
                    "type": "string",
                    "description": "Numéro SIREN de l'entreprise (9 chiffres)"
                },
                "type_recherche": {
                    "type": "string",
                    "enum": ["complet", "procedures_collectives", "historique"],
                    "description": "Type de recherche à effectuer",
                    "default": "complet"
                }
            },
            "required": ["siren"]
        }
    },
    {
        "name": "Download_Query_Results",
        "description": "Télécharge TOUS les résultats d'une requête de jurisprudence (dans la limite d'un plafond) dans un dossier local — un fichier Markdown par décision, plus un index et le JSON brut — et rend le CHEMIN du dossier. À utiliser pour le tri en masse : l'agent lit ensuite l'index puis les décisions pertinentes au lieu de paginer. Un marqueur local stable permet au client de tracer les lectures s'il le souhaite.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Requête (même syntaxe que les outils Search_* : mots-clés, ET/OU, \"expression exacte\", référence d'article)."
                },
                "juridiction": {
                    "type": "string",
                    "enum": ["cassation", "appel", "premiere_instance", "administratif"],
                    "description": "Corpus à interroger. 'administratif' couvre Conseil d'État et cours administratives d'appel.",
                    "default": "cassation"
                },
                "date_debut": {
                    "type": "string",
                    "description": "Date de début (AAAA-MM-JJ). Défaut : il y a 5 ans."
                },
                "date_fin": {
                    "type": "string",
                    "description": "Date de fin (AAAA-MM-JJ). Défaut : aujourd'hui."
                },
                "max_results": {
                    "type": "integer",
                    "description": "Plafond de décisions téléchargées (défaut 200, maximum 500).",
                    "default": 200
                },
                "include_solution": {
                    "type": "boolean",
                    "description": "Si vrai, enrichit chaque décision (plafond 50) avec sa SOLUTION/dispositif seul — sens (rejet/cassation), décision attaquée, extrait du dispositif — SANS les motifs. Un appel API par décision : à réserver à une liste déjà restreinte (max_results bas). Défaut : faux.",
                    "default": False
                },
                "output_dir": {
                    "type": "string",
                    "description": "Dossier racine où créer le sous-dossier de résultats. Défaut autonome : ~/.legifrance-mcp/results/."
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "Build_Research_Corpus",
        "description": "Constitue un corpus jurisprudentiel à partir d'une question, télécharge les décisions et prépare leur revue par lots. Crée un dossier documenté dans Downloads ou dans output_dir, avec les textes, les lots, les fiches et recompile_research.py pour contrôler la couverture, signaler le travail restant et produire le rapport Markdown final.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "Question de droit complète posée par le LLM. Elle sert aussi de titre lisible au dossier du corpus et au rapport Markdown final."
                },
                "queries": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Formulations Légifrance complémentaires. Si absent, la question est utilisée telle quelle. Pour une recherche de qualité, fournir les expressions de principe, exceptions, textes et formulations contraires."
                },
                "juridictions": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["cassation", "appel", "premiere_instance", "administratif"]
                    },
                    "default": ["cassation"],
                    "description": "Corpus interrogés. Chaque couple requête/juridiction est paginé intégralement dans la limite déclarée."
                },
                "date_debut": {
                    "type": "string",
                    "description": "Date minimale AAAA-MM-JJ. Sans valeur, aucune borne ancienne n'est ajoutée : les arrêts de principe historiques restent couverts."
                },
                "date_fin": {
                    "type": "string",
                    "description": "Date maximale AAAA-MM-JJ. Sans valeur, aucune borne n'est ajoutée."
                },
                "max_results_per_query": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 500,
                    "default": 500,
                    "description": "Plafond par couple requête/juridiction. Toute troncature est inscrite dans le manifeste et le rapport."
                },
                "max_decisions": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 2000,
                    "default": 1000,
                    "description": "Plafond global après déduplication."
                },
                "batch_target_tokens": {
                    "type": "integer",
                    "minimum": 5000,
                    "maximum": 150000,
                    "default": 60000,
                    "description": "Volume estimé visé par lot de cartographie. Une décision plus longue reste entière dans son propre lot."
                },
                "batch_max_decisions": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "default": 1,
                    "description": "Nombre maximal de décisions par lot. Par défaut, chaque tâche de revue reçoit une seule décision."
                },
                "fetch_workers": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 8,
                    "default": 4,
                    "description": "Téléchargements de textes intégraux simultanés."
                },
                "output_dir": {
                    "type": "string",
                    "description": "Dossier racine de sortie choisi par l'appelant. Défaut : le dossier Downloads de l'utilisateur. Le corpus y est créé dans un sous-dossier 'AAAA-MM-JJ - Question', à côté du rapport Markdown homonyme."
                }
            },
            "required": ["question"]
        }
    },

]

# ============================================================================
# RESSOURCES MCP
# ============================================================================

MCP_RESOURCES = [
    {
        "uri": "resource://dictionnaire-juridique",
        "name": "Dictionnaire juridique",
        "description": "Définitions et terminologie juridique française",
        "mimeType": "text/markdown"
    }
]


# ============================================================================
# MAPPING FILTRES PAR FOND
# ============================================================================
