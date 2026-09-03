#/tools/handlers.py 
#! MCP SERVEUR LOCAL
"""Handlers pour les outils MCP"""

import json
import os
import unicodedata
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

from tools.session_manager import session_manager
from tools.case_manager import case_manager
from tools.legifrance_client import legifrance_client, est_date_absente, borne_haute_reelle
from tools.bodacc_client import bodacc_client
from tools.justice_lexicon import JusticeLexiconError, justice_lexicon_client
from tools.query_parser import parse_query
from tools.code_parser import parse_code_query
from tools.research_corpus import build_research_corpus
from tools.decision_history import (
    HistoriqueError,
    build_decision_history,
    render_markdown as render_historique,
)
from config.mcp_definitions import INITIALIZE_INSTRUCTIONS
LEGIFRANCE_BASE_URL = "https://www.legifrance.gouv.fr"

def create_response(text: str, resource: Dict = None, is_error: bool = False) -> Dict[str, Any]:
    """Crée une réponse MCP formatée"""
    content = [{"type": "text", "text": text}]
    if resource:
        content.append({"type": "resource", "resource": resource})
    return {"content": content, "isError": is_error}


# Contrat de recherche énoncé par INITIALIZE_INSTRUCTIONS : au-delà de ce
# nombre de résultats, la recherche est refusée pour manque de contexte.
LIMITE_RESULTATS = 500


def _refus_requete_trop_large(total: int) -> Dict[str, Any]:
    """Refuse une recherche dont le total dépasse le contrat des 500 résultats."""
    return create_response(
        f"<tool-use-error>\n"
        f"Requête trop large : {total} résultats trouvés (maximum {LIMITE_RESULTATS}).\n"
        f"La recherche est refusée pour manque de contexte : reformule-la en appliquant "
        f"les instructions de recherche.\n"
        f"\n"
        f"{INITIALIZE_INSTRUCTIONS}\n"
        f"</tool-use-error>",
        is_error=True,
    )


def _borne_pagination(args: Dict[str, Any], page_size_defaut: int, page_size_max: int):
    """
    Coerce et borne `page_size`/`page_number` d'après les défauts et maxima du
    schéma. Ne lève jamais : une valeur absente, `None` ou non convertible
    retombe sur le défaut du schéma. Rend `(page_size, page_number, refus)`
    où `refus` est `None` ou une réponse d'erreur quand la page demandée
    commence au-delà du contrat des 500 résultats.
    """
    def _coerce_int(value, default):
        if value is None:
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    page_size = _coerce_int(args.get("page_size"), page_size_defaut)
    page_number = _coerce_int(args.get("page_number"), 1)

    page_size = max(1, min(page_size, page_size_max))
    page_number = max(1, page_number)

    if (page_number - 1) * page_size >= LIMITE_RESULTATS:
        refus = create_response(
            f"<tool-use-error>\n"
            f"Page hors contrat : la page {page_number} de {page_size} résultats commence "
            f"au-delà du {LIMITE_RESULTATS}e résultat.\n"
            f"Une recherche acceptée rend au plus {LIMITE_RESULTATS} résultats : demande une "
            f"page comprise dans cette limite ou resserre la requête.\n"
            f"</tool-use-error>",
            is_error=True,
        )
        return page_size, page_number, refus

    return page_size, page_number, None


def _analysis_parts(value: Any) -> list[str]:
    """Déplie les éléments atomiques d'un champ d'analyse officiel."""
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, (list, tuple)):
        return [part for item in value for part in _analysis_parts(item)]
    if isinstance(value, dict):
        analysis_keys = ("resumePrincipal", "autreResume", "abstrats")
        if any(key in value for key in analysis_keys):
            return [
                part
                for key in analysis_keys
                if key in value
                for part in _analysis_parts(value.get(key))
            ]
        for key in ("texte", "text", "value", "contenu"):
            if key in value:
                return _analysis_parts(value[key])
    return []


def _analysis_text(value: Any) -> str:
    """Assemble sans coupe les contenus uniques d'une analyse officielle."""
    unique = []
    seen = set()
    for part in _analysis_parts(value):
        if part not in seen:
            seen.add(part)
            unique.append(part)
    return "\n".join(unique)


def _format_analysis(value: str) -> str:
    """Conserve la mise en évidence des occurrences dans le rendu Markdown."""
    return value.replace("<mark>", "**").replace("</mark>", "**").replace("<br/>", " ").strip()


def _search_result_analysis(result: Dict[str, Any]) -> str:
    """Repli sur les extraits de recherche, en conservant toutes leurs valeurs."""
    by_field = {"Abstrat": [], "Résumé principal": []}
    principal = _analysis_text(result.get("resumePrincipal"))
    if principal:
        by_field["Résumé principal"].append(principal)
    for section in result.get("sections", []) or []:
        for extract in section.get("extracts", []) or []:
            field_name = extract.get("searchFieldName", "")
            if field_name in by_field:
                value = _analysis_text(extract.get("values"))
                if value:
                    by_field[field_name].append(value)
    values = by_field["Abstrat"] or by_field["Résumé principal"]
    return _format_analysis(_analysis_text(values))


def _complete_decision_analysis(text_id: str, search_result: Dict[str, Any]) -> tuple[str, bool]:
    """Lit l'analyse sur la décision consultée, jamais dans un extrait tronqué."""
    if text_id:
        try:
            response = legifrance_client.get_decision_text(text_id)
            text = response.get("text", {}) if isinstance(response, dict) else {}
            for field in ("sommaire", "resumePrincipal", "resume", "abstrat"):
                analysis = _analysis_text(text.get(field))
                if analysis:
                    return _format_analysis(analysis), True
        except Exception:
            # La recherche reste exploitable ; le libellé du repli indique
            # explicitement que l'aperçu de recherche n'est pas le texte complet.
            pass
    return _search_result_analysis(search_result), False


def _append_decision_analysis(parts: list[str], text_id: str, result: Dict[str, Any]) -> None:
    analysis, complete = _complete_decision_analysis(text_id, result)
    if analysis:
        label = "Analyse" if complete else "Aperçu d’analyse (consultation complète indisponible)"
        parts.append(f"   {label}: {analysis}")
        return
    text = str(result.get("text") or "")
    if text:
        parts.append(f"   Extraits: {text.replace('<mark>', '**').replace('</mark>', '**')}")

