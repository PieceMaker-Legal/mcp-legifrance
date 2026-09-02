import os
import sys
import unittest
from unittest.mock import patch


ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from tools.bodacc_client import BodaccClient
from tools.handlers import handle_tracking_bodacc


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class BodaccClientTest(unittest.TestCase):
    def test_procedure_collective_fournit_les_champs_du_rendu_et_une_alerte(self):
        payload = {
            "total_count": 1,
            "records": [{"record": {"fields": {
                "dateparution": "2026-01-10",
                "typeavis_lib": "Ouverture d'une procédure collective",
                "tribunal": "Tribunal de commerce de Paris",
                "jugement": "Liquidation judiciaire",
                "commercant": "Exemple SA",
            }}}],
        }
        with patch("tools.bodacc_client.requests.get", return_value=FakeResponse(payload)):
            result = BodaccClient().get_procedures_collectives("123456789")

        self.assertTrue(result["success"])
        self.assertTrue(result["has_procedure"])
        self.assertEqual(result["total_annonces"], 1)
        self.assertEqual(len(result["procedures"]), 1)
        self.assertEqual(result["alertes"], ["⚠️ 1 procédure(s) collective(s)"])

    def test_absence_de_procedure_ne_cree_pas_d_alerte(self):
        with patch(
            "tools.bodacc_client.requests.get",
            return_value=FakeResponse({"total_count": 0, "records": []}),
        ):
            result = BodaccClient().get_procedures_collectives("123456789")

        self.assertTrue(result["success"])
        self.assertFalse(result["has_procedure"])
        self.assertEqual(result["procedures"], [])
        self.assertEqual(result["total_annonces"], 0)
        self.assertEqual(result["alertes"], [])

    def test_handler_ne_rend_pas_une_procedure_comme_absence_d_alerte(self):
        payload = {
            "total_count": 1,
            "records": [{"record": {"fields": {
                "dateparution": "2026-01-10",
                "typeavis_lib": "Ouverture d'une procédure collective",
            }}}],
        }
        with patch("tools.bodacc_client.requests.get", return_value=FakeResponse(payload)):
            response = handle_tracking_bodacc({
                "siren": "123456789",
                "type_recherche": "procedures_collectives",
            }, "test-user")

        summary = response["content"][0]["text"]
        self.assertIn("Total annonces BODACC:** 1", summary)
        self.assertIn("⚠️ 1 procédure(s) collective(s)", summary)
        self.assertNotIn("Aucune alerte détectée", summary)


if __name__ == "__main__":
    unittest.main()
