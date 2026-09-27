"""R7/levier 03 — banc de l'effort de raisonnement : le même modèle que le constat
excess_reasoning, appelé à nouveau sur les mêmes entrées réelles avec un effort de
raisonnement réduit (``reasoning_effort``), comparé à la réponse d'origine.

Seul OpenAI expose ce paramètre pour les modèles à raisonnement (o1/o3/gpt-5...) : la
portée est la même que rules.excess_reasoning, volontairement limitée au format openai.
Sans OPENAI_API_KEY, aucun appel n'est émis : verdict ``not_tested``, jamais un rejet de
qualité (même principe que bench.runner face à une clé absente).

    python -m bench reasoning events.jsonl --finding <finding_id>
"""
import os
from statistics import mean

from bench.client import CandidateLLM
from bench.pricing import cost_per_1000_calls, load_prices
from bench.runner import Throttle, _percentile
from bench.scoring import detect_task_type, score_case, threshold_for
from bench.testset import DEFAULT_MAX_CASES, build_test_cases

DEFAULT_EFFORT = "low"
DEFAULT_MAX_CALLS = 30
DEFAULT_BASE_URL = "https://api.openai.com/v1"


def prove(events, finding, effort=DEFAULT_EFFORT, max_cases=DEFAULT_MAX_CASES,
          max_calls=DEFAULT_MAX_CALLS, min_interval=0.0, prices=None, client_cls=CandidateLLM):
    """Rend {n_cases, task_type, threshold, effort, n_calls, n_errors, score,
    latency_p95_ms, cost_per_1000_calls_usd, reference_cost_per_1000_calls_usd,
    verdict, reasons}. N'échoue jamais par exception : une panne devient un score de 0
    sur le cas concerné, jamais une exception qui interromprait le banc."""
    prices = prices if prices is not None else load_prices()
    cases = build_test_cases(events, finding["app_id"], finding["model"], finding.get("template"), max_cases)
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key or not cases:
        return {
            "n_cases": len(cases), "task_type": None, "threshold": None, "effort": effort,
            "n_calls": 0, "n_errors": 0, "score": None, "latency_p95_ms": None,
            "cost_per_1000_calls_usd": None, "reference_cost_per_1000_calls_usd": None,
            "verdict": "not_tested",
            "reasons": ["clé OPENAI_API_KEY absente : rien de mesuré" if not api_key
                        else "aucun cas de test pour ce groupe"],
        }

    task_type = detect_task_type(cases)
    threshold = threshold_for(task_type)
    client = client_cls(os.environ.get("OPENAI_BASE_URL") or DEFAULT_BASE_URL, api_key, finding["model"],
                        extra={"reasoning_effort": effort})
    throttle = Throttle(max_calls, min_interval)

    scores, latencies, calls_usage = [], [], []
    n_calls = errors = 0
    for case in cases:
        if not throttle.acquire():
            break
        n_calls += 1
        result = client.complete(case.messages)
        latencies.append(result.latency_ms)
        calls_usage.append((result.input_tokens, result.output_tokens))
        if result.error is not None:
            errors += 1
            scores.append(0.0)
            continue
        scores.append(score_case(task_type, result.content, case.reference))

    score = round(sum(scores) / len(scores), 4) if scores else None
    tin = [t for t, _ in calls_usage if t is not None]
    tout = [o for _, o in calls_usage if o is not None]
    new_cost = cost_per_1000_calls(finding["model"], mean(tin), mean(tout), prices) if tin and tout else None
    ref_in = [c.origin_input_tokens for c in cases if c.origin_input_tokens is not None]
    ref_out = [c.origin_output_tokens for c in cases if c.origin_output_tokens is not None]
    ref_cost = (cost_per_1000_calls(finding["model"], mean(ref_in), mean(ref_out), prices)
                if ref_in and ref_out else None)

    reasons = []
    if score is not None and score < threshold:
        reasons.append(f"score {score:.2f} sous le seuil {threshold:.2f}")
    if errors:
        reasons.append(f"{errors}/{n_calls} appel(s) en erreur")
    verdict = "not_tested" if score is None else ("pass" if not reasons else "reject")

    return {
        "n_cases": len(cases), "task_type": task_type, "threshold": threshold, "effort": effort,
        "n_calls": n_calls, "n_errors": errors, "score": score,
        "latency_p95_ms": _percentile(latencies, .95),
        "cost_per_1000_calls_usd": new_cost, "reference_cost_per_1000_calls_usd": ref_cost,
        "verdict": verdict, "reasons": reasons,
    }