def handle_tracking_bodacc(args: Dict[str, Any], user_id: str) -> Dict[str, Any]:
    """TOOL 4 : Vérification SIREN via BODACC"""
    siren = args.get("siren")
    type_recherche = args.get("type_recherche", "complet")
    
    if type_recherche == "procedures_collectives":
        result = bodacc_client.get_procedures_collectives(siren)
    elif type_recherche == "historique":
        result = bodacc_client.get_company_history(siren)
    else:
        result = bodacc_client.get_company_history(siren)
    
    if not result.get("success"):
        return create_response(result.get("error", "Erreur BODACC"), is_error=True)
    
    alertes = result.get("alertes", [])
    total = result.get("total_annonces", 0)
    
    summary = f"""Vérification SIREN {siren}

**Total annonces BODACC:** {total}"""
    
    if alertes:
        summary += "\n\n**⚠️ ALERTES:**"
        for alerte in alertes:
            summary += f"\n{alerte}"
    else:
        summary += "\n\n✅ Aucune alerte détectée"
    
    return create_response(
        summary,
        resource={
            "uri": f"bodacc://siren/{siren}",
            "mimeType": "application/json",
            "text": json.dumps(result, ensure_ascii=False, indent=2)
        }
    )


def handle_dictionnaire_juridique(args: Dict[str, Any], user_id: str) -> Dict[str, Any]:
    """Recherche un terme dans le lexique officiel publié sur justice.fr."""
    try:
        result = justice_lexicon_client.lookup(args.get("terme", ""))
    except (ValueError, JusticeLexiconError) as error:
        return create_response(
            f"<tool-use-error>\n{error}\n</tool-use-error>",
            is_error=True,
        )

    # Une correspondance exacte rend la définition seule. À défaut, les seuls
    # intitulés contenant tous les mots recherchés sont listés, jamais leurs
    # définitions.
    if result["definition"] is not None:
        return create_response(result["definition"])
    return create_response("\n".join(result["suggestions"]))


def handle_consulter_decision(args: Dict[str, Any], user_id: str) -> Dict[str, Any]:
    """
    Récupère le texte intégral d'une décision de jurisprudence.
    Retourne uniquement: nature, titre, visas, texte, decisionAttaquee
    """
    text_id = args.get("text_id") or args.get("id")

    if not text_id:
        return create_response("text_id requis", is_error=True)

    # Nettoyer l'ID
    text_id = text_id.strip()

    try:
        result = legifrance_client.get_decision_text(text_id)

        # Extraire uniquement les champs demandés
        text = result.get("text", {})

        nature = text.get("nature", "")
        titre = text.get("titre", "")
        visas = text.get("visas", "")
        texte_integral = text.get("texte", "")
        texte = texte_integral
        decision_attaquee = text.get("decisionAttaquee", {})

        # Tronquer le texte si "MOYENS ANNEXES" présent (Cour de cassation)
        if "MOYENS ANNEXES" in texte:
            moyens_index = texte.find("MOYENS ANNEXES")
            texte = texte[:moyens_index] + "..."

        # Construction de la réponse synthétique
        summary_parts = [
            f"DÉCISION: {titre}",
            f"",
            f"Nature: {nature}",
        ]

        # Visas (si présents)
        if visas:
            summary_parts.append(f"")
            summary_parts.append(f"VISAS:")
            summary_parts.append(visas)

        # Décision attaquée (si présente). La date à 2999-01-01 (ou son
        # équivalent en millisecondes) est la sentinelle Légifrance d'absence
        # de date : elle ne doit jamais être affichée comme une date réelle.
        if decision_attaquee:
            formation = decision_attaquee.get("formation", "")
            date_da = decision_attaquee.get("date", "")
            date_da_reelle = not est_date_absente(date_da)
            if formation or date_da_reelle:
                summary_parts.append(f"")
                summary_parts.append(f"Décision attaquée: {formation}")
                if date_da_reelle:
                    from datetime import datetime
                    date_str = datetime.fromtimestamp(date_da / 1000).strftime("%d/%m/%Y")
                    summary_parts.append(f"Date: {date_str}")

        # Texte intégral
        summary_parts.append(f"")
        summary_parts.append(f"{'='*80}")
        summary_parts.append(f"TEXTE INTÉGRAL:")
        summary_parts.append(f"{'='*80}")
        summary_parts.append(f"")
        summary_parts.append(texte)
        summary_parts.append(f"")
        summary_parts.append(f"Lien: {LEGIFRANCE_BASE_URL}/juri/id/{text_id}")

        summary = "\n".join(summary_parts)

        # Compter les tokens approximatifs du texte officiel complet. La
        # branche longue doit rester fidèle même si l'affichage synthétique a
        # écarté les moyens annexes.
        estimated_tokens = len(texte_integral) // 4

        # Une ressource MCP embarquée est sérialisable et lisible directement
        # par le client. Aucun fichier local n'est annoncé ni créé à l'insu de
        # l'appelant.
        if estimated_tokens > 25000:
            short_summary = "\n".join([
                f"DÉCISION: {titre}",
                f"",
                f"⚠️ **Décision trop longue** (≈ {estimated_tokens:,} tokens)".replace(',', ' '),
                f"",
                f"Nature: {nature}",
                f"Lien: {LEGIFRANCE_BASE_URL}/juri/id/{text_id}",
                f"",
                "Le texte intégral est joint comme ressource MCP."
            ])

            return create_response(
                short_summary,
                resource={
                    "uri": f"legifrance://jurisprudence/{text_id}/texte-integral",
                    "mimeType": "text/plain; charset=utf-8",
                    "text": texte_integral,
                }
            )

        return create_response(summary)

    except Exception as e:
        return create_response(
            f"❌ **Erreur consultation décision**\n\n"
            f"ID: {text_id}\n"
            f"Erreur: {str(e)}",
            is_error=True
        )

def handle_consulter_article(args: Dict[str, Any], user_id: str) -> Dict[str, Any]:
    """
    Récupère le contenu complet d'un article de code
    """
    article_id = args.get("article_id") or args.get("id")

    if not article_id:
        return create_response("article_id requis", is_error=True)

    article_id = article_id.strip()

    try:
        result = legifrance_client.get_article(article_id)

        # Extraction des informations
        article = result.get("article", {})

        # Informations essentielles
        num = article.get("num", "Article")
        texte = article.get("texte", "")

        # Dates (convertir millisecondes en format lisible)
        date_debut_ms = article.get("dateDebut", 0)
        date_fin_ms = article.get("dateFin", 0)

        from datetime import datetime
        if not est_date_absente(date_debut_ms):
            date_debut_str = datetime.fromtimestamp(date_debut_ms / 1000).strftime("%Y-%m-%d")
        else:
            date_debut_str = "?"

        if not est_date_absente(date_fin_ms):
            date_fin_str = datetime.fromtimestamp(date_fin_ms / 1000).strftime("%Y-%m-%d")
        else:
            date_fin_str = "en vigueur"

        # Section
        section_titre = article.get("sectionParentTitre", "")

        # Obtenir le nom du code depuis le contexte
        context = article.get("context", {})
        titre_txt = context.get("titreTxt", [])
        code_nom = titre_txt[0].get("titre", "") if titre_txt else ""

        # Construction de la réponse simplifiée
        summary_parts = [
            f"**{num}**",
            ""
        ]

        if code_nom:
            summary_parts.append(f"Code: {code_nom}")

        if section_titre:
            summary_parts.append(f"Section: {section_titre}")

        summary_parts.extend([
            f"Validité: {date_debut_str} → {date_fin_str}",
            f"Identifiant: {article_id}",
            f"Lien: {LEGIFRANCE_BASE_URL}/codes/article_lc/{article_id}",
            "",
            texte if texte else "_Texte non disponible_"
        ])

        summary = "\n".join(summary_parts)

        return create_response(summary)

    except Exception as e:
        return create_response(
            f"<tool-use-error>\n"
            f"Erreur consultation article\n"
            f"ID: {article_id}\n"
            f"Erreur: {str(e)}\n"
            f"</tool-use-error>",
            is_error=True
        )

