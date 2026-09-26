"""R11 : lots courts variables, coûts manquants et cache."""
import copy
import json
from pathlib import Path

import pytest

from rules.per_item_calls import detect
from tests.test_parallelizable_steps import series

ROOT = Path(__file__).resolve().parents[1]


def batch():
    es = series(10)
    for e in es:
        e['request']['system'] = 'Instructions communes pour analyser chaque élément. ' * 6
        e['trace'] = dict(id=None, step=None, source=None)
        e['usage']['input_tokens'] = 200
    return es


def test_savings():
    es = batch()
    before = copy.deepcopy(es)
    [f] = detect(es)
    assert f['evidence']['estimated_repeated_system_tokens'] > 500
    assert f['evidence']['est_saving_month_usd'] > 0
    assert f['evidence']['estimated_latency_saving_seconds'] == 18
    assert es == before
    assert detect(es[::-1]) == [f]


@pytest.mark.parametrize('case', ['few', 'identical', 'long', 'history', 'error', 'tools'])
def test_negatives(case):
    es = batch()[:7] if case == 'few' else batch()
    for e in es:
        if case == 'identical':
            e['request']['messages'][0]['content'] = 'Même élément'
        if case == 'long':
            e['usage']['output_tokens'] = 500
        if case == 'history':
            e['request']['messages'].append(dict(role='assistant', content='Historique'))
        if case == 'error':
            e['error'] = dict(message='Erreur')
        if case == 'tools':
            e['request']['tools'] = [dict(name='outil')]
    assert detect(es) == []


def test_unknown_price_and_cache():
    for cached in (0, None, 100):
        es = batch()
        for e in es:
            e['model'] = 'inconnu'
            e['usage']['cached_input_tokens'] = cached
        [f] = detect(es)
        assert f['evidence']['est_saving_month_usd'] is None
        assert f['evidence']['saving_missing']


def test_dataset():
    es = [json.loads(l) for l in (ROOT / 'fixtures/dataset/v1/events.jsonl').read_text().splitlines()]
    assert {f['app_id'] for f in detect(es)} == {'item-loop'}
