import json
import re
import time
import unicodedata
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from itertools import product
from typing import Any, Dict, List, Optional, Tuple

from tools.legifrance_client import JudilibreError, borne_haute_reelle, est_date_absente, legifrance_client
from tools.query_parser import QueryCriteria, normalize_article_reference, parse_query


LIMITE_RESULTATS = 500
LEGIFRANCE_PAGE = 100
JUDILIBRE_PAGE = 50
MAX_REQUETES_JUDILIBRE = 32
VERIFICATIONS_SIMULTANEES = 4
CACHE_TAILLE = 16
CACHE_SECONDES = 600

JURIDICTIONS = ["cassation", "appel", "premiere_instance", "conseil_etat", "caa"]
SOURCES = ["legifrance", "judilibre"]
ALIAS_JURIDICTIONS = {"administratif": ["conseil_etat", "caa"]}

LIBELLES_JURIDICTIONS = {
    "cassation": "Cour de cassation",
    "appel": "Cours d'appel",
    "premiere_instance": "Première instance",
    "conseil_etat": "Conseil d'État",
    "caa": "Cours administratives d'appel",
}

ANNEES_PAR_DEFAUT = {"cassation": 5, "appel": 3, "premiere_instance": 5, "conseil_etat": 5, "caa": 3}

FONDS = {"cassation": "JURI", "appel": "JURI", "premiere_instance": "JURI", "conseil_etat": "CETAT", "caa": "CETAT"}

LIENS_LEGIFRANCE = {
    "JURI": "https://www.legifrance.gouv.fr/juri/id/",
    "CETAT": "https://www.legifrance.gouv.fr/ceta/id/",
}

LIEN_JUDILIBRE = "https://www.courdecassation.fr/decision/"

SIEGES_APPEL = [
    "PARIS", "VERSAILLES", "LYON", "AIX-PROVENCE", "TOULOUSE", "BORDEAUX", "RENNES", "DOUAI",
    "MONTPELLIER", "ROUEN", "NANCY", "DIJON", "GRENOBLE", "ANGERS", "ORLEANS", "AMIENS", "METZ",
    "NIMES", "LIMOGES", "CAEN", "REIMS", "BOURGES", "POITIERS", "RIOM", "PAU", "BESANCON", "AGEN",
    "COLMAR", "BASTIA", "CHAMBERY", "BASSE-TERRE", "FORT-DE-FRANCE", "CAYENNE", "ST-DENIS-REUNION",
    "NOUMEA", "PAPEETE",
]

LIEUX_JUDILIBRE = {"ST-DENIS-REUNION": "ca_saint_denis_reunion"}

VILLES_CAA = ["PARIS", "VERSAILLES", "LYON", "MARSEILLE", "BORDEAUX", "NANTES", "NANCY", "DOUAI", "TOULOUSE"]

PUBLICATIONS_CASSATION = {"TOUS": None, "PUBLIE": "T", "INEDIT": "F"}
PUBLICATIONS_JUDILIBRE = {"PUBLIE": ["b"], "INEDIT": ["n"]}
PUBLICATIONS_RECUEIL = ["TOUS", "PUBLIE", "NON_PUBLIE"]

FORMATIONS_TRANSVERSALES = ["ASSEMBLEE_PLENIERE", "CHAMBRE_MIXTE", "CHAMBRES_REUNIES", "AVIS"]

MATIERES_CASSATION = {
    "CIVIL": ["CHAMBRE_CIVILE_1", "CHAMBRE_CIVILE_2", "CHAMBRE_CIVILE_3", "CHAMBRE_CIVILE"],
    "COMMERCIAL": ["CHAMBRE_COMMERCIALE"],
    "PENAL": ["CHAMBRE_CRIMINELLE"],
    "SOCIAL": ["CHAMBRE_SOCIALE"],
}

CHAMBRES_JUDILIBRE = {
    "CIVIL": ["civ1", "civ2", "civ3"],
    "COMMERCIAL": ["comm"],
    "PENAL": ["cr"],
    "SOCIAL": ["soc"],
}

CHAMBRES_JUDILIBRE_TRANSVERSALES = ["pl", "mi", "creun"]