# ============================================================================
# NOUVEAUX HANDLERS - RECHERCHE JURISPRUDENCE OPTIMISÉE
# ============================================================================

# Matières juridiques exposées par les outils de recherche Cour de cassation,
# mappées sur la facette officielle CASSATION_FORMATION du fonds JURI. Les
# formations transversales (assemblée plénière, chambre mixte, chambres
# réunies, avis) restent jointes à chaque matière : elles statuent sur toutes.
FORMATIONS_TRANSVERSALES = [
    "ASSEMBLEE_PLENIERE",
    "CHAMBRE_MIXTE",
    "CHAMBRES_REUNIES",
    "AVIS",
]

MATIERES_CASSATION = {
    "CIVIL": ["CHAMBRE_CIVILE_1", "CHAMBRE_CIVILE_2", "CHAMBRE_CIVILE_3", "CHAMBRE_CIVILE"],
    "COMMERCIAL": ["CHAMBRE_COMMERCIALE"],
    "PENAL": ["CHAMBRE_CRIMINELLE"],
    "SOCIAL": ["CHAMBRE_SOCIALE"],
}


def formations_cassation(matiere):
    """
    Normalise l'argument `matiere` et rend (matières retenues, formations API).

    Le filtre est obligatoire : sans lui, une recherche renvoie les décisions
    de toutes les chambres, y compris la chambre criminelle sur une question
    purement civile ou commerciale. `TOUTES` n'est donc plus accepté : pour
    couvrir l'ensemble des chambres, il faut énumérer les quatre matières.
    """
    if matiere is None:
        demandees = []
    elif isinstance(matiere, str):
        demandees = [m.strip() for m in matiere.split(",")]
    elif isinstance(matiere, (list, tuple)):
        demandees = [str(m).strip() for m in matiere]
    else:
        demandees = []

    demandees = [m.upper() for m in demandees if m]
    connues = ", ".join(MATIERES_CASSATION)

    if not demandees:
        raise ValueError(
            "Filtre `matiere` obligatoire : indiquez au moins une matière parmi "
            f"{connues}.\n"
            "Sans ce filtre, la recherche renvoie toutes les chambres, y compris "
            "la chambre criminelle sur une question civile ou commerciale.\n"
            "Pour couvrir volontairement toutes les chambres, énumérez les "
            "quatre matières."
        )

    inconnues = [m for m in demandees if m not in MATIERES_CASSATION]
    if inconnues:
        raise ValueError(
            f"Matière(s) inconnue(s) : {', '.join(inconnues)}. "
            f"Valeurs acceptées : {connues}."
        )

    retenues = []
    formations = []
    for m in demandees:
        if m in retenues:
            continue
        retenues.append(m)
        for formation in MATIERES_CASSATION[m]:
            if formation not in formations:
                formations.append(formation)
    formations.extend(FORMATIONS_TRANSVERSALES)
    return retenues, formations


def handle_search_cour_cassation(args: Dict[str, Any], user_id: str) -> Dict[str, Any]:
    """Recherche Cour de cassation avec parsing intelligent de la query"""

    query = args.get("query", "").strip()

    # Parser la query pour extraire opérateurs et termes
    operateur_query, type_recherche, criteres_parsed = parse_query(query)
    type_champ = "ALL"

    # Dates par défaut : 5 ans
    date_fin = args.get("date_fin")
    date_debut = args.get("date_debut")
    if not date_fin:
        date_fin = datetime.now().strftime("%Y-%m-%d")
    if not date_debut:
        date_debut = (datetime.now() - timedelta(days=5*365)).strftime("%Y-%m-%d")
    # Une borne haute à la sentinelle (2999-01-01) viderait silencieusement le
    # résultat ; on la ramène à la dernière date réelle exploitable pour que
    # le filtre DATE_DECISION et l'affichage « Période: » montrent la même
    # borne, celle réellement envoyée à l'API.
    date_fin = borne_haute_reelle(date_fin)

    # Pagination et tri
    sort = "PERTINENCE"  # Fixé sur PERTINENCE
    page_size, page_number, refus_pagination = _borne_pagination(args, 10, 100)
    if refus_pagination is not None:
        return refus_pagination

    # Construction des filtres
    filtres = [
        {
            "facette": "JURIDICTION_JUDICIAIRE",
            "valeurs": ["Cour de cassation"]
        },
        {
            "facette": "DATE_DECISION",
            "dates": {
                "start": date_debut,
                "end": date_fin
            }
        }
    ]

    # Filtre MATIERE (obligatoire) → formations Cour de cassation
    try:
        matieres, formations_api = formations_cassation(args.get("matiere"))
    except ValueError as erreur:
        return create_response(
            f"<tool-use-error>\n{erreur}\n</tool-use-error>",
            is_error=True
        )
    filtres.append({
        "facette": "CASSATION_FORMATION",
        "valeurs": formations_api
    })

    # Filtre PUBLICATION
    publication = args.get("CASSATION_TYPE_PUBLICATION_BULLETIN", "TOUS")
    if publication != "TOUS":
        valeur_pub = "T" if publication == "PUBLIE" else "F"
        filtres.append({
            "facette": "CASSATION_TYPE_PUBLICATION_BULLETIN",
            "valeurs": [valeur_pub]
        })

    try:
        # Appel API avec critères parsés
        # On passe directement les critères au lieu de laisser legifrance_client splitter la query
        result = legifrance_client.search_with_criteres(
            fond="JURI",
            criteres=criteres_parsed,
            operateur=operateur_query,
            filtres=filtres,
            type_champ=type_champ,
            page_number=page_number,
            page_size=page_size,
            sort=sort
        )

        # Construction du résumé
        total = result.get("totalResultNumber", 0)
        resultats = result.get("results", [])

        # Vérifier si la requête est trop large (> 500 résultats)
        if total > LIMITE_RESULTATS:
            return _refus_requete_trop_large(total)

        matiere_str = ", ".join(matieres)

        summary_parts = [
            f"**🏛️ COUR DE CASSATION**",
            f"",
            f"**Requête:** {query}",
            f"**Matière:** {matiere_str}",
            f"**Période:** {date_debut} → {date_fin}",
            f"**Total:** {total:,} décisions".replace(',', ' '),
            f"**Affichées:** {len(resultats)} résultats",
            f""
        ]

        if publication != "TOUS":
            summary_parts.append(f"**Publication:** {publication}")

        summary_parts.append("")
        summary_parts.append("═" * 80)
        summary_parts.append("")

        # Formater les résultats
        for i, r in enumerate(resultats, 1):
            titles = r.get("titles", [])
            if titles:
                titre = titles[0].get("title", "")
                juri_id = titles[0].get("id", "")
            else:
                titre = "Sans titre"
                juri_id = ""

            # Titre de la décision
            summary_parts.append(f"{i}. {titre}")

            # Lien Légifrance
            if juri_id:
                summary_parts.append(f"   Lien: https://www.legifrance.gouv.fr/juri/id/{juri_id}")

            # L'analyse complète vient de la consultation de la décision. Les
            # sections de recherche ne servent ici qu'aux articles visés.
            _append_decision_analysis(summary_parts, juri_id, r)
            sections = r.get("sections", [])
            articles_vises = []

            for section in sections:
                extracts = section.get("extracts", [])
                for extract in extracts:
                    field_name = extract.get("searchFieldName", "")
                    values = extract.get("values", [])

                    if field_name == "Texte appliqué" and values:
                        for val in values:
                            clean = val.replace("<mark>", "").replace("</mark>", "").replace("[...]", "").strip()
                            if clean and clean not in articles_vises:
                                articles_vises.append(clean)

            # Afficher les articles visés
            if articles_vises:
                summary_parts.append(f"   Articles visés: {', '.join(articles_vises[:3])}")
                if len(articles_vises) > 3:
                    summary_parts.append(f"   ... et {len(articles_vises) - 3} autre(s)")

            summary_parts.append("")

        summary = "\n".join(summary_parts)

        return create_response(summary)

    except Exception as e:
        return create_response(
            f"❌ **Erreur recherche Cour de cassation**\n\n"
            f"Requête: {query}\n"
            f"Erreur: {str(e)}",
            is_error=True
        )


