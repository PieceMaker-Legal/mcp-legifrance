#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lecture bornée du lexique juridique officiel publié sur justice.fr."""

from __future__ import annotations

import re
import ssl
import unicodedata
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional

import requests
from requests.adapters import HTTPAdapter

try:
    import truststore
except ImportError:  # Compatibilité avec une installation pas encore mise à jour.
    truststore = None


JUSTICE_LEXICON_BASE_URL = "https://www.justice.fr/lexique"
JUSTICE_LEXICON_LETTERS = "abcdefghijlmnopqrstuvz"
DEFAULT_TIMEOUT_SECONDS = 20
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0.0.0 Safari/537.36"
)


class JusticeLexiconError(RuntimeError):
    """Erreur explicite de téléchargement ou de structure du lexique."""


class _SystemTrustAdapter(HTTPAdapter):
    """Adapte requests au magasin de certificats natif de l'OS."""

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        if truststore is not None:
            pool_kwargs["ssl_context"] = truststore.SSLContext(
                ssl.PROTOCOL_TLS_CLIENT
            )
        return super().init_poolmanager(
            connections,
            maxsize,
            block=block,
            **pool_kwargs,
        )


def _create_session() -> requests.Session:
    session = requests.Session()
    if truststore is not None:
        session.mount("https://", _SystemTrustAdapter())
    return session


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _normalise(value: str) -> str:
    value = value.replace("’", "'").replace("œ", "oe").replace("Œ", "OE")
    decomposed = unicodedata.normalize("NFKD", value)
    without_marks = "".join(
        character for character in decomposed
        if not unicodedata.combining(character)
    )
    return _clean_text(without_marks).casefold()


def _initial_letter(term: str) -> str:
    for character in _normalise(term):
        if "a" <= character <= "z":
            return character
    raise ValueError("Le terme doit contenir au moins une lettre de A à Z.")


class _LexiconHTMLParser(HTMLParser):
    """Extrait les couples ``dt.lexique-content-titre`` / ``dd``."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.entries: List[Dict[str, str]] = []
        self._in_title = False
        self._in_definition = False
        self._title_parts: List[str] = []
        self._definition_parts: List[str] = []
        self._anchor: Optional[str] = None
        self._pending: Optional[Dict[str, str]] = None

    def handle_starttag(self, tag: str, attrs: List[tuple]) -> None:
        attributes = dict(attrs)
        classes = set(attributes.get("class", "").split())
        if tag == "dt" and "lexique-content-titre" in classes:
            self._in_title = True
            self._title_parts = []
            self._anchor = None
        elif self._in_title and tag == "a" and attributes.get("id"):
            self._anchor = attributes["id"]
        elif tag == "dd" and self._pending is not None:
            self._in_definition = True
            self._definition_parts = []
        elif self._in_definition and tag in {"br", "p", "li", "div"}:
            self._definition_parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag == "dt" and self._in_title:
            self._in_title = False
            title = _clean_text("".join(self._title_parts))
            self._pending = {
                "terme": title,
                "definition": "",
                "ancre": self._anchor or "",
            } if title else None
        elif tag == "dd" and self._in_definition:
            self._in_definition = False
            definition = _clean_text("".join(self._definition_parts))
            if self._pending is not None and definition:
                self._pending["definition"] = definition
                self.entries.append(self._pending)
            self._pending = None

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data)
        elif self._in_definition:
            self._definition_parts.append(data)


def parse_lexicon_page(html: str) -> List[Dict[str, str]]:
    """Parse une page alphabétique de justice.fr sans dépendance HTML tierce."""
    parser = _LexiconHTMLParser()
    parser.feed(html)
    parser.close()
    return parser.entries


class JusticeLexiconClient:
    """Client limité aux pages alphabétiques du lexique de justice.fr."""

    def __init__(
        self,
        session: Optional[requests.Session] = None,
        timeout: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.session = session or _create_session()
        self.timeout = timeout

    def _fetch_letter(self, letter: str) -> tuple[str, List[Dict[str, str]]]:
        page_url = f"{JUSTICE_LEXICON_BASE_URL}/letter_{letter}"
        try:
            response = self.session.get(
                page_url,
                headers={
                    "User-Agent": DEFAULT_USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "fr-FR,fr;q=0.9",
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.RequestException as error:
            raise JusticeLexiconError(
                f"Impossible de consulter le lexique justice.fr : {error}"
            ) from error

        body = response.text
        blocked_markers = (
            "Notre système de sécurité a détecté un comportement suspect",
            "ID de support",
            "Accès refusé",
        )
        if any(marker in body for marker in blocked_markers):
            raise JusticeLexiconError(
                "justice.fr a refusé la requête automatisée (page de sécurité F5). "
                "Réessayez ultérieurement depuis une adresse autorisée."
            )

        entries = parse_lexicon_page(body)
        if not entries and 'id="lexique-content"' not in body:
            raise JusticeLexiconError(
                "La structure attendue du lexique justice.fr est absente ; "
                "aucun résultat fiable ne peut être rendu."
            )
        return page_url, entries

    def lookup(self, term: str) -> Dict[str, Any]:
        if not isinstance(term, str) or not term.strip():
            raise ValueError("Le paramètre `terme` est obligatoire.")

        query = _clean_text(term)
        letter = _initial_letter(query)
        page_url, entries = self._fetch_letter(letter)

        needle = _normalise(query)
        match = next(
            (entry for entry in entries if _normalise(entry["terme"]) == needle),
            None,
        )
        if match is not None:
            # Le handler public ne rend que ``definition``. Les autres champs
            # restent internes pour préserver la provenance du texte extrait.
            return {
                "terme": match["terme"],
                "definition": match["definition"],
                "source_url": page_url + (
                    f"#{match['ancre']}" if match.get("ancre") else ""
                ),
                "suggestions": [],
            }

        # Une suggestion peut commencer par une autre lettre que la requête
        # (ex. « intérêts civils » -> « Renvoi sur intérêts civils »). Le
        # balayage porte donc sur toutes les pages déclarées par justice.fr.
        all_entries = list(entries)
        for other_letter in JUSTICE_LEXICON_LETTERS:
            if other_letter == letter:
                continue
            _, letter_entries = self._fetch_letter(other_letter)
            all_entries.extend(letter_entries)

        query_words = [word for word in needle.split(" ") if word]
        suggestions = {
            entry["terme"]
            for entry in all_entries
            if all(word in _normalise(entry["terme"]) for word in query_words)
        }
        ordered_suggestions = sorted(suggestions, key=_normalise)
        if not ordered_suggestions:
            raise JusticeLexiconError(
                f"Aucun terme du lexique justice.fr ne contient tous les mots de « {query} »."
            )

        return {
            "terme": None,
            "definition": None,
            "source_url": JUSTICE_LEXICON_BASE_URL,
            "suggestions": ordered_suggestions,
        }


justice_lexicon_client = JusticeLexiconClient()