FAMILLES_PREMIER_DEGRE = {
    "TRIBUNAL_JUDICIAIRE": ["tribunal judiciaire"],
    "TRIBUNAL_GRANDE_INSTANCE": ["tribunal de grande instance"],
    "TRIBUNAL_INSTANCE": ["tribunal d'instance"],
    "TRIBUNAL_COMMERCE": ["tribunal de commerce"],
    "CONSEIL_PRUDHOMMES": ["conseil de prud'hommes", "conseil des prud'hommes"],
    "TRIBUNAL_CORRECTIONNEL": ["tribunal correctionnel"],
    "TRIBUNAL_SECURITE_SOCIALE": [
        "tribunal des affaires de securite sociale",
        "trib. des affaires de securite sociale",
    ],
    "TRIBUNAL_BAUX_RURAUX": ["tribunal paritaire des baux ruraux"],
    "JURIDICTION_PROXIMITE": ["juridiction de proximite", "juge de proximite"],
    "OUTRE_MER": [
        "tribunal de premiere instance",
        "tribunal superieur d'appel",
        "chambre de l'application des peines",
    ],
    "TRIBUNAL_CONFLITS": ["tribunal_conflit", "tribunal des conflits"],
}

PREMIER_DEGRE_JUDILIBRE = {"TRIBUNAL_JUDICIAIRE": "tj", "TRIBUNAL_COMMERCE": "tcom"}

LIBELLES_JUDILIBRE = {
    "cc": "Cour de cassation",
    "ca": "Cour d'appel",
    "tj": "Tribunal judiciaire",
    "tcom": "Tribunal de commerce",
}

MOIS = {
    "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7,
    "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12,
}
MOIS_AFFICHES = [
    "janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre",
    "octobre", "novembre", "décembre",
]

DATE_TITRE = re.compile(r"\b(\d{1,2})(?:er)?\s+([a-z]+)\s+(\d{4})\b")
NUMERO_TITRE = re.compile(r"^(?:n°\s*)?(\d[\w./-]*)$", re.IGNORECASE)
ELISION = re.compile(r"^(?:[cdjlmnst]|qu|jusqu|lorsqu|puisqu|quoiqu)['’]", re.IGNORECASE)
ARTICLE = re.compile(r"^([LRDC])(\d+(?:-\d+)*)$")
DATE_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PROXIMITE = 10


class RechercheInvalide(ValueError):
    pass


class RechercheTropLarge(Exception):
    def __init__(self, total: int, comptes: List[Dict[str, Any]]):
        super().__init__(f"{total} résultats")
        self.total = total
        self.comptes = comptes


def sans_accents(texte: str) -> str:
    decompose = unicodedata.normalize("NFD", str(texte or "").lower())
    return "".join(c for c in decompose if unicodedata.category(c) != "Mn")


def _liste(valeur: Any, separer: bool = False) -> List[str]:
    if valeur is None:
        return []
    if isinstance(valeur, str):
        valeurs = valeur.split(",") if separer else [valeur]
    elif isinstance(valeur, (list, tuple)):
        valeurs = [str(v) for v in valeur]
    else:
        return []
    retenues = []
    for v in valeurs:
        v = v.strip().upper()
        if v and v not in retenues:
            retenues.append(v)
    return retenues


def formations_cassation(matiere: Any) -> Tuple[List[str], List[str]]:
    demandees = _liste(matiere, separer=True)
    connues = ", ".join(MATIERES_CASSATION)
    if not demandees:
        raise RechercheInvalide(
            "Filtre `matiere` obligatoire pour la Cour de cassation : indiquez au moins une matière parmi "
            f"{connues}.\n"
            "Sans ce filtre, la recherche renvoie toutes les chambres, y compris "
            "la chambre criminelle sur une question civile ou commerciale.\n"
            "Pour couvrir volontairement toutes les chambres, énumérez les "
            "quatre matières."
        )
    inconnues = [m for m in demandees if m not in MATIERES_CASSATION]
    if inconnues:
        raise RechercheInvalide(f"Matière(s) inconnue(s) : {', '.join(inconnues)}. Valeurs acceptées : {connues}.")
    formations = []
    for m in demandees:
        for formation in MATIERES_CASSATION[m]:
            if formation not in formations:
                formations.append(formation)
    return demandees, formations + FORMATIONS_TRANSVERSALES


def familles_premier_degre(argument: Any) -> List[str]:
    demandees = _liste(argument)
    connues = ", ".join(FAMILLES_PREMIER_DEGRE)
    if not demandees:
        raise RechercheInvalide(
            "Filtre `types_premiere_instance` obligatoire pour la première instance : indiquez au "
            f"moins une famille parmi {connues}.\n"
            "En première instance, la matière est portée par le nom de la "
            "juridiction : sans ce filtre, la recherche mélange prud'hommes, "
            "correctionnel et commerce."
        )
    inconnues = [a for a in demandees if a not in FAMILLES_PREMIER_DEGRE]
    if inconnues:
        raise RechercheInvalide(f"Famille(s) inconnue(s) : {', '.join(inconnues)}. Valeurs acceptées : {connues}.")
    return demandees


