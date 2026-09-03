#/tools/decision_history.py
#! MCP SERVEUR LOCAL
"""
Reconstitution du fil procédural d'une décision (historique judiciaire).

L'outil MCP `Historique_Judiciaire` part d'un identifiant officiel
(`JURITEXT…` pour l'ordre judiciaire, `CETATEXT…` pour l'ordre administratif)
et rend deux choses, et deux seulement :

1. l'HISTORIQUE PROCÉDURAL STRICT, tiré de la seule métadonnée officielle
   `decisionAttaquee` : la décision que la décision de départ attaque, celle
   que cette dernière attaquait à son tour, et — dans l'autre sens — les
   décisions dont la métadonnée `decisionAttaquee` désigne une décision du fil.
   Aucun lien n'y est déduit d'une citation, d'une date ou d'une juridiction :
   chaque maillon repose sur une égalité de métadonnées, et sur rien d'autre ;
2. le RELEVÉ DES DÉCISIONS CITANT la décision de départ, retenues seulement si
   son numéro officiel figure littéralement dans le texte consulté. Ce relevé
   ne prétend pas au rattachement procédural : il recense, sans qualifier.

Pour les arrêts de la Cour de cassation, l'API expose bel et bien un index
inverse de cette même métadonnée : les facettes CASSATION_DECISION_ATTAQUEE,
LIEU_DECISION et DATE_DECISION_ATTAQUEE, combinées sans aucun champ de
recherche (une requête purement filtrée), interrogent `decisionAttaquee` dans
l'autre sens et rendent les pourvois formés contre une décision donnée. C'est
la même donnée officielle, seulement interrogée à l'envers : elle est donc
admise dans le fil procédural au même titre qu'une confirmation directe. Elle
ne résout toutefois qu'au couple juridiction + date, la métadonnée ne portant
jamais de numéro — deux décisions de la même juridiction rendues le même jour
lui restent indiscernables.

Pour le lien inverse — une décision de premier degré vers l'arrêt d'appel qui
la confirme ou l'infirme —, aucun index équivalent n'existe : il faut d'abord
rapprocher un candidat par une recherche (nom de la juridiction attaquée à sa
date exacte), que seule la métadonnée `decisionAttaquee` confirme ensuite. Un
candidat que la métadonnée ne confirme pas reste au relevé « citée par ».

Le champ `decisionAttaquee` n'est renseigné que dans le fonds JURI : dans le
fonds CETAT il existe au schéma mais reste vide (constaté sur un échantillon de
décisions du Conseil d'État et de cours administratives d'appel), tout comme
`solution` et `liens`. L'historique procédural d'une décision administrative est
donc, à ce jour, vide par construction — l'outil le déclare plutôt que de le
combler par des rapprochements.

Un maillon absent de la base — cas fréquent : les jugements de première instance
et une grande part des arrêts d'appel ne sont pas publiés — est déclaré comme
non résolu, jamais comblé.
"""

import re
import unicodedata
from datetime import datetime, timedelta, timezone

from tools.legifrance_client import legifrance_client as _client_par_defaut
from tools.query_parser import parse_query

# Corpus supportés, déduits du préfixe de l'identifiant officiel.
FONDS = {
    "JURITEXT": {"fond": "JURI", "ordre": "judiciaire", "lien": "https://www.legifrance.gouv.fr/juri/id/"},
    "CETATEXT": {"fond": "CETAT", "ordre": "administratif", "lien": "https://www.legifrance.gouv.fr/ceta/id/"},
}

# Bornes par défaut : un fil procédural réel dépasse rarement 6 maillons, mais
# le relevé « citée par » d'un arrêt de principe se compte en dizaines. Les
# plafonds par défaut sont donc dimensionnés pour qu'un tel arrêt sorte complet
# sans second appel, et les plafonds absolus laissent la marge d'une décision
# très citée. Chaque décision relevée coûte une consultation : un relevé de 50
# citations, fil compris, tient dans les 200 appels ouverts par défaut.
MAX_DECISIONS_DEFAUT = 20
MAX_DECISIONS_ABSOLU = 60
MAX_APPELS_DEFAUT = 200
MAX_APPELS_ABSOLU = 600

# Décisions postérieures citant la décision de départ (« citée par »). Le
# relevé est borné et sa troncature déclarée : jamais un « aucune » silencieux.
MAX_CITATIONS_DEFAUT = 50
MAX_CITATIONS_ABSOLU = 200
CITATIONS_PAR_PAGE = 50
PAGES_CITATIONS = 5

# Garde-fou de fan-out, pour ne pas transformer un fil en balayage du fonds :
# borne le nombre de résultats ramenés par un seul appel de recherche.
RESULTATS_PAR_RECHERCHE = 6

