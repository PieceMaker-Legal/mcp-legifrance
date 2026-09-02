import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from tools import bulk_download, research_corpus


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
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="legifrance-pagination-")
        self.addCleanup(self.temp.cleanup)

    def _research_search(self, responses, max_results=500):
        client = FakeResearchClient(responses)
        records, report = research_corpus._search_query(
            client, "faute grave", "cassation", None, None, max_results
        )
        return records, report, client.calls

    def _bulk_download(self, responses, max_results=500):
        with patch(
            "tools.bulk_download.legifrance_client.search_with_criteres",
            side_effect=responses,
        ) as search:
            info = bulk_download.download_query_results({
                "query": "faute grave",
                "juridiction": "cassation",
                "max_results": max_results,
                "output_dir": self.temp.name,
            })
        with open(
            os.path.join(info["folder"], bulk_download.MARKER_NAME),
            encoding="utf-8",
        ) as handle:
            marker = json.load(handle)
        with open(os.path.join(info["folder"], "index.md"), encoding="utf-8") as handle:
            index = handle.read()
        return info, marker, index, search.call_args_list

    def test_total_absent_page_pleine_puis_partielle_collecte_les_deux_parcours(self):
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

        info, marker, index, calls = self._bulk_download(responses)
        self.assertEqual(info["downloaded"], 150)
        self.assertEqual(len(calls), 2)
        self.assertIsNone(info["total"])
        self.assertFalse(info["total_api_connu"])
        self.assertFalse(info["truncated"])
        self.assertIsNone(marker["total"])
        self.assertIn("Total API** : inconnu", index)

    def test_total_connu_preserve_le_comportement_des_deux_parcours(self):
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

        info, marker, index, calls = self._bulk_download(responses)
        self.assertEqual(info["total"], 150)
        self.assertTrue(info["total_api_connu"])
        self.assertFalse(info["truncated"])
        self.assertEqual(marker["total"], 150)
        self.assertIn("Total API** : 150", index)
        self.assertEqual(len(calls), 2)

    def test_page_partielle_sans_total_est_considerée_comme_fin_des_resultats(self):
        responses = [{"totalResultNumber": None, "results": search_results(50)}]
        records, report, calls = self._research_search(responses)
        self.assertEqual(len(records), 50)
        self.assertEqual(len(calls), 1)
        self.assertFalse(report["tronquee"])
        self.assertIsNone(report["total_api"])

        info, marker, _index, calls = self._bulk_download(responses)
        self.assertEqual(info["downloaded"], 50)
        self.assertFalse(info["truncated"])
        self.assertIsNone(marker["total"])
        self.assertEqual(len(calls), 1)

    def test_plafond_sans_total_est_signale_comme_tronque_dans_les_deux_parcours(self):
        responses = [{"results": search_results(100)}]
        records, report, calls = self._research_search(responses, max_results=100)
        self.assertEqual(len(records), 100)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["page_size"], 100)
        self.assertTrue(report["tronquee"])
        self.assertIsNone(report["total_api"])

        info, marker, _index, calls = self._bulk_download(responses, max_results=100)
        self.assertEqual(info["downloaded"], 100)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].kwargs["page_size"], 100)
        self.assertTrue(info["truncated"])
        self.assertTrue(marker["truncated"])
        self.assertIsNone(info["total"])


if __name__ == "__main__":
    unittest.main()
