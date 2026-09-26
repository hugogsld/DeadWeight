"""R5 — unbounded_loop (D2.4) : un agent qui refait la même action sans avancer.

Par trace (D1.4), on regarde les appels d'outils que le modèle a demandés, dans
l'ordre des étapes. Une action est une *répétition* si le même outil a déjà été
appelé dans cette trace avec des arguments quasi identiques. Une trace est une
boucle quand les répétitions sont à la fois nombreuses et majoritaires.

Seuils et raisonnement :

- SIMILARITY = 0.6 (Jaccard sur les mots des arguments, pluriel en -s retiré,
  chiffres gardés). « tarif entreprise » / « tarifs entreprise 2026 » = 0,67 :
  même recherche reformulée. « read_page page 3 » / « page 4 » avec une URL
  courte reste sous le seuil : une pagination avance. Les chiffres sont gardés
  exprès, sinon toute pagination deviendrait une boucle.
- MIN_REPEATS = 5 : relancer un outil deux ou trois fois (erreur, vérification,
  résultat vide) est un comportement normal d'agent. Six appels ou plus à la
  même action dans une seule trace, c'est l'agent qui n'exploite pas ce qu'il
  reçoit. La boucle de 8 étapes des fixtures D0.1 en a 7, celles du jeu D0.3 24 ;
  l'agent de recherche du jeu (négatif) en a au plus 1.
- MIN_REPEAT_SHARE = 0.5 : les répétitions doivent être majoritaires. Un long
  agent de 40 étapes qui relit 5 fois la même page mais avance par ailleurs
  n'est pas une boucle.

« Sans condition d'arrêt visible » : une trace dont le dernier appel demande
encore un outil n'a jamais rendu de réponse. Ce n'est pas exigé (une boucle qui
finit par répondre a quand même payé ses répétitions) mais c'est ce qui décide
de la gravité : ``cut`` sans réponse finale, ``trim`` sinon.

Angle mort connu : une pagination dont les arguments sont longs et ne diffèrent
que par un numéro peut dépasser le seuil. D'où ``proven = False``.
"""
import hashlib
import json
import re
from collections import defaultdict

from gateway.traces import assign_traces

SIMILARITY = 0.6
MIN_REPEATS = 5
MIN_REPEAT_SHARE = 0.5

_WORDS = re.compile(r"[^\W_]+")


def _words(arguments):
    try:
        value = json.loads(arguments)
        text = " ".join(str(v) for v in value.values()) if isinstance(value, dict) else str(value)
    except (TypeError, ValueError):
        text = str(arguments or "")
    return {w[:-1] if len(w) > 3 and w.endswith("s") else w for w in _WORDS.findall(text.lower())}


def _similar(a, b):
    if not a and not b:
        return True
    return len(a & b) / len(a | b) >= SIMILARITY


def traces(events):
    """(app, modèle, trace) -> événements triés par étape, erreurs exclues."""
    groups = defaultdict(list)
    for e in assign_traces(events):
        if e.get("error") is None and e["trace"]["id"] is not None:
            groups[e["trace"]["id"]].append(e)
    out = {}
    for trace_id, evts in groups.items():
        evts.sort(key=lambda e: (e["trace"]["step"], e["ts_start"]))
        out[(evts[0]["app_id"], evts[0]["model"], trace_id)] = evts
    return out


def analyse(evts):
    """Actions demandées, répétitions, et présence d'une réponse finale."""
    seen = defaultdict(list)
    actions = repeats = 0
    for e in evts:
        for call in e["response"]["tool_calls"]:
            words = _words(call["arguments"])
            actions += 1
            if any(_similar(words, w) for w in seen[call["name"]]):
                repeats += 1
            seen[call["name"]].append(words)
    final = not evts[-1]["response"]["tool_calls"] and evts[-1]["response"].get("content") is not None
    return actions, repeats, final


def _detect_traces(events):
    found = []
    for (app, model, trace_id), evts in sorted(traces(events).items()):
        actions, repeats, final = analyse(evts)
        if repeats < MIN_REPEATS or repeats / actions < MIN_REPEAT_SHARE:
            continue
        tools = sorted({c["name"] for e in evts for c in e["response"]["tool_calls"]})
        found.append({"app_id": app, "model": model, "event_ids": [e["event_id"] for e in evts],
                      "evidence": {"trace_id": trace_id, "steps": len(evts), "tool_calls": actions,
                                   "repeated_calls": repeats, "repeat_share": round(repeats / actions, 3),
                                   "final_answer": final, "tools": tools}})
    return found


def detect(events):
    """Un finding par (app, modèle), qui regroupe les traces en boucle."""
    groups = defaultdict(list)
    for f in _detect_traces(events):
        groups[(f["app_id"], f["model"])].append(f)
    findings = []
    for (app, model), fs in sorted(groups.items()):
        ev = [f["evidence"] for f in fs]
        unfinished = sum(not x["final_answer"] for x in ev)
        steps = round(sum(x["steps"] for x in ev) / len(ev))
        digest = hashlib.sha256(json.dumps([app, model]).encode()).hexdigest()[:20]
        findings.append({
            "finding_id": f"f_{digest}_unbounded_loop", "rule": "unbounded_loop", "app_id": app,
            "model": model, "template": None, "severity": "cut" if unfinished else "trim",
            "title": (f"{len(fs)} exécution(s) d'environ {steps} étapes où l'agent relance la même "
                      f"action avec des arguments quasi identiques"
                      + (f" ; {unfinished} n'ont jamais rendu de réponse." if unfinished else ".")),
            "proven": False,
            "event_ids": [i for f in fs for i in f["event_ids"]],
            "evidence": {"traces": len(fs), "unfinished_traces": unfinished,
                         "thresholds": {"similarity": SIMILARITY, "min_repeats": MIN_REPEATS,
                                        "min_repeat_share": MIN_REPEAT_SHARE},
                         "per_trace": ev},
        })
    return findings
