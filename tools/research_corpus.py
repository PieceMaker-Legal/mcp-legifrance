#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Corpus exhaustif et validation probatoire pour la recherche jurisprudentielle.

Ce module ne choisit jamais quelques résultats à la place du modèle. Il fige
les résultats de plusieurs requêtes, déduplique les identifiants Légifrance,
télécharge le texte intégral de chaque décision, puis prépare des lots bornés
en volume. Le modèle restitue ensuite une fiche JSON par décision ; la seconde
moitié de ce module contrôle mécaniquement leur couverture et leurs citations.

Il n'y a ni embeddings, ni base vectorielle, ni recherche top-k : toutes les
décisions du manifeste sont parcourues. Le classement lexical n'est qu'un
index de contrôle et ne retire aucune décision des lots.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import json
import math
import os
import re
import shutil
import time
import unicodedata
from typing import Any, Dict, Iterable, List, Optional, Tuple

from tools.bulk_download import JURIDICTION_CONFIG, MARKER_NAME, slugify
from tools.legifrance_client import legifrance_client
from tools.query_parser import parse_query
from tools import research_report_compiler


PAGE_SIZE = 100
MAX_CUMULATIVE_RESULTS = 500
DEFAULT_BATCH_TARGET_TOKENS = 60_000
HARD_BATCH_TARGET_TOKENS = 150_000
DEFAULT_BATCH_MAX_DECISIONS = 1
HARD_BATCH_MAX_DECISIONS = 100
DEFAULT_FETCH_WORKERS = 4
HARD_FETCH_WORKERS = 8

TOKEN_ESTIMATION_METHOD = "ceil(nombre_de_caracteres_utf8_decodes/4)"

STOPWORDS = {
    "alors", "avec", "cette", "dans", "depuis", "des", "dont", "elle",
    "elles", "entre", "est", "leur", "leurs", "mais", "pour", "que",
    "quel", "quelle", "quelles", "quels", "sans", "sur", "une", "aux",
    "decision", "decisions", "jurisprudence",
}


def estimate_tokens(value: str) -> int:
    """Estimation stable et explicite ; jamais présentée comme usage API exact."""
    return int(math.ceil(len(value or "") / 4))


def _normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text).strip().lower()


def _query_terms(question: str, query: str) -> List[str]:
    words = re.findall(r"[a-zA-ZÀ-ÿ0-9.-]{3,}", " ".join([question, query]))
    terms = []
    for word in words:
        normalized = _normalize(word).strip(".-")
        if len(normalized) < 4 or normalized in STOPWORDS or normalized in terms:
            continue
        terms.append(normalized)
    return terms


def _clean_query(args: Dict[str, Any]) -> str:
    """Valide la formulation unique du contrat public Build_Research_Corpus."""
    if "queries" in args:
        raise ValueError(
            "Le paramètre `queries` n'est plus accepté : fournissez une seule "
            "formulation précise dans `query`."
        )
    raw_query = args.get("query")
    if not isinstance(raw_query, str):
        raise ValueError("`query` doit être une chaîne de caractères contenant une formulation précise")
    query = re.sub(r"\s+", " ", raw_query).strip()
    if not query:
        raise ValueError("`query` est requis et doit contenir une formulation de recherche précise")
    return query


def _clean_jurisdictions(raw: Any) -> List[str]:
    if isinstance(raw, str):
        raw = [raw]
    values = raw if isinstance(raw, list) and raw else ["cassation"]
    jurisdictions = []
    for value in values:
        key = str(value or "").strip().lower()
        if key not in JURIDICTION_CONFIG:
            raise ValueError(
                f"juridiction inconnue : {key}. "
                f"Valeurs : {', '.join(sorted(JURIDICTION_CONFIG))}"
            )
        if key not in jurisdictions:
            jurisdictions.append(key)
    return jurisdictions


def _search_identity(result: Dict[str, Any]) -> Tuple[str, str]:
    titles = result.get("titles") or []
    first = titles[0] if titles else {}
    return str(first.get("id") or "").strip(), str(first.get("title") or "Sans titre").strip()


def _date_filter(date_debut: Optional[str], date_fin: Optional[str]) -> List[Dict[str, Any]]:
    if not date_debut and not date_fin:
        return []
    dates = {}
    if date_debut:
        dates["start"] = date_debut
    if date_fin:
        dates["end"] = date_fin
    return [{"facette": "DATE_DECISION", "dates": dates}]


