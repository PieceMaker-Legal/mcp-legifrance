#/config/mcp_definitions.py 
#! MCP SERVEUR LOCAL
"""Définition des outils MCP disponibles"""

QUERY_SYNTAX_DESCRIPTION = """Syntaxe de requête commune :

- Les guillemets délimitent une expression exacte : `"faute grave"`.
- `ET` exige les deux côtés ; `OU` accepte l'un des deux côtés.
- `ET` est prioritaire sur `OU` : `A OU B ET C` signifie `A OU (B ET C)`.
- Les parenthèses changent ce regroupement : `(A OU B) ET C`.
- Les références d'article (`L. 1235-3`, `L1235-3`, `R. 2242-1`) sont normalisées automatiquement.

Exemple non ambigu : `("faute grave" OU "faute lourde") ET licenciement`."""

QUERY_SYNTAX_ET_DESCRIPTION = (
    QUERY_SYNTAX_DESCRIPTION
    + """

Sans opérateur explicite, les mots non entre guillemets sont reliés par `ET` :
`faute grave licenciement`."""
)

QUERY_SYNTAX_PREMIERE_INSTANCE_DESCRIPTION = (
    QUERY_SYNTAX_DESCRIPTION
    + """

En première instance, sans `ET` ou `OU` explicite, les mots non entre guillemets
sont reliés par `OU` afin d'élargir ce corpus limité : `divorce pension`. Les
guillemets et parenthèses restent interprétés ; les opérateurs explicites
conservent la logique commune."""
)

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
                    "description": QUERY_SYNTAX_ET_DESCRIPTION
                },
                "matiere": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["CIVIL", "COMMERCIAL", "PENAL", "SOCIAL"]
                    },
                    "minItems": 1,
                    "description": "OBLIGATOIRE. Matière(s) de la question posée, appliquée(s) à la facette officielle des formations (chambres) de la Cour de cassation. CIVIL (contrats, famille, immobilier, responsabilité civile), COMMERCIAL (sociétés, dirigeants, procédures collectives, concurrence), PENAL (chambre criminelle), SOCIAL (travail, sécurité sociale). Les formations transversales (assemblée plénière, chambre mixte, chambres réunies, avis) sont toujours incluses. Sans ce filtre la recherche mélange toutes les chambres: une question de révocation de dirigeant remonterait des arrêts criminels. Plusieurs matières sont possibles quand la question est réellement mixte (ex: [\"CIVIL\", \"COMMERCIAL\"]); n'énumérez les quatre que pour balayer volontairement toute la Cour."
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
            "required": ["query", "matiere"]
        }
    },
    {
        "name": "Search_Cour_Appel",
        "description": "Recherche dans la jurisprudence des COURS D'APPEL avec parsing intelligent. Volume important: bien cibler avec ville + dates. Le fonds JURI n'expose AUCUNE facette de matière ni de chambre pour les cours d'appel (contrairement à la Cour de cassation): le ciblage par matière passe donc uniquement par des mots-clés ou un article visé dans la query. Vérifié sur la table officielle DILA des tris et filtres (voir docs/facettes-officielles-dila.md): seul APPEL_SIEGE_APPEL (la ville) existe pour ce degré.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": QUERY_SYNTAX_ET_DESCRIPTION
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
        "description": "Recherche ciblée dans la jurisprudence du CONSEIL D'ÉTAT avec parsing intelligent de la query. Le fonds CETAT n'expose pas de facette de matière ni de chambre (table officielle DILA des tris et filtres, voir docs/facettes-officielles-dila.md): le ciblage passe par la query.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": QUERY_SYNTAX_ET_DESCRIPTION
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
        "description": "Recherche dans la jurisprudence des COURS ADMINISTRATIVES D'APPEL avec parsing intelligent. Permet de filtrer par ville de la CAA. Le fonds CETAT n'expose pas de facette de matière ni de chambre (table officielle DILA des tris et filtres, voir docs/facettes-officielles-dila.md); le filtre de ville est appliqué côté client à partir du titre des décisions.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": QUERY_SYNTAX_ET_DESCRIPTION
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
        "description": "Recherche dans la jurisprudence des JURIDICTIONS DE PREMIÈRE INSTANCE. Volume très limité dans la base (~2000 décisions). Query automatiquement optimisée (opérateur OU, au moins un mot - car volume faible). À ce degré, la matière est portée par le NOM de la juridiction et non par une chambre: le filtre PREMIER_DEGRE_TYPE_JURIDICTION est donc OBLIGATOIRE (table officielle DILA des tris et filtres, voir docs/facettes-officielles-dila.md).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": QUERY_SYNTAX_PREMIERE_INSTANCE_DESCRIPTION
                },
                "PREMIER_DEGRE_TYPE_JURIDICTION": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": [
                            "TRIBUNAL_JUDICIAIRE",
                            "TRIBUNAL_GRANDE_INSTANCE",
                            "TRIBUNAL_INSTANCE",
                            "TRIBUNAL_COMMERCE",
                            "CONSEIL_PRUDHOMMES",
                            "TRIBUNAL_CORRECTIONNEL",
                            "TRIBUNAL_SECURITE_SOCIALE",
                            "TRIBUNAL_BAUX_RURAUX",
                            "JURIDICTION_PROXIMITE",
                            "OUTRE_MER",
                            "TRIBUNAL_CONFLITS"
                        ]
                    },
                    "minItems": 1,
                    "description": """OBLIGATOIRE. Famille(s) de juridictions du premier degre. A ce degre, c'est le nom de la juridiction qui porte la matiere: sans ce filtre la recherche melange prud'hommes, correctionnel et commerce.

Correspondance matiere -> famille:
- civil general: TRIBUNAL_JUDICIAIRE, TRIBUNAL_GRANDE_INSTANCE, TRIBUNAL_INSTANCE
- commercial: TRIBUNAL_COMMERCE
- social: CONSEIL_PRUDHOMMES, TRIBUNAL_SECURITE_SOCIALE
- penal: TRIBUNAL_CORRECTIONNEL
- baux ruraux: TRIBUNAL_BAUX_RURAUX
- petits litiges (juridictions et juges de proximite, supprimes en 2017): JURIDICTION_PROXIMITE
- Noumea, Papeete, Mamoudzou, Saint-Pierre: OUTRE_MER
- conflits de competence judiciaire/administratif: TRIBUNAL_CONFLITS

Chaque famille est etendue aux valeurs reelles de la facette officielle PREMIER_DEGRE_TYPE_JURIDICTION, qui mele libelles generiques ("Conseil de prud'hommes") et libelles par ville ("Tribunal correctionnel de Nice")."""
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
            "required": ["query", "PREMIER_DEGRE_TYPE_JURIDICTION"]
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
                    "description": (
                        QUERY_SYNTAX_ET_DESCRIPTION
                        + "\n\nPour une référence d'article seule, Search_Code cible le champ "
                        "NUM_ARTICLE. Ajoutez le nom du code si nécessaire, par exemple "
                        "`752 code de procédure civile`."
                    )
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
    {
        "name": "Historique_Judiciaire",
        "description": (
            "Rend en un seul appel deux relevés distincts pour une décision, sans jamais les "
            "mélanger. 1° L'HISTORIQUE PROCÉDURAL STRICT : la décision attaquée, celle qu'elle "
            "attaquait, et les décisions qui attaquent une décision du fil. Chaque maillon repose "
            "exclusivement sur la métadonnée officielle « décision attaquée » (juridiction et date "
            "identiques) : aucun lien n'est déduit d'une citation, d'une date ou d'une juridiction "
            "commune. 2° LE RELEVÉ « CITÉE PAR » : toutes les décisions du fonds dont le texte "
            "reprend littéralement un numéro d'affaire de la décision de départ, avec la citation "
            "exacte et le lien Légifrance ; ce relevé recense sans rattacher — un précédent cité "
            "y figure comme un recours, et il revient au lecteur de trancher. Une décision "
            "attaquée nommée par les métadonnées mais absente de la base (jugements de première "
            "instance et beaucoup d'arrêts d'appel ne sont pas publiés) est déclarée non résolue, "
            "jamais devinée. Dans le fonds CETAT, la métadonnée « décision attaquée » n'est jamais "
            "renseignée : l'historique procédural d'une décision administrative y est vide par "
            "construction, seul le relevé « citée par » est exploitable. Un relevé tronqué par un "
            "plafond est signalé comme tel, afin qu'une absence ne soit jamais confondue avec une "
            "limite atteinte."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text_id": {
                    "type": "string",
                    "pattern": "^(JURITEXT|CETATEXT)[0-9]+$",
                    "description": (
                        "Identifiant officiel de la décision de départ : JURITEXT000047074185 "
                        "(ordre judiciaire) ou CETATEXT000047444867 (ordre administratif)."
                    )
                },
                "max_decisions": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 60,
                    "default": 20,
                    "description": "Nombre maximal de décisions retenues dans le fil."
                },
                "max_citations": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 200,
                    "default": 50,
                    "description": (
                        "Nombre maximal de décisions citantes relevées. 0 désactive le relevé "
                        "« citée par » et réserve le budget d'appels au fil procédural."
                    )
                },
                "max_api_calls": {
                    "type": "integer",
                    "minimum": 2,
                    "maximum": 600,
                    "default": 200,
                    "description": (
                        "Plafond d'appels API (recherches + consultations), fil procédural et "
                        "relevé des citations compris. Toute troncature par ce plafond est "
                        "signalée dans la télémétrie."
                    )
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
                    "description": QUERY_SYNTAX_ET_DESCRIPTION
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
                    "description": (
                        "Formulations Légifrance complémentaires ; chaque élément suit cette syntaxe. "
                        + QUERY_SYNTAX_ET_DESCRIPTION
                        + "\n\nSi absent, la question est utilisée telle quelle. Pour une recherche de "
                        "qualité, fournir les expressions de principe, exceptions, textes et formulations contraires."
                    )
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