def valeurs_premier_degre(familles: List[str], valeurs_facette: List[str]) -> List[str]:
    prefixes = [p for famille in familles for p in FAMILLES_PREMIER_DEGRE[famille]]
    retenus = []
    for libelle in valeurs_facette:
        if any(sans_accents(libelle).startswith(p) for p in prefixes) and libelle not in retenus:
            retenus.append(libelle)
    return retenus


def _choix(valeur: Any, permis: List[str], nom: str, defaut: str) -> str:
    choisi = str(valeur or defaut).strip().upper()
    if choisi not in permis:
        raise RechercheInvalide(f"`{nom}` inconnu : {choisi}. Valeurs acceptées : {', '.join(permis)}.")
    return choisi


def _sous_ensemble(valeur: Any, permis: List[str], nom: str) -> List[str]:
    retenues = _liste(valeur)
    inconnues = [v for v in retenues if v not in permis]
    if inconnues:
        raise RechercheInvalide(f"`{nom}` inconnu(s) : {', '.join(inconnues)}. Valeurs acceptées : {', '.join(permis)}.")
    return retenues


def _date(valeur: Any, nom: str) -> Optional[str]:
    texte = str(valeur or "").strip()
    if not texte:
        return None
    try:
        datetime.strptime(texte, "%Y-%m-%d")
    except ValueError:
        raise RechercheInvalide(f"`{nom}` doit être une date AAAA-MM-JJ (reçu : {texte}).")
    return texte


def preparer(args: Dict[str, Any], dates_par_defaut: bool = True) -> Dict[str, Any]:
    requete = re.sub(r"\s+", " ", str(args.get("query") or "")).strip()
    if not requete:
        raise RechercheInvalide("`query` est requis.")
    try:
        _operateur, _type, criteres = parse_query(requete)
    except ValueError as erreur:
        raise RechercheInvalide(f"Requête invalide : {erreur}.")

    juridictions = []
    for valeur in _liste(args.get("juridictions")) or ["CASSATION"]:
        cle = valeur.lower()
        for juridiction in ALIAS_JURIDICTIONS.get(cle, [cle]):
            if juridiction not in JURIDICTIONS:
                raise RechercheInvalide(
                    f"Juridiction inconnue : {cle}. Valeurs acceptées : {', '.join(JURIDICTIONS)}."
                )
            if juridiction not in juridictions:
                juridictions.append(juridiction)

    sources = [s.lower() for s in _liste(args.get("sources"))] or list(SOURCES)
    inconnues = [s for s in sources if s not in SOURCES]
    if inconnues:
        raise RechercheInvalide(f"Source(s) inconnue(s) : {', '.join(inconnues)}. Valeurs acceptées : {', '.join(SOURCES)}.")

    plan = {
        "query": requete,
        "criteres": criteres,
        "juridictions": juridictions,
        "sources": [s for s in SOURCES if s in sources],
        "matieres": [],
        "formations": [],
        "publication_cassation": _choix(args.get("publication_cassation"), list(PUBLICATIONS_CASSATION), "publication_cassation", "TOUS"),
        "sieges_appel": _sous_ensemble(args.get("sieges_appel"), SIEGES_APPEL, "sieges_appel"),
        "types_premiere_instance": [],
        "villes_caa": _sous_ensemble(args.get("villes_caa"), VILLES_CAA, "villes_caa"),
        "publication_recueil": _choix(args.get("publication_recueil"), PUBLICATIONS_RECUEIL, "publication_recueil", "TOUS"),
        "date_debut": _date(args.get("date_debut"), "date_debut"),
        "date_fin": _date(args.get("date_fin"), "date_fin"),
        "dates_par_defaut": dates_par_defaut,
    }
    if plan["date_debut"] and plan["date_fin"] and plan["date_debut"] > plan["date_fin"]:
        raise RechercheInvalide("`date_debut` est postérieure à `date_fin`.")
    if "cassation" in juridictions:
        plan["matieres"], plan["formations"] = formations_cassation(args.get("matiere"))
    if "premiere_instance" in juridictions:
        plan["types_premiere_instance"] = familles_premier_degre(args.get("types_premiere_instance"))
    return plan


