"""R5 — unbounded_loop (D2.4) : un agent qui refait la même action sans avancer.

Par trace (D1.4), on regarde les appels d'outils que le modèle a demandés, dans
l'ordre des étapes. Une action est une *répétition* si le même outil a déjà été
appelé dans cette trace avec des arguments quasi identiques. Une trace est une
boucle quand les répétitions sont à la fois nombreuses et majoritaires.

Comparaison des arguments, argument par argument :

- Deux appels du même outil se ressemblent si CHAQUE argument se ressemble :
  mêmes clés, et pour chaque clé des mots proches (Jaccard >= SIMILARITY,
  pluriel en -s retiré, chiffres gardés). Comparer clé par clé, et non tous
  les mots mélangés, évite qu'une longue partie commune (une URL) masque ce
  qui change : ``{url: <longue>, page: 3}`` et ``{url: <longue>, page: 4}``
  diffèrent sur ``page``, la pagination avance.
- Les identifiants techniques sont ignorés : ils changent à chaque appel sans
  rien dire de ce que l'agent demande. Une clé est ignorée si elle porte un nom
  de transport (request_id, nonce, idempotency_key, timestamp…) ou si toutes ses
  valeurs ressemblent à des jetons aléatoires (UUID, hexadécimal long, horodatage).
  Les identifiants métier sont gardés : ``order_id: "ORD-2026-000123"`` puis
  ``"ORD-2026-000124"``, c'est un agent qui traite deux commandes, pas une boucle.

Seuils et raisonnement :

- SIMILARITY = 0.6 : « tarif entreprise » / « tarifs entreprise 2026 » = 0,67,
  même recherche reformulée ; « prix pétrole » / « production opep » = 0.
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

Cas assumé : un agent qui interroge 8 fois l'état d'un même job en attendant
qu'il finisse est signalé. Il paie un appel de modèle par interrogation pour
une attente qu'un simple minuteur ferait. Angle mort : un identifiant métier
qui a l'air aléatoire (hexadécimal long) est ignoré à tort. D'où ``proven = False``.
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
# Identifiants de transport : changent à chaque appel, ne disent rien de la demande.
NOISE_KEYS = re.compile(r"(^|[._])(request_?id|requestid|idempotency_?key|nonce|trace_?id|"
                        r"correlation_?id|timestamp|ts|cache_?buster)$", re.I)
_RANDOM = re.compile(
    r"^(?:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"  # UUID
    r"|[0-9a-f]{16,}"                                                     # hexadécimal long
    r"|\d{10,13}"                                                         # horodatage epoch
    r"|\d{4}-\d{2}-\d{2}[t ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(z|[+-]\d{2}:?\d{2})?)$", re.I)  # ISO 8601


def _flat(arguments):
    """Arguments -> {chemin de clé: valeur texte}. Non-JSON : une seule clé."""
    try:
        value = json.loads(arguments)
    except (TypeError, ValueError):
        return {"": str(arguments or "")}
    out = {}

    def walk(v, path):
        if isinstance(v, dict):
            for k, x in v.items():
                walk(x, f"{path}.{k}" if path else str(k))
        elif isinstance(v, list) and any(isinstance(x, (dict, list)) for x in v):
            for i, x in enumerate(v):
                walk(x, f"{path}[{i}]")
        else:
            out[path] = " ".join(map(str, v)) if isinstance(v, list) else str(v)
    walk(value, "")
    return out


def _words(text):
    return frozenset(w[:-1] if len(w) > 3 and w.endswith("s") else w for w in _WORDS.findall(text.lower()))


def _noise_keys(calls):
    """Clés à ignorer pour un outil dans une trace : nom de transport, ou valeurs toutes aléatoires."""
    keys = {k for c in calls for k in c}
    return {k for k in keys
            if NOISE_KEYS.search(k)
            or all(k in c and _RANDOM.match(c[k].strip()) for c in calls)}


def _similar(a, b):
    """a, b : {clé: mots}. Mêmes clés, et chaque valeur proche."""
    if a.keys() != b.keys():
        return False
    for k in a:
        x, y = a[k], b[k]
        if (x or y) and (not x or not y or len(x & y) / len(x | y) < SIMILARITY):
            return False
    return True


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
    by_tool = defaultdict(list)
    order = []
    for e in evts:
        for call in e["response"]["tool_calls"]:
            flat = _flat(call["arguments"])
            by_tool[call["name"]].append(flat)
            order.append((call["name"], flat))
    noise = {tool: _noise_keys(calls) for tool, calls in by_tool.items()}

    seen = defaultdict(list)
    repeats = 0
    for tool, flat in order:
        sig = {k: _words(v) for k, v in flat.items() if k not in noise[tool]}
        if any(_similar(sig, prev) for prev in seen[tool]):
            repeats += 1
        seen[tool].append(sig)
    final = not evts[-1]["response"]["tool_calls"] and evts[-1]["response"].get("content") is not None
    return len(order), repeats, final


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