def handle_search_cour_appel(args: Dict[str, Any], user_id: str) -> Dict[str, Any]:
    """Recherche Cours d'appel avec parsing intelligent de la query"""

    query = args.get("query", "").strip()

    # Parser la query
    operateur_query, type_recherche, criteres_parsed = parse_query(query)
    type_champ = "ALL"

    # Dates par défaut : 3 ans (volume plus élevé)
    date_fin = args.get("date_fin")
    date_debut = args.get("date_debut")
    if not date_fin:
        date_fin = datetime.now().strftime("%Y-%m-%d")
    if not date_debut:
        date_debut = (datetime.now() - timedelta(days=3*365)).strftime("%Y-%m-%d")
    date_fin = borne_haute_reelle(date_fin)

    sort = args.get("sort", "DATE_DESC")
    page_size, page_number, refus_pagination = _borne_pagination(args, 15, 100)
    if refus_pagination is not None:
        return refus_pagination

    # Construction des filtres
    filtres = [
        {
            "facette": "JURIDICTION_JUDICIAIRE",
            "valeurs": ["Juridictions d'appel"]
        },
        {
            "facette": "DATE_DECISION",
            "dates": {
                "start": date_debut,
                "end": date_fin
            }
        }
    ]

    # Filtre APPEL_SIEGE_APPEL
    sieges = args.get("APPEL_SIEGE_APPEL", [])
    if sieges:
        filtres.append({
            "facette": "APPEL_SIEGE_APPEL",
            "valeurs": sieges
        })

    try:
        result = legifrance_client.search_with_criteres(
            fond="JURI",
            criteres=criteres_parsed,
            operateur=operateur_query,
            filtres=filtres,
            type_champ=type_champ,
            page_number=page_number,
            page_size=page_size,
            sort=sort
        )

        total = result.get("totalResultNumber", 0)
        resultats = result.get("results", [])

        # Vérifier si la requête est trop large (> 500 résultats)
        if total > LIMITE_RESULTATS:
            return _refus_requete_trop_large(total)

        sieges_str = ", ".join(sieges) if sieges else "TOUTES"

        summary_parts = [
            f"**⚖️ COURS D'APPEL**",
            f"",
            f"**Requête:** {query}",
            f"**Cour(s):** {sieges_str}",
            f"**Période:** {date_debut} → {date_fin}",
            f"**Total:** {total:,} décisions".replace(',', ' '),
            f"**Affichées:** {len(resultats)}",
            f"",
            "═" * 80,
            ""
        ]

        for i, r in enumerate(resultats, 1):
            titles = r.get("titles", [])
            if titles:
                titre = titles[0].get("title", "")
                juri_id = titles[0].get("id", "")
            else:
                titre = "Sans titre"
                juri_id = ""

            # Titre de la décision
            summary_parts.append(f"{i}. {titre}")

            # Lien Légifrance
            if juri_id:
                summary_parts.append(f"   Lien: https://www.legifrance.gouv.fr/juri/id/{juri_id}")

            _append_decision_analysis(summary_parts, juri_id, r)
            sections = r.get("sections", [])
            articles_vises = []

            for section in sections:
                extracts = section.get("extracts", [])
                for extract in extracts:
                    field_name = extract.get("searchFieldName", "")
                    values = extract.get("values", [])

                    if field_name == "Texte appliqué" and values:
                        for val in values:
                            clean = val.replace("<mark>", "").replace("</mark>", "").replace("[...]", "").strip()
                            if clean and clean not in articles_vises:
                                articles_vises.append(clean)

            # Afficher les articles visés
            if articles_vises:
                summary_parts.append(f"   Articles visés: {', '.join(articles_vises[:3])}")
                if len(articles_vises) > 3:
                    summary_parts.append(f"   ... et {len(articles_vises) - 3} autre(s)")

            summary_parts.append("")

        summary = "\n".join(summary_parts)

        return create_response(summary)

    except Exception as e:
        return create_response(
            f"❌ **Erreur recherche Cours d'appel**\n\n"
            f"Erreur: {str(e)}",
            is_error=True
        )