def periode(plan: Dict[str, Any], juridiction: str) -> Tuple[Optional[str], Optional[str]]:
    debut, fin = plan["date_debut"], plan["date_fin"]
    if plan["dates_par_defaut"]:
        aujourd_hui = datetime.now()
        fin = fin or aujourd_hui.strftime("%Y-%m-%d")
        debut = debut or (aujourd_hui - timedelta(days=ANNEES_PAR_DEFAUT[juridiction] * 365)).strftime("%Y-%m-%d")
    return debut, (borne_haute_reelle(fin) if fin else None)


def criteres_juridiction(plan: Dict[str, Any], juridiction: str) -> QueryCriteria:
    criteres = plan["criteres"]
    if juridiction == "premiere_instance" and not criteres.explicit_operators and len(criteres) > 1:
        return QueryCriteria(list(criteres), [[critere] for critere in criteres], False)
    return criteres


def _filtres_legifrance(plan: Dict[str, Any], juridiction: str, debut: Optional[str], fin: Optional[str]) -> List[Dict[str, Any]]:
    dates = {}
    if debut:
        dates["start"] = debut
    if fin:
        dates["end"] = fin
    filtres = [{"facette": "DATE_DECISION", "dates": dates}] if dates else []
    if juridiction == "cassation":
        filtres = [{"facette": "JURIDICTION_JUDICIAIRE", "valeurs": ["Cour de cassation"]}] + filtres
        filtres.append({"facette": "CASSATION_FORMATION", "valeurs": plan["formations"]})
        publication = PUBLICATIONS_CASSATION[plan["publication_cassation"]]
        if publication:
            filtres.append({"facette": "CASSATION_TYPE_PUBLICATION_BULLETIN", "valeurs": [publication]})
    elif juridiction == "appel":
        filtres = [{"facette": "JURIDICTION_JUDICIAIRE", "valeurs": ["Juridictions d'appel"]}] + filtres
        if plan["sieges_appel"]:
            filtres.append({"facette": "APPEL_SIEGE_APPEL", "valeurs": plan["sieges_appel"]})
    elif juridiction == "premiere_instance":
        filtres = [{"facette": "JURIDICTION_JUDICIAIRE", "valeurs": ["Juridictions du premier degré"]}] + filtres
    else:
        parent = "CONSEIL_ETAT" if juridiction == "conseil_etat" else "COURS_APPEL"
        enfants = [] if juridiction == "conseil_etat" else list(plan["villes_caa"])
        filtres.append({"facette": "JURIDICTION_NATURE", "valeurs": [parent], "multiValeurs": {parent: enfants}})
        if plan["publication_recueil"] != "TOUS":
            filtres.append({"facette": "PUBLICATION_RECUEIL", "valeurs": [plan["publication_recueil"]]})
    return filtres


def _chercher_legifrance(client: Any, fond: str, criteres: QueryCriteria, filtres: List[Dict[str, Any]], page: int, taille: int) -> Dict[str, Any]:
    return client.search_with_criteres(
        fond=fond,
        criteres=criteres,
        operateur="ET",
        filtres=filtres,
        type_champ="ALL",
        page_number=page,
        page_size=taille,
        sort="PERTINENCE",
    )


def _total(reponse: Dict[str, Any]) -> Optional[int]:
    try:
        total = int(reponse.get("totalResultNumber"))
    except (TypeError, ValueError):
        return None
    if total > 0 or not (reponse.get("results") or []):
        return total
    return None


def _lister_legifrance(client: Any, fond: str, criteres: QueryCriteria, filtres: List[Dict[str, Any]], limite: int) -> Tuple[List[Dict[str, Any]], int]:
    collectes: List[Dict[str, Any]] = []
    appels = 0
    page = 1
    while len(collectes) < limite:
        reponse = _chercher_legifrance(client, fond, criteres, filtres, page, LEGIFRANCE_PAGE)
        appels += 1
        lot = reponse.get("results") or []
        collectes.extend(lot)
        if len(lot) < LEGIFRANCE_PAGE:
            break
        page += 1
    return collectes[:limite], appels


def _alternatives(mot: str) -> List[str]:
    nu = ELISION.sub("", re.sub(r"^[\W_]+|[\W_]+$", "", mot))
    article = ARTICLE.match(nu)
    if article:
        return [f'+"{article.group(1)}. {article.group(2)}"', f"+{nu}"]
    if not nu:
        return []
    return [f"+{nu}"] if re.fullmatch(r"[^\W_]+", nu) else [f'+"{nu}"']


