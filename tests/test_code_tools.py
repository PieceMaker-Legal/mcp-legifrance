import os
import sys
import unittest
from unittest.mock import patch


ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from config.mcp_definitions import MCP_TOOLS
from tools.handlers import handle_consulter_article, handle_search_code


class CodeToolsTest(unittest.TestCase):
    def test_consulter_article_est_annonce(self):
        definition = next(
            tool for tool in MCP_TOOLS if tool["name"] == "consulter_article"
        )
        schema = definition["inputSchema"]
        self.assertEqual(schema["required"], ["article_id"])
        self.assertEqual(
            schema["properties"]["article_id"]["pattern"],
            "^LEGIARTI[0-9]+$",
        )

    @patch("tools.handlers.legifrance_client.get_article")
    def test_consulter_article_retourne_texte_contexte_et_lien(self, get_article):
        get_article.return_value = {
            "article": {
                "num": "L1235-3",
                "texte": "Texte intégral officiel.",
                "dateDebut": 1522540800000,
                "dateFin": 0,
                "sectionParentTitre": "Indemnisation du licenciement",
                "context": {"titreTxt": [{"titre": "Code du travail"}]},
            }
        }

        response = handle_consulter_article(
            {"article_id": "LEGIARTI000036762052"}, "test"
        )

        self.assertFalse(response["isError"])
        text = response["content"][0]["text"]
        self.assertIn("Code du travail", text)
        self.assertIn("Texte intégral officiel.", text)
        self.assertIn("LEGIARTI000036762052", text)
        self.assertIn(
            "https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000036762052",
            text,
        )
        get_article.assert_called_once_with("LEGIARTI000036762052")

    @patch("tools.handlers.legifrance_client.search_with_criteres")
    def test_search_code_applique_date_tri_et_formate_les_extraits(self, search):
        search.return_value = {
            "totalResultNumber": 1,
            "results": [{
                "titles": [{
                    "title": "Code du travail",
                    "cid": "LEGITEXT000006072050",
                }],
                "sections": [{
                    "title": "Section 1 : Dispositions communes.",
                    "extracts": [{
                        "id": "LEGIARTI000036762052",
                        "title": "L1235-3",
                        "legalStatus": "VIGUEUR",
                        "dateDebut": "2018-04-01T00:00:00.000+0000",
                        "dateFin": "2999-01-01T00:00:00.000+0000",
                        "values": ["[...]Si le licenciement survient[...]"],
                    }],
                }],
            }],
        }

        response = handle_search_code({
            "query": "L. 1235-3",
            "date": "2020-01-15",
            "sort": "DATE_VERSION_DESC",
            "page_size": 5,
        }, "test")

        self.assertFalse(response["isError"])
        kwargs = search.call_args.kwargs
        self.assertEqual(kwargs["sort"], "DATE_VERSION_DESC")
        self.assertEqual(kwargs["filtres"], [{
            "facette": "DATE_VERSION",
            "singleDate": "2020-01-15",
        }])
        self.assertEqual(kwargs["type_pagination"], "ARTICLE")

        text = response["content"][0]["text"]
        self.assertIn("Date de vigueur:** 2020-01-15", text)
        self.assertIn("Article L1235-3", text)
        self.assertIn("VIGUEUR · depuis le 2018-04-01", text)
        self.assertIn("Si le licenciement survient", text)
        self.assertIn("LEGIARTI000036762052", text)

    @patch("tools.handlers.legifrance_client.search_with_criteres")
    def test_search_code_refuse_une_date_invalide_sans_appeler_api(self, search):
        response = handle_search_code({
            "query": "L1235-3",
            "date": "15/01/2020",
        }, "test")

        self.assertTrue(response["isError"])
        self.assertIn("Date de vigueur invalide", response["content"][0]["text"])
        search.assert_not_called()


if __name__ == "__main__":
    unittest.main()
