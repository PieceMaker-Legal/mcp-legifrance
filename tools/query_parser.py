# tools/query_parser.py
"""Parser intelligent pour les queries de recherche jurisprudence"""

import re
from typing import List, Dict, Tuple, Any


class QueryCriteria(list):
    """Liste compatible PISTE, enrichie d'un plan booléen en forme DNF.

    Une clause est un champ PISTE : ses critères sont reliés par ``ET``. Les
    clauses sont reliées par ``OU`` via ``recherche.operateur``. La liste
    elle-même reste disponible pour les appelants historiques qui itèrent sur
    les critères.
    """

    def __init__(self, criteria: List[Dict[str, Any]], clauses: List[List[Dict[str, Any]]]):
        super().__init__(criteria)
        self.clauses = clauses

def normalize_article_reference(ref: str) -> str:
    """
    Normalise une référence d'article vers le format sans point ni espace.

    Exemples:
    - "L. 1234-1" → "L1234-1"
    - "L.1234-1" → "L1234-1"
    - "L 1234-1" → "L1234-1"

    Args:
        ref: Référence brute

    Returns:
        Référence normalisée
    """
    normalized = re.sub(r'([A-Z]+)\.?\s*(\d+[-\d]*)', r'\1\2', ref.strip(), flags=re.IGNORECASE)
    return normalized.upper()


def parse_query(query: str, proximite: int = 10) -> Tuple[str, str, List[Dict[str, Any]]]:
    """
    Parse une query avec opérateurs logiques et expressions exactes.
    Normalise automatiquement les références d'articles (L. 1234-1 → L1234-1).

    Exemples supportés:
    - "faute grave" → tous les mots (ET par défaut)
    - "faute" ET "employeur" → opérateur ET explicite
    - "faute" OU "employeur" → opérateur OU explicite
    - "faute de l'employeur" → expression exacte (entre guillemets)
    - "FAUTE" ET "Employeur" ET "LICENCIEMENT" → multiple ET
    - "L. 1235-3" → article normalisé en L1235-3
    - Mixte: "clause non-concurrence" ET validité

    Args:
        query: Query brute
        proximite: Distance max entre mots (pour recherches non-exactes)

    Returns:
        (operateur_global, type_recherche, criteres_formatés)
    """

    text = str(query or "").strip()
    if not text:
        raise ValueError("requête vide")

    article_pattern = r'\b([LRDC])\.?\s*(\d+[-\d]+)\b'
    text = re.sub(
        article_pattern,
        lambda match: normalize_article_reference(match.group(0)),
        text,
        flags=re.IGNORECASE,
    )

    tokens = []
    position = 0
    while position < len(text):
        if text[position].isspace():
            position += 1
            continue
        char = text[position]
        if char in '"«':
            closing = '"' if char == '"' else '»'
            end = text.find(closing, position + 1)
            if end < 0:
                raise ValueError("guillemets non fermés dans la requête")
            value = text[position + 1:end].strip()
            if not value:
                raise ValueError("expression exacte vide")
            tokens.append(("ATOM", value, True))
            position = end + 1
            continue
        if char == '(':
            tokens.append(("LPAREN", char, False))
            position += 1
            continue
        if char == ')':
            tokens.append(("RPAREN", char, False))
            position += 1
            continue
        match = re.match(r'[^\s()]+', text[position:])
        if not match:
            raise ValueError(f"caractère invalide dans la requête : {char}")
        value = match.group(0)
        upper = value.upper()
        tokens.append((upper if upper in {"ET", "OU"} else "ATOM", value, False))
        position += len(value)

    normalized = []
    previous = None
    for token in tokens:
        kind = token[0]
        if previous in {"ATOM", "RPAREN"} and kind in {"ATOM", "LPAREN"}:
            normalized.append(("ET", "ET", False))
        normalized.append(token)
        previous = kind
    if not normalized or normalized[-1][0] in {"ET", "OU", "LPAREN"}:
        raise ValueError("opérateur ou parenthèse ouvrante sans terme à droite")

    index = 0

    def parse_factor():
        nonlocal index
        if index >= len(normalized):
            raise ValueError("terme attendu dans la requête")
        kind, value, exact = normalized[index]
        if kind == "ATOM":
            index += 1
            return ("ATOM", value, exact)
        if kind == "LPAREN":
            index += 1
            node = parse_or()
            if index >= len(normalized) or normalized[index][0] != "RPAREN":
                raise ValueError("parenthèse fermante manquante")
            index += 1
            return node
        raise ValueError("opérateur sans terme à gauche")

    def parse_and():
        nonlocal index
        node = parse_factor()
        while index < len(normalized) and normalized[index][0] == "ET":
            index += 1
            node = ("ET", node, parse_factor())
        return node

    def parse_or():
        nonlocal index
        node = parse_and()
        while index < len(normalized) and normalized[index][0] == "OU":
            index += 1
            node = ("OU", node, parse_and())
        return node

    tree = parse_or()
    if index != len(normalized):
        raise ValueError("parenthèse fermante ou terme inattendu")

    max_clauses = 64

    def distinct_clauses(raw_clauses):
        """Déduplique les clauses logiquement identiques, sans les réordonner."""
        unique = []
        seen = set()
        for clause in raw_clauses:
            key = tuple((atom[1], atom[2]) for atom in clause)
            if key not in seen:
                seen.add(key)
                unique.append(clause)
        if len(unique) > max_clauses:
            raise ValueError("formule booléenne trop complexe (maximum 64 clauses)")
        return unique

    def dnf(node):
        if node[0] == "ATOM":
            return [[node]]
        left, right = dnf(node[1]), dnf(node[2])
        if node[0] == "OU":
            return distinct_clauses(left + right)
        clauses = [first + second for first in left for second in right]
        return distinct_clauses(clauses)

    raw_clauses = dnf(tree)
    clauses = []
    for raw_clause in raw_clauses:
        criteria = []
        for _kind, value, exact in raw_clause:
            criteria.append({
                "valeur": value,
                "operateur": "ET",
                "typeRecherche": "EXACTE" if exact else "TOUS_LES_MOTS_DANS_UN_CHAMP",
                "proximite": None if exact else proximite,
            })
        clauses.append(criteria)
    flattened = []
    for clause in clauses:
        for criterion in clause:
            if criterion not in flattened:
                # La liste historique et le plan DNF doivent exposer les mêmes
                # objets : un appelant compatible qui ajuste un critère voit
                # bien cet ajustement dans la clause ensuite envoyée à PISTE.
                flattened.append(criterion)
    operateur_global = "ET" if len(clauses) == 1 else "OU"
    type_recherche = (
        "EXACTE" if flattened and all(c["typeRecherche"] == "EXACTE" for c in flattened)
        else "TOUS_LES_MOTS_DANS_UN_CHAMP"
    )
    return operateur_global, type_recherche, QueryCriteria(flattened, clauses)


