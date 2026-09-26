"""R17 : transformation, verdict et informations nouvelles."""
import copy
import json
from pathlib import Path

import pytest

from rules.mergeable_steps import detect
from tests.test_parallelizable_steps import series

ROOT = Path(__file__).resolve().parents[1]


def pair():
    es = series(2)
    es[0]['response']['content'] = 'Le rapport détaillé présente les résultats du dossier. ' * 3
    es[1]['request']['messages'] = es[0]['request']['messages'] + [
        dict(role='assistant', content=es[0]['response']['content']),
        dict(role='user', content='Traduis cette réponse en anglais.')]
    es[1]['response']['content'] = 'The detailed report presents the results of the case.'
    return es


def test_cost_of_second_only():
    es = pair()
    original = copy.deepcopy(es)
    [f] = detect(es)
    assert f['event_ids'] == ['p1']
    assert f['evidence']['estimated_latency_saving_seconds'] == 2
    assert f['evidence']['est_saving_month_usd'] > 0
    assert es == original
    assert detect(es[::-1]) == [f]


@pytest.mark.parametrize('case', ['judge', 'new_task', 'model', 'error', 'tools', 'overlap', 'missing_response'])
def test_negatives(case):
    es = pair()
    if case == 'judge':
        es[1]['response']['content'] = 'OK'
    if case == 'new_task':
        es[1]['request']['messages'][-1]['content'] = 'Cherche les dernières ventes.'
    if case == 'model':
        es[1]['model'] = 'claude-opus-4'
    if case == 'error':
        es[0]['error'] = dict(message='échec')
    if case == 'tools':
        es[1]['request']['tools'] = [dict(name='search')]
    if case == 'overlap':
        es[1]['ts_start'] = es[0]['ts_start']
    if case == 'missing_response':
        es[0]['response']['content'] = None
    assert detect(es) == []


def test_unknown_cost():
    es = pair()
    for e in es:
        e['model'] = 'unknown'
    [f] = detect(es)
    assert f['evidence']['est_saving_month_usd'] is None
    assert f['evidence']['saving_missing']


def test_dataset():
    es = [json.loads(l) for l in (ROOT / 'fixtures/dataset/v1/events.jsonl').read_text().splitlines()]
    assert {f['app_id'] for f in detect(es)} == {'rewrite-chain'}
