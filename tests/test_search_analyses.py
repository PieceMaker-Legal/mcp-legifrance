import os
import sys
import unittest
from unittest.mock import patch


ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from tools.handlers import _complete_decision_analysis, _search_result_analysis


class SearchAnalysesTest(unittest.TestCase):
    def test_consultation_conserve_tous_les_elements_du_sommaire(self):
        with patch(
            "tools.handlers.legifrance_client.get_decision_text",
            return_value={"text": {"sommaire": [{
                "id": "SOMMAIRE001",
                "resumePrincipal": "Premier <mark>paragraphe</mark>.",
                "autreResume": "Second paragraphe.",
                "abstrats": [
                    "Premier <mark>paragraphe</mark>.",
                    "Premier abstrat.",
                    "Second abstrat.",
                    "Premier abstrat.",
                ],
            }]}},
        ):
            analysis, complete = _complete_decision_analysis("JURITEXT001", {})

        self.assertTrue(complete)
        self.assertEqual(
            analysis,
            "Premier **paragraphe**.\nSecond paragraphe.\nPremier abstrat.\nSecond abstrat.",
        )

    def test_repli_conserve_toutes_les_valeurs_et_les_marqueurs_de_coupe(self):
        result = {"sections": [{"extracts": [{
            "searchFieldName": "Abstrat",
            "values": ["[...]Premier fragment", "Second fragment[...]"],
        }]}]}

        self.assertEqual(
            _search_result_analysis(result),
            "[...]Premier fragment\nSecond fragment[...]",
        )


if __name__ == "__main__":
    unittest.main()
