"""R19 : sessions longues, contexte dominant et durable, sans lecture de contenu."""
import copy
import json
from pathlib import Path

import pytest

from rules.context_reread import detect

ROOT = Path(__file__).resolve().parents[1]
BASE = json.loads((ROOT / 'fixtures/events.jsonl').read_text().splitlines()[0])


def sessions(n_sessions=3, calls=20, provider='anthropic', model='claude-sonnet-4-5',
             start_cached=15000, growth=12000, shrink=False):
    """Sessions Anthropic dont le cache (donc le contexte) grossit à chaque tour."""
    events = []
    for s in range(n_sessions):
        for i in range(calls):
            e = copy.deepcopy(BASE)
            cached = start_cached + growth * i
            if shrink:
                cached = start_cached + growth * calls if i == 0 else start_cached
            e.update(event_id=f's{s}c{i}', app_id='code-agent', model=model, provider=provider,
                     ts_start=f'2026-09-20T{9 + s:02d}:{i:02d}:00Z',
                     ts_end=f'2026-09-20T{9 + s:02d}:{i:02d}:02Z', latency_ms=2000, error=None)
            e['trace'] = dict(id=f'session-{s}', source='header', step=i)
            e['request'].update(system='Agent.', tools=[], messages=[dict(role='user', content=f'Etape {i}')])
            e['response'].update(content=f'Reponse {i}', tool_calls=[])
            e['usage'].update(input_tokens=600, output_tokens=150, cached_input_tokens=cached)
            events.append(e)
    return events


def test_positive_grows_and_dominates_cost():
    events = sessions()
    before = copy.deepcopy(events)
    [f] = detect(events)
    ev = f['evidence']
    assert ev['sessions'] == 3
    assert ev['calls'] == 60
    assert ev['median_calls_per_session'] == 20
    assert ev['median_context_tokens'] > 8192
    assert ev['context_cost_share'] >= .5
    assert ev['median_last_context_tokens'] >= ev['median_startup_context_tokens']
    assert 'jetons de conversation' in f['title']
    assert f['proven'] is False and f['severity'] == 'trim'
    assert events == before
    assert detect(events[::-1]) == [f]


@pytest.mark.parametrize('case', ['few_sessions', 'short_sessions', 'small_context', 'shrinking',
                                   'no_trace', 'unknown_cache_anthropic', 'error', 'unknown_price'])
def test_negatives(case):
    if case == 'few_sessions':
        events = sessions(n_sessions=1)
    elif case == 'short_sessions':
        events = sessions(calls=3)
    elif case == 'small_context':
        events = sessions(start_cached=200, growth=10)
    elif case == 'shrinking':
        events = sessions(shrink=True)
    else:
        events = sessions()
    if case == 'no_trace':
        for e in events:
            e['trace'] = dict(id=None, source=None, step=None)
    if case == 'unknown_cache_anthropic':
        for e in events:
            e['usage']['cached_input_tokens'] = None
    if case == 'error':
        for e in events:
            e['error'] = dict(message='échec')
    if case == 'unknown_price':
        for e in events:
            e['model'] = 'modele-inconnu'
    assert detect(events) == []


def test_openai_cache_already_counted_in_input():
    """Chez OpenAI/Gemini, le cache est déjà inclus dans input_tokens : pas d'addition."""
    events = sessions(provider='openai', model='gpt-4o', start_cached=0, growth=0)
    for e in events:
        e['usage']['cached_input_tokens'] = 0
        e['usage']['input_tokens'] = 15000  # contexte déjà large, sans cache séparé
    [f] = detect(events)
    assert f['evidence']['median_context_tokens'] == 15000


def test_low_context_cost_share_is_excluded():
    """Sortie très volumineuse : le contexte ne domine plus le coût, même s'il est gros."""
    events = sessions()
    for e in events:
        e['usage']['output_tokens'] = 200000
    assert detect(events) == []


def test_dataset():
    events = [json.loads(l) for l in (ROOT / 'fixtures/dataset/v1/events.jsonl').read_text().splitlines()]
    assert {f['app_id'] for f in detect(events)} == {'code-agent-cache-heavy', 'contract-bot'}
    assert 'chat-short-sessions' not in {f['app_id'] for f in detect(events)}
