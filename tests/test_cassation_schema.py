import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from config.mcp_definitions import MCP_TOOLS
from mcp_stdio_server import process_request
from tools.handlers import formations_cassation, handle_search_cour_cassation


class CassationSchemaTest(unittest.TestCase):
    def test_nature_decision_n_est_plus_annoncee_et_les_autres_filtres_restent(self):
        response = process_request({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
            "params": {},
        })
        discovered = next(
            tool for tool in response["result"]["tools"]
            if tool["name"] == "Search_Cour_Cassation"
        )
        declared = next(
            tool for tool in MCP_TOOLS
            if tool["name"] == "Search_Cour_Cassation"
        )

        for tool in (discovered, declared):
            properties = tool["inputSchema"]["properties"]
            self.assertNotIn("CASSATION_NATURE_DECISION", properties)
            self.assertTrue({
                "query",
                "matiere",
                "CASSATION_TYPE_PUBLICATION_BULLETIN",
                "date_debut",
                "date_fin",
                "page_size",
                "page_number",
            }.issubset(properties))


class MatiereObligatoireTest(unittest.TestCase):
    def test_le_schema_impose_la_matiere(self):
        declared = next(
            tool for tool in MCP_TOOLS
            if tool["name"] == "Search_Cour_Cassation"
        )
        schema = declared["inputSchema"]
        self.assertIn("matiere", schema["required"])
        matiere = schema["properties"]["matiere"]
        self.assertEqual(matiere["type"], "array")
        self.assertEqual(matiere["minItems"], 1)
        self.assertNotIn("TOUTES", matiere["items"]["enum"])
        self.assertNotIn("default", matiere)

    def test_matiere_absente_refusee_sans_appel_reseau(self):
        response = handle_search_cour_cassation({"query": "révocation dirigeant"}, "test")
        self.assertTrue(response["isError"])
        self.assertIn("obligatoire", response["content"][0]["text"])

    def test_matiere_inconnue_refusee(self):
        with self.assertRaises(ValueError) as erreur:
            formations_cassation(["FISCAL"])
        self.assertIn("FISCAL", str(erreur.exception))

    def test_toutes_n_est_plus_accepte(self):
        with self.assertRaises(ValueError):
            formations_cassation("TOUTES")

    def test_formations_par_matiere(self):
        matieres, formations = formations_cassation("COMMERCIAL")
        self.assertEqual(matieres, ["COMMERCIAL"])
        self.assertIn("CHAMBRE_COMMERCIALE", formations)
        self.assertNotIn("CHAMBRE_CRIMINELLE", formations)
        self.assertIn("ASSEMBLEE_PLENIERE", formations)

    def test_matieres_multiples_sans_doublon(self):
        matieres, formations = formations_cassation(["CIVIL", "COMMERCIAL", "CIVIL"])
        self.assertEqual(matieres, ["CIVIL", "COMMERCIAL"])
        self.assertEqual(len(formations), len(set(formations)))
        self.assertIn("CHAMBRE_CIVILE_1", formations)
        self.assertIn("CHAMBRE_COMMERCIALE", formations)
        self.assertNotIn("CHAMBRE_CRIMINELLE", formations)


if __name__ == "__main__":
    unittest.main()
