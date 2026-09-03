"""Verrous d'alignement avec les facettes officielles Legifrance (fonds JURI).

Ces fixtures sont des mesures reelles, prises sur l'API de production le
2026-09-02 (voir docs/facettes-officielles-dila.md). Elles ne doivent pas
etre ajustees pour faire passer un test : si un test de ce fichier echoue,
c'est le depot qui est desaligne, pas la fixture.
"""

import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from config.mcp_definitions import MCP_TOOLS
from tools.handlers import (
    FAMILLES_PREMIER_DEGRE,
    _sans_accents,
    valeurs_premier_degre,
)


# -- Fait 1 : facette APPEL_SIEGE_APPEL (fonds JURI), 36 sieges observes. ---

APPEL_SIEGE_APPEL_OFFICIELLES = [
    "AGEN", "AIX-PROVENCE", "AMIENS", "ANGERS", "BASSE-TERRE", "BASTIA",
    "BESANCON", "BORDEAUX", "BOURGES", "CAEN", "CAYENNE", "CHAMBERY",
    "COLMAR", "DIJON", "DOUAI", "FORT-DE-FRANCE", "GRENOBLE", "LIMOGES",
    "LYON", "METZ", "MONTPELLIER", "NANCY", "NIMES", "NOUMEA", "ORLEANS",
    "PAPEETE", "PARIS", "PAU", "POITIERS", "REIMS", "RENNES", "RIOM",
    "ROUEN", "ST-DENIS-REUNION", "TOULOUSE", "VERSAILLES",
]


# -- Fait 2 : facette PREMIER_DEGRE_TYPE_JURIDICTION (fonds JURI), 61
# libelles observes sous le filtre JURIDICTION_JUDICIAIRE = "Juridictions du
# premier degre", sans recherche textuelle. Copie litterale, accents compris.

PREMIER_DEGRE_LIBELLES_OFFICIELS = [
    "Chambre de l'application des peines du TSA de St Pierre",
    "Conseil de prud'hommes",
    "Juge de proximité de Chartres",
    "Juge de proximité de Clermont-Ferrand",
    "Juge de proximité de Rennes",
    "Juridiction de proximité d'Aix-en-Provence",
    "Juridiction de proximité d'Amiens",
    "Juridiction de proximité d'Angers",
    "Juridiction de proximité d'Auch",
    "Juridiction de proximité d'Aulnay-sous-Bois",
    "Juridiction de proximité d'Epinal",
    "Juridiction de proximité de Besançon",
    "Juridiction de proximité de Boissy-Saint-Léger",
    "Juridiction de proximité de Bourg-en-Bresse",
    "Juridiction de proximité de Douai",
    "Juridiction de proximité de Gonesse",
    "Juridiction de proximité de Lille",
    "Juridiction de proximité de Limoges",
    "Juridiction de proximité de Lyon",
    "Juridiction de proximité de Marseille",
    "Juridiction de proximité de Metz",
    "Juridiction de proximité de Neuilly-sur-Seine",
    "Juridiction de proximité de Niort",
    "Juridiction de proximité de Paris 15ème",
    "Juridiction de proximité de Paris 1er",
    "Juridiction de proximité de Paris 2ème",
    "Juridiction de proximité de Perpignan",
    "Juridiction de proximité de Remiremont",
    "Juridiction de proximité de Rouen",
    "Juridiction de proximité de Sannois",
    "Juridiction de proximité de Strasbourg",
    "Juridiction de proximité de Sète",
    "Juridiction de proximité de Tarascon",
    "Juridiction de proximité de Tulle",
    "Juridiction de proximité de Vanves",
    "Juridiction de proximité de Versailles",
    "Juridiction de proximité du Mans",
    "Juridiction de proximité du Raincy",
    "TRIBUNAL_CONFLIT",
    "Trib. des affaires de sécurité sociale de Charleville-Mézières",
    "Tribunal correctionnel de Nice",
    "Tribunal correctionnel de Paris",
    "Tribunal d'instance",
    "Tribunal de commerce",
    "Tribunal de grande instance",
    "Tribunal de première instance de Nouméa",
    "Tribunal de première instance de Papeete",
    "Tribunal des affaires de sécurité sociale d'Agen",
    "Tribunal des affaires de sécurité sociale de Besançon",
    "Tribunal des affaires de sécurité sociale de Boulogne-sur-Mer",
    "Tribunal des affaires de sécurité sociale de Bourges",
    "Tribunal des affaires de sécurité sociale de Châteauroux",
    "Tribunal des affaires de sécurité sociale de Créte",
    "Tribunal des affaires de sécurité sociale de Grenoble",
    "Tribunal des affaires de sécurité sociale de Moulins",
    "Tribunal des affaires de sécurité sociale de Poitiers",
    "Tribunal des affaires de sécurité sociale de Strasbourg",
    "Tribunal des affaires de sécurité sociale de la Réunion",
    "Tribunal judiciaire de Paris",
    "Tribunal paritaire des baux ruraux de Nîmes",
    "Tribunal supérieur d'appel de Mamoudzou",
]


