"""Tests hors réseau de l'outil Historique_Judiciaire."""

import calendar
import json
import os
import sys
import unittest
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from config.mcp_definitions import MCP_TOOLS
from mcp_stdio_server import process_request
from tools.decision_history import (
    HistoriqueError,
    build_decision_history,
    render_markdown,
)
from tools.handlers import handle_historique_judiciaire


def epoch(iso):
    return calendar.timegm(datetime.strptime(iso, "%Y-%m-%d").timetuple()) * 1000


CA_BORDEAUX = {
    "id": "JURITEXT0001",
    "titre": "Cour d'appel de Bordeaux, 1re chambre civile, 10 novembre 2020, 19/01234",
    "juridiction": "Cour d'appel de Bordeaux",
    "natureJuridiction": "Cour d'appel",
    "nature": "ARRET",
    "formation": "01",
    "dateTexte": epoch("2020-11-10"),
    "numeroAffaire": ["19/01234"],
    "decisionAttaquee": {"formation": "Tribunal judiciaire de Bordeaux", "date": epoch("2019-03-05")},
    "texte": "Décision déférée : jugement du tribunal judiciaire de Bordeaux du 5 mars 2019.",
}

CASSATION = {
    "id": "JURITEXT0002",
    "titre": "Cour de cassation, civile, Chambre civile 2, 26 janvier 2023, 21-15.483",
    "juridiction": "Cour de cassation",
    "natureJuridiction": "Cour de cassation",
    "nature": "ARRET",
    "solution": "Cassation partielle",
    "formation": "CHAMBRE_CIVILE_2",
    "dateTexte": epoch("2023-01-26"),
    "numeroAffaire": ["21-15.483"],
    "decisionAttaquee": {"formation": "Cour d'appel de Bordeaux", "date": epoch("2020-11-10")},
    "texte": (
        "ont formé le pourvoi n° P 21-15.483 contre l'arrêt rendu le 10 novembre 2020 par la "
        "cour d'appel de Bordeaux (1re chambre civile) ; renvoie devant la cour d'appel de Toulouse."
    ),
}

RENVOI = {
    "id": "JURITEXT0003",
    "titre": "Cour d'appel de Toulouse, 4 juin 2024, 23/00567",
    "juridiction": "Cour d'appel de Toulouse",
    "natureJuridiction": "Cour d'appel",
    "nature": "ARRET",
    "formation": "04",
    "dateTexte": epoch("2024-06-04"),
    "numeroAffaire": ["23/00567"],
    "decisionAttaquee": {"formation": None, "date": None},
    "texte": (
        "Statuant sur renvoi après cassation prononcée par arrêt du 26 janvier 2023, "
        "pourvoi n° 21-15.483, de la deuxième chambre civile de la Cour de cassation."
    ),
}

BASE = {d["id"]: d for d in (CA_BORDEAUX, CASSATION, RENVOI)}


class FauxClient:
    """Substitut hors réseau du client PISTE, avec comptage des appels."""

    def __init__(self, base=None):
        self.base = base if base is not None else BASE
        self.consultations = []
        self.recherches = []

    def get_decision_text(self, text_id):
        self.consultations.append(text_id)
        if text_id not in self.base:
            raise Exception(f"inconnu: {text_id}")
        return {"text": dict(self.base[text_id])}

    def search_with_criteres(self, fond, criteres, operateur="ET", filtres=None,
                             page_size=10, **kwargs):
        self.recherches.append([c["valeur"] for c in criteres])
        resultats = []
        for decision in self.base.values():
            corpus = f"{decision['titre']} {decision['texte']} {decision['juridiction']}".lower()
            valeurs = [c["valeur"].lower() for c in criteres]
            trouve = all(v in corpus for v in valeurs) if operateur == "ET" else any(v in corpus for v in valeurs)
            if trouve:
                resultats.append({"titles": [{"id": decision["id"], "title": decision["titre"]}]})
        return {"results": resultats[:page_size], "totalResultNumber": len(resultats)}


