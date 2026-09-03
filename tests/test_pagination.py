import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from tools import research_corpus


def search_results(count, start=0):
    return [
        {
            "titles": [{"id": f"JURITEXT{start + index:06d}", "title": f"Décision {start + index}"}],
            "sections": [],
        }
        for index in range(count)
    ]


class FakeResearchClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def search_with_criteres(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


class PaginationTest(unittest.TestCase):
    def _research_search(self, responses, max_results=500):
        client = FakeResearchClient(responses)
        records, report = research_corpus._search_query(
            client, "faute grave", "cassation", None, None, max_results
        )
        return records, report, client.calls

    def test_total_absent_page_pleine_puis_partielle_collecte_toutes_les_pages(self):
        responses = [
            {"results": search_results(100)},
            {"results": search_results(50, 100)},
        ]
        records, report, calls = self._research_search(responses)
        self.assertEqual(len(records), 150)
        self.assertEqual(len(calls), 2)
        self.assertIsNone(report["total_api"])
        self.assertFalse(report["total_api_connu"])
        self.assertFalse(report["tronquee"])

    def test_total_connu_preserve_le_comportement(self):
        responses = [
            {"totalResultNumber": 150, "results": search_results(100)},
            {"totalResultNumber": 150, "results": search_results(50, 100)},
        ]
        records, report, calls = self._research_search(responses)
        self.assertEqual(len(records), 150)
        self.assertEqual(len(calls), 2)
        self.assertEqual(report["total_api"], 150)
        self.assertTrue(report["total_api_connu"])
        self.assertFalse(report["tronquee"])

    def test_page_partielle_sans_total_est_considerée_comme_fin_des_resultats(self):
        responses = [{"totalResultNumber": None, "results": search_results(50)}]
        records, report, calls = self._research_search(responses)
        self.assertEqual(len(records), 50)
        self.assertEqual(len(calls), 1)
        self.assertFalse(report["tronquee"])
        self.assertIsNone(report["total_api"])

    def test_plafond_sans_total_est_signale_comme_tronque(self):
        responses = [{"results": search_results(100)}]
        records, report, calls = self._research_search(responses, max_results=100)
        self.assertEqual(len(records), 100)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["page_size"], 100)
        self.assertTrue(report["tronquee"])
        self.assertIsNone(report["total_api"])

if __name__ == "__main__":
    unittest.main()