# Borne de l'index inverse (facettes CASSATION_DECISION_ATTAQUEE /
# LIEU_DECISION / DATE_DECISION_ATTAQUEE) : un pourvoi par litige est la
# norme, mais rien n'exclut plusieurs pourvois contre la même décision.
MAX_POURVOIS_PAR_DECISION = 20

MOIS = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]

# Ordre de juridiction, pour qualifier le sens d'un lien (recours ou origine).
DEGRES = (
    (("cour de cassation", "conseil d'etat"), 3, "cassation"),
    (("cour d'appel", "cour administrative d'appel"), 2, "appel"),
)


def _sans_accent(valeur):
    texte = unicodedata.normalize("NFKD", str(valeur or ""))
    return "".join(c for c in texte if not unicodedata.combining(c)).lower()


def _cle_juridiction(valeur):
    """Normalise un nom de juridiction : « Fort de France » == « Fort-de-France »."""
    return re.sub(r"[^a-z0-9]+", "", _sans_accent(valeur))


def _motif(valeur):
    """Normalise un nom de juridiction en mots espacés, sans accent ni
    ponctuation : « Cour d'appel de Fort-de-France » → « cour d appel de
    fort de france ». Sert à repérer un motif par mot entier, et à en
    extraire les jetons de lieu (voir `_juridiction_facette` et `_lieu`)."""
    return re.sub(r"[^a-z0-9]+", " ", _sans_accent(valeur)).strip()


# Correspondance juridiction → valeur de la facette CASSATION_DECISION_ATTAQUEE
# (19 valeurs, aucune autre n'existe côté API). Motifs les plus spécifiques
# d'abord, pour qu'une dénomination générique ne masque pas une dénomination
# plus précise qui la contient. Le « tribunal judiciaire » (juridiction issue
# de la fusion TGI/TI de 2020) n'a AUCUNE valeur de facette : dans ce cas
# `_juridiction_facette` rend None et `_index_inverse` se replie sur
# LIEU_DECISION + DATE_DECISION_ATTAQUEE seuls (forme vérifiée acceptée).
JURIDICTION_FACETTE = (
    ("conseil de prud hommes", "CONSEIL_PRUDHOMME"),
    ("cour d assises", "COUR_ASSISES"),
    ("cour de cassation", "COUR_CASSATION"),
    ("cour de justice de la republique", "COUR_JUSTICE_REPUBLIQUE"),
    ("cour nationale de l incapacite", "COUR_NATIONAL_INCAPACITE_TARIFICATION"),
    ("commission d indemnisation des victimes", "COMMISSION_INDEMNISATION_VICTIMES_INFRACTIONS"),
    ("tribunal des affaires de securite sociale", "TRIBUNAL_AFFAIRES_SECURITE_SOCIALE"),
    ("tribunal de commerce", "TRIBUNAL_COMMERCE"),
    ("tribunal du contentieux de l incapacite", "TRIBUNAL_CONTENTIEUX_INCAPACITE"),
    ("tribunal correctionnel", "TRIBUNAL_CORRECTIONNEL"),
    ("tribunal des forces armees", "TRIBUNAL_FORCES_ARMEES"),
    ("tribunal de grande instance", "TRIBUNAL_GRANDE_INSTANCE"),
    ("tribunal d instance", "TRIBUNAL_INSTANCE"),
    ("tribunal maritime commercial", "TRIBUNAL_MARITIME_COMMERCIAL"),
    ("tribunal paritaire des baux ruraux", "TRIBUNAL_PARITAIRE_BAUX_RURAUX"),
    ("tribunal de police", "TRIBUNAL_POLICE"),
    ("tribunal de premiere instance", "TRIBUNAL_PREMIERE_INSTANCE"),
    ("tribunal superieur d appel", "TRIBUNAL_SUPERIEURS_APPEL"),
    ("cour d appel", "COUR_APPEL"),
)

# Mots de la dénomination générique d'une juridiction (y compris ceux des 19
# libellés ci-dessus), retirés avant d'extraire les jetons de ville envoyés à
# LIEU_DECISION — une recherche plein texte tokenisée en ET : trop de jetons
# rend zéro résultat, il faut n'y garder que le nom du lieu.
_MOTS_GENERIQUES_LIEU = {
    "cour", "appel", "administrative", "administratif", "tribunal", "conseil",
    "prud", "hommes", "grande", "premiere", "instance", "commerce", "assises",
    "judiciaire", "correctionnel", "police", "paritaire", "baux", "ruraux",
    "maritime", "commercial", "forces", "armees", "superieur", "superieurs",
    "nationale", "incapacite", "tarification", "contentieux", "securite",
    "sociale", "affaires", "commission", "indemnisation", "victimes",
    "infractions", "republique", "justice", "cassation", "etat", "conseil",
    "de", "du", "des", "la", "le", "les", "d", "l", "en", "et",
}


