import os
import sys
import json
import subprocess
import unittest
from unittest.mock import patch


ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from config.mcp_definitions import INITIALIZE_INSTRUCTIONS, MCP_RESOURCES, MCP_TOOLS
from mcp_stdio_server import process_request
from tools.handlers import TOOL_HANDLERS


class StdioServerTest(unittest.TestCase):
    def test_initialize_sans_identifiants(self):
        response = process_request({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18"},
        })
        self.assertEqual(response["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual(response["result"]["serverInfo"]["name"], "Légifrance MCP")
        self.assertNotIn("prompts", response["result"]["capabilities"])
        self.assertEqual(response["result"]["instructions"], INITIALIZE_INSTRUCTIONS)
        self.assertIn("Formule une seule requête", response["result"]["instructions"])
        self.assertIn("inclus-le obligatoirement", response["result"]["instructions"])
        self.assertEqual(response["result"]["instructions"].count("société anonyme"), 1)

    def test_seul_le_dictionnaire_est_expose_comme_ressource(self):
        self.assertEqual(
            [resource["uri"] for resource in MCP_RESOURCES],
            ["resource://dictionnaire-juridique"],
        )

    def test_aucun_prompt_de_conclusions_n_est_expose(self):
        response = process_request({
            "jsonrpc": "2.0",
            "id": 4,
            "method": "prompts/list",
            "params": {},
        })
        self.assertEqual(response["error"]["code"], -32601)

    def test_outils_exhaustifs_decouvrables(self):
        response = process_request({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {},
        })
        names = {tool["name"] for tool in response["result"]["tools"]}
        self.assertIn("Build_Research_Corpus", names)
        self.assertNotIn("Validate_Research_Cards", names)
        serialized_tools = json.dumps(response["result"]["tools"], ensure_ascii=False)
        self.assertNotIn("Formule une seule requête", serialized_tools)
        self.assertNotIn("société anonyme", serialized_tools)

    def test_chaque_outil_annonce_possede_un_handler(self):
        announced = {tool["name"] for tool in MCP_TOOLS}
        self.assertEqual(announced - set(TOOL_HANDLERS), set())

    def test_ping(self):
        response = process_request({
            "jsonrpc": "2.0",
            "id": 3,
            "method": "ping",
            "params": {},
        })
        self.assertEqual(response["result"], {})

    def test_notification_sans_id_ne_produit_jamais_de_reponse(self):
        for method in ("ping", "tools/list", "methode/inconnue"):
            with self.subTest(method=method):
                self.assertIsNone(process_request({
                    "jsonrpc": "2.0",
                    "method": method,
                    "params": {},
                }))

    def test_id_null_explicite_recoit_une_reponse(self):
        response = process_request({
            "jsonrpc": "2.0",
            "id": None,
            "method": "ping",
            "params": {},
        })
        self.assertEqual(response, {
            "jsonrpc": "2.0",
            "id": None,
            "result": {},
        })

    def test_requete_sans_method_est_invalide_et_non_une_notification(self):
        self.assertEqual(process_request({"jsonrpc": "2.0"}), {
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": -32600, "message": "Invalid Request"},
        })

    def test_json_non_objet_est_une_requete_invalide(self):
        for data in ([], "bonjour", 42, True, None):
            with self.subTest(data=data):
                self.assertEqual(process_request(data), {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32600, "message": "Invalid Request"},
                })

    def test_processus_rejete_les_json_non_objets_sans_reponse_aux_notifications(self):
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        input_lines = [
            "[]",
            '"bonjour"',
            "42",
            "true",
            "null",
            '{"jsonrpc":"2.0","method":"ping"}',
            "{",
        ]
        completed = subprocess.run(
            [sys.executable, "mcp_stdio_server.py"],
            cwd=ROOT,
            env=environment,
            input="\n".join(input_lines) + "\n",
            text=True,
            capture_output=True,
            check=True,
        )
        responses = [json.loads(line) for line in completed.stdout.splitlines()]

        self.assertNotIn("Traceback", completed.stderr)
        self.assertEqual(responses[:5], [{
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": -32600, "message": "Invalid Request"},
        }] * 5)
        self.assertEqual(responses[5]["id"], None)
        self.assertEqual(responses[5]["error"]["code"], -32700)
        self.assertEqual(len(responses), 6)

    def test_method_non_chaine_est_une_requete_invalide(self):
        for method in (None, 42, []):
            with self.subTest(method=method):
                response = process_request({
                    "jsonrpc": "2.0",
                    "id": 6,
                    "method": method,
                })
                self.assertEqual(response["id"], 6)
                self.assertEqual(response["error"]["code"], -32600)
                self.assertEqual(response["error"]["message"], "Invalid Request")

    def test_consulter_decision_longue_retourne_une_ressource_json_fidele(self):
        texte_integral = (
            "MOYENS ANNEXES\n" + "Texte officiel intégral. " * 5_100
        )
        with patch(
            "tools.handlers.legifrance_client.get_decision_text",
            return_value={"text": {
                "titre": "Arrêt de test",
                "nature": "REJET",
                "texte": texte_integral,
            }},
        ):
            response = process_request({
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {
                    "name": "consulter_decision",
                    "arguments": {"text_id": "JURITEXTLONGUE"},
                },
            })

        serialized = json.dumps(response, ensure_ascii=False)
        self.assertIn("JURITEXTLONGUE", serialized)
        content = response["result"]["content"]
        resource = next(item["resource"] for item in content if item["type"] == "resource")
        self.assertEqual(
            resource["uri"],
            "legifrance://jurisprudence/JURITEXTLONGUE/texte-integral",
        )
        self.assertEqual(resource["mimeType"], "text/plain; charset=utf-8")
        self.assertEqual(resource["text"], texte_integral)
        self.assertNotIn("blob", resource)
        self.assertNotIn("base64", resource["uri"])


if __name__ == "__main__":
    unittest.main()
