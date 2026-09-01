import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from config.mcp_definitions import MCP_RESOURCES, MCP_TOOLS
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
        self.assertIn("Validate_Research_Cards", names)

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


if __name__ == "__main__":
    unittest.main()