def _juridiction_facette(juridiction):
    """Rend la valeur CASSATION_DECISION_ATTAQUEE correspondant au nom de la
    juridiction, ou None si aucune des 19 valeurs de l'API ne correspond."""
    motif = f" {_motif(juridiction)} "
    for cle, valeur in JURIDICTION_FACETTE:
        if f" {cle} " in motif:
            return valeur
    return None


def _lieu(juridiction):
    """Rend au plus deux jetons de ville pour la facette LIEU_DECISION, en
    retirant les mots de la dénomination générique. « Cour d'appel de
    Fort-de-France » rend ainsi [« fort », « france »] — jamais une liste de
    mots vides, et jamais plus de deux jetons (la facette conjugue les jetons
    en ET : au-delà de deux, elle ne rend plus rien)."""
    jetons = [mot for mot in _motif(juridiction).split() if mot not in _MOTS_GENERIQUES_LIEU]
    return jetons[:2]


def _degre(juridiction):
    """Rend (rang, libellé) du degré de juridiction, ou (1, 'premier degré')."""
    cle = _sans_accent(juridiction)
    for motifs, rang, libelle in DEGRES:
        for motif in motifs:
            if _sans_accent(motif) in cle:
                return rang, libelle
    return 1, "premier degré"


def _date_iso(epoch_ms):
    if not isinstance(epoch_ms, (int, float)):
        return ""
    try:
        return datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    except (OverflowError, OSError, ValueError):
        return ""


def _date_litterale(iso):
    """« 2020-11-10 » → « 10 novembre 2020 », forme employée dans les arrêts."""
    if not iso:
        return ""
    try:
        jour = datetime.strptime(iso, "%Y-%m-%d")
    except ValueError:
        return ""
    numero = "1er" if jour.day == 1 else str(jour.day)
    return f"{numero} {MOIS[jour.month - 1]} {jour.year}"


def _echappe(expression):
    """Rend une expression utilisable comme littéral entre guillemets."""
    return str(expression or "").replace('"', " ").strip()


def _identifiants(reponse):
    """Extrait les identifiants officiels d'une réponse de recherche PISTE,
    factorisé pour `_Traceur.rechercher` et `_Traceur.rechercher_par_filtres`."""
    identifiants = []
    for resultat in (reponse or {}).get("results") or []:
        titres = resultat.get("titles") or []
        identifiant = (titres[0] if titres else {}).get("id")
        if identifiant:
            identifiants.append(identifiant)
    return identifiants


class HistoriqueError(ValueError):
    """Erreur d'usage, rendue telle quelle à l'appelant."""


class _Traceur:
    """Parcours borné du fil procédural, avec comptage explicite des appels."""

    def __init__(self, client, fond, base_lien, max_decisions, max_appels):
        self.client = client
        self.fond = fond
        self.base_lien = base_lien
        self.max_decisions = max_decisions
        self.max_appels = max_appels
        self.appels = 0
        self.recherches = 0
        self.index_inverse = 0
        self.consultations = 0
        self.cache = {}
        self.tronque = False
        self.echecs = []

    # --- accès API bornés -------------------------------------------------

    def _budget(self):
        if self.appels >= self.max_appels:
            self.tronque = True
            return False
        return True

    def consulter(self, text_id):
        """Consulte une décision (1 appel), avec cache et échec non bloquant."""
        if text_id in self.cache:
            return self.cache[text_id]
        if not self._budget():
            return None
        self.appels += 1
        self.consultations += 1
        try:
            reponse = self.client.get_decision_text(text_id)
        except Exception as erreur:  # réseau, 4xx, 5xx : consigné, jamais fatal
            self.echecs.append({"id": text_id, "erreur": str(erreur)})
            self.cache[text_id] = None
            return None
        noeud = _noeud(text_id, (reponse or {}).get("text") or {}, self.base_lien)
        self.cache[text_id] = noeud
        return noeud

    def rechercher(self, requete, filtres, taille=RESULTATS_PAR_RECHERCHE, page=1):
        """Exécute une recherche par critères (1 appel) et rend les identifiants trouvés."""
        if not self._budget():
            return []
        self.appels += 1
        self.recherches += 1
        try:
            operateur, _type, criteres = parse_query(requete)
            reponse = self.client.search_with_criteres(
                fond=self.fond,
                criteres=criteres,
                operateur=operateur,
                filtres=filtres,
                page_size=taille,
                page_number=page,
            )
        except Exception as erreur:
            self.echecs.append({"requete": requete, "erreur": str(erreur)})
            return []
        return _identifiants(reponse)

    def rechercher_par_filtres(self, filtres, taille, page=1):
        """
        Interroge l'index inverse (1 appel, compté comme `rechercher`) : une
        requête purement filtrée, sans aucune clé `champs` — `query=""` ne
        construit aucun champ de recherche côté client, ce qui est exactement
        la forme acceptée par l'API pour CASSATION_DECISION_ATTAQUEE /
        LIEU_DECISION / DATE_DECISION_ATTAQUEE.
        """
        if not self._budget():
            return []
        self.appels += 1
        self.recherches += 1
        self.index_inverse += 1
        try:
            reponse = self.client.search(
                fond=self.fond,
                query="",
                filtres=filtres,
                page_size=taille,
                page_number=page,
                operateur="ET",
            )
        except Exception as erreur:
            self.echecs.append({"filtres": filtres, "erreur": str(erreur)})
            return []
        return _identifiants(reponse)


