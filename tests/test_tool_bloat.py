"""R13 : définitions répétées et outils réellement inutilisés."""
import copy
import json
from pathlib import Path

import pytest

from rules.tool_bloat import detect

ROOT = Path(__file__).resolve().parents[1]


def trace():
    base = json.loads((ROOT / 'fixtures/events.jsonl').read_text().splitlines()[0])
    events = []
    for i in range(4):
        e = copy.deepcopy(base)
        e.update(event_id=f't{i}', app_id='tools', ts_start=f'2026-09-20T09:00:0{i}Z',
                 ts_end=f'2026-09-20T09:00:0{i}.500Z')
        e['trace'] = {'id': 't', 'source': 'header', 'step': i}
        e['request']['tools'] = [{'name': f'tool{k}', 'description': 'description ' * 100} for k in range(10)]
        e['response']['tool_calls'] = [{'name': 'tool0', 'arguments': '{"page": %d}' % i}]
        e['usage'].update(input_tokens=5000, output_tokens=20, cached_input_tokens=0)
        events.append(e)
    return events


def test_estimates_are_labelled_and_gain_priced_without_mutation():
    events = trace()
    before = copy.deepcopy(events)
    [f] = detect(events)
    assert f['rule'] == 'tool_bloat' and f['proven'] is False
    assert f['evidence']['unused_tool_share'] == .9
    assert f['evidence']['estimated_declaration_tokens'] > 1000 * 4
    assert f['evidence']['est_saving_month_usd'] > 0
    assert '4' in f['evidence']['token_estimation']
    assert events == before
    assert detect(list(reversed(events))) == [f]


@pytest.mark.parametrize('change', ['short', 'used', 'few_calls', 'error', 'no_trace'])
def test_negatives(change):
    events = trace()
    if change == 'few_calls':
        events = events[:2]
    for e in events:
        if change == 'short':
            for tool in e['request']['tools']:
                tool['description'] = 'court'
        if change == 'used':
            e['response']['tool_calls'] = [{'name': f'tool{k}', 'arguments': '{}'} for k in range(8)]
        if change == 'error':
            e['error'] = {'type': 'failure', 'message': 'failure'}
        if change == 'no_trace':
            e['trace'] = {'id': None, 'source': None}
    assert detect(events) == []


@pytest.mark.parametrize('change', ['unknown_model', 'unknown_usage', 'cached'])
def test_missing_savings_never_fabricated(change):
    events = trace()
    for e in events:
        if change == 'unknown_model':
            e['model'] = 'not-priced'
        if change == 'unknown_usage':
            e['usage']['input_tokens'] = None
        if change == 'cached':
            e['usage']['cached_input_tokens'] = 500
    [f] = detect(events)
    assert f['evidence']['est_saving_month_usd'] is None
    assert f['evidence']['saving_missing']


def test_dataset_exact_apps():
    events = [json.loads(l) for l in (ROOT / 'fixtures/dataset/v1/events.jsonl').read_text().splitlines()]
    assert {f['app_id'] for f in detect(events)} == {'wide-tools'}