def requetes_judilibre(clauses: List[List[Dict[str, Any]]]) -> List[str]:
    requetes: List[str] = []
    for clause in clauses:
        choix = [options for critere in clause for mot in str(critere["valeur"]).split() if (options := _alternatives(mot))]
        if not choix:
            continue
        combinaisons = list(product(*choix))
        if len(combinaisons) > MAX_REQUETES_JUDILIBRE:
            combinaisons = [tuple(options[0] for options in choix)]
        for termes in combinaisons:
            requete = " ".join(termes)
            if requete not in requetes:
                requetes.append(requete)
    return requetes


def lieu_judilibre(siege: str) -> str:
    if siege in LIEUX_JUDILIBRE:
        return LIEUX_JUDILIBRE[siege]
    return "ca_" + re.sub(r"[^a-z]+", "_", sans_accents(siege)).strip("_")


def _filtres_judilibre(plan: Dict[str, Any], juridiction: str, debut: Optional[str], fin: Optional[str]) -> Optional[List[Tuple[str, str]]]:
    if "judilibre" not in plan["sources"]:
        return None
    if juridiction == "cassation":
        filtres = [("jurisdiction", "cc")]
        chambres = [c for m in plan["matieres"] for c in CHAMBRES_JUDILIBRE[m]] + CHAMBRES_JUDILIBRE_TRANSVERSALES
        filtres += [("chamber", c) for c in chambres]
        filtres += [("publication", p) for p in PUBLICATIONS_JUDILIBRE.get(plan["publication_cassation"], [])]
    elif juridiction == "appel":
        filtres = [("jurisdiction", "ca")] + [("location", lieu_judilibre(s)) for s in plan["sieges_appel"]]
    elif juridiction == "premiere_instance":
        codes = []
        for famille in plan["types_premiere_instance"]:
            code = PREMIER_DEGRE_JUDILIBRE.get(famille)
            if code and code not in codes:
                codes.append(code)
        if not codes:
            return None
        filtres = [("jurisdiction", code) for code in codes]
    else:
        return None
    if debut:
        filtres.append(("date_start", debut))
    if fin:
        filtres.append(("date_end", fin))
    return filtres


def _chercher_judilibre(client: Any, requete: str, filtres: List[Tuple[str, str]], page: int, taille: int) -> Dict[str, Any]:
    return client.judilibre("/search", [("query", requete), *filtres, ("page", str(page)), ("page_size", str(taille))])