def _noeud(text_id, texte, base_lien):
    """Réduit une décision consultée à ses métadonnées officielles utiles."""
    attaquee = texte.get("decisionAttaquee") or {}
    numeros = [str(n).strip() for n in (texte.get("numeroAffaire") or []) if str(n).strip()]
    numero_seul = str(texte.get("num") or "").strip()
    if numero_seul and numero_seul not in numeros:
        numeros.append(numero_seul)
    juridiction = texte.get("juridiction") or ""
    date_iso = _date_iso(texte.get("dateTexte"))
    rang, degre = _degre(juridiction)
    return {
        "id": text_id,
        "titre": texte.get("titre") or texte.get("titreLong") or text_id,
        "juridiction": juridiction,
        "nature_juridiction": texte.get("natureJuridiction") or "",
        "formation": texte.get("formation") or "",
        "degre": degre,
        "rang": rang,
        "date": date_iso,
        "date_litterale": _date_litterale(date_iso),
        "nature": texte.get("nature") or "",
        "solution": texte.get("solution") or "",
        "publication": texte.get("publicationRecueil") or texte.get("typePublicationBulletin") or "",
        "numeros": numeros,
        "ecli": texte.get("ecli") or "",
        "lien": f"{base_lien}{text_id}",
        "decision_attaquee": {
            "formation": attaquee.get("formation") or "",
            "date": _date_iso(attaquee.get("date")),
        },
        "texte": texte.get("texte") or "",
    }


def _extrait(texte, ancre, marge=140):
    """Rend la citation littérale entourant l'ancre, sans la reformuler."""
    position = texte.find(ancre)
    if position < 0:
        return ""
    debut = max(0, position - marge)
    fin = min(len(texte), position + len(ancre) + marge)
    extrait = " ".join(texte[debut:fin].split())
    prefixe = "…" if debut > 0 else ""
    suffixe = "…" if fin < len(texte) else ""
    return f"{prefixe}{extrait}{suffixe}"


def _meme_decision_attaquee(candidat, noeud):
    """Vrai si `candidat.decisionAttaquee` désigne bien `noeud` (métadonnées)."""
    attaquee = candidat["decision_attaquee"]
    if not attaquee["date"] or attaquee["date"] != noeud["date"]:
        return False
    if not attaquee["formation"]:
        return False
    return _cle_juridiction(attaquee["formation"]) == _cle_juridiction(noeud["juridiction"])


def _qualifier(noeud, candidat):
    """
    Qualifie le lien candidat→noeud à partir de la seule métadonnée officielle
    `decisionAttaquee`. Rend (relation, certitude, preuve), ou None : une
    citation, une date ou une juridiction commune n'établissent rien ici.
    """
    if _meme_decision_attaquee(candidat, noeud):
        relation = ("pourvoi en cassation contre cette décision" if candidat["rang"] == 3
                    else "recours (appel) contre cette décision")
        preuve = (f"Métadonnée « décision attaquée » du {candidat['id']} : "
                  f"{candidat['decision_attaquee']['formation']}, "
                  f"{candidat['decision_attaquee']['date']}")
        return relation, "certaine", preuve
    if _meme_decision_attaquee(noeud, candidat):
        return ("décision attaquée par le recours", "certaine",
                f"Métadonnée « décision attaquée » du {noeud['id']} : "
                f"{noeud['decision_attaquee']['formation']}, {noeud['decision_attaquee']['date']}")
    return None


