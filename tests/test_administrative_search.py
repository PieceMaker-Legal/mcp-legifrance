import os
import sys
import unittest
from unittest.mock import patch


ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from tools.handlers import handle_search_caa, handle_search_conseil_etat


def result(text_id, title):
    return {"titles": [{"id": text_id, "title": title}], "sections": []}


def results(count, prefix, title_prefix="Tribunal administratif"):
    return [
        result(f"{prefix}{index:03d}", f"{title_prefix} {index}")
        for index in range(count)
    ]


class AdministrativeSearchTest(unittest.TestCase):
    @patch("tools.handlers.legifrance_client.search_with_criteres")
    def test_conseil_etat_trouve_une_decision_de_la_deuxieme_page_cetat(self, search):
        search.side_effect = [
            {"totalResultNumber": 101, "results": results(100, "OTHER")},
            {"totalResultNumber": 101, "results": [
                result("CEPAGE2", "Conseil d'État, 5 mai 2026"),
            ]},
        ]

        response = handle_search_conseil_etat({"query": "urbanisme"}, "test")

        self.assertFalse(response["isError"])
        text = response["content"][0]["text"]
        self.assertIn("Conseil d'État filtré:** 1 décisions", text)
        self.assertIn("CEPAGE2", text)
        self.assertEqual([call.kwargs["page_number"] for call in search.call_args_list], [1, 2])

    @patch("tools.handlers.legifrance_client.search_with_criteres")
    def test_caa_ville_trouve_la_deuxieme_page_et_filtre_la_ville(self, search):
        search.side_effect = [
            {"totalResultNumber": 102, "results": results(100, "OTHER")},
            {"totalResultNumber": 102, "results": [
                result("CAA_PARIS_PAGE2", "CAA Paris, 6 mai 2026"),
                result("CAA_LYON_PAGE2", "CAA Lyon, 6 mai 2026"),
            ]},
        ]

        response = handle_search_caa({
            "query": "urbanisme",
            "CAA_VILLE": ["PARIS"],
        }, "test")

        self.assertFalse(response["isError"])
        text = response["content"][0]["text"]
        self.assertIn("CAA filtrées:** 1 décisions", text)
        self.assertIn("CAA_PARIS_PAGE2", text)
        self.assertNotIn("CAA_LYON_PAGE2", text)
        self.assertEqual([call.kwargs["page_number"] for call in search.call_args_list], [1, 2])

    @patch("tools.handlers.legifrance_client.search_with_criteres")
    def test_pagination_est_appliquee_apres_le_filtre_caa(self, search):
        search.return_value = {"totalResultNumber": 3, "results": [
            result("CAA_PARIS_1", "CAA Paris, première décision"),
            result("CAA_PARIS_2", "CAA Paris, deuxième décision"),
            result("CAA_LYON", "CAA Lyon, autre décision"),
        ]}

        response = handle_search_caa({
            "query": "urbanisme",
            "CAA_VILLE": ["PARIS"],
            "page_number": 2,
            "page_size": 1,
        }, "test")

        text = response["content"][0]["text"]
        self.assertIn("CAA filtrées:** 2 décisions", text)
        self.assertIn("Page:** 2 — 1 décision(s) affichée(s)", text)
        self.assertIn("CAA_PARIS_2", text)
        self.assertNotIn("CAA_PARIS_1", text)

    @patch("tools.handlers.legifrance_client.search_with_criteres")
    def test_limite_cetat_est_signalee_comme_troncature(self, search):
        search.side_effect = [
            {"totalResultNumber": 600, "results": results(
                100, f"CE{page}", "Conseil d'État"
            )}
            for page in range(5)
        ]

        response = handle_search_conseil_etat({"query": "urbanisme"}, "test")

        self.assertFalse(response["isError"])
        text = response["content"][0]["text"]
        self.assertIn("Limite de parcours CETAT atteinte", text)
        self.assertIn("résultats filtrés et leur total sont partiels", text)
        self.assertEqual(len(search.call_args_list), 5)
        self.assertEqual(search.call_args_list[-1].kwargs["page_number"], 5)


if __name__ == "__main__":
    unittest.main()
