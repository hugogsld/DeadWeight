"""Client, execution et classement du banc de modeles : contre de vrais serveurs
HTTP locaux (jamais le reseau), un qui est d'accord, un qui est en desaccord,
un qui erreure a chaque appel."""
import json
from pathlib import Path

import pytest

from bench.client import CandidateLLM
from bench.models import BenchCase, Candidate
from bench.report import dry_run_estimate, rank, to_dict
from bench.runner import HARD_MAX_CALLS, Throttle, run_candidate
from tests.bench_servers import FakeCandidateServer

ROOT = Path(__file__).resolve().parents[1]


def _candidate(server, kind='openai', model='gpt-5-nano', size_class='small', origin='US'):
    return Candidate(id=f'test-{kind}', kind=kind, model=model, base_url_env='DW_BENCH_TEST_UNSET',
                     default_base_url=server.base_url, api_key_env=None,
                     size_class=size_class, origin=origin, note='fixture de test')


def _cases(n=5, reference='spam'):
    return [BenchCase(event_id=f'e{i}', messages=({'role': 'user', 'content': reference},),
                     reference=reference, origin_input_tokens=60, origin_output_tokens=2)
            for i in range(n)]


@pytest.fixture
def echo_server():
    server = FakeCandidateServer(behavior='echo')
    yield server
    server.stop()


@pytest.fixture
def fixed_server():
    server = FakeCandidateServer(behavior='fixed', fixed_answer='AUTRE_REPONSE')
    yield server
    server.stop()


@pytest.fixture
def error_server():
    server = FakeCandidateServer(behavior='error')
    yield server
    server.stop()


# --- client --------------------------------------------------------------------

def test_client_never_leaks_key_on_transport_error():
    client = CandidateLLM('http://127.0.0.1:1', 'sk-secret-do-not-leak', 'gpt-5-nano', timeout_s=1)
    result = client.complete([{'role': 'user', 'content': 'hello'}])
    assert result.content is None and result.error is not None
    assert 'sk-secret-do-not-leak' not in json.dumps(result)


def test_client_reports_http_error(error_server):
    client = CandidateLLM(error_server.base_url, None, 'x')
    result = client.complete([{'role': 'user', 'content': 'hello'}])
    assert result.content is None and result.error == 'http_500'


def test_client_returns_content_latency_and_usage(echo_server):
    client = CandidateLLM(echo_server.base_url, None, 'x')
    result = client.complete([{'role': 'user', 'content': 'spam'}])
    assert result.content == 'spam' and result.error is None
    assert result.latency_ms >= 0 and result.input_tokens == 10 and result.output_tokens == 3


# --- run_candidate : accord ------------------------------------------------------

def test_agreeing_candidate_passes_classification(echo_server):
    candidate = _candidate(echo_server)
    result = run_candidate(candidate, _cases(40), 'classification')
    assert result.verdict == 'pass' and result.score == 1.0 and result.n_errors == 0
    assert result.cost_per_1000_calls_usd is not None  # gpt-5-nano est au catalogue


def test_disagreeing_candidate_is_rejected(fixed_server):
    candidate = _candidate(fixed_server)
    result = run_candidate(candidate, _cases(40), 'classification')
    assert result.verdict == 'reject' and result.score == 0.0
    assert any('sous le seuil' in r for r in result.reasons)


def test_erroring_candidate_is_rejected_with_error_rate(error_server):
    candidate = _candidate(error_server)
    result = run_candidate(candidate, _cases(30), 'classification')
    assert result.verdict == 'reject' and result.n_errors == 30
    assert any('erreur' in r for r in result.reasons)


def test_ollama_candidate_cost_is_always_zero(echo_server):
    candidate = _candidate(echo_server, kind='ollama', model='llama3.3:70b', size_class='local')
    result = run_candidate(candidate, _cases(10), 'classification')
    assert result.cost_per_1000_calls_usd == 0.0


def test_throttle_caps_calls_before_first_request(echo_server):
    candidate = _candidate(echo_server)
    throttle = Throttle(max_calls=3, min_interval_s=0)
    result = run_candidate(candidate, _cases(20), 'classification', throttle)
    assert result.n_calls == 3
    assert Throttle(max_calls=10 ** 6).max_calls == HARD_MAX_CALLS


def test_no_cases_is_not_tested_never_a_crash(echo_server):
    candidate = _candidate(echo_server)
    result = run_candidate(candidate, [], 'classification')
    assert result.verdict == 'not_tested' and result.score is None


# --- classement et dry-run --------------------------------------------------------

def test_rank_orders_pass_before_reject_before_not_tested(echo_server, fixed_server):
    good = run_candidate(_candidate(echo_server), _cases(40), 'classification')
    bad = run_candidate(_candidate(fixed_server), _cases(40), 'classification')
    empty = run_candidate(_candidate(echo_server, kind='ollama'), [], 'classification')
    ranked = rank([bad, empty, good])
    assert [r.verdict for r in ranked] == ['pass', 'reject', 'not_tested']
    assert to_dict(good)['verdict'] == 'pass'


def test_dry_run_estimate_is_zero_for_ollama_without_calling_anything(error_server):
    candidate = _candidate(error_server, kind='ollama', size_class='local')
    estimate = dry_run_estimate(candidate, _cases(50))
    assert estimate['estimated_cost_usd'] == 0.0 and estimate['n_calls_planned'] == 50


def test_dry_run_estimate_uses_origin_tokens_for_hosted_candidates(error_server):
    candidate = _candidate(error_server, model='gpt-5-nano')
    estimate = dry_run_estimate(candidate, _cases(1000))
    assert estimate['estimated_cost_usd'] > 0
    assert estimate['n_calls_planned'] == 1000


def test_models_refusing_temperature_are_retried_without_it(monkeypatch):
    """gpt-5 et o-series refusent temperature=0 (400) : une relance sans le paramètre."""
    from bench import client as client_mod
    sent = []

    def fake_call(self, body):
        sent.append(dict(body))
        if 'temperature' in body:
            return client_mod.CallResult(None, 1.0, None, None, 'http_400')
        return client_mod.CallResult('spam', 1.0, 10, 1, None)

    monkeypatch.setattr(client_mod.CandidateLLM, '_call', fake_call)
    llm = client_mod.CandidateLLM.__new__(client_mod.CandidateLLM)
    llm.model = 'gpt-5-nano'
    result = llm.complete([{'role': 'user', 'content': 'x'}])
    assert result.content == 'spam' and result.error is None
    assert 'temperature' in sent[0] and 'temperature' not in sent[1]