def build_search_payload_champs(query: str, proximite: int = 10) -> Tuple[str, str, List[Dict[str, Any]]]:
    """
    Construit la structure 'champs' pour l'API Légifrance à partir d'une query parsée.

    Args:
        query: Query brute avec opérateurs (ex: "faute" ET "employeur")
        proximite: Distance max entre mots (défaut: 10)

    Returns:
        (operateur_global, type_champ, champs_structure)
    """

    operateur_global, type_recherche, criteres = parse_query(query, proximite)

    # PISTE combine les champs par ``recherche.operateur`` et les critères
    # d'un champ par ``champ.operateur``. Une clause DNF devient donc un champ.
    clauses = getattr(criteres, "clauses", [list(criteres)])
    champs = []
    for clause in clauses:
        champs.append({
            "typeChamp": "ALL",
            "operateur": "ET",
            "criteres": [{
                "operateur": "ET",
                "typeRecherche": critere["typeRecherche"],
                "valeur": critere["valeur"],
                "proximite": proximite if critere["typeRecherche"] != "EXACTE" else None,
            } for critere in clause],
        })

    return operateur_global, "ALL", champs


# Tests unitaires
if __name__ == "__main__":
    print("="*80)
    print("TESTS DU PARSER DE QUERY")
    print("="*80)

    tests = [
        "faute grave licenciement",
        "faute ET employeur",
        "faute OU employeur",
        '"faute de l\'employeur"',
        "FAUTE ET Employeur ET LICENCIEMENT",
        '"clause de non-concurrence" ET validité',
        "licenciement",
        "faute OU employeur OU licenciement",
        '"expression exacte"',
        "mot1 ET mot2 OU mot3",  # Mixte
    ]

    for test in tests:
        print(f"\n🔍 Query: {test}")
        operateur, type_rech, criteres = parse_query(test)
        print(f"   Opérateur global: {operateur}")
        print(f"   Type recherche: {type_rech}")
        print(f"   Critères ({len(criteres)}):")
        for c in criteres:
            print(f"      - '{c['valeur']}' ({c['typeRecherche']})")

    print("\n" + "="*80)
    print("TEST CONSTRUCTION PAYLOAD API")
    print("="*80)

    query_test = "faute ET employeur"
    op, tc, champs = build_search_payload_champs(query_test)

    import json
    print(f"\nQuery: {query_test}")
    print(f"\nStructure générée:")
    print(json.dumps(champs, indent=2, ensure_ascii=False))
