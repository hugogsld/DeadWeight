"""Regle 1 — low_entropy_output (D2.1), portee de detector/scan.py.

Un appel LLM dont les sorties, une fois normalisees, ne prennent qu'une poignee
de valeurs n'est pas du raisonnement : c'est un aiguillage facture au prix d'un modele.
Groupement : application x modele x gabarit de prompt. Aucun appel LLM, que de la statistique.

Trois formes de sortie (#105), ramenees a une meme etiquette comparable (``output_of``) :

- texte : ``normalize`` (casse, espaces, ponctuation de bord) ;
- JSON (``{"category": "spam"}``, eventuellement dans un bloc ```json) : champs a plat, cles triees,
  valeurs en minuscules -> ``category=spam``. Les scores de confiance (cle confidence, score,
  probability... a valeur decimale) sont retires : ils varient sans changer la branche choisie.
  Les autres nombres sont gardes (un montant extrait est de l'information) ;
- appel d'outil qui repond DIRECTEMENT a l'utilisateur (dernier message = utilisateur, pas un
  resultat d'outil) : ``outil <nom> <arguments a plat>``. C'est l'aiguillage des agents a handoff
  (triage OpenAI : ``transfer_to_faq_agent`` sans argument). Un appel d'outil dans une boucle d'agent
  (apres un resultat d'outil) continue un travail : il reste ignore, comme avant.

Pas de faux positif sur un vrai travail : un outil appele avec des arguments riches et varies
(une requete differente par demande) donne autant d'etiquettes que d'appels, au-dela de MAX_DISTINCT.
"""
import hashlib
import json
import math
import os
import re
from collections import Counter, defaultdict

# Seuils repris tels quels du prototype (verdicts identiques au hackathon).
# DW_MIN_CALLS : seuil unique, abaissable pour une demo sur peu d'executions (defaut inchange : 30).
MIN_CALLS = int(os.environ.get("DW_MIN_CALLS", "30"))      # en dessous, la distribution n'est pas significative
MAX_DISTINCT = 8    # au-dela, on considere que le modele produit de l'information
CUT_DISTINCT = 4    # <= 4 sorties : remplacable par des regles (cut), sinon trim
MAX_SAMPLES_PER_OUTPUT = 12

_EDGE_PUNCT = re.compile(r"^[\s\W_]+|[\s\W_]+$")
_NUMBERS = re.compile(r"\d+")


def normalize(text):
    """Casse, espaces et ponctuation de bord : 'Spam.' == ' spam ' == 'SPAM!'."""
    collapsed = " ".join(str(text).lower().split())
    return _EDGE_PUNCT.sub("", collapsed)[:200]


_FENCE = re.compile(r"^```[a-z]*\s*|\s*```$", re.I)
_SCORE_KEYS = re.compile(r"(^|[._])(confidence|score|probability|proba|certainty|likelihood)$", re.I)


def _flat(value, path=""):
    """Objet JSON -> [(chemin, texte)] trie ; scores de confiance decimaux retires."""
    if isinstance(value, dict):
        return sorted(kv for k, v in value.items() for kv in _flat(v, f"{path}.{k}" if path else str(k)))
    if isinstance(value, list):
        return [(path, "|".join(t for _, t in (kv for x in value for kv in _flat(x))))]
    if isinstance(value, float) and not value.is_integer() and _SCORE_KEYS.search(path):
        return []
    if isinstance(value, bool) or value is None:
        return [(path, json.dumps(value))]
    return [(path, " ".join(str(value).lower().split()))]


def _fields(value):
    return ", ".join(f"{k}={v}" if k else v for k, v in _flat(value))


def _json_object(text):
    stripped = _FENCE.sub("", str(text).strip())
    if not stripped.startswith("{"):
        return None
    try:
        value = json.loads(stripped)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def canon(text):
    """Etiquette d'une sortie texte : JSON a plat si c'est un objet JSON, sinon ``normalize``."""
    obj = _json_object(text)
    return normalize(text) if obj is None else normalize(_fields(obj))


def _tool_signature(call):
    try:
        args = json.loads(call.get("arguments") or "{}")
    except (TypeError, ValueError):
        args = call.get("arguments")
    fields = _fields(args) if isinstance(args, dict) else " ".join(str(args).lower().split())
    return " ".join(x for x in ("outil", call.get("name") or "?", fields) if x)