def date_iso(valeur: Any) -> str:
    if est_date_absente(valeur):
        return ""
    if isinstance(valeur, (int, float)):
        try:
            return datetime.fromtimestamp(valeur / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        except (OverflowError, OSError, ValueError):
            return ""
    texte = str(valeur).strip()
    if texte.isdigit() and len(texte) >= 10:
        return date_iso(int(texte))
    return texte[:10] if DATE_ISO.match(texte[:10]) else ""


def date_longue(iso: str) -> str:
    try:
        jour = datetime.strptime(iso, "%Y-%m-%d")
    except (TypeError, ValueError):
        return iso or ""
    return f"{'1er' if jour.day == 1 else jour.day} {MOIS_AFFICHES[jour.month - 1]} {jour.year}"


def _date_du_titre(titre: str) -> Tuple[str, int]:
    plat = sans_accents(titre)
    for segment_index, segment in enumerate(plat.split(",")):
        trouve = DATE_TITRE.search(segment)
        if trouve and trouve.group(2) in MOIS:
            try:
                jour = datetime(int(trouve.group(3)), MOIS[trouve.group(2)], int(trouve.group(1)))
            except ValueError:
                continue
            return jour.strftime("%Y-%m-%d"), segment_index
    return "", -1


def _resultat_legifrance(resultat: Dict[str, Any], juridiction: str, rang: int) -> Optional[Dict[str, Any]]:
    titres = resultat.get("titles") or []
    premier = titres[0] if titres else {}
    identifiant = str(premier.get("id") or "").strip()
    if not identifiant:
        return None
    titre = str(premier.get("title") or "Sans titre").strip()
    date_titre, position = _date_du_titre(titre)
    numeros = []
    if position >= 0:
        for segment in titre.split(",")[position + 1:]:
            trouve = NUMERO_TITRE.match(segment.strip())
            if trouve:
                numeros.append(trouve.group(1))
    fond = FONDS[juridiction]
    return {
        "id": identifiant,
        "source": "legifrance",
        "juridiction": juridiction,
        "titre": titre,
        "date": date_iso(resultat.get("date")) or date_titre,
        "numeros": numeros,
        "lien": f"{LIENS_LEGIFRANCE[fond]}{identifiant}",
        "rang": rang,
        "resultat": resultat,
    }


def _resultat_judilibre(resultat: Dict[str, Any], juridiction: str, rang: int) -> Optional[Dict[str, Any]]:
    identifiant = str(resultat.get("id") or "").strip()
    if not re.fullmatch(r"[0-9a-f]{24}", identifiant):
        return None
    numeros = [str(n) for n in resultat.get("numbers") or [] if n] or ([str(resultat["number"])] if resultat.get("number") else [])
    date = date_iso(resultat.get("decision_date"))
    code = str(resultat.get("jurisdiction") or "")
    lieu = str(resultat.get("location") or "")
    morceaux = [LIBELLES_JUDILIBRE.get(code, code or "Judilibre")]
    if lieu and code != "cc":
        morceaux[0] += f" ({lieu})"
    if date:
        morceaux.append(date_longue(date))
    if numeros:
        morceaux.append(f"n° {numeros[0]}")
    return {
        "id": identifiant,
        "source": "judilibre",
        "juridiction": juridiction,
        "titre": ", ".join(morceaux),
        "date": date,
        "numeros": numeros,
        "lien": f"{LIEN_JUDILIBRE}{identifiant}",
        "rang": rang,
        "resultat": resultat,
        "code": code,
        "lieu": lieu,
    }


def _cle_numero(valeur: str) -> str:
    return re.sub(r"^n°", "", re.sub(r"\s+", "", str(valeur).lower()))


def meme_numero(gauche: str, droite: str) -> bool:
    a, b = _cle_numero(gauche), _cle_numero(droite)
    if not a or not b:
        return False
    if a == b:
        return True
    premier = re.fullmatch(r"(\d{2})/0*(\d{3,})", a)
    second = re.fullmatch(r"(\d{2})/0*(\d{3,})", b)
    if not premier or not second or premier.group(1) != second.group(1):
        return False
    x, y = premier.group(2), second.group(2)
    return x == y or x[:-1] == y or y[:-1] == x


def _code_legifrance(resultat: Dict[str, Any]) -> Optional[str]:
    if resultat["juridiction"] == "cassation":
        return "cc"
    if resultat["juridiction"] == "appel":
        return "ca"
    if resultat["juridiction"] == "premiere_instance":
        titre = sans_accents(resultat["titre"])
        if titre.startswith("tribunal judiciaire"):
            return "tj"
        if titre.startswith("tribunal de commerce") or titre.startswith("tribunal des activites economiques"):
            return "tcom"
    return None


def meme_decision(legifrance: Dict[str, Any], judilibre: Dict[str, Any]) -> bool:
    code = _code_legifrance(legifrance)
    if not code or code != judilibre.get("code") or not legifrance["date"] or legifrance["date"] != judilibre["date"]:
        return False
    if code == "ca" and judilibre.get("lieu"):
        mots_titre = set(re.findall(r"[a-z]+", sans_accents(legifrance["titre"].split(",")[0])))
        mots_lieu = [m for m in judilibre["lieu"].split("_")[1:] if m]
        if mots_lieu and not all(m in mots_titre for m in mots_lieu):
            return False
    return any(meme_numero(a, b) for a in legifrance["numeros"] for b in judilibre["numeros"])


def _stem(mot: str) -> str:
    return re.sub(r"[sx]$", "", mot) if len(mot) > 3 else mot


def mots(texte: str) -> List[str]:
    normalise = re.sub(
        r"\b([LRDC])\.?\s*(\d+[-\d]+)\b",
        lambda trouve: normalize_article_reference(trouve.group(0)),
        str(texte or ""),
        flags=re.IGNORECASE,
    )
    return [_stem(m) for m in re.split(r"[^a-z0-9]+", sans_accents(normalise)) if m]


def index_texte(texte: str) -> Dict[str, List[int]]:
    index: Dict[str, List[int]] = {}
    for position, mot in enumerate(mots(texte)):
        index.setdefault(mot, []).append(position)
    return index


def _critere_trouve(index: Dict[str, List[int]], critere: Dict[str, Any]) -> bool:
    termes = mots(critere["valeur"])
    if not termes:
        return True
    premier, suite = termes[0], termes[1:]
    if critere.get("typeRecherche") == "EXACTE":
        return any(all(debut + i + 1 in index.get(mot, []) for i, mot in enumerate(suite)) for debut in index.get(premier, []))
    if not suite:
        return premier in index
    ecart = (critere.get("proximite") or PROXIMITE) + len(suite)
    return any(all(any(abs(p - debut) <= ecart for p in index.get(mot, [])) for mot in suite) for debut in index.get(premier, []))


def clauses_trouvees(texte: str, clauses: List[List[Dict[str, Any]]]) -> bool:
    index = index_texte(texte)
    return any(all(_critere_trouve(index, critere) for critere in clause) for clause in clauses)


def a_verifier(clauses: List[List[Dict[str, Any]]]) -> bool:
    return any(len(mots(critere["valeur"])) > 1 for clause in clauses for critere in clause)


def sans_balises(valeur: Any) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", str(valeur or ""))).strip()


def titre_judilibre(decision: Dict[str, Any], defaut: str) -> str:
    lieu = sans_balises(decision.get("location")) or sans_balises(decision.get("jurisdiction"))
    date = date_longue(str(decision.get("decision_date") or "")[:10])
    numero = sans_balises(decision.get("number")) or next((sans_balises(n) for n in decision.get("numbers") or [] if n), "")
    morceaux = [m for m in (lieu, date, f"n° {numero}" if numero else "") if m]
    return ", ".join(morceaux) or defaut


def decision_judilibre(client: Any, identifiant: str) -> Dict[str, Any]:
    return client.judilibre("/decision", [("id", identifiant), ("resolve_references", "true")])


def _compter(client: Any, plan: Dict[str, Any], etat: Dict[str, Any]) -> List[Dict[str, Any]]:
    etapes = []
    for juridiction in plan["juridictions"]:
        debut, fin = periode(plan, juridiction)
        criteres = criteres_juridiction(plan, juridiction)
        fond = FONDS[juridiction]
        filtres = _filtres_legifrance(plan, juridiction, debut, fin)
        etape = {
            "juridiction": juridiction,
            "debut": debut,
            "fin": fin,
            "fond": fond,
            "criteres": criteres,
            "filtres": filtres,
            "legifrance": None,
            "judilibre": None,
            "requetes_judilibre": [],
            "filtres_judilibre": None,
        }
        if "legifrance" in plan["sources"]:
            sonde = _chercher_legifrance(client, fond, criteres, filtres, 1, 1)
            etat["appels"] += 1
            if juridiction == "premiere_instance":
                valeurs = []
                for facette in sonde.get("facets") or []:
                    if facette.get("facetElem") == "PREMIER_DEGRE_TYPE_JURIDICTION":
                        valeurs = list((facette.get("values") or {}).keys())
                        break
                libelles = valeurs_premier_degre(plan["types_premiere_instance"], valeurs)
                if libelles:
                    filtres = filtres + [{"facette": "PREMIER_DEGRE_TYPE_JURIDICTION", "valeurs": libelles}]
                    etape["filtres"] = filtres
                    sonde = _chercher_legifrance(client, fond, criteres, filtres, 1, 1)
                    etat["appels"] += 1
                else:
                    sonde = {"totalResultNumber": 0, "results": []}
            total = _total(sonde)
            if total is None:
                liste, appels = _lister_legifrance(client, fond, criteres, filtres, LIMITE_RESULTATS + 1)
                etat["appels"] += appels
                total = len(liste)
            etape["legifrance"] = total
        filtres_judilibre = _filtres_judilibre(plan, juridiction, debut, fin) if etat["judilibre_actif"] else None
        if filtres_judilibre is not None:
            requetes = requetes_judilibre(criteres.clauses)
            try:
                total = 0
                for requete in requetes:
                    reponse = _chercher_judilibre(client, requete, filtres_judilibre, 0, 1)
                    etat["appels"] += 1
                    compte = reponse.get("total")
                    if not isinstance(compte, int) or compte < 0:
                        raise JudilibreError("nombre de résultats absent de la réponse")
                    total += compte
                etape["judilibre"] = total
                etape["requetes_judilibre"] = requetes
                etape["filtres_judilibre"] = filtres_judilibre
            except Exception as erreur:
                _judilibre_indisponible(etat, erreur)
        etapes.append(etape)
    return etapes


def _judilibre_indisponible(etat: Dict[str, Any], erreur: Exception) -> None:
    if etat["judilibre_actif"]:
        etat["avertissements"].append(f"Judilibre indisponible, résultats Légifrance seuls : {erreur}")
    etat["judilibre_actif"] = False


def collecter(plan: Dict[str, Any], client: Any = None) -> Dict[str, Any]:
    client = client or legifrance_client
    etat = {"appels": 0, "judilibre_actif": "judilibre" in plan["sources"], "avertissements": []}
    etapes = _compter(client, plan, etat)
    comptes = [
        {"juridiction": e["juridiction"], "debut": e["debut"], "fin": e["fin"], "legifrance": e["legifrance"], "judilibre": e["judilibre"]}
        for e in etapes
    ]
    total = sum((e["legifrance"] or 0) + (e["judilibre"] or 0) for e in etapes)
    if total > LIMITE_RESULTATS:
        raise RechercheTropLarge(total, comptes)

    legifrance: List[Dict[str, Any]] = []
    judilibre: List[Dict[str, Any]] = []
    vus = set()
    for etape in etapes:
        if etape["legifrance"]:
            liste, appels = _lister_legifrance(client, etape["fond"], etape["criteres"], etape["filtres"], LIMITE_RESULTATS)
            etat["appels"] += appels
            for rang, brut in enumerate(liste, 1):
                resultat = _resultat_legifrance(brut, etape["juridiction"], rang)
                if resultat and resultat["id"] not in vus:
                    vus.add(resultat["id"])
                    legifrance.append(resultat)
        if etape["judilibre"] and etat["judilibre_actif"]:
            try:
                for requete in etape["requetes_judilibre"]:
                    page = 0
                    while True:
                        reponse = _chercher_judilibre(client, requete, etape["filtres_judilibre"], page, JUDILIBRE_PAGE)
                        etat["appels"] += 1
                        lot = reponse.get("results") or []
                        for brut in lot:
                            resultat = _resultat_judilibre(brut, etape["juridiction"], len(judilibre) + 1)
                            if resultat and resultat["id"] not in vus:
                                vus.add(resultat["id"])
                                resultat["clauses"] = etape["criteres"].clauses
                                judilibre.append(resultat)
                        if len(lot) < JUDILIBRE_PAGE or not reponse.get("next_page"):
                            break
                        page += 1
            except Exception as erreur:
                _judilibre_indisponible(etat, erreur)

    fusionnees = 0
    restants = []
    for resultat in judilibre:
        jumeau = next((l for l in legifrance if "judilibre" not in l and meme_decision(l, resultat)), None)
        if jumeau:
            jumeau["judilibre"] = {"id": resultat["id"], "lien": resultat["lien"]}
            fusionnees += 1
        else:
            restants.append(resultat)

    ecartees = 0
    a_controler = [r for r in restants if a_verifier(r["clauses"])]
    if a_controler and etat["judilibre_actif"]:
        def verifier(resultat: Dict[str, Any]) -> None:
            try:
                resultat["decision"] = decision_judilibre(client, resultat["id"])
            except Exception as erreur:
                resultat["verification"] = f"texte indisponible ({erreur}) : expression exacte non vérifiée"
        with ThreadPoolExecutor(max_workers=VERIFICATIONS_SIMULTANEES) as pool:
            list(pool.map(verifier, a_controler))
        etat["appels"] += len(a_controler)
        controles = {r["id"] for r in a_controler}
        conserves = []
        for resultat in restants:
            texte = str((resultat.get("decision") or {}).get("text") or "")
            if resultat["id"] in controles and texte and not clauses_trouvees(texte, resultat["clauses"]):
                ecartees += 1
            else:
                conserves.append(resultat)
        restants = conserves

    resultats = legifrance + restants
    resultats.sort(key=lambda r: (r["source"] != "legifrance", r["rang"]))
    resultats.sort(key=lambda r: r["date"], reverse=True)
    return {
        "resultats": resultats,
        "comptes": comptes,
        "total_avant_fusion": total,
        "fusionnees": fusionnees,
        "ecartees": ecartees,
        "avertissements": etat["avertissements"],
        "appels": etat["appels"],
        "judilibre_actif": etat["judilibre_actif"],
    }


_cache: "OrderedDict[str, Tuple[float, Dict[str, Any]]]" = OrderedDict()


def _cle_cache(plan: Dict[str, Any]) -> str:
    visible = {k: v for k, v in plan.items() if k != "criteres"}
    visible["periodes"] = [periode(plan, j) for j in plan["juridictions"]]
    return json.dumps(visible, sort_keys=True, ensure_ascii=False)


def collecter_avec_cache(plan: Dict[str, Any], client: Any = None) -> Dict[str, Any]:
    cle = _cle_cache(plan)
    maintenant = time.monotonic()
    trouve = _cache.get(cle)
    if trouve and maintenant - trouve[0] < CACHE_SECONDES:
        _cache.move_to_end(cle)
        return trouve[1]
    collecte = collecter(plan, client)
    _cache[cle] = (maintenant, collecte)
    while len(_cache) > CACHE_TAILLE:
        _cache.popitem(last=False)
    return collecte


def vider_cache() -> None:
    _cache.clear()
