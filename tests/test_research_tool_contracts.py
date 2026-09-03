"""Contrats communs des outils publics de recherche."""

import os
import sys
import json
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from config.mcp_definitions import (
    MCP_TOOLS,
    QUERY_DESCRIPTION,
    QUERY_PREMIERE_INSTANCE_DESCRIPTION,
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

    def test_tools_list_ne_repete_pas_l_instruction_generale(self):
        tools_avec_requete = {
            tool["name"]
            for tool in MCP_TOOLS
            if "query" in tool["inputSchema"]["properties"]
        }
        self.assertEqual(tools_avec_requete, set(PUBLIC_QUERY_TOOLS))

        for name, property_name in PUBLIC_QUERY_TOOLS.items():
            with self.subTest(tool=name):
                description = self.tools[name]["inputSchema"]["properties"][property_name]["description"]
                self.assertNotIn("Les guillemets recherchent une expression exacte", description)
                self.assertNotIn("les parenthèses regroupent les alternatives", description)

        descriptions = json.dumps(MCP_TOOLS, ensure_ascii=False)
        self.assertNotIn("Les guillemets recherchent une expression exacte", descriptions)
        self.assertNotIn("société anonyme", descriptions)
        self.assertNotIn("poser des questions de clarification plutôt que multiplier les formulations", descriptions)
        self.assertNotIn("Il est recommandé d'inclure l'article de référence", descriptions)
        self.assertNotIn("borner les dates à la version du texte applicable", descriptions)

        for name in (
            "Search_Cour_Cassation",
            "Search_Cour_Appel",
            "Search_Conseil_Etat",
            "Search_CAA",
            "Download_Query_Results",
        ):
            self.assertEqual(
                self.tools[name]["inputSchema"]["properties"]["query"]["description"],
                QUERY_DESCRIPTION,
            )

    def test_build_corpus_exige_une_formulation_unique(self):
        schema = self.tools["Build_Research_Corpus"]["inputSchema"]
        self.assertEqual(schema["required"], ["question", "query"])
        self.assertNotIn("queries", schema["properties"])
        self.assertNotIn("max_decisions", schema["properties"])
        self.assertNotIn("max_results_per_query", schema["properties"])

    def test_exception_premiere_instance_est_explicite_et_centralisee(self):
        description = self.tools["Search_Premiere_Instance"]["inputSchema"]["properties"]["query"]["description"]
        self.assertEqual(description, QUERY_PREMIERE_INSTANCE_DESCRIPTION)
        self.assertIn("reliés par `OU`", description)
        self.assertIn("Sans `ET` ou `OU` explicite", description)

    def test_particularites_code_et_build_corpus_sont_preservees(self):
        code = self.tools["Search_Code"]["inputSchema"]["properties"]
        self.assertIn("NUM_ARTICLE", code["query"]["description"])
        self.assertIn("version d'un article valable à une date passée", code["date"]["description"])

        build = self.tools["Build_Research_Corpus"]
        self.assertIn("au-delà de 500 résultats", build["description"])
        self.assertIn("distincte de la question de droit", build["inputSchema"]["properties"]["query"]["description"])

    def test_alias_recherche_jurisprudence_n_est_plus_routable(self):
        self.assertNotIn("recherche_jurisprudence", TOOL_HANDLERS)
        response = handle_tool_call("recherche_jurisprudence", {}, "test")
        self.assertTrue(response["isError"])
        self.assertIn("non reconnu", response["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()
