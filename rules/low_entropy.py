"""Regle 1 — low_entropy_output (D2.1), portee de detector/scan.py.

Un appel LLM dont les sorties, une fois normalisees, ne prennent qu'une poignee
de valeurs n'est pas du raisonnement : c'est un aiguillage facture au prix d'un modele.
Groupement : application x modele x gabarit de prompt. Aucun appel LLM, que de la statistique.
"""
import hashlib
import math
import re
from collections import Counter, defaultdict

# Seuils repris tels quels du prototype (verdicts identiques au hackathon).
MIN_CALLS = 30      # en dessous, la distribution n'est pas significative
MAX_DISTINCT = 8    # au-dela, on considere que le modele produit de l'information
CUT_DISTINCT = 4    # <= 4 sorties : remplacable par des regles (cut), sinon trim
MAX_SAMPLES_PER_OUTPUT = 12

_EDGE_PUNCT = re.compile(r"^[\s\W_]+|[\s\W_]+$")
_NUMBERS = re.compile(r"\d+")


def normalize(text):
    """Casse, espaces et ponctuation de bord : 'Spam.' == ' spam ' == 'SPAM!'."""
    collapsed = " ".join(str(text).lower().split())
    return _EDGE_PUNCT.sub("", collapsed)[:200]


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
        if e.get("error") or e["response"].get("content") is None:
            continue
        groups[(e["app_id"], e["model"], template_of(e))].append(e)
    return groups


def _finding(app_id, model, template, evts, outputs, raw):
    dist = Counter(outputs)
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
                  f"c'est un aiguillage, pas du raisonnement"),
        "proven": False,
        "event_ids": [e["event_id"] for e in evts],
        "evidence": {
            "calls": n,
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
        raw = [e["response"]["content"] for e in evts]
        outputs = [normalize(r) for r in raw]
        distinct = len(set(outputs))
        if distinct > MAX_DISTINCT:
            continue
        # Entrees aussi repetitives que les sorties : sortie dictee par l'entree,
        # c'est un probleme de cache (regle no_cache), pas un classifieur.
        if len({_input_key(e) for e in evts}) <= distinct:
            continue
        findings.append(_finding(app_id, model, template, evts, outputs, raw))
    return sorted(findings, key=lambda f: f["evidence"]["entropy_bits"])
