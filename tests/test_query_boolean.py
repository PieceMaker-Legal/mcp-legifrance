import os
import sys
import unittest
from unittest.mock import patch


ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from tools.code_parser import parse_code_query
from tools.handlers import handle_search_cour_cassation
from tools.legifrance_client import LegifranceClient
from tools.query_parser import build_search_payload_champs, parse_query
from tools.research_corpus import _search_query


def search_result(text_id):
    return {"titles": [{"id": text_id, "title": text_id}], "sections": []}


class QueryBooleanTest(unittest.TestCase):
    def assert_clauses(self, query, expected):
        _operator, _search_type, criteria = parse_query(query)
        self.assertEqual(
            [[criterion["valeur"] for criterion in clause] for clause in criteria.clauses],
            expected,
        )

    def test_precedence_et_avant_ou_et_parentheses(self):
        self.assert_clauses("A ET B", [["A", "B"]])
        self.assert_clauses("A OU B", [["A"], ["B"]])
        self.assert_clauses("A ET B OU C", [["A", "B"], ["C"]])
        self.assert_clauses("A OU B ET C", [["A"], ["B", "C"]])
        self.assert_clauses("(A OU B) ET C", [["A", "C"], ["B", "C"]])

    def test_expressions_exactes_articles_et_code_sont_preserves(self):
        _operator, _search_type, criteria = parse_query(
            '"faute grave" ET L. 1234-1 OU préavis'
        )
        self.assertEqual(criteria.clauses[0][0]["valeur"], "faute grave")
        self.assertEqual(criteria.clauses[0][0]["typeRecherche"], "EXACTE")
        self.assertEqual(criteria.clauses[0][1]["valeur"], "L1234-1")
        self.assertEqual(criteria.clauses[1][0]["valeur"], "préavis")
        _operator, _search_type, code_criteria, field = parse_code_query(
            "L. 1234-1 OU préavis ET faute"
        )
        self.assertEqual(field, "ALL")
        self.assertEqual(
            [[criterion["valeur"] for criterion in clause] for clause in code_criteria.clauses],
            [["L1234-1"], ["préavis", "faute"]],
        )

    def test_requetes_vides_et_operateurs_orphelins_echouent_explicitement(self):
        with self.assertRaisesRegex(ValueError, "requête vide"):
            parse_query("  ")
        with self.assertRaisesRegex(ValueError, "sans terme"):
            parse_query("A ET")
        with self.assertRaisesRegex(ValueError, "sans terme"):
            parse_query("OU A")

    def test_nombre_de_clauses_est_borne_y_compris_avec_des_ou(self):
        query = " OU ".join(f"terme{i}" for i in range(65))
        with self.assertRaisesRegex(ValueError, "maximum 64 clauses"):
            parse_query(query)

    def test_client_envoie_une_requete_multichamps_et_preserve_pagination_tri_total(self):
        _operator, _search_type, criteria = parse_query("A ET B OU C")
        client = LegifranceClient()
        payloads = []

        def request(_endpoint, payload):
            payloads.append(payload)
            return {"totalResultNumber": 42, "results": [search_result("C")]}

        with patch.object(client, "_request", side_effect=request):
            response = client.search_with_criteres(
                "JURI", criteria, page_number=2, page_size=25,
                sort="DATE_DESC", second_sort="ID_DESC", type_pagination="ARTICLE",
            )

        self.assertEqual(response["totalResultNumber"], 42)
        self.assertEqual(len(payloads), 1)
        payload = payloads[0]
        recherche = payload["recherche"]
        self.assertEqual(recherche["pageNumber"], 2)
        self.assertEqual(recherche["pageSize"], 25)
        self.assertEqual(recherche["operateur"], "OU")
        self.assertEqual(payload["sort"], "DATE_DESC")
        self.assertEqual(payload["secondSort"], "ID_DESC")
        self.assertEqual(payload["typePagination"], "ARTICLE")
        self.assertEqual(
            [[criterion["valeur"] for criterion in field["criteres"]]
             for field in recherche["champs"]],
            [["A", "B"], ["C"]],
        )
        self.assertTrue(all(field["operateur"] == "ET" for field in recherche["champs"]))

    def test_build_payload_transforme_la_dnf_en_champs_piste(self):
        operator, type_champ, fields = build_search_payload_champs(
            "A OU B ET C", proximite=7
        )
        self.assertEqual(operator, "OU")
        self.assertEqual(type_champ, "ALL")
        self.assertEqual(
            [[criterion["valeur"] for criterion in field["criteres"]]
             for field in fields],
            [["A"], ["B", "C"]],
        )
        self.assertTrue(all(field["operateur"] == "ET" for field in fields))
        self.assertEqual(fields[1]["criteres"][1]["proximite"], 7)

        operator, _type_champ, fields = build_search_payload_champs("(A OU B) ET C")
        self.assertEqual(operator, "OU")
        self.assertEqual(
            [[criterion["valeur"] for criterion in field["criteres"]]
             for field in fields],
            [["A", "C"], ["B", "C"]],
        )

        operator, _type_champ, fields = build_search_payload_champs('"faute grave"')
        self.assertEqual(operator, "ET")
        self.assertEqual(len(fields), 1)
        self.assertIsNone(fields[0]["criteres"][0]["proximite"])

    def test_client_conserve_le_contrat_des_criteres_historiques(self):
        client = LegifranceClient()
        criteria = [
            {"valeur": "A", "operateur": "OU", "typeRecherche": "TOUS_LES_MOTS_DANS_UN_CHAMP"},
            {"valeur": "B", "operateur": "OU", "typeRecherche": "TOUS_LES_MOTS_DANS_UN_CHAMP"},
        ]
        with patch.object(client, "_request", return_value={"results": []}) as request:
            client.search_with_criteres("JURI", criteria, operateur="OU")
        recherche = request.call_args.args[1]["recherche"]
        self.assertEqual(recherche["operateur"], "OU")
        self.assertEqual(recherche["champs"][0]["operateur"], "OU")

    def test_client_honore_le_forcage_ou_dune_clause_unique(self):
        _operator, _search_type, criteria = parse_query("faute grave")
        self.assertIs(criteria[0], criteria.clauses[0][0])
        for criterion in criteria:
            criterion["operateur"] = "OU"

        client = LegifranceClient()
        with patch.object(client, "_request", return_value={"results": []}) as request:
            client.search_with_criteres("JURI", criteria, operateur="OU")

        recherche = request.call_args.args[1]["recherche"]
        self.assertEqual(recherche["operateur"], "OU")
        self.assertEqual(recherche["champs"][0]["operateur"], "OU")
        self.assertEqual(
            [criterion["operateur"] for criterion in recherche["champs"][0]["criteres"]],
            ["OU", "OU"],
        )

    @patch("tools.handlers.legifrance_client.search_with_criteres")
    def test_handler_transmet_le_plan_mixte_au_client(self, search):
        search.return_value = {"totalResultNumber": 1, "results": [search_result("AB")]}
        response = handle_search_cour_cassation({
            "query": "A ET B OU C",
            "matiere": "CIVIL",
        }, "test")

        self.assertFalse(response["isError"])
        criteria = search.call_args.kwargs["criteres"]
        self.assertEqual(
            [[item["valeur"] for item in clause] for clause in criteria.clauses],
            [["A", "B"], ["C"]],
        )

    def test_corpus_transmet_et_pagine_un_plan_mixte(self):
        class CorpusClient:
            def __init__(self):
                self.calls = []

            def search_with_criteres(self, **kwargs):
                self.calls.append(kwargs)
                return {
                    "totalResultNumber": 2,
                    "results": [search_result("AB"), search_result("C")],
                }

        client = CorpusClient()
        results, report = _search_query(
            client, "A ET B OU C", "cassation", None, None, 100
        )
        self.assertEqual([item["titles"][0]["id"] for item in results], ["AB", "C"])
        self.assertFalse(report["tronquee"])
        self.assertEqual(
            [[item["valeur"] for item in clause]
            for clause in client.calls[0]["criteres"].clauses],
            [["A", "B"], ["C"]],
        )


if __name__ == "__main__":
    unittest.main()
