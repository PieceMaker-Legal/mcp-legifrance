#/tools/handlers.py 
#! MCP SERVEUR LOCAL
"""Handlers pour les outils MCP"""

import json
import os
import re
from datetime import datetime
from typing import Dict, Any, Optional

from tools.session_manager import session_manager
from tools.case_manager import case_manager
from tools import jurisprudence_search as recherche
from tools.legifrance_client import legifrance_client, est_date_absente
from tools.bodacc_client import bodacc_client
from tools.justice_lexicon import JusticeLexiconError, justice_lexicon_client
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


def _consulter_decision_judilibre(text_id: str) -> Dict[str, Any]:
    decision = recherche.decision_judilibre(legifrance_client, text_id)
    texte = str(decision.get("text") or "").strip()
    lien = f"{recherche.LIEN_JUDILIBRE}{text_id}"
    parts = [f"DÉCISION: {recherche.titre_judilibre(decision, text_id)}", ""]
    for libelle, valeur in (
        ("Formation", decision.get("formation") or decision.get("chamber")),
        ("Solution", decision.get("solution")),
        ("Publication", ", ".join(map(str, decision.get("publication") or [])) if isinstance(decision.get("publication"), list) else decision.get("publication")),
        ("ECLI", decision.get("ecli")),
    ):
        if recherche.sans_balises(valeur):
            parts.append(f"{libelle}: {recherche.sans_balises(valeur)}")
    if recherche.sans_balises(decision.get("visa")):
        parts += ["", "VISAS:", recherche.sans_balises(decision.get("visa"))]
    if len(texte) // 4 > 25000:
        return create_response(
            "\n".join(parts + ["", f"⚠️ **Décision trop longue** (≈ {len(texte) // 4:,} tokens)".replace(",", " "), f"Lien: {lien}", "", "Le texte intégral est joint comme ressource MCP."]),
            resource={"uri": f"judilibre://decision/{text_id}/texte-integral", "mimeType": "text/plain; charset=utf-8", "text": texte},
        )
    return create_response("\n".join(parts + ["", "=" * 80, "TEXTE INTÉGRAL:", "=" * 80, "", texte, "", f"Lien: {lien}"]))


def handle_consulter_decision(args: Dict[str, Any], user_id: str) -> Dict[str, Any]:
    """
    Récupère le texte intégral d'une décision de jurisprudence.
    Retourne uniquement: nature, titre, visas, texte, decisionAttaquee
    """
    text_id = args.get("text_id") or args.get("id")

    if not text_id:
        return create_response("text_id requis", is_error=True)

    text_id = text_id.strip()
    lien = f"{recherche.LIENS_LEGIFRANCE['CETAT' if text_id.startswith('CETATEXT') else 'JURI']}{text_id}"

    try:
        if re.fullmatch(r"[0-9a-f]{24}", text_id):
            return _consulter_decision_judilibre(text_id)
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
                date_str = recherche.date_longue(recherche.date_iso(date_da)) if date_da_reelle else ""
                if date_str:
                    summary_parts.append(f"Date: {date_str}")

        # Texte intégral
        summary_parts.append(f"")
        summary_parts.append(f"{'='*80}")
        summary_parts.append(f"TEXTE INTÉGRAL:")
        summary_parts.append(f"{'='*80}")
        summary_parts.append(f"")
        summary_parts.append(texte)
        summary_parts.append(f"")
        summary_parts.append(f"Lien: {lien}")

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
                f"Lien: {lien}",
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

def _articles_vises(resultat: Dict[str, Any]) -> list[str]:
    articles = []
    for section in resultat.get("sections", []) or []:
        for extract in section.get("extracts", []) or []:
            if extract.get("searchFieldName", "") != "Texte appliqué":
                continue
            for valeur in extract.get("values", []) or []:
                propre = valeur.replace("<mark>", "").replace("</mark>", "").replace("[...]", "").strip()
                if propre and propre not in articles:
                    articles.append(propre)
    return articles


def _analyse_judilibre(decision: Dict[str, Any], resultat: Dict[str, Any]) -> tuple[str, str]:
    resumes = []
    for entree in decision.get("titlesAndSummaries") or []:
        resume = recherche.sans_balises(entree.get("summary"))
        if resume and resume not in resumes:
            resumes.append(resume)
    resume = recherche.sans_balises(decision.get("summary") or resultat.get("summary")) or "\n".join(resumes)
    if resume:
        return "Analyse", resume
    extraits = (resultat.get("highlights") or {}).get("text") or []
    extrait = " […] ".join(str(e).replace("<em>", "**").replace("</em>", "**").strip() for e in extraits[:3] if e)
    return ("Extraits", extrait) if extrait else ("", "")


def _ligne_compte(compte: Dict[str, Any]) -> str:
    morceaux = []
    if compte["legifrance"] is not None:
        morceaux.append(f"Légifrance {compte['legifrance']}")
    if compte["judilibre"] is not None:
        morceaux.append(f"Judilibre {compte['judilibre']}")
    periode = f"{compte['debut'] or 'origine'} → {compte['fin'] or 'aujourd’hui'}"
    return f"- {recherche.LIBELLES_JURIDICTIONS[compte['juridiction']]} ({periode}) : {', '.join(morceaux) or 'aucune source'}"


