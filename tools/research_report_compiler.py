#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Valide les fiches et compile le rapport d'un corpus Légifrance.

Ce fichier n'utilise que la bibliothèque standard afin de rester exécutable
une fois copié dans un dossier de corpus.
"""

import argparse
import json
import math
import os
import sys
from typing import Any, Dict, Iterable, List, Optional, Tuple


EXPECTED_TYPES = {
    "pertinent": bool,
    "solution": str,
    "citation_exacte": str,
}


def _load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"objet JSON attendu dans {path}")
    return value


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
                raise ValueError(f"objet JSON attendu dans {path}:{line_number}")
            values.append(value)
    return values


def _write_json(path: str, value: Any) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _write_jsonl(path: str, values: Iterable[Dict[str, Any]]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        for value in values:
            handle.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")


def _estimate_tokens(value: Any) -> int:
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return int(math.ceil(len(text) / 4))


def _schema_errors(card: Dict[str, Any], text_id: str) -> List[Dict[str, str]]:
    errors = []
    for field, expected_type in EXPECTED_TYPES.items():
        if not isinstance(card.get(field), expected_type):
            errors.append({
                "id": text_id,
                "champ": field,
                "raison": f"type attendu : {expected_type.__name__}",
            })
    return errors


def _card_files(folder: str) -> List[str]:
    cards_dir = os.path.join(folder, "cards")
    if not os.path.isdir(cards_dir):
        return []
    return [
        os.path.join(cards_dir, name)
        for name in sorted(os.listdir(cards_dir))
        if name.endswith(".jsonl")
    ]


def validate_cards(folder: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any], Dict[str, Any]]:
    """Contrôle la couverture, le schéma et les citations littérales."""
    decisions = _load_jsonl(os.path.join(folder, "decisions.jsonl"))
    decision_by_id = {str(record["id"]): record for record in decisions}
    paths = _card_files(folder)

    cards = []
    read_errors = []
    for path in paths:
        try:
            cards.extend(_load_jsonl(path))
        except (OSError, ValueError) as exc:
            read_errors.append(str(exc))

    seen = set()
    duplicates = []
    unknown = []
    schema_errors = []
    relevant_without_quote = []
    invalid_quotes = []
    valid_cards = []
    for card in cards:
        text_id = str(card.get("id") or "").strip()
        if not text_id or text_id not in decision_by_id:
            unknown.append(text_id or "<sans identifiant>")
            continue
        if text_id in seen:
            duplicates.append(text_id)
            continue
        seen.add(text_id)
        record = decision_by_id[text_id]
        current_schema_errors = _schema_errors(card, text_id)
        schema_errors.extend(current_schema_errors)
        quote = str(card.get("citation_exacte") or "").strip()
        position = str(record.get("texte") or "").find(quote) if quote else -1
        quote_valid = bool(quote) and position >= 0
        quote_invalid = bool(quote) and not quote_valid
        if quote_invalid:
            invalid_quotes.append({"id": text_id, "texte": quote[:160]})
        missing_quote = card.get("pertinent") is True and not quote_valid
        if missing_quote:
            relevant_without_quote.append(text_id)

        validated = dict(card)
        validated.update({
            "citation_exacte": quote if quote_valid else "",
            "position_citation": position if quote_valid else None,
            "citation_valide": quote_valid,
            "lien": record.get("lien", ""),
            "date": record.get("date", ""),
            "juridiction": record.get("juridiction", ""),
            "numero": record.get("numero", ""),
            "score_lexical": record.get("score_lexical", 0),
        })
        if not current_schema_errors and not quote_invalid and not missing_quote:
            valid_cards.append(validated)

    missing = sorted(set(decision_by_id) - seen)
    errors = {
        "fiches_manquantes": missing,
        "identifiants_inconnus": unknown,
        "doublons": duplicates,
        "erreurs_schema": schema_errors,
        "fiches_pertinentes_sans_citation": relevant_without_quote,
        "citations_invalides": invalid_quotes,
        "erreurs_lecture": read_errors,
    }
    telemetry = _load_json(os.path.join(folder, "telemetry.json"))
    metrics = {
        **telemetry,
        "fiches_recues": len(cards),
        "fiches_valides_uniques": len(valid_cards),
        "fiches_manquantes": len(missing),
        "identifiants_inconnus": len(unknown),
        "doublons": len(duplicates),
        "erreurs_schema": len(schema_errors),
        "fiches_pertinentes_sans_citation": len(relevant_without_quote),
        "citations_invalides": len(invalid_quotes),
        "tokens_sortie_fiches_estimes": sum(_estimate_tokens(card) for card in cards),
        "couverture_complete": not any(errors.values()),
    }
    _write_jsonl(os.path.join(folder, "cards-validated.jsonl"), valid_cards)
    _write_json(os.path.join(folder, "metrics.json"), metrics)
    _write_json(os.path.join(folder, "validation-errors.json"), errors)
    return valid_cards, metrics, errors


def _cell(value: Any) -> str:
    if isinstance(value, list):
        value = "; ".join(str(item) for item in value)
    text = str(value or "").replace("|", "\\|")
    return "<br>".join(part.strip() for part in text.splitlines() if part.strip())


def compile_report(
    folder: str,
    cards: List[Dict[str, Any]],
    metrics: Dict[str, Any],
    output_path: Optional[str] = None,
) -> str:
    """Transforme les fiches pertinentes validées en tableau Markdown."""
    relevant = [card for card in cards if card.get("pertinent") is True]
    relevant.sort(
        key=lambda card: (str(card.get("date") or ""), str(card.get("id") or "")),
        reverse=True,
    )
    output_path = os.path.abspath(output_path or f"{folder}.md")
    lines = [
        f"# {os.path.basename(folder)}", "", "## Couverture", "",
        f"- **Couverture complète** : {'oui' if metrics.get('couverture_complete') else 'non'}",
        f"- **Décisions scannées** : {metrics.get('decisions_scannees', 0)}",
        f"- **Fiches reçues** : {metrics.get('fiches_recues', 0)}",
        f"- **Fiches manquantes** : {metrics.get('fiches_manquantes', 0)}",
        f"- **Citations rejetées** : {metrics.get('citations_invalides', 0)}",
        f"- **Décisions pertinentes** : {len(relevant)}",
        "", "## Matrice des décisions pertinentes", "",
        "| Décision | Solution | Citation | Source |",
        "| --- | --- | --- | --- |",
    ]
    for card in relevant:
        identity = " — ".join(filter(None, [
            _cell(card.get("id")), _cell(card.get("juridiction")),
            _cell(card.get("date")), _cell(card.get("numero")),
        ]))
        lines.append("| " + " | ".join([
            identity, _cell(card.get("solution")),
            _cell(card.get("citation_exacte")), _cell(card.get("lien")),
        ]) + " |")
    if not relevant:
        lines.append("| _Aucune décision pertinente validée_ |  |  |  |")
    with open(output_path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines).rstrip() + "\n")
    return output_path


def _remaining_work(errors: Dict[str, Any], complete: bool) -> str:
    lines = ["# Travail restant pour le LLM", ""]
    if complete:
        return "\n".join(lines + ["Validation complète. Aucun travail restant.", ""])
    instructions = (
        ("Fiches manquantes à produire", errors["fiches_manquantes"]),
        ("Identifiants inconnus à corriger ou retirer", errors["identifiants_inconnus"]),
        ("Doublons à résoudre", errors["doublons"]),
        ("Fiches dont le schéma est à corriger", errors["erreurs_schema"]),
        ("Fiches pertinentes auxquelles ajouter une citation littérale", errors["fiches_pertinentes_sans_citation"]),
        ("Citations à remplacer par un passage littéral", errors["citations_invalides"]),
        ("Fichiers JSONL à réparer", errors["erreurs_lecture"]),
    )
    for heading, values in instructions:
        if not values:
            continue
        lines.extend([f"## {heading}", ""])
        for value in values:
            rendered = json.dumps(value, ensure_ascii=False) if isinstance(value, dict) else str(value)
            lines.append(f"- {rendered}")
        lines.append("")
    lines.extend([
        "Corriger uniquement les fiches signalées dans `cards/`, puis relancer :",
        "", "```sh", "python3 recompile_research.py .", "```", "",
    ])
    return "\n".join(lines)


def validate_and_compile(folder: str, output_path: Optional[str] = None) -> Dict[str, Any]:
    """Exécute toute la finalisation et rend un statut de type test."""
    folder = os.path.abspath(folder)
    cards, metrics, errors = validate_cards(folder)
    report = compile_report(folder, cards, metrics, output_path)
    remaining_path = os.path.join(folder, "remaining-work.md")
    with open(remaining_path, "w", encoding="utf-8") as handle:
        handle.write(_remaining_work(errors, bool(metrics["couverture_complete"])))
    return {
        "folder": folder,
        "report": report,
        "remaining_work": remaining_path,
        "coverage_complete": bool(metrics["couverture_complete"]),
        "cards": metrics["fiches_recues"],
        "valid_cards": metrics["fiches_valides_uniques"],
        "missing": metrics["fiches_manquantes"],
        "invalid_quotes": metrics["citations_invalides"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Valider les fiches et compiler le rapport Markdown Légifrance."
    )
    parser.add_argument("folder", nargs="?", default=".", help="dossier du corpus")
    parser.add_argument("--output", help="chemin Markdown de sortie")
    args = parser.parse_args()
    try:
        result = validate_and_compile(args.folder, args.output)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"❌ ERREUR DE VALIDATION : {exc}\n")
    if result["coverage_complete"]:
        print(f"✅ VALIDATION COMPLÈTE — {result['valid_cards']}/{result['cards']} fiches valides")
        print(f"Rapport : {result['report']}")
        raise SystemExit(0)
    print(
        f"❌ VALIDATION INCOMPLÈTE — {result['valid_cards']}/{result['cards']} fiches valides, "
        f"{result['missing']} manquante(s), {result['invalid_quotes']} citation(s) rejetée(s)",
        file=sys.stderr,
    )
    print(f"Travail restant : {result['remaining_work']}", file=sys.stderr)
    raise SystemExit(1)


if __name__ == "__main__":
    main()
