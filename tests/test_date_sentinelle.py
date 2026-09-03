import os
import sys
import unittest
from unittest.mock import patch


ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from tools.legifrance_client import est_date_absente, borne_haute_reelle
from tools import research_corpus
from tools.handlers import handle_search_conseil_etat


class EstDateAbsenteTest(unittest.TestCase):
    def test_chaine_sentinelle_2999_01_01_est_absente(self):
        self.assertTrue(est_date_absente("2999-01-01"))

    def test_chaine_sentinelle_horodatee_est_absente(self):
        self.assertTrue(est_date_absente("2999-01-01T00:00:00.000+0000"))

    def test_annee_2999_avec_autre_date_est_absente(self):
        self.assertTrue(est_date_absente("2999-12-31"))

    def test_entier_millisecondes_sentinelle_est_absent(self):
        self.assertTrue(est_date_absente(32472144000000))

    def test_none_est_absent(self):
        self.assertTrue(est_date_absente(None))

    def test_chaine_vide_est_absente(self):
        self.assertTrue(est_date_absente(""))

    def test_zero_est_absent(self):
        self.assertTrue(est_date_absente(0))

    def test_date_reelle_en_chaine_nest_pas_absente(self):
        self.assertFalse(est_date_absente("2005-04-11"))

    def test_date_reelle_en_millisecondes_nest_pas_absente(self):
        self.assertFalse(est_date_absente(1113177600000))

    def test_chaine_non_analysable_nest_pas_absente(self):
        self.assertFalse(est_date_absente("en vigueur"))


class FormatDateResearchCorpusTest(unittest.TestCase):
    def test_sentinelle_en_millisecondes_rend_chaine_vide(self):
        self.assertEqual(research_corpus._format_date(32472144000000), "")

    def test_sentinelle_en_chaine_rend_chaine_vide(self):
        self.assertEqual(research_corpus._format_date("2999-01-01"), "")

    def test_date_normale_en_millisecondes_est_formatee(self):
        self.assertEqual(research_corpus._format_date(1113177600000), "2005-04-11")


class BorneHauteReelleTest(unittest.TestCase):
    def test_sentinelle_chaine_devient_derniere_date_reelle(self):
        self.assertEqual(borne_haute_reelle("2999-01-01"), "2998-12-31")

    def test_sentinelle_horodatee_devient_derniere_date_reelle(self):
        self.assertEqual(
            borne_haute_reelle("2999-01-01T00:00:00.000+0000"), "2998-12-31"
        )

    def test_annee_2999_avec_autre_date_devient_derniere_date_reelle(self):
        self.assertEqual(borne_haute_reelle("2999-12-31"), "2998-12-31")

    def test_date_reelle_est_inchangee(self):
        self.assertEqual(borne_haute_reelle("2026-09-03"), "2026-09-03")


class DateFilterResearchCorpusTest(unittest.TestCase):
    def test_borne_haute_sentinelle_est_normalisee_dans_le_filtre(self):
        filtres = research_corpus._date_filter("2020-01-01", "2999-01-01")
        self.assertEqual(filtres[0]["dates"]["end"], "2998-12-31")

    def test_absence_de_borne_haute_ne_cree_aucune_cle_end(self):
        filtres = research_corpus._date_filter("2020-01-01", None)
        self.assertNotIn("end", filtres[0]["dates"])


class HandlerBorneHauteTest(unittest.TestCase):
    @patch("tools.handlers.legifrance_client.search_with_criteres")
    def test_recherche_conseil_etat_envoie_la_borne_haute_normalisee(self, search):
        search.return_value = {"totalResultNumber": 0, "results": []}

        response = handle_search_conseil_etat(
            {"query": "urbanisme", "date_fin": "2999-01-01"}, "test"
        )

        self.assertFalse(response["isError"])
        filtres = search.call_args.kwargs["filtres"]
        date_filter = next(f for f in filtres if f["facette"] == "DATE_DECISION")
        self.assertEqual(date_filter["dates"]["end"], "2998-12-31")


if __name__ == "__main__":
    unittest.main()
