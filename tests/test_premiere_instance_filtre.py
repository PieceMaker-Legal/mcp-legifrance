import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from config.mcp_definitions import MCP_TOOLS
from tools.handlers import (
    FAMILLES_PREMIER_DEGRE,
    familles_premier_degre,
    handle_search_premiere_instance,
    valeurs_premier_degre,
)


def _outil():
    return next(t for t in MCP_TOOLS if t["name"] == "Search_Premiere_Instance")


class SchemaPremiereInstanceTest(unittest.TestCase):
    def test_le_filtre_est_declare_obligatoire(self):
        schema = _outil()["inputSchema"]
        self.assertIn("PREMIER_DEGRE_TYPE_JURIDICTION", schema["required"])

    def test_les_familles_du_schema_sont_celles_du_handler(self):
        champ = _outil()["inputSchema"]["properties"]["PREMIER_DEGRE_TYPE_JURIDICTION"]
        self.assertEqual(champ["type"], "array")
        self.assertEqual(champ["minItems"], 1)
        self.assertEqual(sorted(champ["items"]["enum"]), sorted(FAMILLES_PREMIER_DEGRE))

    def test_aucune_valeur_attrape_tout(self):
        champ = _outil()["inputSchema"]["properties"]["PREMIER_DEGRE_TYPE_JURIDICTION"]
        self.assertNotIn("TOUTES", champ["items"]["enum"])
        self.assertNotIn("default", champ)


class FamillesPremierDegreTest(unittest.TestCase):
    def test_filtre_absent_refuse_sans_appel_reseau(self):
        reponse = handle_search_premiere_instance({"query": "contrat"}, "test")
        self.assertTrue(reponse["isError"])
        self.assertIn("obligatoire", reponse["content"][0]["text"])

    def test_famille_inconnue_refusee(self):
        with self.assertRaises(ValueError) as erreur:
            familles_premier_degre(["TOUTES"])
        self.assertIn("TOUTES", str(erreur.exception))

    def test_chaine_simple_acceptee_et_doublons_supprimes(self):
        self.assertEqual(familles_premier_degre("conseil_prudhommes"), ["CONSEIL_PRUDHOMMES"])
        self.assertEqual(
            familles_premier_degre(["TRIBUNAL_COMMERCE", "TRIBUNAL_COMMERCE"]),
            ["TRIBUNAL_COMMERCE"],
        )


class ExpansionFacetteTest(unittest.TestCase):
    VALEURS = [
        "Tribunal correctionnel de Nice",
        "Tribunal de grande instance",
        "Tribunal judiciaire de Paris",
        "Tribunal d'instance d'Auch",
        "Conseil de prud'hommes",
        "Juridiction de proximité de Rouen",
        "Trib. des affaires de sécurité sociale de Charleville-Mézières",
        "TRIBUNAL_CONFLIT",
    ]

    def test_les_libelles_par_ville_sont_couverts(self):
        self.assertEqual(
            valeurs_premier_degre(["TRIBUNAL_CORRECTIONNEL"], self.VALEURS),
            ["Tribunal correctionnel de Nice"],
        )

    def test_le_penal_n_attrape_pas_le_social(self):
        penal = valeurs_premier_degre(["TRIBUNAL_CORRECTIONNEL"], self.VALEURS)
        self.assertNotIn("Conseil de prud'hommes", penal)

    def test_tribunal_d_instance_distinct_du_tribunal_de_grande_instance(self):
        self.assertEqual(
            valeurs_premier_degre(["TRIBUNAL_INSTANCE"], self.VALEURS),
            ["Tribunal d'instance d'Auch"],
        )

    def test_les_accents_et_abreviations_sont_normalises(self):
        self.assertEqual(
            valeurs_premier_degre(["TRIBUNAL_SECURITE_SOCIALE"], self.VALEURS),
            ["Trib. des affaires de sécurité sociale de Charleville-Mézières"],
        )

    def test_aucune_correspondance_rend_une_liste_vide(self):
        self.assertEqual(valeurs_premier_degre(["TRIBUNAL_BAUX_RURAUX"], self.VALEURS), [])


if __name__ == "__main__":
    unittest.main()