def _routes_by_tool(event):
    msgs = event["request"].get("messages") or []
    return bool(event["response"].get("tool_calls")) and bool(msgs) and msgs[-1].get("role") == "user"


def output_kind(event):
    """'appel_outil', 'json', 'texte', ou None si l'appel n'a pas de sortie comparable."""
    if event.get("error"):
        return None
    if _routes_by_tool(event):
        return "appel_outil"
    content = event["response"].get("content")
    if content is None:
        return None
    return "json" if _json_object(content) is not None else "texte"


def output_of(event):
    """Etiquette comparable de la decision prise par l'appel, ou None (erreur, etape de boucle)."""
    kind = output_kind(event)
    if kind == "appel_outil":
        return normalize(" + ".join(sorted(_tool_signature(c) for c in event["response"]["tool_calls"])))
    return None if kind is None else canon(event["response"]["content"])


def _raw(event):
    if output_kind(event) == "appel_outil":
        return json.dumps([[c.get("name"), c.get("arguments")] for c in event["response"]["tool_calls"]])
    return event["response"]["content"]


def shannon(counts):
    n = sum(counts.values())
    return -sum(c / n * math.log2(c / n) for c in counts.values()) + 0.0


def template_of(event):
    """Gabarit = prompt systeme sans les nombres (ids, dates) : meme tache = meme gabarit."""
    system = event["request"].get("system") or ""
    key = _NUMBERS.sub("#", " ".join(system.split()))
    return hashlib.sha1(key.encode()).hexdigest()[:10]


def _input_key(event):
    msgs = event["request"]["messages"]
    return normalize(" ".join(m.get("content") or "" for m in msgs))


def _groups(events):
    groups = defaultdict(list)
    for e in events:
        if output_of(e) is None:
            continue
        groups[(e["app_id"], e["model"], template_of(e))].append(e)
    return groups


def _finding(app_id, model, template, evts, outputs, raw):
    dist = Counter(outputs)
    kinds = Counter(output_kind(e) for e in evts)
    kind = kinds.most_common(1)[0][0]
    how = {"appel_outil": " (choix fait par appel d'outil)", "json": " (réponses en JSON)"}
    seen, samples = Counter(), []
    for e, out in zip(evts, outputs):
        if seen[out] < MAX_SAMPLES_PER_OUTPUT:
            seen[out] += 1
            samples.append({"event_id": e["event_id"], "output": out})
    n = len(evts)
    cut = len(dist) <= CUT_DISTINCT
    return {
        "finding_id": f"f_{app_id}_{template}_low_entropy",
        "rule": "low_entropy_output",
        "app_id": app_id,
        "model": model,
        "template": template,
        "severity": "cut" if cut else "trim",
        "title": (f"{n} appels à {model} ne produisent que {len(dist)} réponses différentes : "
                  f"c'est un aiguillage, pas du raisonnement{how.get(kind, '')}"),
        "proven": False,
        "event_ids": [e["event_id"] for e in evts],
        "evidence": {
            "calls": n,
            "output_kind": kind,
            "distinct_outputs": len(dist),
            "distinct_raw_outputs": len(set(raw)),
            "entropy_bits": round(shannon(dist), 2),
            "max_entropy_bits": round(math.log2(n), 2),
            "output_distribution": dict(dist.most_common()),
            "samples": samples,
        },
    }


def detect(events):
    findings = []
    for (app_id, model, template), evts in _groups(events).items():
        if len(evts) < MIN_CALLS:
            continue
        raw = [_raw(e) for e in evts]
        outputs = [output_of(e) for e in evts]
        distinct = len(set(outputs))
        if distinct > MAX_DISTINCT:
            continue
        # Entrees aussi repetitives que les sorties : sortie dictee par l'entree,
        # c'est un probleme de cache (regle no_cache), pas un classifieur.
        if len({_input_key(e) for e in evts}) <= distinct:
            continue
        findings.append(_finding(app_id, model, template, evts, outputs, raw))
    return sorted(findings, key=lambda f: f["evidence"]["entropy_bits"])
