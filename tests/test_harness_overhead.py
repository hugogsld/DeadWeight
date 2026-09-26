"""R18 : part fixe, prix inconnus, cache et distinction des outils inutiles."""
import copy
import json
from pathlib import Path

import pytest

from rules.harness_overhead import detect
from tests.test_per_item_calls import batch

ROOT = Path(__file__).resolve().parents[1]


def heavy():
    es = batch() * 2
    es = [copy.deepcopy(e) for e in es]
    for i, e in enumerate(es):
        e['event_id'] = f'h{i}'
        e['request']['system'] = 'Instructions générales de traitement. ' * 150
        e['request']['messages'][0]['content'] = f'Dossier {i} avec des observations.'
        e['usage'].update(input_tokens=1700, output_tokens=100, cached_input_tokens=0)
    return es


def test_fixed_cost_and_purity():
    es = heavy()
    before = copy.deepcopy(es)
    [f] = detect(es)
    assert f['evidence']['fixed_input_share'] > .7
    assert f['evidence']['fixed_cost_month_usd_min'] > 0
    assert f['evidence']['cache_saving_month_usd_max'] == 0
    assert es == before
    assert detect(es[::-1]) == [f]


@pytest.mark.parametrize('case', ['few', 'small', 'long_output', 'tools_used', 'error'])
def test_negatives(case):
    es = heavy()[:19] if case == 'few' else heavy()
    for e in es:
        if case == 'small':
            e['request']['system'] = 'Court.'
        if case == 'long_output':
            e['usage']['output_tokens'] = 1000
        if case == 'tools_used':
            e['response']['tool_calls'] = [dict(name='search')]
        if case == 'error':
            e['error'] = dict(message='Erreur')
    assert detect(es) == []


def test_cache_bounds_and_missing_prices():
    es = heavy()
    for e in es:
        e['usage']['cached_input_tokens'] = 1000
    [f] = detect(es)
    ev = f['evidence']
    assert ev['estimated_cached_fixed_tokens_min'] <= ev['estimated_cached_fixed_tokens_max']
    assert ev['cache_saving_month_usd_max'] > 0
    assert ev['fixed_cost_month_usd_min'] <= ev['fixed_cost_month_usd_max']
    for e in es:
        e['model'] = 'inconnu'
    [f] = detect(es)
    assert f['evidence']['fixed_cost_month_usd_min'] is None
    assert f['evidence']['saving_missing']


def test_no_duplicate_tool_bloat():
    es = heavy()
    for i, e in enumerate(es):
        e['trace'] = dict(id='heavy', source='header', step=i)
        e['request']['tools'] = [dict(name=f't{k}', description='Longue définition. ' * 100) for k in range(10)]
    assert detect(es) == []


def test_dataset():
    es = [json.loads(l) for l in (ROOT / 'fixtures/dataset/v1/events.jsonl').read_text().splitlines()]
    assert {f['app_id'] for f in detect(es)} == {'heavy-harness'}


def test_anthropic_counts_cached_tokens_outside_input():
    es = heavy()
    for e in es:
        e['provider'] = 'anthropic'
        e['usage'].update(input_tokens=700, cached_input_tokens=1000)
    [f] = detect(es)
    assert f['evidence']['fixed_input_share'] == pytest.approx(1425 / 1700)
    assert f['evidence']['estimated_cached_fixed_tokens_min'] == 725 * 20
    assert f['evidence']['estimated_cached_fixed_tokens_max'] == 1000 * 20


def test_unknown_cache_does_not_become_zero():
    es = heavy()
    for e in es:
        e['usage']['cached_input_tokens'] = None
    [f] = detect(es)
    assert f['evidence']['fixed_cost_month_usd_min'] is None
    assert f['evidence']['estimated_cached_fixed_tokens_min'] is None
    assert f['evidence']['saving_missing']
