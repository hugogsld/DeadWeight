"""R10 : indépendance visible, durées et limites."""
import copy
import json
from pathlib import Path

import pytest

from rules.parallelizable_steps import detect

ROOT = Path(__file__).resolve().parents[1]


def series(n=4):
    base = json.loads((ROOT / 'fixtures/events.jsonl').read_text().splitlines()[0])
    result = []
    for i in range(n):
        e = copy.deepcopy(base)
        e.update(event_id=f'p{i}', app_id='parallel', model='gpt-4o-mini', provider='openai',
                 ts_start=f'2026-09-20T09:00:{i * 3:02d}Z',
                 ts_end=f'2026-09-20T09:00:{i * 3 + 2:02d}Z', latency_ms=2000, error=None)
        e['trace'] = dict(id='p', source='header', step=i)
        e['request'].update(system='Analyse le dossier.', tools=[], messages=[dict(role='user', content=f'Dossier distinct {i}')])
        e['response'].update(content=f'Analyse particulière du dossier {i}.', tool_calls=[])
        e['usage'].update(input_tokens=100, output_tokens=30, cached_input_tokens=0)
        result.append(e)
    return result


def test_gain_and_purity():
    events = series()
    before = copy.deepcopy(events)
    [f] = detect(events)
    assert f['evidence']['estimated_latency_saving_seconds'] == 6
    assert f['proven'] is False
    assert events == before
    assert detect(events[::-1]) == [f]


@pytest.mark.parametrize('case', ['dependent', 'tools', 'overlap', 'unknown', 'error', 'no_trace', 'few'])
def test_exclusions(case):
    events = series()
    if case == 'few':
        events = events[:1]
    for i, e in enumerate(events):
        if case == 'dependent' and i:
            e['request']['messages'].append(dict(role='assistant', content=events[0]['response']['content']))
        if case == 'tools':
            e['request']['tools'] = [{'name': 'write'}]
        if case == 'unknown':
            e['response']['content'] = None
        if case == 'error':
            e['error'] = {'message': 'échec'}
        if case == 'no_trace':
            e['trace'] = dict(id=None, source=None, step=None)
        if case == 'overlap':
            e['ts_start'] = events[0]['ts_start']
    assert detect(events) == []


def test_dataset():
    events = [json.loads(s) for s in (ROOT / 'fixtures/dataset/v1/events.jsonl').read_text().splitlines()]
    assert {f['app_id'] for f in detect(events)} == {'serial-independent'}
