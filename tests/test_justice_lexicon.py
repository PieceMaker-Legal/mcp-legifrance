import os
import sys
import unittest
from unittest.mock import Mock, patch


ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from tools.handlers import handle_dictionnaire_juridique
from tools.justice_lexicon import (
    JusticeLexiconClient,
    JusticeLexiconError,
    parse_lexicon_page,
)


SAMPLE_HTML = """
<html><body><div id="lexique-content"><dl>
  <dt class="lexique-content-titre"><a id="Acces_au_droit"></a>
    Accès au droit
  </dt>
  <dd><p>Possibilité de connaître ses droits et obligations.</p></dd>
  <dt class="lexique-content-titre"><a id="Action_civile"></a>Action civile</dt>
  <dd><p>Action ouverte à la victime.</p><p>Elle vise la réparation.</p></dd>
  <dt class="lexique-content-titre"><a id="Assignation"></a>Assignation</dt>
  <dd><p>Acte de procédure payant et rédigé par un commissaire de justice, l'assignation est remise à l'adversaire par le commissaire de justice et vaut convocation en justice.</p></dd>
</dl></div></body></html>
"""


def fake_response(html=SAMPLE_HTML):
    response = Mock()
    response.text = html
    response.raise_for_status.return_value = None
    return response


class JusticeLexiconParserTest(unittest.TestCase):
    def test_parse_les_termes_definitions_et_ancres(self):
        entries = parse_lexicon_page(SAMPLE_HTML)
        self.assertEqual(entries, [
            {
                "terme": "Accès au droit",
                "definition": "Possibilité de connaître ses droits et obligations.",
                "ancre": "Acces_au_droit",
            },
            {
                "terme": "Action civile",
                "definition": "Action ouverte à la victime. Elle vise la réparation.",
                "ancre": "Action_civile",
            },
            {
                "terme": "Assignation",
                "definition": "Acte de procédure payant et rédigé par un commissaire de justice, l'assignation est remise à l'adversaire par le commissaire de justice et vaut convocation en justice.",
                "ancre": "Assignation",
            },
        ])


class JusticeLexiconClientTest(unittest.TestCase):
    def test_recherche_ignore_casse_et_accents_et_ne_charge_qu_une_lettre(self):
        session = Mock()
        session.get.return_value = fake_response()
        result = JusticeLexiconClient(session=session).lookup("ACCES AU DROIT")

        self.assertEqual(result["terme"], "Accès au droit")
        self.assertEqual(
            result["source_url"],
            "https://www.justice.fr/lexique/letter_a#Acces_au_droit",
        )
        self.assertEqual(
            session.get.call_args.args[0],
            "https://www.justice.fr/lexique/letter_a",
        )
        self.assertEqual(session.get.call_args.kwargs["timeout"], 20)

    def test_page_f5_est_une_erreur_et_non_un_resultat_vide(self):
        session = Mock()
        session.get.return_value = fake_response(
            "<html><h2>Accès refusé</h2><p>ID de support : 123</p></html>"
        )
        with self.assertRaisesRegex(JusticeLexiconError, "sécurité F5"):
            JusticeLexiconClient(session=session).lookup("appel")

    def test_structure_inconnue_est_signalee(self):
        session = Mock()
        session.get.return_value = fake_response("<html><body>nouvelle page</body></html>")
        with self.assertRaisesRegex(JusticeLexiconError, "structure attendue"):
            JusticeLexiconClient(session=session).lookup("appel")

    def test_recherche_non_exacte_balaie_toutes_les_lettres(self):
        session = Mock()
        renvoi_html = """
        <div id="lexique-content"><dl>
          <dt class="lexique-content-titre"><a id="Renvoi_interets"></a>
            Renvoi sur intérêts civils
          </dt>
          <dd><p>Définition qui ne doit pas être rendue dans les suggestions.</p></dd>
        </dl></div>
        """

        def response_for_url(url, **kwargs):
            if url.endswith("letter_r"):
                return fake_response(renvoi_html)
            return fake_response('<div id="lexique-content"></div>')

        session.get.side_effect = response_for_url
        result = JusticeLexiconClient(session=session).lookup("intérêts civils")

        self.assertIsNone(result["definition"])
        self.assertEqual(result["suggestions"], ["Renvoi sur intérêts civils"])
        self.assertTrue(any(
            call.args[0].endswith("letter_r") for call in session.get.call_args_list
        ))


class JusticeLexiconHandlerTest(unittest.TestCase):
    def test_handler_rend_uniquement_du_texte(self):
        payload = {
            "terme": "Assignation",
            "definition": "Acte de procédure payant et rédigé par un commissaire de justice, l'assignation est remise à l'adversaire par le commissaire de justice et vaut convocation en justice.",
            "source_url": "https://www.justice.fr/lexique/letter_a#Assignation",
        }
        with patch("tools.handlers.justice_lexicon_client.lookup", return_value=payload):
            response = handle_dictionnaire_juridique({"terme": "Assignation"}, "test-user")

        self.assertFalse(response["isError"])
        self.assertEqual(len(response["content"]), 1)
        self.assertEqual(response["content"][0]["type"], "text")
        self.assertEqual(response["content"][0]["text"], payload["definition"])
        self.assertNotIn("resource", response["content"][0])

    def test_handler_rend_les_erreurs_actionnables(self):
        with patch(
            "tools.handlers.justice_lexicon_client.lookup",
            side_effect=JusticeLexiconError("justice.fr indisponible"),
        ):
            response = handle_dictionnaire_juridique({"terme": "appel"}, "test-user")
        self.assertTrue(response["isError"])
        self.assertIn("justice.fr indisponible", response["content"][0]["text"])

    def test_handler_liste_uniquement_les_intitules_en_recherche_partielle(self):
        payload = {
            "terme": None,
            "definition": None,
            "source_url": "https://www.justice.fr/lexique",
            "suggestions": ["Renvoi sur intérêts civils"],
        }
        with patch("tools.handlers.justice_lexicon_client.lookup", return_value=payload):
            response = handle_dictionnaire_juridique(
                {"terme": "intérêts civils"}, "test-user"
            )

        self.assertEqual(
            response["content"],
            [{"type": "text", "text": "Renvoi sur intérêts civils"}],
        )
        self.assertNotIn("Définition", response["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()
