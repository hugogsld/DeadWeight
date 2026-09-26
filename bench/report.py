"""Agregation : classement des candidats et estimation --dry-run avant depense."""
from bench.pricing import cost_per_1000_calls


def rank(results):
    """pass d'abord (meilleur score, puis moins cher), puis reject, puis not_tested."""
    order = {'pass': 0, 'reject': 1, 'not_tested': 2}

    def key(result):
        cost = result.cost_per_1000_calls_usd
        return (order[result.verdict], -(result.score or 0.0), cost if cost is not None else float('inf'))

    return sorted(results, key=key)


def to_dict(result):
    candidate = result.candidate
    return {
        'candidate_id': candidate.id, 'kind': candidate.kind, 'model': candidate.model,
        'size_class': candidate.size_class, 'origin': candidate.origin,
        'n_cases': result.n_cases, 'n_calls': result.n_calls, 'n_errors': result.n_errors,
        'score': result.score, 'latency_p50_ms': result.latency_p50_ms,
        'latency_p95_ms': result.latency_p95_ms,
        'cost_per_1000_calls_usd': result.cost_per_1000_calls_usd,
        'verdict': result.verdict, 'reasons': list(result.reasons),
    }


def dry_run_estimate(candidate, cases, prices=None):
    """Ce qui serait appele et son cout estime, sans emettre un seul appel.

    Estimation batie sur les jetons de l'appel d'origine (proxy le plus proche
    avant d'avoir des mesures reelles du candidat) ; cout nul et certain pour
    l'execution locale (Ollama).
    """
    n = len(cases)
    if candidate.kind == 'ollama':
        return {'candidate_id': candidate.id, 'model': candidate.model, 'n_calls_planned': n,
                'estimated_cost_usd': 0.0, 'note': 'execution locale : cout nul'}
    tin = [c.origin_input_tokens for c in cases if c.origin_input_tokens is not None]
    tout = [c.origin_output_tokens for c in cases if c.origin_output_tokens is not None]
    avg_in = sum(tin) / len(tin) if tin else None
    avg_out = sum(tout) / len(tout) if tout else None
    per_1000 = cost_per_1000_calls(candidate.model, avg_in, avg_out, prices)
    estimated = round(per_1000 * n / 1000, 4) if per_1000 is not None else None
    note = None if estimated is not None else 'cout non estimable (jetons ou tarif inconnus)'
    return {'candidate_id': candidate.id, 'model': candidate.model, 'n_calls_planned': n,
            'estimated_cost_usd': estimated, 'note': note}