def handle_search_conseil_etat(args: Dict[str, Any], user_id: str) -> Dict[str, Any]:
    """Recherche Conseil d'État avec parsing intelligent de la query"""

    query = args.get("query", "").strip()

    # Parser la query pour extraire opérateurs et termes
    operateur_query, type_recherche, criteres_parsed = parse_query(query)
    type_champ = "ALL"

    # Dates par défaut : 5 ans
    date_fin = args.get("date_fin")
    date_debut = args.get("date_debut")
    if not date_fin:
        date_fin = datetime.now().strftime("%Y-%m-%d")
    if not date_debut:
        date_debut = (datetime.now() - timedelta(days=5*365)).strftime("%Y-%m-%d")
    date_fin = borne_haute_reelle(date_fin)

    # Pagination et tri
    sort = "PERTINENCE"
    page_size, page_number, refus_pagination = _borne_pagination(args, 10, 100)
    if refus_pagination is not None:
        return refus_pagination

    # Construction des filtres
    filtres = [
        {
            "facette": "DATE_DECISION",
            "dates": {
                "start": date_debut,
                "end": date_fin
            }
        },
        # JURIDICTION_NATURE est une facette hiérarchique du fonds CETAT : la
        # forme plate {"facette": "JURIDICTION_NATURE", "valeurs": [...]}
        # rend HTTP 500, il faut impérativement la clé multiValeurs (mesure
        # du 2026-09-02, voir docs/facettes-officielles-dila.md). Une liste
        # fille vide sélectionne tout le parent CONSEIL_ETAT.
        {
            "facette": "JURIDICTION_NATURE",
            "valeurs": ["CONSEIL_ETAT"],
            "multiValeurs": {"CONSEIL_ETAT": []}
        }
    ]

    # Filtre PUBLICATION_RECUEIL
    publication = args.get("PUBLICATION_RECUEIL", "TOUS")
    if publication != "TOUS":
        valeur_pub = "PUBLIE" if publication == "PUBLIE" else "NON_PUBLIE"
        filtres.append({
            "facette": "PUBLICATION_RECUEIL",
            "valeurs": [valeur_pub]
        })

    try:
        result = legifrance_client.search_with_criteres(
            fond="CETAT",
            criteres=criteres_parsed,
            operateur=operateur_query,
            filtres=filtres,
            type_champ=type_champ,
            page_number=page_number,
            page_size=page_size,
            sort=sort
        )
        resultats = result.get("results", []) or []
        reported_total = result.get("totalResultNumber")
        try:
            total = int(reported_total) if reported_total is not None else None
        except (TypeError, ValueError):
            total = None

        if total is not None and total > LIMITE_RESULTATS:
            return _refus_requete_trop_large(total)

        summary_parts = [
            f"**⚖️ CONSEIL D'ÉTAT**",
            f"",
            f"**Requête:** {query}",
            f"**Période:** {date_debut} → {date_fin}",
            f"**Page:** {page_number} — {len(resultats)} décision(s) affichée(s)",
            f""
        ]

        if total is not None:
            summary_parts.append(
                f"**Total rendu par l'API:** {total:,} décisions".replace(',', ' ')
            )

        if publication != "TOUS":
            summary_parts.append(f"**Publication:** {publication}")

        summary_parts.append("")
        summary_parts.append("═" * 80)
        summary_parts.append("")

        # Formater les résultats
        for i, r in enumerate(resultats, 1):
            titles = r.get("titles", [])
            if titles:
                titre = titles[0].get("title", "")
                juri_id = titles[0].get("id", "")
            else:
                titre = "Sans titre"
                juri_id = ""

            summary_parts.append(f"**{i}. {titre}**")
            summary_parts.append(f"   ID: {juri_id}")

            # Lien Légifrance
            if juri_id:
                summary_parts.append(f"   Lien: {LEGIFRANCE_BASE_URL}/cetat/id/{juri_id}")

            _append_decision_analysis(summary_parts, juri_id, r)

            summary_parts.append("")

        summary = "\n".join(summary_parts)

        return create_response(summary)

    except Exception as e:
        return create_response(
            f"<tool-use-error>\n"
            f"Erreur recherche Conseil d'État\n"
            f"Requête: {query}\n"
            f"Erreur: {str(e)}\n"
            f"</tool-use-error>",
            is_error=True
        )


def handle_search_caa(args: Dict[str, Any], user_id: str) -> Dict[str, Any]:
    """Recherche CAA avec parsing intelligent de la query"""

    query = args.get("query", "").strip()

    # Parser la query pour extraire opérateurs et termes
    operateur_query, type_recherche, criteres_parsed = parse_query(query)
    type_champ = "ALL"

    # Dates par défaut : 3 ans
    date_fin = args.get("date_fin")
    date_debut = args.get("date_debut")
    if not date_fin:
        date_fin = datetime.now().strftime("%Y-%m-%d")
    if not date_debut:
        date_debut = (datetime.now() - timedelta(days=3*365)).strftime("%Y-%m-%d")
    date_fin = borne_haute_reelle(date_fin)

    # Pagination et tri
    sort = "PERTINENCE"
    page_size, page_number, refus_pagination = _borne_pagination(args, 15, 100)
    if refus_pagination is not None:
        return refus_pagination

    # Construction des filtres
    filtres = [
        {
            "facette": "DATE_DECISION",
            "dates": {
                "start": date_debut,
                "end": date_fin
            }
        }
    ]

    # Filtre PUBLICATION_RECUEIL
    publication = args.get("PUBLICATION_RECUEIL", "TOUS")
    if publication != "TOUS":
        valeur_pub = "PUBLIE" if publication == "PUBLIE" else "NON_PUBLIE"
        filtres.append({
            "facette": "PUBLICATION_RECUEIL",
            "valeurs": [valeur_pub]
        })

    # Filtre CAA_VILLE
    villes = args.get("CAA_VILLE", [])

    # La facette JURIDICTION_NATURE du fonds CETAT est hiérarchique : la
    # forme plate {"facette": "JURIDICTION_NATURE", "valeurs": ["COURS_APPEL"]}
    # rend HTTP 500, il faut impérativement la clé multiValeurs pour préciser
    # les villes filles. Une liste vide sélectionne toutes les CAA. Ce filtre
    # serveur remplace le tri côté client sur le titre, qui plafonnait le
    # nombre de décisions atteignables à la taille du parcours.
    filtres.append({
        "facette": "JURIDICTION_NATURE",
        "valeurs": ["COURS_APPEL"],
        "multiValeurs": {"COURS_APPEL": list(villes)}
    })

    try:
        result = legifrance_client.search_with_criteres(
            fond="CETAT",
            criteres=criteres_parsed,
            operateur=operateur_query,
            filtres=filtres,
            type_champ=type_champ,
            page_number=page_number,
            page_size=page_size,
            sort=sort
        )
        resultats = result.get("results", []) or []
        reported_total = result.get("totalResultNumber")
        try:
            total_api = int(reported_total) if reported_total is not None else None
        except (TypeError, ValueError):
            total_api = None

        if total_api is not None and total_api > LIMITE_RESULTATS:
            return _refus_requete_trop_large(total_api)

        villes_str = ", ".join(villes) if villes else "TOUTES"

        summary_parts = [
            f"**⚖️ COURS ADMINISTRATIVES D'APPEL**",
            f"",
            f"**Requête:** {query}",
            f"**Ville(s):** {villes_str}",
            f"**Période:** {date_debut} → {date_fin}",
            f"**Page:** {page_number} — {len(resultats)} décision(s) affichée(s)",
            f""
        ]

        if total_api is not None:
            summary_parts.append(
                f"**Total rendu par l'API:** {total_api:,} décisions".replace(',', ' ')
            )

        if publication != "TOUS":
            summary_parts.append(f"**Publication:** {publication}")

        summary_parts.append("")
        summary_parts.append("═" * 80)
        summary_parts.append("")

        # Formater les résultats
        for i, r in enumerate(resultats, 1):
            titles = r.get("titles", [])
            if titles:
                titre = titles[0].get("title", "")
                juri_id = titles[0].get("id", "")
            else:
                titre = "Sans titre"
                juri_id = ""

            summary_parts.append(f"**{i}. {titre}**")
            summary_parts.append(f"   ID: {juri_id}")

            # Lien Légifrance
            if juri_id:
                summary_parts.append(f"   Lien: {LEGIFRANCE_BASE_URL}/cetat/id/{juri_id}")

            _append_decision_analysis(summary_parts, juri_id, r)

            summary_parts.append("")

        summary = "\n".join(summary_parts)

        return create_response(summary)

    except Exception as e:
        return create_response(
            f"<tool-use-error>\n"
            f"Erreur recherche CAA\n"
            f"Requête: {query}\n"
            f"Erreur: {str(e)}\n"
            f"</tool-use-error>",
            is_error=True
        )