ORIGINE_INDEX_INVERSE = (
    "index inverse de la métadonnée « décision attaquée » "
    "(CASSATION_DECISION_ATTAQUEE / LIEU_DECISION / DATE_DECISION_ATTAQUEE)"
)


def _index_inverse(traceur, noeud):
    """
    Rend les identifiants des pourvois en cassation dont la métadonnée
    officielle `decisionAttaquee` désigne `noeud`, trouvés par l'index inverse
    plutôt que par une recherche de citation.

    N'agit que sur le fonds JURI (seul fonds où `decisionAttaquee` existe), et
    seulement si `noeud["date"]` est renseignée. N'émet aucune requête si ni
    la facette de juridiction ni un lieu ne sont déterminés : une requête sur
    la seule date rend des dizaines de décisions sans rapport (mesuré : 65 à
    76 résultats pour la date seule, contre 4 à 11 avec un discriminant).
    """
    if traceur.fond != "JURI" or not noeud["date"]:
        return []

    valeur_facette = _juridiction_facette(noeud["juridiction"])
    jetons_lieu = _lieu(noeud["juridiction"])
    if not valeur_facette and not jetons_lieu:
        return []

    filtres = [{"facette": "DATE_DECISION_ATTAQUEE",
                "dates": {"start": noeud["date"], "end": noeud["date"]}}]
    if valeur_facette:
        filtres.append({"facette": "CASSATION_DECISION_ATTAQUEE", "valeurs": [valeur_facette]})
    if jetons_lieu:
        # Un seul élément de `valeurs` contenant les jetons espacés : la
        # facette conjugue les mots d'un même élément en ET (voir docstring
        # de `_lieu`), et plusieurs éléments de la liste seraient en OU.
        filtres.append({"facette": "LIEU_DECISION", "valeurs": [" ".join(jetons_lieu)]})

    identifiants = traceur.rechercher_par_filtres(filtres, taille=MAX_POURVOIS_PAR_DECISION)
    if len(identifiants) >= MAX_POURVOIS_PAR_DECISION:
        # D'autres pourvois existent probablement au-delà de la borne : une
        # troncature de l'index inverse n'est pas moins une troncature.
        traceur.tronque = True
    return identifiants


def _candidats(traceur, noeud, filtres_amont):
    """
    Rapproche des décisions susceptibles d'être reliées à `noeud`. Rien n'est
    conclu ici : `_qualifier` retient ou écarte chaque candidat sur la seule
    métadonnée `decisionAttaquee`.

    Deux sources de candidats, l'une amont, l'autre aval :
      - amont — la juridiction nommée par `decisionAttaquee`, à sa date
        exacte : aucun index n'existe pour ce sens (premier degré → appel),
        il faut ramener un candidat par recherche avant que la métadonnée ne
        le confirme ;
      - aval — l'index inverse officiel de la même métadonnée, qui rend
        directement les pourvois en cassation visant `noeud`, sans recherche
        par citation (voir `_index_inverse`).
    """
    trouvailles = []

    attaquee = noeud["decision_attaquee"]
    if attaquee["formation"] and attaquee["date"]:
        filtres = list(filtres_amont) + [{
            "facette": "DATE_DECISION",
            "dates": {"start": attaquee["date"], "end": attaquee["date"]},
        }]
        requete = f'"{_echappe(attaquee["formation"])}"'
        for identifiant in traceur.rechercher(requete, filtres=filtres):
            trouvailles.append((identifiant, "juridiction et date de la métadonnée « décision attaquée »"))

    for identifiant in _index_inverse(traceur, noeud):
        trouvailles.append((identifiant, ORIGINE_INDEX_INVERSE))

    return trouvailles