def _outil(nom):
    return next(t for t in MCP_TOOLS if t["name"] == nom)


class AppelSiegeAppelTest(unittest.TestCase):
    def test_enumeration_exactement_les_36_sieges_observes(self):
        champ = _outil("Search_Cour_Appel")["inputSchema"]["properties"]["APPEL_SIEGE_APPEL"]
        enum = champ["items"]["enum"]

        manquantes = sorted(set(APPEL_SIEGE_APPEL_OFFICIELLES) - set(enum))
        inventees = sorted(set(enum) - set(APPEL_SIEGE_APPEL_OFFICIELLES))

        self.assertEqual(manquantes, [], f"sieges manquants dans l'enumeration : {manquantes}")
        self.assertEqual(inventees, [], f"sieges inventes dans l'enumeration : {inventees}")
        self.assertEqual(len(enum), len(set(enum)), "l'enumeration contient des doublons")

    def test_cayenne_present(self):
        champ = _outil("Search_Cour_Appel")["inputSchema"]["properties"]["APPEL_SIEGE_APPEL"]
        self.assertIn("CAYENNE", champ["items"]["enum"])


class CouverturePremierDegreTest(unittest.TestCase):
    """La partition FAMILLES_PREMIER_DEGRE doit exactement recouvrir les 61
    libelles reels, sans orphelin ni double appartenance."""

    def test_toutes_les_familles_couvrent_les_61_libelles_sans_exception(self):
        couverts = valeurs_premier_degre(
            list(FAMILLES_PREMIER_DEGRE), PREMIER_DEGRE_LIBELLES_OFFICIELS
        )
        orphelins = [l for l in PREMIER_DEGRE_LIBELLES_OFFICIELS if l not in couverts]
        self.assertEqual(
            orphelins, [],
            f"libelles reels non reclames par aucune famille : {orphelins}"
        )

    def test_aucun_libelle_reclame_par_deux_familles(self):
        conflits = {}
        for libelle in PREMIER_DEGRE_LIBELLES_OFFICIELS:
            normalise = _sans_accents(libelle)
            familles_correspondantes = [
                famille
                for famille, prefixes in FAMILLES_PREMIER_DEGRE.items()
                if any(normalise.startswith(prefixe) for prefixe in prefixes)
            ]
            if len(familles_correspondantes) > 1:
                conflits[libelle] = familles_correspondantes

        self.assertEqual(
            conflits, {},
            f"libelles reclames par plusieurs familles a la fois : {conflits}"
        )

    def test_aucune_famille_declaree_n_est_morte(self):
        mortes = [
            famille
            for famille in FAMILLES_PREMIER_DEGRE
            if not valeurs_premier_degre([famille], PREMIER_DEGRE_LIBELLES_OFFICIELS)
        ]
        self.assertEqual(
            mortes, [],
            f"famille(s) declaree(s) ne reclamant aucun des 61 libelles reels : {mortes}"
        )

    def test_conseil_prudhommes_et_tribunal_correctionnel_rendent_exactement_les_bons_libelles(self):
        self.assertEqual(
            valeurs_premier_degre(["CONSEIL_PRUDHOMMES"], PREMIER_DEGRE_LIBELLES_OFFICIELS),
            ["Conseil de prud'hommes"],
        )

        correctionnel = valeurs_premier_degre(
            ["TRIBUNAL_CORRECTIONNEL"], PREMIER_DEGRE_LIBELLES_OFFICIELS
        )
        self.assertEqual(
            correctionnel,
            ["Tribunal correctionnel de Nice", "Tribunal correctionnel de Paris"],
        )
        self.assertNotIn("TRIBUNAL_CORRECTIONNEL", correctionnel)


if __name__ == "__main__":
    unittest.main()
