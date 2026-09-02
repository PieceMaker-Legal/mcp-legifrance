"""Contrats communs des outils publics de recherche."""

import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from config.mcp_definitions import (
    MCP_TOOLS,
    QUERY_SYNTAX_DESCRIPTION,
    QUERY_SYNTAX_ET_DESCRIPTION,
    QUERY_SYNTAX_PREMIERE_INSTANCE_DESCRIPTION,
)
from tools.handlers import TOOL_HANDLERS, handle_tool_call


PUBLIC_QUERY_TOOLS = {
    "Search_Cour_Cassation": "query",
    "Search_Cour_Appel": "query",
    "Search_Conseil_Etat": "query",
    "Search_CAA": "query",
    "Search_Premiere_Instance": "query",
    "Search_Code": "query",
    "Download_Query_Results": "query",
    "Build_Research_Corpus": "query",
}


class ResearchToolContractsTest(unittest.TestCase):
    def setUp(self):
        self.tools = {tool["name"]: tool for tool in MCP_TOOLS}

    def test_huit_outils_publics_partagent_la_syntaxe_complete(self):
        tools_avec_requete = {
            tool["name"]
            for tool in MCP_TOOLS
            if "query" in tool["inputSchema"]["properties"]
        }
        self.assertEqual(tools_avec_requete, set(PUBLIC_QUERY_TOOLS))

        for name, property_name in PUBLIC_QUERY_TOOLS.items():
            with self.subTest(tool=name):
                description = self.tools[name]["inputSchema"]["properties"][property_name]["description"]
                self.assertIn(QUERY_SYNTAX_DESCRIPTION, description)
                self.assertIn('guillemets délimitent une expression exacte', description)
                self.assertIn('parenthèses changent ce regroupement', description)
                self.assertIn('`ET` est prioritaire sur `OU`', description)
                self.assertIn('("faute grave" OU "faute lourde") ET licenciement', description)
                if name != "Search_Premiere_Instance":
                    self.assertIn(QUERY_SYNTAX_ET_DESCRIPTION, description)
                    self.assertIn("reliés par `ET`", description)

    def test_build_corpus_exige_une_formulation_unique(self):
        schema = self.tools["Build_Research_Corpus"]["inputSchema"]
        self.assertEqual(schema["required"], ["question", "query"])
        self.assertNotIn("queries", schema["properties"])
        self.assertNotIn("max_decisions", schema["properties"])
        self.assertNotIn("max_results_per_query", schema["properties"])

    def test_exception_premiere_instance_est_explicite_et_centralisee(self):
        description = self.tools["Search_Premiere_Instance"]["inputSchema"]["properties"]["query"]["description"]
        self.assertEqual(description, QUERY_SYNTAX_PREMIERE_INSTANCE_DESCRIPTION)
        self.assertIn("reliés par `OU`", description)
        self.assertNotIn("reliés par `ET`", description)

    def test_alias_recherche_jurisprudence_n_est_plus_routable(self):
        self.assertNotIn("recherche_jurisprudence", TOOL_HANDLERS)
        response = handle_tool_call("recherche_jurisprudence", {}, "test")
        self.assertTrue(response["isError"])
        self.assertIn("non reconnu", response["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()