def _decisions_citantes(traceur, racine, max_citations):
    """
    Relève toutes les décisions du fonds qui citent littéralement un numéro
    officiel de la décision de départ — postérieures comme antérieures, du même
    ordre. La citation n'est retenue que si le numéro figure réellement dans le
    texte consulté : un résultat de recherche approchant ne fait pas preuve.

    Rend (citations, complet) : `complet` est faux dès qu'une page de résultats
    ou un plafond a été laissé de côté, pour que l'absence soit distinguée de
    la troncature.
    """
    citations = []
    vues = {racine["id"]}
    complet = True
    if max_citations <= 0:
        # Relevé explicitement désactivé par l'appelant : ce n'est pas une
        # troncature, il n'y a simplement rien qui ait été laissé de côté.
        return citations, complet
    for numero in racine["numeros"]:
        valeur = _echappe(numero)
        if not valeur:
            continue
        for page in range(1, PAGES_CITATIONS + 1):
            if len(citations) >= max_citations:
                complet = False
                break
            identifiants = traceur.rechercher(
                f'"{valeur}"', filtres=[], taille=CITATIONS_PAR_PAGE, page=page,
            )
            for identifiant in identifiants:
                if identifiant in vues:
                    continue
                vues.add(identifiant)
                if len(citations) >= max_citations:
                    complet = False
                    continue
                citant = traceur.consulter(identifiant)
                if citant is None:
                    continue
                extrait = _extrait(citant["texte"], numero)
                if not extrait:
                    # Le moteur a rapproché sans que le numéro figure au texte :
                    # sans citation littérale, rien n'est affirmé.
                    continue
                citations.append({
                    "id": identifiant,
                    "titre": citant["titre"],
                    "juridiction": citant["juridiction"],
                    "formation": citant["formation"],
                    "date": citant["date"],
                    "solution": citant["solution"],
                    "publication": citant["publication"],
                    "numero_cite": numero,
                    "citation": extrait,
                    "lien": citant["lien"],
                })
            if len(identifiants) < CITATIONS_PAR_PAGE:
                break
            if page == PAGES_CITATIONS:
                complet = False
    if traceur.tronque:
        complet = False
    citations.sort(key=lambda c: (c["date"] or "9999-12-31", c["id"]))
    return citations, complet