def _search_query(
    client: Any,
    query: str,
    jurisdiction: str,
    date_debut: Optional[str],
    date_fin: Optional[str],
    max_results: int,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    config = JURIDICTION_CONFIG[jurisdiction]
    operator, _search_type, criteria = parse_query(query)
    filters = list(config["filtres"]) + _date_filter(date_debut, date_fin)
    collected: List[Dict[str, Any]] = []
    total = None
    total_api_connu = False
    page = 1
    calls = 0

    while len(collected) < max_results:
        requested_page_size = min(PAGE_SIZE, max_results - len(collected))
        response = client.search_with_criteres(
            fond=config["fond"],
            criteres=criteria,
            operateur=operator,
            filtres=filters,
            type_champ="ALL",
            page_number=page,
            page_size=requested_page_size,
            sort="PERTINENCE",
        )
        calls += 1
        batch = response.get("results") or []
        reported_total = response.get("totalResultNumber")
        try:
            parsed_total = int(reported_total) if reported_total is not None else None
        except (TypeError, ValueError):
            parsed_total = None
        # Un zéro n'est fiable que pour une réponse vide. Une page non vide
        # accompagnée d'un total nul doit rester traitée comme un total absent.
        if parsed_total is not None and (parsed_total > 0 or not batch):
            total = parsed_total
            total_api_connu = True
        if not batch:
            break
        collected.extend(batch)
        if len(collected) >= max_results:
            break
        if len(batch) < requested_page_size:
            break
        if total_api_connu and len(collected) >= total:
            break
        page += 1

    returned = collected[:max_results]
    tronquee = (
        len(returned) < total
        if total_api_connu else len(returned) >= max_results
    )
    return returned, {
        "query": query,
        "juridiction": jurisdiction,
        "total_api": total,
        "total_api_connu": total_api_connu,
        "collectes": len(returned),
        "tronquee": tronquee,
        "appels_recherche": calls,
    }


def _preflight_cumulative_total(
    client: Any,
    query: str,
    jurisdictions: List[str],
    date_debut: Optional[str],
    date_fin: Optional[str],
) -> List[Dict[str, Any]]:
    """Lit les totaux officiels avant toute collecte ou téléchargement."""
    reports = []
    cumulative_total = 0
    for jurisdiction in jurisdictions:
        _results, report = _search_query(
            client, query, jurisdiction, date_debut, date_fin, max_results=1,
        )
        total = report["total_api"]
        if not report["total_api_connu"] or total is None:
            raise ValueError(
                "L'API Légifrance n'a pas fourni de nombre de résultats fiable ; "
                "la recherche est arrêtée avant tout téléchargement."
            )
        cumulative_total += total
        # Ce n'est pas une collecte : une page de taille 1 serait naturellement
        # tronquée pour tout total supérieur à 1. Ne pas exposer ce signal comme
        # une troncature du corpus dans la télémétrie.
        reports.append({
            "query": query,
            "juridiction": jurisdiction,
            "total_api": total,
            "total_api_connu": True,
            "appels_recherche": report["appels_recherche"],
            "phase": "contrôle_préalable",
        })

    if cumulative_total > MAX_CUMULATIVE_RESULTS:
        raise ValueError(
            f"La formulation produit {cumulative_total} résultats cumulés pour les juridictions "
            f"demandées, au-delà de la limite absolue de {MAX_CUMULATIVE_RESULTS}. "
            "Aucun téléchargement n'a été lancé. Reformulez avec des guillemets pour une expression "
            "exacte, des mots juridiques choisis et les opérateurs ET/OU ; incluez si possible "
            "l'article de référence et bornez les dates à la version du texte applicable. Si les faits, "
            "la période ou le droit applicable restent incertains, posez d'abord des questions."
        )
    return reports


def _format_date(value: Any) -> str:
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value / 1000).strftime("%Y-%m-%d")
        except (OverflowError, OSError, ValueError):
            return ""
    text = str(value or "").strip()
    return text[:10] if text else ""


def _first_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, list):
            for item in value:
                if str(item or "").strip():
                    return str(item).strip()
        elif str(value or "").strip():
            return str(value).strip()
    return ""


