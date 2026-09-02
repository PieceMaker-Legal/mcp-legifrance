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

L'API Légifrance n'expose aucun index inverse : pour trouver les décisions dont
la métadonnée pointe vers le fil, il faut d'abord les rapprocher par une
recherche (nom de la juridiction attaquée à sa date exacte, numéro d'affaire
cité). Ces recherches ne servent qu'à produire des candidats : le rattachement,
lui, n'est prononcé que si `decisionAttaquee` le confirme. Un candidat qui cite
le numéro sans que sa métadonnée le confirme reste au relevé « citée par ».

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

# Garde-fous de fan-out, pour ne pas transformer un fil en balayage du fonds.
NUMEROS_PAR_DECISION = 3
CANDIDATS_PAR_NUMERO = 6

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

    def rechercher(self, requete, filtres, taille=CANDIDATS_PAR_NUMERO, page=1):
        """Exécute une recherche (1 appel) et rend les identifiants trouvés."""
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
        identifiants = []
        for resultat in (reponse or {}).get("results") or []:
            titres = resultat.get("titles") or []
            identifiant = (titres[0] if titres else {}).get("id")
            if identifiant:
                identifiants.append(identifiant)
        return identifiants


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


def _candidats(traceur, noeud, filtres_amont):
    """
    Rapproche des décisions susceptibles d'être reliées à `noeud`. Rien n'est
    conclu ici : l'API n'expose pas d'index inverse de `decisionAttaquee`, il
    faut donc d'abord ramener des candidats, que `_qualifier` retient ou écarte
    sur la seule métadonnée.

    Deux sources de candidats, l'une amont, l'autre aval :
      - la juridiction nommée par `decisionAttaquee`, à sa date exacte ;
      - les décisions citant un numéro officiel de `noeud`, qui est la façon
        dont un recours désigne en pratique la décision qu'il attaque.
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

    for numero in noeud["numeros"][:NUMEROS_PAR_DECISION]:
        valeur = _echappe(numero)
        if not valeur:
            continue
        for identifiant in traceur.rechercher(f'"{valeur}"', filtres=[], taille=CANDIDATS_PAR_NUMERO):
            trouvailles.append((identifiant, f"décision citant le numéro {numero}"))

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
            if identifiant not in fil:
                fil[identifiant] = {"noeud": candidat, "liens": []}
                a_traiter.append(identifiant)

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
    if telemetrie["echecs"]:
        lignes.append(f"- ⚠️ {len(telemetrie['echecs'])} appel(s) en échec, détaillés dans la ressource JSON.")
    lignes.append("")
    lignes.append(
        "Le chaînage n'est pas fourni par l'API Légifrance. Le fil ci-dessus est reconstruit "
        "sur la seule métadonnée officielle « décision attaquée » : chaque maillon repose sur une "
        "égalité de métadonnées, jamais sur une citation. Les décisions citantes sont relevées à "
        "part, sans être rattachées au fil."
    )
    if historique["ordre"] == "administratif":
        lignes.append(
            "Dans le fonds CETAT, la métadonnée « décision attaquée » n'est jamais renseignée : "
            "aucun historique procédural ne peut y être établi sur cette base, et le fil se réduit "
            "à la décision de départ. Seul le relevé des décisions citantes est exploitable."
        )
    return "\n".join(lignes)
