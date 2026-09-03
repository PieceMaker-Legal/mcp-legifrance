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
    def test_caa_ville_envoie_le_filtre_juridiction_nature_avec_multivaleurs(self, search):
        search.return_value = {"totalResultNumber": 1, "results": [
            result("CAA_PARIS_1", "CAA Paris, 6 mai 2026"),
        ]}

        response = handle_search_caa({
            "query": "urbanisme",
            "CAA_VILLE": ["PARIS", "LYON"],
        }, "test")

        self.assertFalse(response["isError"])
        self.assertEqual(len(search.call_args_list), 1)
        filtres = search.call_args_list[0].kwargs["filtres"]
        self.assertIn(
            {
                "facette": "JURIDICTION_NATURE",
                "valeurs": ["COURS_APPEL"],
                "multiValeurs": {"COURS_APPEL": ["PARIS", "LYON"]},
            },
            filtres,
        )

    @patch("tools.handlers.legifrance_client.search_with_criteres")
    def test_caa_sans_ville_selectionne_toutes_les_cours_administratives_dappel(self, search):
        search.return_value = {"totalResultNumber": 0, "results": []}

        response = handle_search_caa({"query": "urbanisme"}, "test")

        self.assertFalse(response["isError"])
        filtres = search.call_args_list[0].kwargs["filtres"]
        self.assertIn(
            {
                "facette": "JURIDICTION_NATURE",
                "valeurs": ["COURS_APPEL"],
                "multiValeurs": {"COURS_APPEL": []},
            },
            filtres,
        )

    @patch("tools.handlers.legifrance_client.search_with_criteres")
    def test_caa_fait_un_seul_appel_et_transmet_la_pagination_telle_quelle(self, search):
        search.return_value = {"totalResultNumber": 42, "results": [
            result("CAA_X", "Décision X"),
        ]}

        response = handle_search_caa({
            "query": "urbanisme",
            "CAA_VILLE": ["PARIS"],
            "page_number": 3,
            "page_size": 20,
        }, "test")

        self.assertFalse(response["isError"])
        self.assertEqual(len(search.call_args_list), 1)
        kwargs = search.call_args_list[0].kwargs
        self.assertEqual(kwargs["page_number"], 3)
        self.assertEqual(kwargs["page_size"], 20)
        text = response["content"][0]["text"]
        self.assertIn("Total rendu par l'API:** 42 décisions", text)
        self.assertIn("Page:** 3 — 1 décision(s) affichée(s)", text)

    @patch("tools.handlers.legifrance_client.search_with_criteres")
    def test_caa_naplique_aucun_filtrage_sur_le_titre(self, search):
        search.return_value = {"totalResultNumber": 1, "results": [
            result("SANS_TITRE_CAA", "Décision sans mention CAA dans le titre"),
        ]}

        response = handle_search_caa({
            "query": "urbanisme",
            "CAA_VILLE": ["PARIS"],
        }, "test")

        self.assertFalse(response["isError"])
        text = response["content"][0]["text"]
        self.assertIn("SANS_TITRE_CAA", text)

    def test_caa_refuse_une_pagination_qui_depasse_la_limite_de_lapi(self):
        response = handle_search_caa({
            "query": "urbanisme",
            "page_number": 101,
            "page_size": 100,
        }, "test")

        self.assertTrue(response["isError"])
        text = response["content"][0]["text"]
        self.assertIn("<tool-use-error>", text)
        self.assertIn("10 000", text)

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