def _decision_record(seed: Dict[str, Any], response: Dict[str, Any]) -> Dict[str, Any]:
    text = (response or {}).get("text") or {}
    body = str(text.get("texte") or "").strip()
    number = _first_text(text.get("numeroAffaire"), text.get("num"), text.get("numeroPublicationBulletin"))
    publication = _first_text(text.get("typePublicationBulletin"), text.get("publicationRecueil"))
    summary = _first_text(text.get("sommaire"), text.get("resume"), seed.get("analyse"))
    title = _first_text(text.get("titre"), text.get("titreLong"), seed.get("titre"), seed.get("id"))
    source_base = JURIDICTION_CONFIG[seed["juridiction_source"]]["link_base"]

    return {
        "id": seed["id"],
        "titre": title,
        "juridiction": _first_text(text.get("juridiction"), text.get("natureJuridiction")),
        "formation": _first_text(text.get("formation"), text.get("juridictionJudiciaire")),
        "date": _format_date(text.get("dateTexte")),
        "numero": number,
        "ecli": _first_text(text.get("ecli")),
        "solution": _first_text(text.get("solution"), text.get("nature")),
        "publication": publication,
        "sommaire": summary,
        "texte": body,
        "lien": f"{source_base}{seed['id']}",
        "requêtes": seed["requêtes"],
        "juridictions_recherche": seed["juridictions_recherche"],
        "rang_min": seed["rang_min"],
        "caracteres": len(body),
        "tokens_texte_estimes": estimate_tokens(body),
    }


def _fetch_one(client: Any, seed: Dict[str, Any], retries: int = 3) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    error = None
    for attempt in range(retries):
        try:
            response = client.get_decision_text(seed["id"])
            record = _decision_record(seed, response)
            if not record["texte"]:
                raise ValueError("texte intégral vide")
            return record, None
        except Exception as exc:  # best-effort : l'erreur est conservée dans le manifeste
            error = str(exc)
            if attempt + 1 < retries:
                time.sleep(0.25 * (2 ** attempt))
    return None, error or "erreur inconnue"


def _score_decision(record: Dict[str, Any], terms: List[str]) -> Dict[str, Any]:
    normalized = _normalize(" ".join([record.get("sommaire", ""), record.get("texte", "")]))
    occurrences = {}
    for term in terms:
        count = normalized.count(term)
        if count:
            occurrences[term] = count
    score = round(sum(1 + math.log2(count) for count in occurrences.values()), 3)
    record["score_lexical"] = score
    record["termes_trouves"] = occurrences
    return record


def _paragraphs(body: str) -> List[str]:
    return [re.sub(r"\s+", " ", part).strip() for part in re.split(r"\n\s*\n|\r?\n", body or "") if part.strip()]


def _relevant_extracts(record: Dict[str, Any], max_extracts: int = 3) -> List[Dict[str, Any]]:
    terms = list((record.get("termes_trouves") or {}).keys())
    extracts = []
    for index, paragraph in enumerate(_paragraphs(record.get("texte", "")), 1):
        normalized = _normalize(paragraph)
        matches = [term for term in terms if term in normalized]
        if matches:
            extracts.append((len(matches), index, paragraph, matches))
    extracts.sort(key=lambda item: (-item[0], item[1]))
    return [
        {"paragraphe": index, "termes": matches, "texte": paragraph[:800]}
        for _count, index, paragraph, matches in extracts[:max_extracts]
    ]


def _batch_decision_markdown(position: int, record: Dict[str, Any]) -> str:
    """Rend le texte intégral de chaque décision pour la revue modèle."""
    lines = [
        f"# {position}. {record['titre']}",
        "",
        f"- **Identifiant** : {record['id']}",
        f"- **Date** : {record.get('date', '')}",
        f"- **Numéro** : {record.get('numero', '')}",
        f"- **Solution** : {record.get('solution', '')}",
        f"- **Légifrance** : {record.get('lien', '')}",
        f"- **Texte intégral local** : {record.get('fichier', '')}",
        "",
        "## Sommaire officiel",
        "",
        record.get("sommaire") or "_Absent._",
        "",
        "## Texte intégral",
        "",
        record.get("texte") or "_Absent._",
    ]
    return "\n".join(lines).rstrip() + "\n"


