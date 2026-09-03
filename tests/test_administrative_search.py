import os
import sys
import unittest
from unittest.mock import patch


ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from config.mcp_definitions import INITIALIZE_INSTRUCTIONS
from tools.handlers import (
    handle_search_caa,
    handle_search_code,
    handle_search_conseil_etat,
    handle_search_cour_cassation,
)


def result(text_id, title):
    return {"titles": [{"id": text_id, "title": title}], "sections": []}


def results(count, prefix, title_prefix="Tribunal administratif"):
    return [
        result(f"{prefix}{index:03d}", f"{title_prefix} {index}")
        for index in range(count)
    ]


class AdministrativeSearchTest(unittest.TestCase):
    @patch("tools.handlers.legifrance_client.search_with_criteres")
    def test_conseil_etat_envoie_le_filtre_juridiction_nature_avec_multivaleurs_et_un_seul_appel(self, search):
        search.return_value = {"totalResultNumber": 1, "results": [
            result("CE1", "Décision quelconque"),
        ]}

        response = handle_search_conseil_etat({
            "query": "urbanisme",
            "page_number": 2,
            "page_size": 7,
        }, "test")

        self.assertFalse(response["isError"])
        self.assertEqual(len(search.call_args_list), 1)
        kwargs = search.call_args_list[0].kwargs
        self.assertIn(
            {
                "facette": "JURIDICTION_NATURE",
                "valeurs": ["CONSEIL_ETAT"],
                "multiValeurs": {"CONSEIL_ETAT": []},
            },
            kwargs["filtres"],
        )
        self.assertEqual(kwargs["page_number"], 2)
        self.assertEqual(kwargs["page_size"], 7)

    @patch("tools.handlers.legifrance_client.search_with_criteres")
    def test_conseil_etat_naplique_aucun_filtrage_sur_le_titre(self, search):
        search.return_value = {"totalResultNumber": 1, "results": [
            result("CE_SANS_TITRE", "Décision sans mention d'aucune juridiction dans le titre"),
        ]}

        response = handle_search_conseil_etat({"query": "urbanisme"}, "test")

        self.assertFalse(response["isError"])
        text = response["content"][0]["text"]
        self.assertIn("CE_SANS_TITRE", text)

    @patch("tools.handlers.legifrance_client.search_with_criteres")
    def test_conseil_etat_total_superieur_a_500_declenche_le_refus(self, search):
        search.return_value = {"totalResultNumber": 600, "results": results(10, "CE")}

        response = handle_search_conseil_etat({"query": "urbanisme"}, "test")

        self.assertTrue(response["isError"])
        text = response["content"][0]["text"]
        self.assertIn("<tool-use-error>", text)
        self.assertIn("600", text)
        self.assertIn("Au-delà de 500 résultats", INITIALIZE_INSTRUCTIONS)
        self.assertIn("Au-delà de 500 résultats", text)

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

    def test_caa_refuse_toujours_une_pagination_qui_depasse_500_sans_appel_reseau(self):
        response = handle_search_caa({
            "query": "urbanisme",
            "page_number": 101,
            "page_size": 100,
        }, "test")

        self.assertTrue(response["isError"])
        text = response["content"][0]["text"]
        self.assertIn("<tool-use-error>", text)
        self.assertIn("Page hors contrat", text)
        self.assertIn("500", text)
        self.assertNotIn("10 000", text)

    @patch("tools.handlers.legifrance_client.search_with_criteres")
    def test_caa_total_superieur_a_500_declenche_le_refus_partage(self, search):
        search.return_value = {"totalResultNumber": 501, "results": results(10, "CAA")}

        response = handle_search_caa({"query": "urbanisme"}, "test")

        self.assertTrue(response["isError"])
        text = response["content"][0]["text"]
        self.assertIn("<tool-use-error>", text)
        self.assertIn("501", text)
        self.assertIn("Au-delà de 500 résultats", text)

    @patch("tools.handlers.legifrance_client.search_with_criteres")
    def test_cassation_total_superieur_a_500_declenche_le_refus_partage(self, search):
        search.return_value = {"totalResultNumber": 723, "results": results(10, "CC")}

        response = handle_search_cour_cassation({
            "query": "faute",
            "matiere": "CIVIL",
        }, "test")

        self.assertTrue(response["isError"])
        text = response["content"][0]["text"]
        self.assertIn("<tool-use-error>", text)
        self.assertIn("723", text)
        self.assertIn("Au-delà de 500 résultats", text)

    @patch("tools.handlers.legifrance_client.search_with_criteres")
    def test_search_code_total_superieur_a_500_declenche_le_refus(self, search):
        search.return_value = {"totalResultNumber": 900, "results": []}

        response = handle_search_code({"query": "contrat de travail"}, "test")

        self.assertTrue(response["isError"])
        text = response["content"][0]["text"]
        self.assertIn("<tool-use-error>", text)
        self.assertIn("900", text)
        self.assertIn("Au-delà de 500 résultats", text)

    @patch("tools.handlers.legifrance_client.search_with_criteres")
    def test_cassation_borne_une_pagination_invalide_aux_defauts_du_schema(self, search):
        search.return_value = {"totalResultNumber": 1, "results": [
            result("CC1", "Décision"),
        ]}

        response = handle_search_cour_cassation({
            "query": "faute",
            "matiere": "CIVIL",
            "page_size": "pas-un-entier",
            "page_number": 0,
        }, "test")

        self.assertFalse(response["isError"])
        kwargs = search.call_args_list[0].kwargs
        # page_size non convertible retombe sur le défaut du schéma (10) ;
        # page_number est borné à 1 au minimum.
        self.assertEqual(kwargs["page_size"], 10)
        self.assertEqual(kwargs["page_number"], 1)

    @patch("tools.handlers.legifrance_client.search_with_criteres")
    def test_cassation_borne_un_page_size_hors_maximum(self, search):
        search.return_value = {"totalResultNumber": 1, "results": [
            result("CC2", "Décision"),
        ]}

        response = handle_search_cour_cassation({
            "query": "faute",
            "matiere": "CIVIL",
            "page_size": 5000,
        }, "test")

        self.assertFalse(response["isError"])
        kwargs = search.call_args_list[0].kwargs
        self.assertEqual(kwargs["page_size"], 100)


if __name__ == "__main__":
    unittest.main()
