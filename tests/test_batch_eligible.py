"""R14 : candidats asynchrones, pas une preuve d'absence d'utilisateur."""
import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from report.cost import chiffrer
from rules.batch_eligible import detect

ROOT = Path(__file__).resolve().parents[1]


def bursts(hour=2, days=(0, 1, 2), size=10):
    base = json.loads((ROOT / 'fixtures/events.jsonl').read_text().splitlines()[0])
    events = []
    for day in days:
        for i in range(size):
            e = copy.deepcopy(base)
            ts = datetime(2026, 9, 20, hour, tzinfo=timezone.utc) + timedelta(days=day, seconds=i * 2)
            e.update(event_id=f'b{day}-{i}', app_id='nightly', ts_start=ts.isoformat(),
                     ts_end=(ts + timedelta(seconds=1)).isoformat())
            e['request']['messages'][0]['content'] = f'Produit {day}-{i}'
            events.append(e)
    return events


def test_regular_night_bursts_are_candidates_with_exact_half_cost():
    events = bursts()
    before = copy.deepcopy(events)
    [f] = detect(events)
    assert f['proven'] is False and f['severity'] == 'candidate'
    assert f['evidence']['bursts'] == 3
    assert f['evidence']['interval_cv'] == 0
    assert f['evidence']['timezone_assumption'] == 'UTC'
    assert f['evidence']['est_saving_month_usd'] == pytest.approx(chiffrer(events)['cout_mensuel_usd'] / 2)
    assert events == before and detect(events[::-1]) == [f]


@pytest.mark.parametrize('events', [bursts(hour=14), bursts(days=(0, 1)), bursts(size=9), bursts(days=(0, 1, 5)), []])
def test_not_scheduled_enough(events):
    assert detect(events) == []


@pytest.mark.parametrize('field', ['stream', 'error', 'other_provider', 'different_template'])
def test_ineligible_calls_are_excluded(field):
    events = bursts()
    for e in events:
        if field == 'stream':
            e['request']['params']['stream'] = True
        if field == 'error':
            e['error'] = {'type': 'error', 'message': 'failure'}
        if field == 'other_provider':
            e['provider'] = 'unsupported'
        if field == 'different_template':
            e['request']['system'] = e['event_id']  # hashing must keep non-numeric labels distinct
    assert detect(events) == []


@pytest.mark.parametrize('provider', ['openai', 'anthropic', 'gemini'])
def test_supported_providers_and_missing_cost(provider):
    events = bursts()
    for e in events:
        e['provider'] = provider
        e['model'] = 'unknown'
    [f] = detect(events)
    assert f['evidence']['est_saving_month_usd'] is None
    assert f['evidence']['saving_missing']


def test_timezone_offsets_converted_to_utc():
    events = bursts()
    for e in events:
        for key in ('ts_start', 'ts_end'):
            e[key] = datetime.fromisoformat(e[key]).astimezone(timezone(timedelta(hours=12))).isoformat()
    assert len(detect(events)) == 1


def test_null_tokens_do_not_become_zero_savings():
    events = bursts()
    events[0]['usage']['input_tokens'] = None
    [f] = detect(events)
    assert f['evidence']['est_saving_month_usd'] is None


def test_dataset_exact_apps():
    events = [json.loads(l) for l in (ROOT / 'fixtures/dataset/v1/events.jsonl').read_text().splitlines()]
    assert {f['app_id'] for f in detect(events)} == {'night-batch'}
