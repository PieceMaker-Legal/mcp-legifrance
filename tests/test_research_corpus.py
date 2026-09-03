import json
import os
import sys
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from tools.research_corpus import (
    build_research_corpus,
    rebuild_research_mapping,
)
from tools.research_report_compiler import validate_and_compile


def search_result(text_id):
    return {"titles": [{"id": text_id, "title": f"Décision {text_id}"}], "sections": []}


class FakeLegifranceClient:
    def __init__(self):
        self.fetch_calls = []

    def search_with_criteres(self, **kwargs):
        values = " ".join(item["valeur"] for item in kwargs["criteres"])
        ids = ["JURITEXT001", "JURITEXT002"] if "premiere" in values else ["JURITEXT002", "JURITEXT003"]
        return {"totalResultNumber": len(ids), "results": [search_result(value) for value in ids]}

    def get_decision_text(self, text_id):
        self.fetch_calls.append(text_id)
        return {"text": {
            "id": text_id,
            "titre": f"Arrêt {text_id[-3:]}",
            "juridiction": "Cour de cassation",
            "formation": "CHAMBRE_COMMERCIALE",
            "dateTexte": 1_700_000_000_000,
            "numeroAffaire": f"22-{text_id[-3:]}",
            "solution": "REJET",
            "typePublicationBulletin": "PUBLIE",
            "sommaire": "La révocation doit respecter la contradiction.",
            "texte": (
                "La société anonyme examine la révocation de son directeur général.\n\n"
                "Le dirigeant doit avoir connaissance des motifs et pouvoir présenter ses observations.\n\n"
                "PAR CES MOTIFS, REJETTE le pourvoi."
            ),
        }}


class MultiSummaryClient(FakeLegifranceClient):
    def get_decision_text(self, text_id):
        response = super().get_decision_text(text_id)
        response["text"]["sommaire"] = [{
            "resumePrincipal": "Analyse première.",
            "abstrats": ["Analyse première.", "Analyse seconde.", "Analyse seconde."],
        }]
        return response


class GenericLawClient:
    def __init__(self, text_id, body):
        self.text_id = text_id
        self.body = body

    def search_with_criteres(self, **kwargs):
        return {
            "totalResultNumber": 1,
            "results": [search_result(self.text_id)],
        }

    def get_decision_text(self, text_id):
        return {"text": {
            "id": text_id,
            "titre": f"Arrêt {text_id[-3:]}",
            "juridiction": "Cour de cassation",
            "formation": "CHAMBRE_SOCIALE",
            "dateTexte": 1_700_000_000_000,
            "numeroAffaire": "22-001",
            "solution": "REJET",
            "texte": self.body,
        }}


class OverLimitClient:
    """Simule deux juridictions dont les totaux cumulés dépassent la limite."""
    def __init__(self):
        self.search_calls = []
        self.fetch_calls = []

    def search_with_criteres(self, **kwargs):
        self.search_calls.append(kwargs)
        values = kwargs["filtres"][0].get("valeurs", [])
        total = 250 if values == ["Cour de cassation"] else 251
        return {"totalResultNumber": total, "results": [search_result("JURITEXT000")]}

    def get_decision_text(self, text_id):
        self.fetch_calls.append(text_id)
        raise AssertionError("aucun téléchargement ne doit commencer")


class EmptyResultsClient:
    def __init__(self):
        self.search_calls = []
        self.fetch_calls = []

    def search_with_criteres(self, **kwargs):
        self.search_calls.append(kwargs)
        return {"totalResultNumber": 0, "results": []}

    def get_decision_text(self, text_id):
        self.fetch_calls.append(text_id)
        raise AssertionError("un corpus vide ne télécharge aucun texte")


class ResearchCorpusTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="legifrance-research-")
        self.addCleanup(self.temp.cleanup)

    def test_construction_telecharge_toute_la_formulation_unique(self):
        client = FakeLegifranceClient()
        info = build_research_corpus({
            "question": "Conditions de révocation",
            "query": "premiere révocation",
            "juridictions": ["cassation"],
            "output_dir": self.temp.name,
            "fetch_workers": 2,
        }, client=client)
        self.assertEqual(info["identified"], 2)
        self.assertEqual(info["downloaded"], 2)
        self.assertEqual(sorted(client.fetch_calls), ["JURITEXT001", "JURITEXT002"])
        self.assertGreater(info["tokens_input_estimated"], 0)
        self.assertEqual(info["model_reviewed"], 2)
        with open(info["telemetry"], encoding="utf-8") as handle:
            telemetry = json.load(handle)
        self.assertEqual(telemetry["total_resultats_cumules_avant_deduplication"], 2)

    def test_index_contient_l_analyse_officielle_complete(self):
        info = build_research_corpus({
            "question": "Conditions de révocation",
            "query": "premiere révocation",
            "juridictions": ["cassation"],
            "output_dir": self.temp.name,
            "fetch_workers": 1,
        }, client=MultiSummaryClient())

        with open(info["index"], encoding="utf-8") as handle:
            index = handle.read()
        self.assertIn("Analyse officielle complète", index)
        self.assertIn("Analyse première.<br>Analyse seconde.", index)
        self.assertEqual(index.count("Analyse première."), 2)

    def test_rejette_l_ancien_tableau_queries(self):
        with self.assertRaisesRegex(ValueError, "`queries` n'est plus accepté"):
            build_research_corpus({
                "question": "Conditions de révocation",
                "queries": ["révocation"],
                "output_dir": self.temp.name,
            }, client=FakeLegifranceClient())

    def test_rejette_query_qui_n_est_pas_une_chaine(self):
        for query in ([], {}, 42, None):
            with self.subTest(query=query), self.assertRaisesRegex(ValueError, "chaîne de caractères"):
                build_research_corpus({
                    "question": "Conditions de révocation",
                    "query": query,
                    "output_dir": self.temp.name,
                }, client=FakeLegifranceClient())

    def test_total_zero_produit_un_corpus_vide_sans_telechargement(self):
        client = EmptyResultsClient()
        info = build_research_corpus({
            "question": "Conditions de révocation",
            "query": "révocation ET contradictoire",
            "output_dir": self.temp.name,
        }, client=client)
        self.assertEqual((info["identified"], info["downloaded"], info["scanned"]), (0, 0, 0))
        self.assertEqual(client.fetch_calls, [])
        self.assertEqual(len(client.search_calls), 1)
        with open(info["telemetry"], encoding="utf-8") as handle:
            telemetry = json.load(handle)
        self.assertNotIn("tronquee", telemetry["contrôle_préalable"][0])
        self.assertFalse(telemetry["requêtes"][0]["tronquee"])

    def test_refuse_plus_de_500_resultats_avant_tout_telechargement(self):
        client = OverLimitClient()
        with self.assertRaisesRegex(ValueError, "501 résultats cumulés") as caught:
            build_research_corpus({
                "question": "Conditions de révocation",
                "query": "révocation ET contradictoire",
                "juridictions": ["cassation", "appel"],
                "output_dir": self.temp.name,
            }, client=client)
        self.assertIn("guillemets", str(caught.exception))
        self.assertEqual(len(client.search_calls), 2)
        self.assertEqual(client.fetch_calls, [])

    def test_question_generique_est_lotee_avec_le_texte_integral(self):
        body = (
            "Le salarié invoque une faute grave et conteste l'absence de préavis.\n\n"
            "La cour retient que les griefs ne rendaient pas impossible son maintien."
        )
        info = build_research_corpus({
            "question": "La faute grave prive-t-elle le salarié de préavis ?",
            "query": "faute grave préavis",
            "output_dir": self.temp.name,
            "fetch_workers": 1,
        }, client=GenericLawClient("JURITEXTFAUTE", body))

        self.assertEqual(info["model_reviewed"], 1)
        self.assertEqual(info["batches"], 1)
        title = os.path.basename(info["folder"])
        self.assertRegex(
            title,
            r"^\d{4}-\d{2}-\d{2} - La faute grave prive-t-elle le salarié de préavis$",
        )
        self.assertEqual(info["report"], info["folder"] + ".md")
        self.assertTrue(os.path.isfile(os.path.join(info["folder"], "README.md")))
        self.assertTrue(os.path.isfile(os.path.join(info["folder"], "recompile_research.py")))
        with open(os.path.join(info["folder"], "batch-plan.json"), encoding="utf-8") as handle:
            plan = json.load(handle)
        self.assertEqual(plan[0]["decisions"], ["JURITEXTFAUTE"])
        with open(os.path.join(info["folder"], plan[0]["fichier"]), encoding="utf-8") as handle:
            self.assertIn(body, handle.read())

    def test_sigle_pca_n_exclut_pas_la_decision_de_la_revue_modele(self):
        body = (
            "La SA a révoqué son PCA sans l'avoir mis en mesure de présenter "
            "ses observations."
        )
        info = build_research_corpus({
            "question": "Conditions de révocation d'un PCA",
            "query": "révocation PCA",
            "output_dir": self.temp.name,
            "fetch_workers": 1,
        }, client=GenericLawClient("JURITEXTPCA", body))

        decisions_path = os.path.join(info["folder"], "decisions.jsonl")
        with open(decisions_path, encoding="utf-8") as handle:
            decision = json.loads(handle.readline())
        decision.update({
            "candidat_cartographie_modele": False,
            "criteres_filtre_trouves": [],
            "contextes_cartographie": [],
        })
        with open(decisions_path, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(decision, ensure_ascii=False) + "\n")
        telemetry_path = os.path.join(info["folder"], "telemetry.json")
        with open(telemetry_path, encoding="utf-8") as handle:
            telemetry = json.load(handle)
        telemetry["filtre_candidature"] = {"criteres": ["revocation"]}
        with open(telemetry_path, "w", encoding="utf-8") as handle:
            json.dump(telemetry, handle)

        rebuilt = rebuild_research_mapping({"folder": info["folder"]})
        self.assertEqual(rebuilt["model_reviewed"], 1)
        with open(os.path.join(info["folder"], "batch-plan.json"), encoding="utf-8") as handle:
            plan = json.load(handle)
        self.assertEqual(plan[0]["decisions"], ["JURITEXTPCA"])
        with open(decisions_path, encoding="utf-8") as handle:
            rebuilt_decision = json.loads(handle.readline())
        self.assertNotIn("candidat_cartographie_modele", rebuilt_decision)
        with open(telemetry_path, encoding="utf-8") as handle:
            rebuilt_telemetry = json.load(handle)
        self.assertNotIn("filtre_candidature", rebuilt_telemetry)
        self.assertEqual(rebuilt_telemetry["decisions_revue_modele"], 1)

    def test_validation_exige_une_citation_litterale(self):
        info = build_research_corpus({
            "question": "Conditions de révocation",
            "query": "premiere révocation",
            "output_dir": self.temp.name,
            "fetch_workers": 1,
        }, client=FakeLegifranceClient())
        cards_path = os.path.join(info["folder"], "cards", "lot-001.jsonl")
        quote = "Le dirigeant doit avoir connaissance des motifs et pouvoir présenter ses observations."
        with open(cards_path, "w", encoding="utf-8") as handle:
            for text_id in ("JURITEXT001", "JURITEXT002"):
                pertinent = text_id == "JURITEXT001"
                handle.write(json.dumps({
                    "id": text_id,
                    "pertinent": pertinent,
                    "solution": "rejet",
                    "citation_exacte": quote if pertinent else "",
                }, ensure_ascii=False) + "\n")
        result = validate_and_compile(info["folder"])
        self.assertTrue(result["coverage_complete"])
        self.assertEqual(result["report"], info["report"])
        self.assertTrue(os.path.isfile(info["report"]))
        with open(info["report"], encoding="utf-8") as handle:
            report = handle.read()
        self.assertIn("## Couverture", report)
        self.assertIn("## Matrice des décisions pertinentes", report)
        self.assertIn("| Décision | Solution | Citation | Source |", report)
        self.assertIn("JURITEXT001", report)
        self.assertNotIn("JURITEXT002", report)
        with open(result["remaining_work"], encoding="utf-8") as handle:
            self.assertIn("Validation complète. Aucun travail restant.", handle.read())

    def test_compilateur_indique_les_fiches_restantes(self):
        info = build_research_corpus({
            "question": "Conditions de révocation",
            "query": "premiere révocation",
            "output_dir": self.temp.name,
            "fetch_workers": 1,
        }, client=FakeLegifranceClient())
        cards_path = os.path.join(info["folder"], "cards", "lot-001.jsonl")
        with open(cards_path, "w", encoding="utf-8") as handle:
            handle.write(json.dumps({
                "id": "JURITEXT001",
                "pertinent": False,
                "solution": "",
                "citation_exacte": "",
            }, ensure_ascii=False) + "\n")

        result = validate_and_compile(info["folder"])
        self.assertFalse(result["coverage_complete"])
        with open(result["remaining_work"], encoding="utf-8") as handle:
            remaining = handle.read()
        self.assertIn("Fiches manquantes à produire", remaining)
        self.assertIn("JURITEXT002", remaining)

    def test_compilateur_indique_toutes_les_fiches_quand_cards_est_vide(self):
        info = build_research_corpus({
            "question": "Conditions de révocation",
            "query": "premiere révocation",
            "output_dir": self.temp.name,
            "fetch_workers": 1,
        }, client=FakeLegifranceClient())

        result = validate_and_compile(info["folder"])
        self.assertFalse(result["coverage_complete"])
        self.assertEqual(result["cards"], 0)
        with open(result["remaining_work"], encoding="utf-8") as handle:
            remaining = handle.read()
        self.assertIn("JURITEXT001", remaining)
        self.assertIn("JURITEXT002", remaining)


if __name__ == "__main__":
    unittest.main()