class SchemaTest(unittest.TestCase):
    def test_outil_annonce_et_decouvrable(self):
        declare = next(t for t in MCP_TOOLS if t["name"] == "Historique_Judiciaire")
        self.assertEqual(declare["inputSchema"]["required"], ["text_id"])
        self.assertEqual(
            declare["inputSchema"]["properties"]["text_id"]["pattern"],
            "^(JURITEXT|CETATEXT)[0-9]+$",
        )
        reponse = process_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
        noms = [t["name"] for t in reponse["result"]["tools"]]
        self.assertIn("Historique_Judiciaire", noms)


class ValidationTest(unittest.TestCase):
    def test_identifiant_absent_refuse_sans_appel(self):
        client = FauxClient()
        with self.assertRaises(HistoriqueError):
            build_decision_history({}, client=client)
        self.assertEqual(client.consultations, [])

    def test_identifiant_non_juridictionnel_refuse_sans_appel(self):
        client = FauxClient()
        with self.assertRaises(HistoriqueError) as contexte:
            build_decision_history({"text_id": "LEGIARTI000036762052"}, client=client)
        self.assertIn("JURITEXT", str(contexte.exception))
        self.assertEqual(client.consultations, [])

    def test_handler_rend_une_erreur_exploitable(self):
        reponse = handle_historique_judiciaire({"text_id": "LEGIARTI000001"}, "test")
        self.assertTrue(reponse["isError"])
        self.assertIn("tool-use-error", reponse["content"][0]["text"])


class FilTest(unittest.TestCase):
    def setUp(self):
        self.client = FauxClient()
        self.historique = build_decision_history({"text_id": "JURITEXT0002"}, client=self.client)

    def test_le_fil_se_limite_a_la_chaine_des_decisions_attaquees(self):
        identifiants = [n["id"] for n in self.historique["fil"]]
        self.assertEqual(identifiants, ["JURITEXT0001", "JURITEXT0002"])
        dates = [n["date"] for n in self.historique["fil"]]
        self.assertEqual(dates, sorted(dates))

    def test_la_decision_attaquee_est_certaine_et_prouvee_par_la_metadonnee(self):
        lien = next(l for l in self.historique["liens"] if l["vers"] == "JURITEXT0001")
        self.assertEqual(lien["relation"], "décision attaquée par le recours")
        self.assertEqual(lien["certitude"], "certaine")
        self.assertIn("Cour d'appel de Bordeaux", lien["preuve"])

    def test_le_renvoi_n_entre_pas_au_fil_mais_figure_au_releve(self):
        # L'arrêt de renvoi cite le numéro du pourvoi, mais sa métadonnée
        # « décision attaquée » ne désigne pas la cassation : il n'est donc pas
        # un maillon procédural au sens strict, seulement une décision citante.
        self.assertNotIn("JURITEXT0003", [n["id"] for n in self.historique["fil"]])
        self.assertEqual([l["vers"] for l in self.historique["liens"]], ["JURITEXT0001"])
        citation = next(c for c in self.historique["citations"] if c["id"] == "JURITEXT0003")
        self.assertIn("21-15.483", citation["citation"])
        self.assertFalse(citation["dans_le_fil"])

    def test_aucun_lien_ne_repose_sur_autre_chose_qu_une_metadonnee(self):
        for lien in self.historique["liens"]:
            self.assertEqual(lien["certitude"], "certaine")
            self.assertIn("Métadonnée « décision attaquée »", lien["preuve"])

    def test_le_maillon_absent_de_la_base_est_declare_non_resolu(self):
        manquants = self.historique["liens_non_resolus"]
        self.assertEqual(len(manquants), 1)
        self.assertEqual(manquants[0]["juridiction"], "Tribunal judiciaire de Bordeaux")
        self.assertEqual(manquants[0]["date"], "2019-03-05")

    def test_chaque_maillon_porte_son_lien_legifrance(self):
        for noeud in self.historique["fil"]:
            self.assertEqual(noeud["lien"], f"https://www.legifrance.gouv.fr/juri/id/{noeud['id']}")

    def test_le_texte_integral_n_est_pas_recopie_dans_la_sortie(self):
        for noeud in self.historique["fil"]:
            self.assertNotIn("texte", noeud)

    def test_la_telemetrie_compte_les_appels_reellement_emis(self):
        telemetrie = self.historique["telemetrie"]
        self.assertEqual(
            telemetrie["appels_api"],
            len(self.client.consultations) + len(self.client.recherches),
        )
        self.assertEqual(telemetrie["consultations"], len(self.client.consultations))
        self.assertFalse(telemetrie["tronque"])

    def test_le_rendu_markdown_expose_le_fil_et_ses_reserves(self):
        rendu = render_markdown(self.historique)
        self.assertIn("HISTORIQUE JUDICIAIRE", rendu)
        self.assertIn("← décision de départ", rendu)
        self.assertIn("Maillons non résolus", rendu)
        self.assertIn("Tribunal judiciaire de Bordeaux", rendu)
        self.assertIn("legifrance.gouv.fr/juri/id/JURITEXT0003", rendu)


