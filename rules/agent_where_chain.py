"""R6 — agent_where_chain (D2.4) : un agent qui prend toujours le même chemin.

Un agent est payé pour choisir ses outils. Si, exécution après exécution, il
appelle exactement les mêmes outils dans le même ordre, ce choix n'est jamais
exercé : une chaîne d'étapes fixe (code, workflow) ferait le même travail sans
les appels de modèle qui décident de l'étape suivante.

Par application et modèle, on prend les traces TERMINÉES (dernier appel = une
réponse, pas un nouvel appel d'outil) et on compare leur séquence de noms
d'outils. Les arguments sont ignorés : ils changent à chaque exécution (numéro
de commande) sans que le chemin change. Des appels parallèles dans une même
étape sont triés, leur ordre n'a pas de sens.

Seuils et raisonnement :

- MIN_TRACES = 10 : il faut assez d'exécutions pour distinguer une habitude
  d'une coïncidence. Si l'agent choisissait vraiment entre deux ordres
  seulement, à pile ou face, la probabilité qu'au moins 9 traces sur 10 suivent
  le même chemin est d'environ 2 %. Avec 3 traces, elle serait de 25 % : les
  3 traces des fixtures D0.1 ne suffisent pas, volontairement.
- MIN_DOMINANT_SHARE = 0.9 : une exécution sur dix peut dévier (erreur d'outil,
  cas limite) sans que la conclusion change ; au-delà, l'agent sert.
- MIN_TOOL_CALLS = 2 : un seul appel d'outil puis une réponse est le schéma
  normal d'une recherche documentaire ; ce n'est pas un agent à remplacer.

Les traces jamais terminées (souvent des boucles, voir unbounded_loop) sont
exclues : leur chemin n'est pas complet.
"""
import hashlib
import json
from collections import Counter, defaultdict

from rules.unbounded_loop import traces

MIN_TRACES = 10
MIN_DOMINANT_SHARE = 0.9
MIN_TOOL_CALLS = 2


def path(evts):
    """Séquence des outils appelés, ou None si la trace n'est pas terminée."""
    last = evts[-1]["response"]
    if last["tool_calls"] or last.get("content") is None:
        return None
    return tuple(name for e in evts for name in sorted(c["name"] for c in e["response"]["tool_calls"]))


def detect(events):
    groups = defaultdict(list)
    for (app, model, _), evts in traces(events).items():
        p = path(evts)
        if p is not None and len(p) >= MIN_TOOL_CALLS:
            groups[(app, model)].append((p, evts))

    findings = []
    for (app, model), runs in sorted(groups.items()):
        if len(runs) < MIN_TRACES:
            continue
        counts = Counter(p for p, _ in runs)
        dominant, n = counts.most_common(1)[0]
        share = n / len(runs)
        if share < MIN_DOMINANT_SHARE:
            continue
        declared = sorted({t["name"] for _, evts in runs for e in evts for t in e["request"]["tools"]})
        digest = hashlib.sha256(json.dumps([app, model]).encode()).hexdigest()[:20]
        findings.append({
            "finding_id": f"f_{digest}_agent_where_chain", "rule": "agent_where_chain", "app_id": app,
            "model": model, "template": None, "severity": "trim",
            "title": (f"Sur {len(runs)} exécutions, l'agent suit {n} fois exactement le même chemin : "
                      f"{' → '.join(dominant)}, puis une réponse."),
            "proven": False,
            "event_ids": [e["event_id"] for p, evts in runs if p == dominant for e in evts],
            "evidence": {"traces": len(runs), "dominant_path": list(dominant),
                         "dominant_share": round(share, 3), "distinct_paths": len(counts),
                         "model_calls_per_trace": round(sum(len(evts) for _, evts in runs) / len(runs), 1),
                         "tools_declared": declared,
                         "thresholds": {"min_traces": MIN_TRACES, "min_dominant_share": MIN_DOMINANT_SHARE,
                                        "min_tool_calls": MIN_TOOL_CALLS}},
        })
    return findings
