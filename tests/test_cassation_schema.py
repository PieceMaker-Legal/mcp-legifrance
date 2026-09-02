import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from config.mcp_definitions import MCP_TOOLS
from mcp_stdio_server import process_request


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


if __name__ == "__main__":
    unittest.main()