FAMILLES_PREMIER_DEGRE = {
    "TRIBUNAL_JUDICIAIRE": ["tribunal judiciaire"],
    "TRIBUNAL_GRANDE_INSTANCE": ["tribunal de grande instance"],
    "TRIBUNAL_INSTANCE": ["tribunal d'instance"],
    "TRIBUNAL_COMMERCE": ["tribunal de commerce"],
    "CONSEIL_PRUDHOMMES": ["conseil de prud'hommes", "conseil des prud'hommes"],
    "TRIBUNAL_CORRECTIONNEL": ["tribunal correctionnel"],
    "TRIBUNAL_SECURITE_SOCIALE": [
        "tribunal des affaires de securite sociale",
        "trib. des affaires de securite sociale",
    ],
    "TRIBUNAL_BAUX_RURAUX": ["tribunal paritaire des baux ruraux"],
    "JURIDICTION_PROXIMITE": ["juridiction de proximite", "juge de proximite"],
    "OUTRE_MER": [
        "tribunal de premiere instance",
        "tribunal superieur d'appel",
        "chambre de l'application des peines",
    ],
    "TRIBUNAL_CONFLITS": ["tribunal_conflit", "tribunal des conflits"],
}


def _sans_accents(texte):
    """Minuscule sans accents, pour comparer les libelles de la facette."""
    decompose = unicodedata.normalize("NFD", texte.lower())
    return "".join(c for c in decompose if unicodedata.category(c) != "Mn")


def familles_premier_degre(argument):
    """
    Normalise l'argument `PREMIER_DEGRE_TYPE_JURIDICTION` et rend la liste des
    familles demandees. Leve ValueError si le filtre est absent ou inconnu.

    En premiere instance, la matiere est portee par le nom de la juridiction :
    sans ce filtre, une recherche sociale remonte du correctionnel et du
    commercial. Le filtre est donc obligatoire, comme la matiere en cassation.
    """
    if argument is None:
        demandees = []
    elif isinstance(argument, str):
        demandees = [argument]
    elif isinstance(argument, (list, tuple)):
        demandees = [str(a) for a in argument]
    else:
        demandees = []

    demandees = [a.strip().upper() for a in demandees if str(a).strip()]
    connues = ", ".join(FAMILLES_PREMIER_DEGRE)

    if not demandees:
        raise ValueError(
            "Filtre `PREMIER_DEGRE_TYPE_JURIDICTION` obligatoire : indiquez au "
            f"moins une famille parmi {connues}.\n"
            "En premiere instance, la matiere est portee par le nom de la "
            "juridiction : sans ce filtre, la recherche melange prud'hommes, "
            "correctionnel et commerce."
        )

    inconnues = [a for a in demandees if a not in FAMILLES_PREMIER_DEGRE]
    if inconnues:
        raise ValueError(
            f"Famille(s) inconnue(s) : {', '.join(inconnues)}. "
            f"Valeurs acceptees : {connues}."
        )

    retenues = []
    for a in demandees:
        if a not in retenues:
            retenues.append(a)
    return retenues


def valeurs_premier_degre(familles, valeurs_facette):
    """
    Etend les familles demandees aux libelles reels de la facette officielle
    PREMIER_DEGRE_TYPE_JURIDICTION, qui mele libelles generiques
    ("Conseil de prud'hommes") et libelles par ville ("Tribunal correctionnel
    de Nice"). Rend la liste des libelles a envoyer a l'API.
    """
    prefixes = []
    for famille in familles:
        prefixes.extend(FAMILLES_PREMIER_DEGRE[famille])

    retenus = []
    for libelle in valeurs_facette:
        normalise = _sans_accents(libelle)
        if any(normalise.startswith(p) for p in prefixes) and libelle not in retenus:
            retenus.append(libelle)
    return retenus