class PlafondTest(unittest.TestCase):
    def test_le_plafond_de_decisions_borne_le_fil_et_signale_la_troncature(self):
        historique = build_decision_history(
            {"text_id": "JURITEXT0002", "max_decisions": 1}, client=FauxClient()
        )
        self.assertEqual(len(historique["fil"]), 1)
        self.assertTrue(historique["telemetrie"]["tronque"])

    def test_le_plafond_d_appels_borne_le_parcours(self):
        client = FauxClient()
        historique = build_decision_history(
            {"text_id": "JURITEXT0002", "max_api_calls": 3}, client=client
        )
        self.assertLessEqual(historique["telemetrie"]["appels_api"], 3)
        self.assertTrue(historique["telemetrie"]["tronque"])

    def test_un_echec_de_consultation_est_consigne_sans_interrompre_le_fil(self):
        base = dict(BASE)
        base.pop("JURITEXT0003")
        base["JURITEXT0002"] = dict(CASSATION)
        client = FauxClient(base)
        historique = build_decision_history({"text_id": "JURITEXT0002"}, client=client)
        self.assertIn("JURITEXT0001", [n["id"] for n in historique["fil"]])


class AdministratifTest(unittest.TestCase):
    """Le fonds CETAT ne renseigne jamais `decisionAttaquee` : aucun historique
    procédural ne peut y être établi, et rien n'est comblé par des citations."""

    CAA = {
        "id": "CETATEXT0001",
        "titre": "Cour administrative d'appel de Marseille, 12/04/2023, 23MA00123",
        "juridiction": "Cour administrative d'appel de Marseille",
        "natureJuridiction": "COURS_APPEL",
        "nature": "Texte",
        "formation": "",
        "dateTexte": epoch("2023-04-12"),
        "numeroAffaire": [],
        "num": "23MA00123",
        "decisionAttaquee": {},
        "texte": "Par une ordonnance n°2201273 du 2 janvier 2023, le tribunal administratif de Bastia a rejeté la requête.",
    }
    CE = {
        "id": "CETATEXT0002",
        "titre": "Conseil d'État, 5 février 2024, 470123",
        "juridiction": "Conseil d'État",
        "natureJuridiction": "CONSEIL_ETAT",
        "nature": "Texte",
        "formation": "",
        "dateTexte": epoch("2024-02-05"),
        "numeroAffaire": [],
        "num": "470123",
        "decisionAttaquee": {},
        "texte": (
            "Vu la procédure suivante : Par un arrêt n° 23MA00123 du 12 avril 2023, "
            "la cour administrative d'appel de Marseille a rejeté la requête de M. B."
        ),
    }

    def setUp(self):
        base = {d["id"]: d for d in (self.CAA, self.CE)}
        self.historique = build_decision_history(
            {"text_id": "CETATEXT0001"}, client=FauxClient(base),
        )

    def test_le_fil_administratif_se_reduit_a_la_decision_de_depart(self):
        self.assertEqual(self.historique["ordre"], "administratif")
        self.assertEqual([n["id"] for n in self.historique["fil"]], ["CETATEXT0001"])
        self.assertEqual(self.historique["liens"], [])

    def test_le_pourvoi_est_relevé_comme_citant_et_non_comme_maillon(self):
        citation = next(c for c in self.historique["citations"] if c["id"] == "CETATEXT0002")
        self.assertIn("23MA00123", citation["citation"])
        self.assertFalse(citation["dans_le_fil"])
        self.assertTrue(citation["lien"].startswith("https://www.legifrance.gouv.fr/ceta/id/"))

    def test_le_rendu_declare_l_absence_de_metadonnee_dans_le_fonds_cetat(self):
        rendu = render_markdown(self.historique)
        self.assertIn("n'est jamais renseignée", rendu)


