"""Jeu de test, scoring et catalogue du banc de modeles (M2.2) : aucun appel reseau."""
import json
from pathlib import Path

import pytest

from bench.catalog import load_candidates, resolve_api_key, resolve_base_url
from bench.pricing import cost_per_1000_calls, load_prices
from bench.scoring import detect_task_type, score_case, threshold_for, token_overlap_f1
from bench.testset import build_test_cases

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / 'fixtures/dataset/v1/events.jsonl'


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Unexpected network request')
    monkeypatch.setattr('urllib.request.urlopen', forbidden)


@pytest.fixture(scope='module')
def dataset():
    return [json.loads(line) for line in DATASET.read_text().splitlines()]


def _event(event_id, content, app_id='mail-triage', model='gpt-4o', text='gagnez un iphone',
          error=None, in_tokens=60, out_tokens=2):
    return {
        'event_id': event_id, 'app_id': app_id, 'model': model, 'error': error,
        'usage': {'input_tokens': in_tokens, 'output_tokens': out_tokens},
        'request': {'system': 'Classe ce mail.', 'messages': [{'role': 'user', 'content': text}]},
        'response': {'content': content},
    }


# --- testset -----------------------------------------------------------------

def test_build_test_cases_excludes_errors_and_other_groups():
    events = [
        _event('e0', 'spam'),
        _event('e1', 'spam', app_id='autre-app'),
        _event('e2', 'spam', model='gpt-4o-mini'),
        _event('e3', 'spam', error={'type': 'x', 'message': 'boom'}),
        _event('e4', None),
        _event('e5', 'facture'),
    ]
    cases = build_test_cases(events, 'mail-triage', 'gpt-4o')
    assert {c.event_id for c in cases} == {'e0', 'e5'}
    assert all(c.reference in ('spam', 'facture') for c in cases)


def test_build_test_cases_caps_at_max_cases():
    events = [_event(f'e{i}', 'spam') for i in range(120)]
    cases = build_test_cases(events, 'mail-triage', 'gpt-4o', max_cases=10)
    assert len(cases) == 10


def test_build_test_cases_is_deterministic_across_calls():
    events = [_event(f'e{i}', 'spam') for i in range(80)]
    first = [c.event_id for c in build_test_cases(events, 'mail-triage', 'gpt-4o', max_cases=20)]
    second = [c.event_id for c in build_test_cases(events, 'mail-triage', 'gpt-4o', max_cases=20)]
    assert first == second
    assert first != sorted(first)  # tirage par hachage, pas l'ordre chronologique


def test_build_test_cases_carries_origin_usage_for_dry_run_estimate():
    events = [_event('e0', 'spam', in_tokens=123, out_tokens=4)]
    cases = build_test_cases(events, 'mail-triage', 'gpt-4o')
    assert cases[0].origin_input_tokens == 123 and cases[0].origin_output_tokens == 4


def test_real_dataset_mail_triage_builds_cases(dataset):
    cases = build_test_cases(dataset, 'mail-triage', 'gpt-4o', max_cases=50)
    assert 30 <= len(cases) <= 50
    assert all(c.reference for c in cases)


# --- scoring -------------------------------------------------------------------

def test_detect_task_type_classification_on_few_distinct_outputs():
    events = [_event(f'e{i}', 'spam' if i % 2 else 'facture') for i in range(10)]
    cases = build_test_cases(events, 'mail-triage', 'gpt-4o')
    assert detect_task_type(cases) == 'classification'


def test_detect_task_type_text_on_many_distinct_outputs():
    events = [_event(f'e{i}', f'reponse unique numero {i}') for i in range(20)]
    cases = build_test_cases(events, 'mail-triage', 'gpt-4o')
    assert detect_task_type(cases) == 'text'


def test_score_case_classification_ignores_case_and_punctuation():
    assert score_case('classification', 'SPAM !', 'spam') == 1.0
    assert score_case('classification', 'facture', 'spam') == 0.0
    assert score_case('classification', None, 'spam') == 0.0


def test_score_case_text_uses_token_overlap_f1():
    reference = 'le vol est confirme pour demain matin'
    assert score_case('text', reference, reference) == 1.0
    assert score_case('text', 'un texte completement different ici', reference) < 0.3
    assert token_overlap_f1('', 'quelque chose') == 0.0


def test_threshold_for_matches_task_type():
    assert threshold_for('classification') == 0.95
    assert threshold_for('text') == 0.5


# --- catalogue et prix -----------------------------------------------------------

def test_load_candidates_returns_curated_list_with_required_fields():
    candidates = load_candidates()
    assert 5 <= len(candidates) <= 20
    for c in candidates:
        assert c.kind in ('openai', 'openrouter', 'mistral', 'ollama')
        assert c.size_class in ('local', 'small', 'medium')
        assert c.origin in ('FR', 'EU', 'US', 'CN')
        assert c.note


def test_load_candidates_filters_by_size_class():
    local_only = load_candidates(size_classes=['local'])
    assert local_only and all(c.size_class == 'local' for c in local_only)


def test_ollama_candidate_has_no_api_key_env():
    ollama = [c for c in load_candidates(kinds=['ollama'])]
    assert ollama
    assert all(c.api_key_env is None for c in ollama)
    assert resolve_api_key(ollama[0]) is None


def test_resolve_base_url_prefers_env_over_default(monkeypatch):
    candidate = load_candidates(kinds=['ollama'])[0]
    monkeypatch.setenv(candidate.base_url_env, 'http://example.invalid/v1')
    assert resolve_base_url(candidate) == 'http://example.invalid/v1'
    monkeypatch.delenv(candidate.base_url_env)
    assert resolve_base_url(candidate) == candidate.default_base_url


def test_cost_per_1000_calls_uses_pricing_catalogue():
    prices = load_prices()
    cost = cost_per_1000_calls('gpt-5-nano', 1_000_000, 1_000_000, prices)
    assert cost == pytest.approx((0.05 + 0.40) * 1000, rel=1e-3)


def test_cost_per_1000_calls_is_none_when_unknown():
    assert cost_per_1000_calls('modele-inconnu-xyz', 100, 100) is None
    assert cost_per_1000_calls('gpt-5-nano', None, 100) is None
