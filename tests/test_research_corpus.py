import json
import os
import sys
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from tools.research_corpus import build_research_corpus, validate_research_cards


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


class ResearchCorpusTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="legifrance-research-")
        self.addCleanup(self.temp.cleanup)

    def test_construction_deduplique_et_telecharge_tout(self):
        client = FakeLegifranceClient()
        info = build_research_corpus({
            "question": "Conditions de révocation",
            "queries": ["premiere révocation", "seconde révocation"],
            "juridictions": ["cassation"],
            "output_dir": self.temp.name,
            "fetch_workers": 2,
        }, client=client)
        self.assertEqual(info["identified"], 3)
        self.assertEqual(info["downloaded"], 3)
        self.assertEqual(sorted(client.fetch_calls), ["JURITEXT001", "JURITEXT002", "JURITEXT003"])
        self.assertGreater(info["tokens_input_estimated"], 0)

    def test_validation_exige_une_citation_litterale(self):
        info = build_research_corpus({
            "question": "Conditions de révocation",
            "queries": ["premiere révocation"],
            "output_dir": self.temp.name,
            "fetch_workers": 1,
        }, client=FakeLegifranceClient())
        cards_path = os.path.join(info["folder"], "cards", "lot-001.jsonl")
        quote = "Le dirigeant doit avoir connaissance des motifs et pouvoir présenter ses observations."
        with open(cards_path, "w", encoding="utf-8") as handle:
            for text_id in ("JURITEXT001", "JURITEXT002"):
                handle.write(json.dumps({
                    "id": text_id,
                    "pertinent": True,
                    "question_juridique": "contradictoire",
                    "faits_determinants": [],
                    "solution": "rejet",
                    "portee": "condition procédurale",
                    "sens": "neutre",
                    "citation_exacte": quote,
                    "incertitudes": [],
                }, ensure_ascii=False) + "\n")
        result = validate_research_cards({"folder": info["folder"]})
        self.assertTrue(result["coverage_complete"])


if __name__ == "__main__":
    unittest.main()