def build_decision_history(args, client=None):
    """
    Point d'entrée métier. Rend un dict :
      { seed, fil, liens_non_resolus, telemetrie }
    ou lève HistoriqueError avec un message clair en français.
    """
    text_id = str(args.get("text_id") or args.get("id") or "").strip()
    if not text_id:
        raise HistoriqueError("text_id requis (identifiant JURITEXT… ou CETATEXT…).")

    prefixe = next((p for p in FONDS if text_id.upper().startswith(p)), None)
    if not prefixe:
        raise HistoriqueError(
            f"Identifiant non reconnu : {text_id}. Attendu un identifiant officiel de décision, "
            "JURITEXT… (ordre judiciaire) ou CETATEXT… (ordre administratif)."
        )
    corpus = FONDS[prefixe]

    max_decisions = max(1, min(int(args.get("max_decisions") or MAX_DECISIONS_DEFAUT), MAX_DECISIONS_ABSOLU))
    max_appels = max(2, min(int(args.get("max_api_calls") or MAX_APPELS_DEFAUT), MAX_APPELS_ABSOLU))
    demande_citations = args.get("max_citations")
    max_citations = (MAX_CITATIONS_DEFAUT if demande_citations is None
                     else max(0, min(int(demande_citations), MAX_CITATIONS_ABSOLU)))

    traceur = _Traceur(
        client or _client_par_defaut,
        corpus["fond"], corpus["lien"], max_decisions, max_appels,
    )

    racine = traceur.consulter(text_id)
    if racine is None:
        echec = traceur.echecs[-1]["erreur"] if traceur.echecs else "cause inconnue"
        raise HistoriqueError(f"Consultation impossible de {text_id} : {echec}")

    # Facettes de juridiction : la recherche de la décision attaquée est bornée
    # aux degrés inférieurs dans l'ordre judiciaire. L'ordre administratif
    # n'expose pas de scission équivalente, ses recherches restent non filtrées
    # — et son champ `decisionAttaquee` étant toujours vide, son fil se réduit
    # à la décision de départ.
    if corpus["fond"] == "JURI":
        filtres_amont = [{"facette": "JURIDICTION_JUDICIAIRE",
                          "valeurs": ["Juridictions d'appel", "Juridictions du premier degré"]}]
    else:
        filtres_amont = []

    fil = {text_id: {"noeud": racine, "liens": []}}
    non_resolus = []
    a_traiter = [text_id]
    traites = set()
    pourvois_par_index = 0

    while a_traiter and len(fil) < max_decisions and traceur.appels < max_appels:
        courant_id = a_traiter.pop(0)
        if courant_id in traites:
            continue
        traites.add(courant_id)
        noeud = fil[courant_id]["noeud"]

        attaquee_resolue = False
        for identifiant, origine in _candidats(traceur, noeud, filtres_amont):
            if identifiant == courant_id:
                continue
            if len(fil) >= max_decisions and identifiant not in fil:
                traceur.tronque = True
                continue
            candidat = traceur.consulter(identifiant)
            if candidat is None:
                continue
            qualification = _qualifier(noeud, candidat)
            if not qualification:
                continue
            relation, certitude, preuve = qualification
            if relation == "décision attaquée par le recours":
                attaquee_resolue = True
            issu_de_l_index = origine == ORIGINE_INDEX_INVERSE
            if issu_de_l_index:
                # L'index ne renvoie que juridiction + date, jamais de numéro :
                # il ne distingue pas deux décisions de cette juridiction
                # rendues ce jour-là. La certitude reste celle de `_qualifier`
                # (l'index ne fait que fournir le candidat), mais la limite se
                # dit dans la preuve.
                preuve += (
                    " — l'index ne résout qu'au couple juridiction et date : il ne "
                    "distingue pas deux décisions de cette juridiction rendues ce jour-là"
                )
            lien = {
                "de": courant_id,
                "vers": identifiant,
                "relation": relation,
                "certitude": certitude,
                "preuve": preuve,
                "origine_du_lien": origine,
            }
            if not any(l["vers"] == identifiant for l in fil[courant_id]["liens"]):
                fil[courant_id]["liens"].append(lien)
                if issu_de_l_index:
                    pourvois_par_index += 1
            if identifiant not in fil:
                fil[identifiant] = {"noeud": candidat, "liens": []}
                a_traiter.append(identifiant)

        # La métadonnée ne nomme que la juridiction et la date : si plusieurs
        # décisions de cette juridiction ce jour-là figurent à la base, elle ne
        # permet pas de les départager. Le lien reste rendu, mais sa certitude
        # est abaissée et l'ambiguïté est dite.
        candidates = [l for l in fil[courant_id]["liens"]
                      if l["relation"] == "décision attaquée par le recours"]
        if len(candidates) > 1:
            for lien in candidates:
                lien["certitude"] = "probable"
                lien["preuve"] += (
                    f" — {len(candidates)} décisions de cette juridiction à cette date "
                    "figurent à la base : la métadonnée ne permet pas de les départager"
                )

        attaquee = noeud["decision_attaquee"]
        if attaquee["formation"] and attaquee["date"] and not attaquee_resolue:
            non_resolus.append({
                "depuis": courant_id,
                "juridiction": attaquee["formation"],
                "date": attaquee["date"],
                "motif": "décision attaquée nommée par les métadonnées mais absente de la base Légifrance",
            })

    if a_traiter:
        traceur.tronque = True

    # Relevé « citée par » : effectué avant que les textes ne soient libérés,
    # et après le fil, qui reste prioritaire sur le budget d'appels.
    citations, citations_completes = _decisions_citantes(traceur, racine, max_citations)
    dans_le_fil = set(fil)
    for citation in citations:
        citation["dans_le_fil"] = citation["id"] in dans_le_fil

    ordonne = sorted(
        (entree["noeud"] for entree in fil.values()),
        key=lambda n: (n["date"] or "9999-12-31", n["rang"]),
    )
    liens = [lien for entree in fil.values() for lien in entree["liens"]]

    for noeud in ordonne:
        noeud.pop("texte", None)

    return {
        "seed": text_id,
        "ordre": corpus["ordre"],
        "fond": corpus["fond"],
        "fil": ordonne,
        "liens": liens,
        "liens_non_resolus": non_resolus,
        "citations": citations,
        "citations_completes": citations_completes,
        "telemetrie": {
            "appels_api": traceur.appels,
            "recherches": traceur.recherches,
            "recherches_index_inverse": traceur.index_inverse,
            "pourvois_par_index": pourvois_par_index,
            "consultations": traceur.consultations,
            "decisions_dans_le_fil": len(ordonne),
            "decisions_citantes": len(citations),
            "plafond_decisions": max_decisions,
            "plafond_citations": max_citations,
            "plafond_appels_api": max_appels,
            "tronque": traceur.tronque,
            "echecs": traceur.echecs,
        },
    }


