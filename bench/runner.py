"""Execution du banc : appelle chaque candidat sur le jeu de test, mesure latence
et taux d'erreur, plafonne les appels. Meme esprit que proof.replay.Throttle :
plafond dur non contournable, et un intervalle minimal entre deux appels.
"""
import math
import time

from bench.catalog import resolve_api_key, resolve_base_url
from bench.client import CandidateLLM
from bench.models import CandidateResult
from bench.pricing import cost_per_1000_calls
from bench.scoring import score_case, threshold_for

HARD_MAX_CALLS = 200
DEFAULT_MAX_CALLS = 50
DEFAULT_MIN_INTERVAL_S = 0.0
AUTH_ERROR_CODES = {'http_401', 'http_403'}  # problème 17 : pas mesuré, pas un rejet de qualité
MISSING_KEY_REASON = "non testé (clé absente) : authentification refusée par le fournisseur"


class Throttle:
    def __init__(self, max_calls=DEFAULT_MAX_CALLS, min_interval_s=DEFAULT_MIN_INTERVAL_S,
                 clock=time.monotonic, sleep=time.sleep):
        self.max_calls = max(0, min(int(max_calls), HARD_MAX_CALLS))
        self.min_interval_s = max(0.0, float(min_interval_s))
        self.clock, self.sleep = clock, sleep
        self.calls, self._last = 0, None

    def acquire(self):
        if self.calls >= self.max_calls:
            return False
        if self._last is not None:
            wait = self._last + self.min_interval_s - self.clock()
            if wait > 0:
                self.sleep(wait)
        self._last = self.clock()
        self.calls += 1
        return True


def _percentile(values, q):
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[math.ceil(q * len(ordered)) - 1], 2)


def _cost(candidate, calls_usage, prices):
    if candidate.kind == 'ollama':
        return 0.0
    tin = [t for t, _ in calls_usage if t is not None]
    tout = [t for _, t in calls_usage if t is not None]
    avg_in = sum(tin) / len(tin) if tin else None
    avg_out = sum(tout) / len(tout) if tout else None
    return cost_per_1000_calls(candidate.model, avg_in, avg_out, prices)


def run_candidate(candidate, cases, task_type, throttle=None, prices=None, client_cls=CandidateLLM):
    """N'echoue jamais par exception : un candidat en panne devient un verdict reject, sauf si
    tous ses appels ont echoue en authentification (cle absente ou refusee) : ce n'est alors pas
    mesure, donc pas un rejet de qualite (probleme 17)."""
    throttle = throttle or Throttle()
    extra = {k: v for k, v in (('route', candidate.route), ('max_tokens', candidate.max_tokens)) if v}
    client = client_cls(resolve_base_url(candidate), resolve_api_key(candidate), candidate.model, **extra)

    scores, latencies, calls_usage, error_codes = [], [], [], []
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
            error_codes.append(result.error)
            scores.append(0.0)
            continue
        scores.append(score_case(task_type, result.content, case.reference))

    if n_calls and errors == n_calls and all(code in AUTH_ERROR_CODES for code in error_codes):
        return CandidateResult(
            candidate=candidate, n_cases=len(cases), n_calls=n_calls, n_errors=errors, score=None,
            latency_p50_ms=_percentile(latencies, .5), latency_p95_ms=_percentile(latencies, .95),
            cost_per_1000_calls_usd=None, verdict='not_tested', reasons=(MISSING_KEY_REASON,),
        )

    threshold = threshold_for(task_type)
    score = round(sum(scores) / len(scores), 4) if scores else None
    error_rate = errors / n_calls if n_calls else None

    reasons = []
    if not cases:
        reasons.append("aucun cas de test pour ce groupe")
    elif n_calls == 0:
        reasons.append("plafond d'appels atteint avant le premier appel")
    if score is not None and score < threshold:
        reasons.append(f'score {score:.2f} sous le seuil {threshold:.2f}')
    if error_rate:
        reasons.append(f'{errors}/{n_calls} appel(s) en erreur')

    verdict = 'not_tested' if score is None else ('pass' if not reasons else 'reject')
    return CandidateResult(
        candidate=candidate, n_cases=len(cases), n_calls=n_calls, n_errors=errors,
        score=score, latency_p50_ms=_percentile(latencies, .5),
        latency_p95_ms=_percentile(latencies, .95),
        cost_per_1000_calls_usd=_cost(candidate, calls_usage, prices),
        verdict=verdict, reasons=tuple(reasons),
    )
