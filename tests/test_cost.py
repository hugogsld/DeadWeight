"""D2.5: measured usage only; no invented prices or observation window."""
import copy
import json
from pathlib import Path

import pytest

from report.cost import chiffrer

ROOT = Path(__file__).resolve().parents[1]
EVENTS = [json.loads(line) for line in (ROOT / 'fixtures/events.jsonl').read_text().splitlines()]
PRICES = {'gpt-4o': {'in': 2, 'out': 8}}


def event(**changes):
    result = copy.deepcopy(EVENTS[0])
    result.update(ts_start='2026-09-01T00:00:00Z', ts_end='2026-09-02T00:00:00Z',
                  latency_ms=100, usage={'input_tokens': 1000, 'output_tokens': 100, 'cached_input_tokens': 0})
    result.update(changes)
    return result


def test_monthly_projection_and_latency():
    result = chiffrer([event(), event(latency_ms=300)], PRICES)
    assert result == {'cout_mensuel_usd': pytest.approx(0.168), 'latence_mediane_ms': 200,
                      'latence_p95_ms': 300, 'nb_appels': 2, 'nb_erreurs': 0, 'manquants': []}


def test_window_is_chronological_and_includes_overlapping_calls():
    early = event(ts_start='2026-09-01T02:00:00+02:00', ts_end='2026-09-03T00:00:00Z')
    late = event(ts_start='2026-09-02T00:00:00Z')
    assert chiffrer([late, early], PRICES)['cout_mensuel_usd'] == pytest.approx(0.084)


def test_p95_nearest_rank_and_single_call():
    assert chiffrer([event(latency_ms=i) for i in range(1, 21)], PRICES)['latence_p95_ms'] == 19
    assert chiffrer([event()], PRICES)['latence_p95_ms'] == 100


@pytest.mark.parametrize(('model', 'key'), [('gpt-4o', 'openai/gpt-4o'), ('openai/gpt-4o', 'gpt-4o')])
def test_provider_prefix_aliases(model, key):
    assert chiffrer([event(model=model)], {key: PRICES['gpt-4o']})['cout_mensuel_usd'] == pytest.approx(0.084)


def test_exact_prefixed_price_wins():
    prices = dict(PRICES, **{'openai/gpt-4o': {'in': 4, 'out': 16}})
    assert chiffrer([event(model='openai/gpt-4o')], prices)['cout_mensuel_usd'] == pytest.approx(0.168)


@pytest.mark.parametrize('field', ['input_tokens', 'output_tokens', 'cached_input_tokens'])
def test_null_tokens_invalidate_cost_without_hiding_latency(field):
    e = event()
    e['usage'][field] = None
    result = chiffrer([event(), e], PRICES)
    assert result['cout_mensuel_usd'] is None
    assert field in ' '.join(result['manquants'])
    assert result['latence_mediane_ms'] == 100


def test_unknown_model_invalidates_whole_cost():
    result = chiffrer([event(), event(model='unknown')], PRICES)
    assert result['cout_mensuel_usd'] is None
    assert 'unknown' in ' '.join(result['manquants'])


def test_errors_are_counted_separately_and_excluded_from_cost():
    failed = event(error={'type': 'error', 'message': 'failed'}, model='unknown',
                   usage={'input_tokens': None, 'output_tokens': None}, latency_ms=500,
                   ts_end='2026-09-03T00:00:00Z')
    result = chiffrer([event(), failed], PRICES)
    assert result['cout_mensuel_usd'] == pytest.approx(0.042)
    assert result['nb_appels'] == 2 and result['nb_erreurs'] == 1
    assert result['latence_mediane_ms'] == 300
    assert result['manquants'] == []


@pytest.mark.parametrize('events', [[], [event(error={'type': 'error', 'message': 'failed'})]])
def test_no_successful_calls_does_not_invent_zero_cost(events):
    result = chiffrer(events, PRICES)
    assert result['cout_mensuel_usd'] is None
    assert result['manquants']
    if not events:
        assert result['latence_mediane_ms'] is None and result['latence_p95_ms'] is None
        assert result['nb_appels'] == 0


@pytest.mark.parametrize('end', ['2026-09-01T00:00:00Z', '2026-08-31T00:00:00Z'])
def test_nonpositive_window_is_not_projectable(end):
    result = chiffrer([event(ts_end=end)], PRICES)
    assert result['cout_mensuel_usd'] is None
    assert result['manquants']


def test_positive_cache_requires_explicit_price():
    e = event(usage={'input_tokens': 1000, 'output_tokens': 100, 'cached_input_tokens': 500})
    result = chiffrer([e], PRICES)
    assert result['cout_mensuel_usd'] is None
    assert 'cache' in ' '.join(result['manquants'])


@pytest.mark.parametrize(('provider', 'expected'), [('openai', .0615), ('gemini', .0615), ('anthropic', .0915)])
def test_cache_accounting_respects_provider_usage(provider, expected):
    e = event(provider=provider, usage={'input_tokens': 1000, 'output_tokens': 100, 'cached_input_tokens': 500})
    assert chiffrer([e], {'gpt-4o': {'in': 2, 'out': 8, 'cached_in': .5}})['cout_mensuel_usd'] == pytest.approx(expected)


def test_absent_optional_cache_and_measured_zero_are_supported():
    result = chiffrer([event(usage={'input_tokens': 0, 'output_tokens': 0})], PRICES)
    assert result['cout_mensuel_usd'] == 0
    assert result['manquants'] == []


def test_missing_rate_is_not_zero():
    result = chiffrer([event()], {'gpt-4o': {'in': 2}})
    assert result['cout_mensuel_usd'] is None
    assert 'out' in ' '.join(result['manquants'])


def test_default_catalog_is_loaded_relative_to_module(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    result = chiffrer([event()])
    prices = json.loads((ROOT / 'fixtures/pricing.json').read_text())['gpt-4o']
    assert result['cout_mensuel_usd'] == pytest.approx((1000 * prices['in'] + 100 * prices['out']) / 1e6 * 30)


def test_real_fixtures_are_all_priced_and_keep_counts():
    # le catalogue connaît les noms des API (claude-sonnet-4-5, suffixes de date) : tout est chiffré
    before = copy.deepcopy(EVENTS)
    result = chiffrer(EVENTS)
    assert result['nb_appels'] == 50 and result['nb_erreurs'] == 1
    assert result['cout_mensuel_usd'] > 0 and result['manquants'] == []
    assert result['latence_mediane_ms'] > 0
    assert EVENTS == before


def test_unknown_model_is_still_reported():
    events = copy.deepcopy(EVENTS)
    events[0]['model'] = 'modele-maison-inconnu'
    result = chiffrer(events)
    assert result['cout_mensuel_usd'] is None
    assert any('modele-maison-inconnu' in m for m in result['manquants'])


def test_lookup_accepts_api_names_and_dated_versions():
    from report.cost import lookup
    prices = {'claude-sonnet-4-5': {'in': 3}, 'gpt-4o': {'in': 2.5}, 'gemini-2.0-flash': {'in': 0.1}}
    assert lookup(prices, 'claude-sonnet-4-5-20250929') == {'in': 3}
    assert lookup(prices, 'gpt-4o-2024-08-06') == {'in': 2.5}
    assert lookup(prices, 'openai/gpt-4o') == {'in': 2.5}
    assert lookup(prices, 'gemini-2.0-flash-001') == {'in': 0.1}
    assert lookup(prices, 'inconnu') is None and lookup(prices, None) is None
