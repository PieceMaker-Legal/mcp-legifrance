#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Serveur MCP Légifrance autonome (transport stdio local)

Serveur JSON-RPC 2.0 local sur stdio.
La logique métier (handlers d'outils, clients Légifrance/BODACC et définitions
MCP) reste entièrement locale ; seules les API juridiques officielles sont
appelées par les clients dédiés.

IMPORTANT : stdout est réservé aux messages JSON-RPC. Tout log doit aller sur
stderr — un simple print() égaré sur stdout corromprait le protocole.
"""

import sys
import os
import json
import logging

# Rendre config/tools/resources importables comme packages de premier niveau,
# comme le faisait mcp_http_wrapper.py avec son propre répertoire.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
    stream=sys.stderr,
)
logger = logging.getLogger('legifrance.mcp_stdio')

from config.mcp_definitions import MCP_TOOLS, MCP_RESOURCES
from tools.handlers import handle_tool_call
from resources import get_dictionnaire

# Le serveur est lancé pour un seul opérateur : il n'y a ni login ni session à
# établir. handle_tool_call() conserve un paramètre positionnel user_id ; une
# constante locale suffit, car aucun outil ne varie selon cette valeur.
LOCAL_USER_ID = "local-stdio-user"


# ============================================================================
# UTILITAIRES JSON-RPC 2.0 (repris de mcp_http_wrapper.py)
# ============================================================================

def jsonrpc_success(id, result):
    return {"jsonrpc": "2.0", "id": id, "result": result}


def jsonrpc_error(id, code, message, data=None):
    error = {"code": code, "message": message}
    if data:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": id, "error": error}


# ============================================================================
# HANDLERS MCP (repris tels quels de mcp_http_wrapper.py, sans l'auth HTTP)
# ============================================================================

def handle_initialize(params):
    # Support both old and new protocol versions
    client_version = params.get("protocolVersion", "2024-11-05")
    supported_versions = ["2024-11-05", "2025-06-18"]

    # Use the client's version if supported, otherwise use latest
    protocol_version = client_version if client_version in supported_versions else "2024-11-05"

    return {
        "protocolVersion": protocol_version,
        "capabilities": {
            "tools": {"enabled": True, "list": True, "call": True},
            "resources": {"enabled": True, "list": True, "read": True}
        },
        "serverInfo": {"name": "Légifrance MCP", "version": "2.0.0"}
    }


def handle_tools_list(params):
    return {"tools": MCP_TOOLS}


def handle_tools_call(params, user_id):
    tool_name = params.get("name")
    arguments = params.get("arguments", {})
    return handle_tool_call(tool_name, arguments, user_id)


def handle_resources_list(params):
    return {"resources": MCP_RESOURCES}


def handle_resources_read(params):
    uri = params.get("uri", "")

    content_map = {
        "resource://dictionnaire-juridique": get_dictionnaire,
    }

    getter = content_map.get(uri)
    if getter:
        return {
            "contents": [{
                "uri": uri,
                "mimeType": "text/markdown",
                "text": getter()
            }]
        }

    return {
        "contents": [{
            "uri": uri,
            "mimeType": "text/plain",
            "text": f"Ressource non trouvée: {uri}"
        }]
    }


def handle_ping(params):
    # N'existait pas côté HTTP (le endpoint /health jouait ce rôle) mais fait
    # partie du protocole MCP stdio standard pour les vérifications de vie.
    return {}


HANDLERS = {
    "initialize": lambda p: handle_initialize(p),
    "tools/list": lambda p: handle_tools_list(p),
    "tools/call": lambda p: handle_tools_call(p, LOCAL_USER_ID),
    "resources/list": lambda p: handle_resources_list(p),
    "resources/read": lambda p: handle_resources_read(p),
    "ping": lambda p: handle_ping(p),
}


# ============================================================================
# BOUCLE PRINCIPALE STDIO
# ============================================================================

def process_request(data):
    """Traite une requête JSON-RPC déjà décodée.

    Retourne un dict de réponse JSON-RPC, ou None si aucune réponse ne doit
    être émise (notification sans clé ``id``).
    """
    # JSON-RPC exige un objet au niveau racine. ``json.loads`` accepte aussi
    # les tableaux et les scalaires JSON : ils doivent être signalés comme
    # requêtes invalides, et non déclencher une AttributeError interne.
    if not isinstance(data, dict):
        logger.error("Invalid JSON-RPC request: expected an object")
        return jsonrpc_error(None, -32600, "Invalid Request")

    if data.get("jsonrpc") != "2.0":
        logger.error(f"Invalid JSON-RPC version: {data.get('jsonrpc')}")
        return jsonrpc_error(data.get("id"), -32600, "Invalid jsonrpc version")

    method = data.get("method")
    request_id = data.get("id")

    # Un objet incomplet ou dont ``method`` n'est pas une chaîne ne constitue
    # pas une notification : c'est une requête JSON-RPC invalide.
    if not isinstance(method, str) or not method:
        logger.error("Invalid or missing method in request")
        return jsonrpc_error(request_id, -32600, "Invalid Request")

    # En JSON-RPC, l'absence de la clé ``id`` (et non sa valeur) définit une
    # notification. ``{"id": null}`` reste donc une requête à laquelle le
    # serveur peut répondre avec ``"id": null``.
    is_notification = "id" not in data
    params = data.get("params") or {}

    # Notifications (pas de réponse)
    if method.startswith("notifications/"):
        logger.info(f"Processing notification: {method}")
        return None

    handler = HANDLERS.get(method)
    if not handler:
        logger.error(f"Method not found: {method}")
        response = jsonrpc_error(request_id, -32601, f"Method not found: {method}")
        return None if is_notification else response

    try:
        logger.info(f"Calling handler for: {method}")
        result = handler(params)
        logger.info(f"Handler completed successfully for: {method}")
        response = jsonrpc_success(request_id, result)
        return None if is_notification else response
    except Exception as e:
        logger.exception(f"Internal error in {method}: {str(e)}")
        response = jsonrpc_error(request_id, -32603, f"Internal error: {str(e)}")
        return None if is_notification else response


def _write_response(response):
    sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main():
    logger.info("Démarrage serveur MCP Légifrance (stdio)")

    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue

        try:
            data = json.loads(line)
        except json.JSONDecodeError as e:
            logger.error(f"Parse error: {str(e)}")
            _write_response(jsonrpc_error(None, -32700, f"Parse error: {str(e)}"))
            continue

        try:
            response = process_request(data)
        except Exception as e:
            # Filet de sécurité : ne jamais laisser une exception non gérée
            # planter le process (ni, surtout, rien écrire sur stdout).
            logger.exception(f"Unexpected error: {str(e)}")
            response = jsonrpc_error(data.get("id") if isinstance(data, dict) else None,
                                      -32603, f"Unexpected error: {str(e)}")

        if response is not None:
            _write_response(response)

    logger.info("Fin du flux stdin — arrêt du serveur")


if __name__ == "__main__":
    main()