def _lignes_filtres(plan: Dict[str, Any]) -> list[str]:
    lignes = []
    if plan["matieres"]:
        lignes.append(f"**Matière (cassation):** {', '.join(plan['matieres'])}")
    if "cassation" in plan["juridictions"] and plan["publication_cassation"] != "TOUS":
        lignes.append(f"**Publication (cassation):** {plan['publication_cassation']}")
    if "appel" in plan["juridictions"] and plan["sieges_appel"]:
        lignes.append(f"**Cour(s) d'appel:** {', '.join(plan['sieges_appel'])}")
    if plan["types_premiere_instance"]:
        lignes.append(f"**Première instance:** {', '.join(plan['types_premiere_instance'])}")
    if "caa" in plan["juridictions"] and plan["villes_caa"]:
        lignes.append(f"**CAA:** {', '.join(plan['villes_caa'])}")
    if {"conseil_etat", "caa"} & set(plan["juridictions"]) and plan["publication_recueil"] != "TOUS":
        lignes.append(f"**Recueil Lebon:** {plan['publication_recueil']}")
    return lignes


def handle_recherche_jurisprudence(args: Dict[str, Any], user_id: str) -> Dict[str, Any]:
    try:
        plan = recherche.preparer(args)
    except recherche.RechercheInvalide as erreur:
        return create_response(f"<tool-use-error>\n{erreur}\n</tool-use-error>", is_error=True)

    page_size, page_number, refus_pagination = _borne_pagination(args, 10, 100)
    if refus_pagination is not None:
        return refus_pagination

    try:
        collecte = recherche.collecter_avec_cache(plan, legifrance_client)
    except recherche.RechercheTropLarge as trop:
        refus = _refus_requete_trop_large(trop.total)
        detail = "\n".join(_ligne_compte(compte) for compte in trop.comptes)
        refus["content"][0]["text"] = refus["content"][0]["text"].replace(
            "</tool-use-error>", f"\nDétail des totaux :\n{detail}\n</tool-use-error>"
        )
        return refus
    except Exception as e:
        return create_response(
            f"<tool-use-error>\nErreur recherche jurisprudence\nRequête: {plan['query']}\nErreur: {e}\n</tool-use-error>",
            is_error=True,
        )

    resultats = collecte["resultats"]
    debut = (page_number - 1) * page_size
    page = resultats[debut:debut + page_size]
    parts = [
        "**⚖️ RECHERCHE JURISPRUDENCE (Légifrance + Judilibre)**",
        "",
        f"**Requête:** {plan['query']}",
        f"**Sources:** {', '.join('Légifrance' if s == 'legifrance' else 'Judilibre' for s in plan['sources'])}",
        *_lignes_filtres(plan),
        "**Totaux par juridiction (avant fusion):**",
        *(_ligne_compte(compte) for compte in collecte["comptes"]),
        f"**Total:** {len(resultats)} décision(s) distincte(s)",
    ]
    if collecte["fusionnees"]:
        parts.append(f"**Doublons Légifrance/Judilibre fusionnés:** {collecte['fusionnees']}")
    if collecte["ecartees"]:
        parts.append(
            f"**Résultats Judilibre écartés:** {collecte['ecartees']} (expression exacte absente du texte intégral)"
        )
    for avertissement in collecte["avertissements"]:
        parts.append(f"⚠️ {avertissement}")
    parts += [
        f"**Page:** {page_number} — résultats {debut + 1 if page else 0} à {debut + len(page)} sur {len(resultats)}, du plus récent au plus ancien",
        "",
        "═" * 80,
        "",
    ]

    for position, resultat in enumerate(page, debut + 1):
        if resultat["source"] == "legifrance":
            origine = "Légifrance + Judilibre" if resultat.get("judilibre") else "Légifrance"
            parts.append(f"{position}. {resultat['titre']}")
            parts.append(f"   Source: {origine} — {recherche.LIBELLES_JURIDICTIONS[resultat['juridiction']]}")
            parts.append(f"   ID: {resultat['id']}")
            parts.append(f"   Lien: {resultat['lien']}")
            if resultat.get("judilibre"):
                parts.append(f"   Lien Judilibre: {resultat['judilibre']['lien']}")
            _append_decision_analysis(parts, resultat["id"], resultat["resultat"])
            articles = _articles_vises(resultat["resultat"])
            if articles:
                parts.append(f"   Articles visés: {', '.join(articles[:3])}")
                if len(articles) > 3:
                    parts.append(f"   ... et {len(articles) - 3} autre(s)")
        else:
            decision = resultat.get("decision")
            if decision is None:
                try:
                    decision = recherche.decision_judilibre(legifrance_client, resultat["id"])
                    resultat["decision"] = decision
                except Exception:
                    decision = {}
            parts.append(f"{position}. {recherche.titre_judilibre(decision, resultat['titre'])}")
            parts.append(f"   Source: Judilibre — {recherche.LIBELLES_JURIDICTIONS[resultat['juridiction']]}")
            parts.append(f"   ID: {resultat['id']}")
            parts.append(f"   Lien: {resultat['lien']}")
            libelle, analyse = _analyse_judilibre(decision, resultat["resultat"])
            if analyse:
                parts.append(f"   {libelle}: {analyse}")
            if resultat.get("verification"):
                parts.append(f"   ⚠️ {resultat['verification']}")
        parts.append("")

    return create_response("\n".join(parts))


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
    "Search_Jurisprudence": handle_recherche_jurisprudence,
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