class BruitTest(unittest.TestCase):
    """Deux décisions étrangères citant le même numéro de norme ne sont pas liées."""

    PREMIERE = {
        "id": "CETATEXT0011",
        "titre": "CAA de Nantes, 08/01/2021, 20NT00288",
        "juridiction": "CAA de Nantes",
        "natureJuridiction": "COURS_APPEL",
        "nature": "Texte",
        "formation": "",
        "dateTexte": epoch("2021-01-08"),
        "numeroAffaire": [],
        "num": "20NT00288",
        "decisionAttaquee": {},
        "texte": "au titre du règlement (CE) n° 73/2009 relatif aux droits à paiement unique",
    }
    ETRANGERE = {
        "id": "CETATEXT0012",
        "titre": "CAA de Bordeaux, 14/09/2022, 20BX01111",
        "juridiction": "CAA de Bordeaux",
        "natureJuridiction": "COURS_APPEL",
        "nature": "Texte",
        "formation": "",
        "dateTexte": epoch("2022-09-14"),
        "numeroAffaire": [],
        "num": "20BX01111",
        "decisionAttaquee": {},
        "texte": "en vertu du règlement (CE) n° 73/2009, la dotation agricole a été recalculée",
    }

    def test_aucun_lien_n_est_forge_sur_un_numero_de_reglement(self):
        base = {d["id"]: d for d in (self.PREMIERE, self.ETRANGERE)}
        historique = build_decision_history({"text_id": "CETATEXT0011"}, client=FauxClient(base))
        self.assertEqual([n["id"] for n in historique["fil"]], ["CETATEXT0011"])
        self.assertEqual(historique["liens"], [])

    def test_un_numero_commun_sans_appartenance_officielle_ne_lie_pas(self):
        proche = dict(self.ETRANGERE)
        proche["texte"] = "l'arrêt n° 20NT00999 du 8 janvier 2021 est mentionné"
        premiere = dict(self.PREMIERE)
        premiere["texte"] = "l'arrêt n° 20NT00999 concerne une autre partie"
        base = {premiere["id"]: premiere, proche["id"]: proche}
        historique = build_decision_history({"text_id": "CETATEXT0011"}, client=FauxClient(base))
        self.assertEqual(historique["liens"], [])


class CitationDoctrinaleTest(unittest.TestCase):
    """Citer un précédent n'est pas être dans le même litige."""

    PRECEDENT = {
        "id": "JURITEXT0021",
        "titre": "Cour de cassation, Assemblée plénière, 13 janvier 2020, 17-19.963",
        "juridiction": "Cour de cassation",
        "natureJuridiction": "Cour de cassation",
        "nature": "ARRET",
        "formation": "ASSEMBLEE_PLENIERE",
        "dateTexte": epoch("2020-01-13"),
        "numeroAffaire": ["17-19.963"],
        "decisionAttaquee": {},
        "texte": "N° V 17-19.963, Assemblée plénière, 13 janvier 2020.",
    }
    CITANTE = {
        "id": "JURITEXT0022",
        "titre": "Cour de cassation, civile, Chambre commerciale, 21 octobre 2020, 18-17.064",
        "juridiction": "Cour de cassation",
        "natureJuridiction": "Cour de cassation",
        "nature": "ARRET",
        "formation": "CHAMBRE_COMMERCIALE",
        "dateTexte": epoch("2020-10-21"),
        "numeroAffaire": ["18-17.064"],
        "decisionAttaquee": {},
        "texte": (
            "il résulte de la jurisprudence de la Cour (Ass. plén., 13 janvier 2020, "
            "pourvoi n° 17-19.963, publié) que la faute du préposé engage"
        ),
    }

    def test_un_precedent_cite_n_allonge_pas_le_fil_mais_figure_au_releve(self):
        base = {d["id"]: d for d in (self.PRECEDENT, self.CITANTE)}
        historique = build_decision_history(
            {"text_id": "JURITEXT0021"}, client=FauxClient(base),
        )
        # Aucun lien procédural : le contexte de la citation est doctrinal.
        self.assertEqual(historique["liens"], [])
        self.assertEqual([n["id"] for n in historique["fil"]], ["JURITEXT0021"])
        # Mais la décision citante est bien relevée, avec sa citation littérale.
        citation = next(c for c in historique["citations"] if c["id"] == "JURITEXT0022")
        self.assertIn("17-19.963", citation["citation"])
        self.assertFalse(citation["dans_le_fil"])

    def test_meme_une_citation_en_contexte_procedural_ne_rattache_pas(self):
        # Le contexte de la citation n'est plus interprété : seule la
        # métadonnée « décision attaquée » rattache. Une citation, aussi
        # procédurale soit-elle, ne fait qu'entrer au relevé.
        procedurale = dict(self.CITANTE)
        procedurale["texte"] = (
            "sur le pourvoi n° 17-19.963 formé contre l'arrêt rendu le 9 avril 2019, "
            "statuant après cassation, la chambre commerciale"
        )
        base = {self.PRECEDENT["id"]: self.PRECEDENT, procedurale["id"]: procedurale}
        historique = build_decision_history(
            {"text_id": "JURITEXT0021"}, client=FauxClient(base),
        )
        self.assertEqual([n["id"] for n in historique["fil"]], ["JURITEXT0021"])
        self.assertIn("JURITEXT0022", [c["id"] for c in historique["citations"]])

    def test_la_metadonnee_rattache_la_ou_la_citation_ne_rattache_pas(self):
        # Même texte doctrinal, mais la métadonnée désigne le précédent : le
        # rattachement est alors prononcé, et il est « certain ».
        recours = dict(self.CITANTE)
        recours["decisionAttaquee"] = {
            "formation": "Cour de cassation", "date": epoch("2020-01-13"),
        }
        base = {self.PRECEDENT["id"]: self.PRECEDENT, recours["id"]: recours}
        historique = build_decision_history(
            {"text_id": "JURITEXT0021"}, client=FauxClient(base),
        )
        lien = next(l for l in historique["liens"] if l["vers"] == "JURITEXT0022")
        self.assertEqual(lien["certitude"], "certaine")