def handle_search_premiere_instance(args: Dict[str, Any], user_id: str) -> Dict[str, Any]:
    """Recherche première instance avec parsing intelligent de la query"""

    query = args.get("query", "").strip()

    # Parser la query (utilise OU par défaut si pas d'opérateur explicite dans la query)
    operateur_query, type_recherche, criteres_parsed = parse_query(query)

    # Si la query ne contient pas d'opérateurs explicites ET/OU, forcer OU car volume faible
    if " ET " not in query.upper() and " OU " not in query.upper():
        operateur_query = "OU"
        # Mettre à jour les critères avec OU
        for c in criteres_parsed:
            c["operateur"] = "OU"

    type_champ = "ALL"

    # Dates par défaut : 5 ans
    date_fin = args.get("date_fin")
    date_debut = args.get("date_debut")
    if not date_fin:
        date_fin = datetime.now().strftime("%Y-%m-%d")
    if not date_debut:
        date_debut = (datetime.now() - timedelta(days=5*365)).strftime("%Y-%m-%d")
    date_fin = borne_haute_reelle(date_fin)

    sort = args.get("sort", "DATE_DESC")
    page_size, page_number, refus_pagination = _borne_pagination(args, 20, 100)
    if refus_pagination is not None:
        return refus_pagination

    # Construction des filtres
    filtres = [
        {
            "facette": "JURIDICTION_JUDICIAIRE",
            "valeurs": ["Juridictions du premier degré"]
        },
        {
            "facette": "DATE_DECISION",
            "dates": {
                "start": date_debut,
                "end": date_fin
            }
        }
    ]

    # Filtre PREMIER_DEGRE_TYPE_JURIDICTION (obligatoire)
    try:
        familles = familles_premier_degre(args.get("PREMIER_DEGRE_TYPE_JURIDICTION"))
    except ValueError as erreur:
        return create_response(
            f"<tool-use-error>\n{erreur}\n</tool-use-error>",
            is_error=True
        )

    try:
        # La facette officielle mele libelles generiques et libelles par ville :
        # on lit ses valeurs reelles pour la requete en cours, puis on etend les
        # familles demandees. Sans cette etape, "Tribunal correctionnel" ne
        # remonterait pas "Tribunal correctionnel de Nice".
        sonde = legifrance_client.search_with_criteres(
            fond="JURI",
            criteres=criteres_parsed,
            operateur=operateur_query,
            filtres=filtres,
            type_champ=type_champ,
            page_number=1,
            page_size=1,
            sort=sort
        )
        valeurs_facette = []
        for facette in sonde.get("facets") or []:
            if facette.get("facetElem") == "PREMIER_DEGRE_TYPE_JURIDICTION":
                valeurs_facette = list((facette.get("values") or {}).keys())
                break

        libelles = valeurs_premier_degre(familles, valeurs_facette)
        if not libelles:
            return create_response(
                f"**📋 JURIDICTIONS DE PREMIÈRE INSTANCE**\n\n"
                f"**Requête:** {query}\n"
                f"**Famille(s):** {', '.join(familles)}\n"
                f"**Période:** {date_debut} → {date_fin}\n\n"
                f"Aucune décision de ces juridictions ne correspond à cette "
                f"requête sur cette période.\n"
                f"La recherche n'a pas été élargie aux autres juridictions du "
                f"premier degré."
            )

        filtres.append({
            "facette": "PREMIER_DEGRE_TYPE_JURIDICTION",
            "valeurs": libelles
        })

        result = legifrance_client.search_with_criteres(
            fond="JURI",
            criteres=criteres_parsed,
            operateur=operateur_query,
            filtres=filtres,
            type_champ=type_champ,
            page_number=page_number,
            page_size=page_size,
            sort=sort
        )

        total = result.get("totalResultNumber", 0)
        resultats = result.get("results", [])

        # Vérifier si la requête est trop large (> 500 résultats)
        if total > LIMITE_RESULTATS:
            return _refus_requete_trop_large(total)

        types_str = ", ".join(familles)

        summary_parts = [
            f"**📋 JURIDICTIONS DE PREMIÈRE INSTANCE**",
            f"",
            f"**Requête:** {query}",
            f"**Type(s):** {types_str}",
            f"**Période:** {date_debut} → {date_fin}",
            f"**Total:** {total} décisions",
            f"**Affichées:** {len(resultats)}",
            f"",
            f"⚠️ Volume très limité dans la base Légifrance",
            f"",
            "═" * 80,
            ""
        ]

        for i, r in enumerate(resultats, 1):
            titles = r.get("titles", [])
            if titles:
                titre = titles[0].get("title", "")
                juri_id = titles[0].get("id", "")
            else:
                titre = "Sans titre"
                juri_id = ""

            # Titre de la décision
            summary_parts.append(f"{i}. {titre}")

            # Lien Légifrance
            if juri_id:
                summary_parts.append(f"   Lien: https://www.legifrance.gouv.fr/juri/id/{juri_id}")

            _append_decision_analysis(summary_parts, juri_id, r)
            sections = r.get("sections", [])
            articles_vises = []

            for section in sections:
                extracts = section.get("extracts", [])
                for extract in extracts:
                    field_name = extract.get("searchFieldName", "")
                    values = extract.get("values", [])

                    if field_name == "Texte appliqué" and values:
                        for val in values:
                            clean = val.replace("<mark>", "").replace("</mark>", "").replace("[...]", "").strip()
                            if clean and clean not in articles_vises:
                                articles_vises.append(clean)

            # Afficher les articles visés
            if articles_vises:
                summary_parts.append(f"   Articles visés: {', '.join(articles_vises[:3])}")
                if len(articles_vises) > 3:
                    summary_parts.append(f"   ... et {len(articles_vises) - 3} autre(s)")

            summary_parts.append("")

        summary = "\n".join(summary_parts)

        return create_response(summary)

    except Exception as e:
        return create_response(
            f"❌ **Erreur recherche première instance**\n\n"
            f"Erreur: {str(e)}",
            is_error=True
        )


def handle_search_code(args: Dict[str, Any], user_id: str) -> Dict[str, Any]:
    """Recherche dans les codes juridiques avec parsing intelligent"""

    query = args.get("query", "").strip()

    # Parser la query pour détecter références d'articles et opérateurs
    operateur_query, type_recherche, criteres_parsed, type_champ = parse_code_query(query)

    # Date de version : CODE_DATE exige ce filtre pour ne retourner que les
    # articles applicables à la date demandée. Sans filtre, l'API mélange les
    # versions historiques d'un même numéro d'article.
    date_version = args.get("date") or datetime.now().strftime("%Y-%m-%d")
    try:
        datetime.strptime(date_version, "%Y-%m-%d")
    except (TypeError, ValueError):
        return create_response(
            "❌ **Date de vigueur invalide**\n\n"
            "Utilisez le format YYYY-MM-DD (par exemple 2020-01-15).",
            is_error=True
        )

    # Pagination et tri
    sort = args.get("sort", "PERTINENCE")
    page_size, page_number, refus_pagination = _borne_pagination(args, 10, 50)
    if refus_pagination is not None:
        return refus_pagination

    filtres = [{
        "facette": "DATE_VERSION",
        "singleDate": date_version
    }]

    try:
        # Appel API avec critères parsés
        result = legifrance_client.search_with_criteres(
            fond="CODE_DATE",
            criteres=criteres_parsed,
            operateur=operateur_query,
            filtres=filtres,
            type_champ=type_champ,
            page_number=page_number,
            page_size=page_size,
            sort=sort,
            type_pagination="ARTICLE"
        )

        # Construction du résumé
        total = result.get("totalResultNumber", 0)
        resultats = result.get("results", [])

        if total > LIMITE_RESULTATS:
            return _refus_requete_trop_large(total)

        summary_parts = [
            f"**Requête:** {query}",
            f"**Type recherche:** {type_recherche} ({type_champ})",
            f"**Date de vigueur:** {date_version}",
            f"**Total:** {total:,} résultats".replace(',', ' '),
            f"**Affichés:** {len(resultats)}",
            f""
        ]

        # Formater les résultats
        for i, r in enumerate(resultats, 1):
            titles = r.get("titles", [])
            if titles:
                titre_code = titles[0].get("title", "")
                code_id = titles[0].get("cid", "")
            else:
                titre_code = "Sans titre"
                code_id = ""

            sections = r.get("sections", [])

            summary_parts.append(f"**{i}. {titre_code}**")

            # L'API CODE_DATE place les articles dans sections[].extracts[].
            # Leur texte d'aperçu se trouve dans `values`, et non dans `text`.
            if sections:
                for section in sections:
                    section_title = section.get("title", "")
                    extracts = section.get("extracts", [])

                    if section_title:
                        # Nettoyer les balises <mark>
                        clean_title = section_title.replace("<mark>", "**").replace("</mark>", "**")
                        summary_parts.append(f"   📖 {clean_title}")

                    for extract in extracts:
                        article_num = extract.get("title") or extract.get("num", "")
                        article_id = extract.get("id", "")
                        article_values = extract.get("values") or []
                        if isinstance(article_values, str):
                            article_values = [article_values]
                        article_text = extract.get("text", "")
                        statut = extract.get("legalStatus", "")
                        date_debut = str(extract.get("dateDebut") or "")[:10]
                        date_fin = str(extract.get("dateFin") or "")[:10]

                        if article_num:
                            summary_parts.append(f"   • Article {article_num}")

                        metadata = []
                        if statut:
                            metadata.append(statut)
                        if date_debut:
                            validite = f"depuis le {date_debut}"
                            if date_fin and not est_date_absente(date_fin):
                                validite += f" jusqu'au {date_fin}"
                            metadata.append(validite)
                        if metadata:
                            summary_parts.append(f"     {' · '.join(metadata)}")

                        if article_id:
                            summary_parts.append(f"     🔗 https://www.legifrance.gouv.fr/codes/article_lc/{article_id}")

                        apercus = article_values or ([article_text] if article_text else [])
                        for apercu in apercus:
                            clean_text = str(apercu).replace("<mark>", "**").replace("</mark>", "**")
                            summary_parts.append(f"     {clean_text}")

            summary_parts.append("")

        summary = "\n".join(summary_parts)

        return create_response(summary)

    except Exception as e:
        return create_response(
            f"❌ **Erreur recherche codes**\n\n"
            f"Requête: {query}\n"
            f"Erreur: {str(e)}",
            is_error=True
        )