def _decision_markdown(position: int, record: Dict[str, Any]) -> str:
    lines = [f"# {position}. {record['titre']}", ""]
    fields = [
        ("Identifiant", record.get("id")),
        ("Juridiction", record.get("juridiction")),
        ("Formation", record.get("formation")),
        ("Date", record.get("date")),
        ("Numéro", record.get("numero")),
        ("ECLI", record.get("ecli")),
        ("Solution", record.get("solution")),
        ("Publication", record.get("publication")),
        ("Légifrance", record.get("lien")),
        ("Tokens du texte estimés", record.get("tokens_texte_estimes")),
        ("Score lexical de contrôle", record.get("score_lexical")),
    ]
    for label, value in fields:
        if value not in (None, "", []):
            lines.append(f"- **{label}** : {value}")
    lines.extend(["", "## Sommaire officiel", "", record.get("sommaire") or "_Absent._", ""])
    lines.extend(["## Texte intégral", ""])
    for index, paragraph in enumerate(_paragraphs(record.get("texte", "")), 1):
        lines.append(f"[¶{index:04d}] {paragraph}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _batch_header(question: str) -> str:
    return f"""# Lot de cartographie jurisprudentielle exhaustive

## Question

{question}

## Consigne

Lire **chaque décision** ci-dessous et produire exactement une ligne JSON par
décision. Chaque décision est fournie avec son texte intégral ; ce n'est ni un
classement ni un top-k. Ne jamais créer d'identifiant ni de citation.
Juger la pertinence d'après les motifs propres du juge et le dispositif, jamais
d'après les seuls moyens, prétentions ou arguments des avocats. Le dispositif
commence généralement par `PAR CES MOTIFS` ou `DÉCIDE :` ; `MOYENS ANNEXES`
appartient aux parties. `solution` indique ce que le juge prononce.
`citation_exacte` reproduit littéralement un passage du juge qui justifie la
pertinence. Une décision non pertinente produit tout de même une fiche avec
`pertinent: false`, une solution factuelle et `citation_exacte: ""`.

Schéma minimal :

```json
{{"id":"JURITEXT…","pertinent":true,"solution":"…","citation_exacte":"citation littérale…"}}
```

## Décisions

"""


def _write_json(path: str, value: Any) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _write_jsonl(path: str, values: Iterable[Dict[str, Any]]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        for value in values:
            handle.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")


def _safe_title_component(value: str, max_length: int = 150) -> str:
    """Produit un titre lisible utilisable comme nom de fichier portable."""
    cleaned = re.sub(r'[\x00-\x1f<>:"/\\|?*]+', " ", str(value or ""))
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return cleaned[:max_length].rstrip(" .") or "Recherche jurisprudentielle"


def _research_output_title(question: str) -> str:
    return f"{datetime.now().strftime('%Y-%m-%d')} - {_safe_title_component(question)}"


def _research_report_path(folder: str, marker: Dict[str, Any]) -> str:
    title = _safe_title_component(
        str(marker.get("output_title") or os.path.basename(folder)),
        max_length=180,
    )
    return os.path.join(os.path.dirname(folder), f"{title}.md")


def _research_readme(question: str, report_path: str) -> str:
    return f"""# Reprendre cette recherche Légifrance

## Question

{question}

## Organisation

- `decisions/` : textes intégraux, un fichier Markdown par décision.
- `batches/` : lots à confier au modèle ; chaque décision doit être examinée.
- `cards/` : fiches JSONL brutes produites par le modèle.
- `cards-validated.jsonl` : toutes les fiches valides, y compris les non pertinentes, conservées pour l'audit.
- `metrics.json` et `validation-errors.json` : couverture et erreurs à corriger.
- `telemetry.json` : requêtes, volumes, échecs, limites et estimation des tokens.

## Reprendre le travail

1. Lire `batch-plan.json` et traiter chaque lot encore sans fichier correspondant dans `cards/`.
2. Produire exactement une fiche JSON par décision.
3. Valider et compiler avec :

```sh
python3 recompile_research.py .
```

4. Si la commande échoue, lire `remaining-work.md` et corriger uniquement les fiches signalées.
5. Relancer la commande jusqu'à obtenir `VALIDATION COMPLÈTE` et un code de sortie `0`.

Le rapport final est `{os.path.basename(report_path)}`. Il contient la couverture et un tableau des seules décisions pertinentes. Ne jamais supprimer les fiches non pertinentes de l'audit : elles prouvent que chaque décision a bien été examinée.
"""


def build_research_corpus(args: Dict[str, Any], client: Any = None) -> Dict[str, Any]:
    """Construit le corpus complet, ses lots et sa télémétrie."""
    client = client or legifrance_client
    question = re.sub(r"\s+", " ", str(args.get("question") or "")).strip()
    if not question:
        raise ValueError("`question` est requise et doit formuler la question de droit")
    query = _clean_query(args)
    jurisdictions = _clean_jurisdictions(args.get("juridictions"))
    target_tokens = min(
        max(5_000, int(args.get("batch_target_tokens") or DEFAULT_BATCH_TARGET_TOKENS)),
        HARD_BATCH_TARGET_TOKENS,
    )
    max_batch_decisions = min(
        max(1, int(args.get("batch_max_decisions") or DEFAULT_BATCH_MAX_DECISIONS)),
        HARD_BATCH_MAX_DECISIONS,
    )
    workers = min(max(1, int(args.get("fetch_workers") or DEFAULT_FETCH_WORKERS)), HARD_FETCH_WORKERS)
    date_debut = args.get("date_debut") or None
    date_fin = args.get("date_fin") or None

    preflight_reports = _preflight_cumulative_total(
        client, query, jurisdictions, date_debut, date_fin,
    )
    search_reports = []
    seeds: Dict[str, Dict[str, Any]] = {}
    for jurisdiction in jurisdictions:
        total = next(
            item["total_api"] for item in preflight_reports
            if item["juridiction"] == jurisdiction
        )
        if total == 0:
            search_reports.append({
                "query": query,
                "juridiction": jurisdiction,
                "total_api": 0,
                "total_api_connu": True,
                "collectes": 0,
                "tronquee": False,
                "appels_recherche": 0,
                "phase": "collecte",
            })
            continue
        results, report = _search_query(
            client, query, jurisdiction, date_debut, date_fin,
            total,
        )
        report["phase"] = "collecte"
        search_reports.append(report)
        if report["tronquee"]:
            raise ValueError(
                "La collecte Légifrance est incomplète après le contrôle préalable ; "
                "aucun téléchargement n'a été lancé. Réessayez avec une formulation plus précise."
            )
        for rank, result in enumerate(results, 1):
            text_id, title = _search_identity(result)
            if not text_id:
                continue
            seed = seeds.setdefault(text_id, {
                "id": text_id,
                "titre": title,
                "analyse": "",
                "requêtes": [query],
                "juridictions_recherche": [],
                "juridiction_source": jurisdiction,
                "rang_min": rank,
            })
            if jurisdiction not in seed["juridictions_recherche"]:
                seed["juridictions_recherche"].append(jurisdiction)
            seed["rang_min"] = min(seed["rang_min"], rank)

    # Initialise le jeton avant le parallélisme lorsque le client réel expose
    # cette méthode. Les clients de test n'en ont pas besoin.
    if hasattr(client, "_get_token"):
        client._get_token()

    records = []
    failures = []
    seed_values = list(seeds.values())
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(_fetch_one, client, seed): seed for seed in seed_values}
        for future in as_completed(futures):
            seed = futures[future]
            record, error = future.result()
            if record:
                records.append(record)
            else:
                failures.append({"id": seed["id"], "erreur": error})

    order = {seed["id"]: index for index, seed in enumerate(seed_values)}
    terms = _query_terms(question, query)
    records.sort(key=lambda record: order.get(record["id"], 10 ** 9))
    records = [_score_decision(record, terms) for record in records]
    for record in records:
        record["extraits_lexicaux"] = _relevant_extracts(record)

    default_root = os.path.join(os.path.expanduser("~"), "Downloads")
    root = os.path.abspath(args.get("output_dir") or default_root)
    output_title = _research_output_title(question)
    folder = os.path.join(root, output_title)
    report_path = os.path.join(root, f"{output_title}.md")
    if os.path.exists(folder) or os.path.exists(report_path):
        raise ValueError(
            f"une recherche portant déjà ce titre existe dans {root}; "
            "choisissez un autre output_dir ou déplacez le résultat existant"
        )
    decisions_dir = os.path.join(folder, "decisions")
    batches_dir = os.path.join(folder, "batches")
    cards_dir = os.path.join(folder, "cards")
    os.makedirs(decisions_dir, exist_ok=False)
    os.makedirs(batches_dir, exist_ok=False)
    os.makedirs(cards_dir, exist_ok=False)

    with open(os.path.join(folder, "README.md"), "w", encoding="utf-8") as handle:
        handle.write(_research_readme(question, report_path))
    shutil.copyfile(
        research_report_compiler.__file__,
        os.path.join(folder, "recompile_research.py"),
    )

    files = ["README.md", "recompile_research.py"]
    decision_paths = {}
    for position, record in enumerate(records, 1):
        name = f"{position:04d}-{slugify(record['titre'], max_length=70)}-{record['id']}.md"
        relative = os.path.join("decisions", name)
        with open(os.path.join(folder, relative), "w", encoding="utf-8") as handle:
            handle.write(_decision_markdown(position, record))
        files.append(relative)
        decision_paths[record["id"]] = relative
        record["fichier"] = relative

    # Chaque texte téléchargé est revu par le modèle. Le score lexical sert
    # uniquement à l'index de contrôle et ne retire aucune décision des lots.
    batches = []
    current_records = []
    current_parts = []
    header = _batch_header(question)
    current_tokens = estimate_tokens(header)

    def flush_batch() -> None:
        nonlocal current_records, current_parts, current_tokens
        if not current_records:
            return
        number = len(batches) + 1
        name = f"lot-{number:03d}.md"
        content = header + "\n\n".join(current_parts).rstrip() + "\n"
        relative = os.path.join("batches", name)
        with open(os.path.join(folder, relative), "w", encoding="utf-8") as handle:
            handle.write(content)
        files.append(relative)
        batches.append({
            "lot": number,
            "fichier": relative,
            "sortie_attendue": os.path.join("cards", f"lot-{number:03d}.jsonl"),
            "decisions": [record["id"] for record in current_records],
            "nombre_decisions": len(current_records),
            "caracteres": len(content),
            "tokens_entree_estimes": estimate_tokens(content),
        })
        current_records = []
        current_parts = []
        current_tokens = estimate_tokens(header)

    reviewed_records = records
    for position, record in enumerate(reviewed_records, 1):
        part = _batch_decision_markdown(position, record)
        part_tokens = estimate_tokens(part)
        if current_records and (
            current_tokens + part_tokens > target_tokens
            or len(current_records) >= max_batch_decisions
        ):
            flush_batch()
        current_records.append(record)
        current_parts.append(part)
        current_tokens += part_tokens
    flush_batch()

    ranked = sorted(records, key=lambda record: (-record["score_lexical"], record["rang_min"], record["id"]))
    index_lines = [
        "# Index exhaustif — recherche jurisprudentielle",
        "",
        f"- **Question** : {question}",
        f"- **Décisions identifiées (dédupliquées)** : {len(seeds)}",
        f"- **Décisions dont le texte intégral a été téléchargé et scanné** : {len(records)}",
        f"- **Décisions à revoir par modèle** : {len(reviewed_records)}",
        f"- **Échecs de téléchargement** : {len(failures)}",
        f"- **Lots de cartographie** : {len(batches)}",
        "- **Classement** : lexical, pour contrôle humain uniquement ; il ne modifie jamais les lots.",
        "",
        "| Rang contrôle | Score | Décision | Date | Solution | Fichier |",
        "| ---: | ---: | --- | --- | --- | --- |",
    ]
    for rank, record in enumerate(ranked, 1):
        title = str(record["titre"]).replace("|", "\\|")
        solution = str(record.get("solution") or "").replace("|", "\\|")
        index_lines.append(
            f"| {rank} | {record['score_lexical']} | {title} | {record.get('date', '')} | "
            f"{solution} | [{record['id']}]({record['fichier']}) |"
        )
    with open(os.path.join(folder, "index.md"), "w", encoding="utf-8") as handle:
        handle.write("\n".join(index_lines) + "\n")
    files.append("index.md")

    _write_jsonl(os.path.join(folder, "decisions.jsonl"), records)
    files.append("decisions.jsonl")
    _write_json(os.path.join(folder, "batch-plan.json"), batches)
    files.append("batch-plan.json")

    telemetry = {
        "methode": "corpus exhaustif fixe, sans embeddings ni top-k",
        "estimation_tokens": TOKEN_ESTIMATION_METHOD,
        "contrôle_préalable": preflight_reports,
        "total_resultats_cumules_avant_deduplication": sum(
            report["total_api"] for report in preflight_reports
        ),
        "requêtes": search_reports,
        "appels_api_recherche": sum(
            report["appels_recherche"] for report in [*preflight_reports, *search_reports]
        ),
        "decisions_identifiees_dedoublonnees": len(seeds),
        "decisions_texte_integral_telecharge": len(records),
        "decisions_scannees": len(records),
        "decisions_revue_modele": len(reviewed_records),
        "echecs_texte_integral": len(failures),
        "caracteres_texte_integral": sum(record["caracteres"] for record in records),
        "tokens_texte_integral_estimes": sum(record["tokens_texte_estimes"] for record in records),
        "lots": len(batches),
        "decisions_max_par_lot": max_batch_decisions,
        "tokens_entree_cartographie_estimes": sum(batch["tokens_entree_estimes"] for batch in batches),
        "tokens_modele_exacts": None,
        "tronquee": False,
        "echecs": failures,
    }
    _write_json(os.path.join(folder, "telemetry.json"), telemetry)
    files.append("telemetry.json")

    marker = {
        "kind": "legifrance-research",
        "question": question,
        "output_title": output_title,
        "report": report_path,
        "query": query,
        "juridictions": jurisdictions,
        "date_debut": date_debut,
        "date_fin": date_fin,
        "created": datetime.now().isoformat(timespec="seconds"),
        "identified": len(seeds),
        "downloaded": len(records),
        "scanned": len(records),
        "failed": len(failures),
        "truncated": False,
        "files": ["index.md", "decisions.jsonl", "batch-plan.json", "telemetry.json", *files],
    }
    _write_json(os.path.join(folder, MARKER_NAME), marker)

    return {
        "folder": folder,
        "report": report_path,
        "question": question,
        "query": query,
        "identified": len(seeds),
        "downloaded": len(records),
        "scanned": len(records),
        "failed": len(failures),
        "model_reviewed": len(reviewed_records),
        "batches": len(batches),
        "batch_plan": os.path.join(folder, "batch-plan.json"),
        "index": os.path.join(folder, "index.md"),
        "telemetry": os.path.join(folder, "telemetry.json"),
        "tokens_input_estimated": telemetry["tokens_entree_cartographie_estimes"],
        "token_estimation_method": TOKEN_ESTIMATION_METHOD,
        "truncated": False,
    }


def _load_jsonl(path: str) -> List[Dict[str, Any]]:
    values = []
    with open(path, "r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            try:
                value = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"JSON invalide {path}:{line_number} : {exc}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"Fiche non objet {path}:{line_number}")
            values.append(value)
    return values


def rebuild_research_mapping(args: Dict[str, Any]) -> Dict[str, Any]:
    """Recrée les lots d'un corpus existant sans rappeler l'API officielle.

    Les anciens lots et fiches sont déplacés dans ``mapping-archives`` : cette
    opération est donc réversible et ne supprime aucune analyse antérieure.
    """
    folder = os.path.abspath(str(args.get("folder") or ""))
    marker_path = os.path.join(folder, MARKER_NAME)
    if not folder or not os.path.isdir(folder):
        raise ValueError("folder de recherche introuvable")
    try:
        with open(marker_path, "r", encoding="utf-8") as handle:
            marker = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("marqueur de recherche introuvable ou invalide") from exc
    if marker.get("kind") != "legifrance-research":
        raise ValueError("le dossier n'est pas un corpus de recherche exhaustive")

    records = _load_jsonl(os.path.join(folder, "decisions.jsonl"))
    question = str(marker.get("question") or "").strip()
    target_tokens = min(
        max(5_000, int(args.get("batch_target_tokens") or DEFAULT_BATCH_TARGET_TOKENS)),
        HARD_BATCH_TARGET_TOKENS,
    )
    max_batch_decisions = min(
        max(1, int(args.get("batch_max_decisions") or DEFAULT_BATCH_MAX_DECISIONS)),
        HARD_BATCH_MAX_DECISIONS,
    )
    for record in records:
        # Les anciennes versions inscrivaient un filtre métier dans ces
        # champs. La reconstruction fait désormais repasser chaque décision
        # téléchargée dans les lots, quelle que soit sa terminologie.
        record.pop("candidat_cartographie_modele", None)
        record.pop("criteres_filtre_trouves", None)
        record.pop("contextes_cartographie", None)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    archive = os.path.join(folder, "mapping-archives", stamp)
    os.makedirs(archive, exist_ok=False)
    for name in ("batches", "cards"):
        path = os.path.join(folder, name)
        if os.path.exists(path):
            shutil.move(path, os.path.join(archive, name))
    for name in (
        "batch-plan.json", "cards-validated.jsonl", "metrics.json",
        "validation-errors.json", "remaining-work.md", "analysis-matrix.md",
    ):
        path = os.path.join(folder, name)
        if os.path.exists(path):
            shutil.move(path, os.path.join(archive, name))
    report_path = _research_report_path(folder, marker)
    if os.path.exists(report_path):
        shutil.move(report_path, os.path.join(archive, os.path.basename(report_path)))

    batches_dir = os.path.join(folder, "batches")
    cards_dir = os.path.join(folder, "cards")
    os.makedirs(batches_dir, exist_ok=False)
    os.makedirs(cards_dir, exist_ok=False)
    header = _batch_header(question)
    batches = []
    current_records = []
    current_parts = []
    current_tokens = estimate_tokens(header)

    def flush_batch() -> None:
        nonlocal current_records, current_parts, current_tokens
        if not current_records:
            return
        number = len(batches) + 1
        name = f"lot-{number:03d}.md"
        content = header + "\n\n".join(current_parts).rstrip() + "\n"
        with open(os.path.join(batches_dir, name), "w", encoding="utf-8") as handle:
            handle.write(content)
        batches.append({
            "lot": number,
            "fichier": os.path.join("batches", name),
            "sortie_attendue": os.path.join("cards", f"lot-{number:03d}.jsonl"),
            "decisions": [record["id"] for record in current_records],
            "nombre_decisions": len(current_records),
            "caracteres": len(content),
            "tokens_entree_estimes": estimate_tokens(content),
        })
        current_records = []
        current_parts = []
        current_tokens = estimate_tokens(header)

    reviewed_records = records
    for position, record in enumerate(reviewed_records, 1):
        part = _batch_decision_markdown(position, record)
        part_tokens = estimate_tokens(part)
        if current_records and (
            current_tokens + part_tokens > target_tokens
            or len(current_records) >= max_batch_decisions
        ):
            flush_batch()
        current_records.append(record)
        current_parts.append(part)
        current_tokens += part_tokens
    flush_batch()

    _write_jsonl(os.path.join(folder, "decisions.jsonl"), records)
    _write_json(os.path.join(folder, "batch-plan.json"), batches)
    with open(os.path.join(folder, "telemetry.json"), "r", encoding="utf-8") as handle:
        telemetry = json.load(handle)
    for key in (
        "decisions_candidates_modele",
        "decisions_fermees_statiquement",
        "filtre_candidature",
    ):
        telemetry.pop(key, None)
    telemetry.update({
        "methode": "corpus exhaustif fixe, revue de chaque décision téléchargée, sans RAG ni top-k",
        "decisions_revue_modele": len(reviewed_records),
        "lots": len(batches),
        "decisions_max_par_lot": max_batch_decisions,
        "tokens_entree_cartographie_estimes": sum(
            batch["tokens_entree_estimes"] for batch in batches
        ),
        "tokens_modele_exacts": None,
        "mapping_archive": archive,
        "mapping_reconstruit": datetime.now().isoformat(timespec="seconds"),
    })
    _write_json(os.path.join(folder, "telemetry.json"), telemetry)
    marker["mapping_archive"] = archive
    marker["mapping_reconstruit"] = telemetry["mapping_reconstruit"]
    marker_files = marker.get("files") if isinstance(marker.get("files"), list) else []
    for name in ("README.md", "recompile_research.py"):
        if name not in marker_files:
            marker_files.append(name)
    marker["files"] = marker_files
    with open(os.path.join(folder, "README.md"), "w", encoding="utf-8") as handle:
        handle.write(_research_readme(question, report_path))
    shutil.copyfile(
        research_report_compiler.__file__,
        os.path.join(folder, "recompile_research.py"),
    )
    _write_json(marker_path, marker)

    return {
        "folder": folder,
        "archive": archive,
        "scanned": len(records),
        "model_reviewed": len(reviewed_records),
        "batches": len(batches),
        "tokens_input_estimated": telemetry["tokens_entree_cartographie_estimes"],
        "token_estimation_method": TOKEN_ESTIMATION_METHOD,
    }