def render_markdown(historique):
    """Rend le fil procédural en Markdown, sources et incertitudes comprises."""
    seed = historique["seed"]
    lignes = [
        "**⛓️ HISTORIQUE JUDICIAIRE**",
        "",
        f"**Décision de départ :** {seed}",
        f"**Ordre :** {historique['ordre']}",
        f"**Décisions reliées :** {len(historique['fil'])}",
        "",
        "═" * 80,
        "",
    ]

    liens_par_cible = {}
    for lien in historique["liens"]:
        liens_par_cible.setdefault(lien["vers"], []).append(lien)

    for index, noeud in enumerate(historique["fil"], 1):
        marque = " ← décision de départ" if noeud["id"] == seed else ""
        lignes.append(f"{index}. {noeud['titre']}{marque}")
        entete = [noeud["date"] or "date inconnue", noeud["juridiction"] or "juridiction inconnue"]
        if noeud["formation"]:
            entete.append(f"formation {noeud['formation']}")
        lignes.append(f"   {' — '.join(entete)}")
        if noeud["numeros"]:
            lignes.append(f"   Numéro(s) : {', '.join(noeud['numeros'])}")
        if noeud["solution"]:
            lignes.append(f"   Solution : {noeud['solution']}")
        elif noeud["nature"]:
            lignes.append(f"   Nature : {noeud['nature']}")
        for lien in liens_par_cible.get(noeud["id"], []):
            lignes.append(f"   Lien : {lien['relation']} (depuis {lien['de']}, certitude {lien['certitude']})")
            if lien["preuve"]:
                lignes.append(f"     Preuve : {lien['preuve']}")
        lignes.append(f"   Légifrance : {noeud['lien']}")
        lignes.append("")

    if historique["liens_non_resolus"]:
        lignes.append("**Maillons non résolus**")
        lignes.append("")
        for manquant in historique["liens_non_resolus"]:
            lignes.append(
                f"- {manquant['juridiction']}, {manquant['date']} "
                f"(visée par {manquant['depuis']}) — {manquant['motif']}"
            )
        lignes.append("")

    citations = historique.get("citations") or []
    if citations or historique.get("citations_completes") is False:
        lignes.append(f"**Décisions citant cette décision : {len(citations)}**")
        lignes.append("")
        if not citations:
            lignes.append("- Aucune citation littérale relevée dans les limites du relevé.")
        for index, citation in enumerate(citations, 1):
            marque = " (déjà dans le fil)" if citation.get("dans_le_fil") else ""
            lignes.append(f"{index}. {citation['titre']}{marque}")
            entete = [citation["date"] or "date inconnue",
                      citation["juridiction"] or "juridiction inconnue"]
            if citation["formation"]:
                entete.append(f"formation {citation['formation']}")
            lignes.append(f"   {' — '.join(entete)}")
            if citation["solution"]:
                lignes.append(f"   Solution : {citation['solution']}")
            lignes.append(f"   Cite le n° {citation['numero_cite']} : {citation['citation']}")
            lignes.append(f"   Légifrance : {citation['lien']}")
        if historique.get("citations_completes") is False:
            lignes.append("")
            lignes.append(
                "- ⚠️ Relevé tronqué par un plafond : d'autres décisions citantes existent "
                "probablement. Relancer avec un `max_citations` et un `max_api_calls` plus élevés."
            )
        lignes.append("")

    telemetrie = historique["telemetrie"]
    lignes.append("**Télémétrie**")
    lignes.append("")
    lignes.append(
        f"- Appels API : {telemetrie['appels_api']} "
        f"({telemetrie['recherches']} recherches, {telemetrie['consultations']} consultations) ; "
        f"plafonds {telemetrie['plafond_appels_api']} appels / {telemetrie['plafond_decisions']} décisions"
    )
    if telemetrie["tronque"]:
        lignes.append("- ⚠️ Parcours tronqué par un plafond : le fil peut être incomplet.")
    lignes.append(
        f"- Décisions citantes relevées : {telemetrie.get('decisions_citantes', 0)} "
        f"(plafond {telemetrie.get('plafond_citations', 0)})"
    )
    if telemetrie.get("recherches_index_inverse"):
        lignes.append(
            f"- Index inverse (décision attaquée) : {telemetrie['recherches_index_inverse']} "
            f"appel(s), {telemetrie.get('pourvois_par_index', 0)} pourvoi(s) rattaché(s) au fil"
        )
    if telemetrie["echecs"]:
        lignes.append(f"- ⚠️ {len(telemetrie['echecs'])} appel(s) en échec, détaillés dans la ressource JSON.")
    lignes.append("")
    lignes.append(
        "Les pourvois en cassation contre une décision sont obtenus par l'index inverse officiel "
        "de la métadonnée « décision attaquée » (facettes CASSATION_DECISION_ATTAQUEE / "
        "LIEU_DECISION / DATE_DECISION_ATTAQUEE) : exact, mais résolu au seul couple juridiction "
        "et date, la métadonnée ne portant jamais de numéro. Le lien vers la décision attaquée "
        "d'un degré inférieur n'est, lui, pas indexé : il repose sur une recherche bornée, "
        "confirmée par cette même métadonnée. Les décisions citantes restent relevées à part, "
        "sans être rattachées au fil."
    )
    if historique["ordre"] == "administratif":
        lignes.append(
            "Dans le fonds CETAT, la métadonnée « décision attaquée » n'est jamais renseignée : "
            "aucun historique procédural ne peut y être établi sur cette base, et le fil se réduit "
            "à la décision de départ. Seul le relevé des décisions citantes est exploitable."
        )
    return "\n".join(lignes)