# ============================================================================
# ROUTER PRINCIPAL
# ============================================================================

def handle_build_research_corpus(args: Dict[str, Any], user_id: str) -> Dict[str, Any]:
    """Fige et télécharge un corpus exhaustif, puis prépare les lots de cartographie."""
    try:
        info = build_research_corpus(args)
    except ValueError as e:
        return create_response(f"❌ {e}", is_error=True)

    truncated_note = (
        "\n⚠️ Le manifeste est tronqué par au moins un plafond explicite. "
        "Augmentez le plafond ou resserrez les requêtes avant toute conclusion."
        if info["truncated"] else ""
    )
    summary = (
        "**📚 CORPUS JURISPRUDENTIEL EXHAUSTIF PRÉPARÉ**\n\n"
        f"**Question:** {info['question']}\n"
        f"**Formulation:** {info['query']}\n"
        f"**Décisions identifiées (dédupliquées):** {info['identified']}\n"
        f"**Textes intégraux téléchargés et scannés:** {info['scanned']}\n"
        f"**Échecs:** {info['failed']}\n"
        f"**Décisions à revoir par modèle économique:** {info['model_reviewed']}\n"
        f"**Lots à cartographier:** {info['batches']}\n"
        f"**Entrée LLM estimée:** {info['tokens_input_estimated']:,} tokens "
        f"({info['token_estimation_method']}; ce n'est pas un relevé fournisseur)\n"
        f"{truncated_note}\n\n"
        f"**Dossier:** {info['folder']}\n"
        f"**Rapport Markdown attendu après validation:** {info['report']}\n"
        f"**Plan des lots:** {info['batch_plan']}\n"
        f"**Télémétrie:** {info['telemetry']}\n\n"
        "Traitez chaque fichier `batches/lot-*.md` et écrivez exactement une "
        "fiche JSON par décision dans le fichier `cards/lot-*.jsonl` correspondant. "
        "Exécutez ensuite `python3 recompile_research.py .` depuis le dossier. "
        "Toutes les décisions doivent "
        "recevoir une fiche du modèle, y compris celles qui ne sont finalement pas "
        "pertinentes pour la question."
    )
    return create_response(summary)


def handle_historique_judiciaire(args: Dict[str, Any], user_id: str) -> Dict[str, Any]:
    """Reconstitue le fil procédural d'une décision (judiciaire ou administratif)."""
    try:
        historique = build_decision_history(args)
    except HistoriqueError as erreur:
        return create_response(f"<tool-use-error>\n{erreur}\n</tool-use-error>", is_error=True)
    except Exception as erreur:
        return create_response(
            f"❌ **Erreur historique judiciaire**\n\n"
            f"ID: {args.get('text_id', '')}\n"
            f"Erreur: {erreur}",
            is_error=True
        )

    return create_response(
        render_historique(historique),
        resource={
            "uri": f"legifrance://historique/{historique['seed']}",
            "mimeType": "application/json",
            "text": json.dumps(historique, ensure_ascii=False, indent=2),
        }
    )


TOOL_HANDLERS = {
    # Nouveaux outils optimisés
    "Search_Cour_Cassation": handle_search_cour_cassation,
    "Search_Cour_Appel": handle_search_cour_appel,
    "Search_Conseil_Etat": handle_search_conseil_etat,
    "Search_CAA": handle_search_caa,
    "Search_Premiere_Instance": handle_search_premiere_instance,
    "Search_Code": handle_search_code,
    "Build_Research_Corpus": handle_build_research_corpus,
    "Historique_Judiciaire": handle_historique_judiciaire,
    "dictionnaire_juridique": handle_dictionnaire_juridique,

    # mcp_definitions.py annonce « Tracking_BODACC » (T majuscule) alors que la
    # table ne contenait que « tracking_BODACC » : l'outil annoncé tombait donc
    # sur « Outil non reconnu ». Les deux clés sont enregistrées pour corriger
    # l'appel sans casser un appelant existant.
    "Tracking_BODACC": handle_tracking_bodacc,

    # Anciens outils (compatibilité)
    "consulter_decision": handle_consulter_decision,
    "consulter_article": handle_consulter_article,
    "tracking_BODACC": handle_tracking_bodacc,
}


def handle_tool_call(tool_name: str, arguments: Dict[str, Any], user_id: str) -> Dict[str, Any]:
    """Router principal des appels d'outils"""
    handler = TOOL_HANDLERS.get(tool_name)
    
    if not handler:
        return create_response(f"Outil '{tool_name}' non reconnu", is_error=True)
    
    try:
        return handler(arguments, user_id)
    except Exception as e:
        return create_response(f"Erreur: {str(e)}", is_error=True)
