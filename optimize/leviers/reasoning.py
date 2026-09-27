"""R7/levier 03 : baisser l'effort de raisonnement d'un modèle qui réfléchit longtemps pour une
réponse triviale, prouvé au banc (même modèle, effort réduit, rejoué sur les mêmes entrées et
comparé à la réponse d'origine — bench.reasoning.prove, clé OpenAI nécessaire). Sans clé, non
testé, comme optimize.propose._model : jamais de score inventé."""
from optimize.propose import MESURE, NON_TESTE, _cost, _m, _p95, _pct_change
from proof.replay import THRESHOLD


def reasoning_proposal(finding, events, keys_available, prove_reasoning=None):
    if prove_reasoning is None:
        from bench.reasoning import prove as prove_reasoning
    if not keys_available:
        return {
            "type": "raisonnement", "finding_id": finding["finding_id"], "app_id": finding["app_id"],
            "model": finding["model"],
            "changement": f"Baisser l'effort de raisonnement de {finding['model']}.",
            "verdict": "non_teste", "raisons": ["aucune clé pour le banc : rien de mesuré"],
            "mesures": {"precision": _m(None, NON_TESTE, "%")},
        }
    result = prove_reasoning(events, finding)
    score = result.get("score")
    bench_passed = result["verdict"] == "pass"
    # bench.scoring.threshold_for descend a 0.5 en texte libre (F1 de recouvrement, indicatif) :
    # trop permissif pour un "pass" ici. proof.replay.THRESHOLD (0.95, meme seuil que le rejeu des
    # regles) est le plancher du projet, reutilise ici, applique en plus du seuil interne du banc,
    # jamais a sa place.
    passed = bench_passed and score is not None and score >= THRESHOLD
    reasons = list(result.get("reasons") or [])
    if bench_passed and not passed:
        reasons.append(f"score {score:.2f} sous le seuil du projet ({THRESHOLD:.0%})")
    verdict = "pass" if passed else ("non_teste" if result["verdict"] == "not_tested" else "reject")
    group = [e for e in events if e["event_id"] in set(finding["event_ids"])]
    before_p95 = _p95([e["latency_ms"] for e in group])
    spent, ref, measured = _cost(group), result.get("reference_cost_per_1000_calls_usd"), result.get("cost_per_1000_calls_usd")
    return {
        "type": "raisonnement", "finding_id": finding["finding_id"], "app_id": finding["app_id"],
        "model": finding["model"],
        "changement": (f"Baisser l'effort de raisonnement de {finding['model']} à « {result['effort']} »." if passed
                       else f"Aucun effort de raisonnement réduit ne tient le seuil pour {finding['model']}."),
        "verdict": verdict, "raisons": reasons, "preuve": result,
        "mesures": {
            "precision": _m(round(score * 100, 1), MESURE, "%") if score is not None else _m(None, NON_TESTE, "%"),
            "appels_rejoues": (_m(result["n_calls"], MESURE) if result.get("n_calls")
                              else _m(None, NON_TESTE)),
            "latence_p95": (_m(_pct_change(before_p95, result.get("latency_p95_ms")), MESURE, "%") if passed
                           else _m(None, NON_TESTE, "%")),
            "cout": (_m(_pct_change(ref, measured), MESURE, "%") if passed and ref and measured
                    else _m(None, NON_TESTE, "%")),
        },
        "cout_usd": ({"avant": spent, "apres": spent * measured / ref, "statut": MESURE}
                    if passed and ref and measured and spent is not None else None),
    }