class CassationsSuccessivesTest(unittest.TestCase):
    """Deux cassations d'un même litige : le numéro cité ne les rattache pas."""

    def test_le_numero_officiel_cite_ne_suffit_pas_a_relier_deux_cassations(self):
        premiere = {
            "id": "JURITEXT0011",
            "titre": "Cour de cassation, 28 octobre 2020, 19-85.744",
            "juridiction": "Cour de cassation",
            "natureJuridiction": "Cour de cassation",
            "nature": "ARRET",
            "formation": "CHAMBRE_CRIMINELLE",
            "dateTexte": epoch("2020-10-28"),
            "numeroAffaire": ["19-85.744"],
            "decisionAttaquee": {},
            "texte": "N° T 19-85.744 F-D, 28 octobre 2020, cassation.",
        }
        seconde = {
            "id": "JURITEXT0012",
            "titre": "Cour de cassation, 20 décembre 2023, 21-87.233",
            "juridiction": "Cour de cassation",
            "natureJuridiction": "Cour de cassation",
            "nature": "ARRET",
            "formation": "CHAMBRE_CRIMINELLE",
            "dateTexte": epoch("2023-12-20"),
            "numeroAffaire": ["21-87.233"],
            "decisionAttaquee": {},
            "texte": "arrêt rendu le 4 novembre 2021 qui, statuant après cassation (pourvoi n° 19-85.744), condamne",
        }
        base = {premiere["id"]: premiere, seconde["id"]: seconde}
        historique = build_decision_history({"text_id": "JURITEXT0012"}, client=FauxClient(base))
        # Le lien existe en droit, mais aucune métadonnée ne l'atteste : il est
        # rendu comme citation, sans être promu en maillon procédural.
        self.assertEqual([n["id"] for n in historique["fil"]], ["JURITEXT0012"])
        self.assertEqual(historique["liens"], [])
        self.assertEqual(historique["citations"], [])


class CitationsTest(unittest.TestCase):
    """Relevé « citée par » : toute décision citant littéralement la décision."""

    CITANTE = {
        "id": "JURITEXT0004",
        "titre": "Cour d'appel d'Orléans, 14 mai 2020, 19/01949",
        "juridiction": "Cour d'appel d'Orléans",
        "natureJuridiction": "Cour d'appel",
        "nature": "ARRET",
        "solution": "Infirme la décision déférée",
        "formation": "C1",
        "dateTexte": epoch("2020-05-14"),
        "numeroAffaire": ["19/01949"],
        "decisionAttaquee": {},
        "texte": "au visa de la jurisprudence (Civ. 2e, 26 janvier 2023, pourvoi n° 21-15.483), la cour retient",
    }
    HOMONYME = {
        "id": "JURITEXT0005",
        "titre": "Cour d'appel de Douai, 3 mars 2021, 20/00111",
        "juridiction": "Cour d'appel de Douai",
        "natureJuridiction": "Cour d'appel",
        "nature": "ARRET",
        "formation": "01",
        "dateTexte": epoch("2021-03-03"),
        "numeroAffaire": ["20/00111"],
        "decisionAttaquee": {},
        # Le moteur peut rapprocher cette décision ; son texte ne cite pas le
        # numéro, aucune citation ne doit donc être affirmée.
        "texte": "pourvoi n° 21-15.484 sans rapport avec le litige",
    }

    def base(self):
        base = dict(BASE)
        base[self.CITANTE["id"]] = self.CITANTE
        base[self.HOMONYME["id"]] = self.HOMONYME
        return base

    def test_une_decision_citante_est_relevee_avec_sa_citation(self):
        historique = build_decision_history(
            {"text_id": "JURITEXT0002"}, client=FauxClient(self.base()),
        )
        citation = next(c for c in historique["citations"] if c["id"] == "JURITEXT0004")
        self.assertEqual(citation["numero_cite"], "21-15.483")
        self.assertIn("21-15.483", citation["citation"])
        self.assertEqual(citation["lien"], "https://www.legifrance.gouv.fr/juri/id/JURITEXT0004")
        self.assertTrue(historique["citations_completes"])
        self.assertEqual(
            historique["telemetrie"]["decisions_citantes"], len(historique["citations"]),
        )

    def test_un_rapprochement_sans_citation_litterale_est_ecarte(self):
        historique = build_decision_history(
            {"text_id": "JURITEXT0002"}, client=FauxClient(self.base()),
        )
        self.assertNotIn("JURITEXT0005", [c["id"] for c in historique["citations"]])

    def test_le_releve_est_independant_du_fil_et_le_signale(self):
        # Le relevé « citée par » ne dépend pas de l'étendue du fil : même fil
        # réduit à la seule décision de départ, les citants restent relevés, et
        # `dans_le_fil` distingue ce qui appartient déjà au fil procédural.
        complet = build_decision_history(
            {"text_id": "JURITEXT0002"}, client=FauxClient(self.base()),
        )
        renvoi = next(c for c in complet["citations"] if c["id"] == "JURITEXT0003")
        self.assertFalse(renvoi["dans_le_fil"])

        seul = build_decision_history(
            {"text_id": "JURITEXT0002", "max_decisions": 1}, client=FauxClient(self.base()),
        )
        self.assertEqual([n["id"] for n in seul["fil"]], ["JURITEXT0002"])
        self.assertIn("JURITEXT0004", [c["id"] for c in seul["citations"]])
        self.assertFalse(any(c["dans_le_fil"] for c in seul["citations"]))

    def test_le_releve_est_desactivable_et_la_troncature_declaree(self):
        vide = build_decision_history(
            {"text_id": "JURITEXT0002", "max_citations": 0}, client=FauxClient(self.base()),
        )
        self.assertEqual(vide["citations"], [])
        self.assertTrue(vide["citations_completes"])

        borne = build_decision_history(
            {"text_id": "JURITEXT0002", "max_citations": 1}, client=FauxClient(self.base()),
        )
        self.assertEqual(len(borne["citations"]), 1)
        self.assertFalse(borne["citations_completes"])
        rendu = render_markdown(borne)
        self.assertIn("Relevé tronqué", rendu)

    def test_le_rendu_liste_les_decisions_citantes(self):
        historique = build_decision_history(
            {"text_id": "JURITEXT0002"}, client=FauxClient(self.base()),
        )
        rendu = render_markdown(historique)
        self.assertIn("Décisions citant cette décision", rendu)
        self.assertIn("Cour d'appel d'Orléans, 14 mai 2020, 19/01949", rendu)
        self.assertIn("Cite le n° 21-15.483", rendu)


if __name__ == "__main__":
    unittest.main()
