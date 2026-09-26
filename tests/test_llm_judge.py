"""R16 : relecture répétée, traces explicites ou reconstruites."""
import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from report.cost import chiffrer
from rules.llm_judge import detect

ROOT = Path(__file__).resolve().parents[1]


def pairs(header=True, count=6):
    base = json.loads((ROOT / 'fixtures/events.jsonl').read_text().splitlines()[0])
    events = []
    for i in range(count):
        response = f'Document {i} : ' + 'Une réponse détaillée et utile pour le client. ' * 4
        first = copy.deepcopy(base)
        ts = datetime(2026, 9, 20, tzinfo=timezone.utc) + timedelta(hours=i)
        first.update(event_id=f'gen{i}', app_id='reviewer', ts_start=ts.isoformat(), ts_end=(ts+timedelta(seconds=1)).isoformat())
        first['request']['system'] = 'Rédige puis vérifie les réponses.'
        first['request']['messages'] = [{'role': 'user', 'content': f'Rédige le document {i}'}]
        first['response']['content'] = response
        first['usage'].update(input_tokens=200, output_tokens=100)
        first['trace'] = {'id': f't{i}' if header else None, 'source': 'header' if header else None, 'step': 0}
        second = copy.deepcopy(first)
        second.update(event_id=f'judge{i}', ts_start=(ts+timedelta(seconds=2)).isoformat(), ts_end=(ts+timedelta(seconds=3)).isoformat())
        second['request']['messages'] += [{'role': 'assistant', 'content': response},
                                         {'role': 'user', 'content': 'Vérifie la réponse et réponds oui ou non.'}]
        second['response']['content'] = 'OK'
        second['usage'].update(input_tokens=400, output_tokens=2)
        second['trace']['step'] = 1
        events.extend([first, second])
    return events


@pytest.mark.parametrize('header', [True, False])
def test_detects_judges_only_and_priced_sampling_scenario(header):
    events = pairs(header)
    before = copy.deepcopy(events)
    [f] = detect(events)
    assert set(f['event_ids']) == {f'judge{i}' for i in range(6)}
    assert f['evidence']['judge_share'] == 1 and f['evidence']['traces'] == 6
    assert f['proven'] is False and f['severity'] == 'candidate'
    assert f['evidence']['assumed_review_sample_share'] == .1
    assert f['evidence']['est_saving_month_usd'] == pytest.approx(chiffrer(events[1::2])['cout_mensuel_usd'] * .9)
    assert events == before and detect(events[::-1]) == [f]


@pytest.mark.parametrize('change', ['long_answer', 'not_contained', 'no_review_intent', 'error', 'too_few', 'small_previous', 'concurrent'])
def test_negatives(change):
    events = pairs()
    if change == 'too_few':
        events = events[:8]
    for first, second in zip(events[::2], events[1::2]):
        if change == 'long_answer':
            second['response']['content'] = 'Une nouvelle analyse complète.'
            second['usage']['output_tokens'] = 100
        if change == 'not_contained':
            second['request']['messages'] = [{'role': 'user', 'content': 'Vérifie un autre texte.'}]
        if change == 'no_review_intent':
            first['request']['system'] = second['request']['system'] = 'Assistant.'
            second['request']['messages'][-1]['content'] = 'Tu peux continuer ?'
        if change == 'error':
            second['error'] = {'type': 'error', 'message': 'failure'}
        if change == 'small_previous':
            first['response']['content'] = 'OK'
        if change == 'concurrent':
            second['ts_start'] = first['ts_start']
    assert detect(events) == []


def test_occasional_review_is_not_systematic():
    events = pairs()
    for e in events[1::2][:2]:
        e['response']['content'] = 'Une réponse longue qui ne juge pas.'
    assert detect(events) == []


def test_review_can_use_different_model():
    events = pairs()
    for e in events[1::2]:
        e['model'] = 'gpt-4o-mini'
    [f] = detect(events)
    assert f['model'] == 'gpt-4o-mini'


def test_unknown_price_is_explained():
    events = pairs()
    for e in events:
        e['model'] = 'unknown'
    [f] = detect(events)
    assert f['evidence']['est_saving_month_usd'] is None and f['evidence']['saving_missing']


@pytest.mark.parametrize('verdict', ['oui', 'NON.', '8/10', '0.9', 'valide', 'approved'])
def test_common_verdicts(verdict):
    events = pairs()
    for e in events[1::2]:
        e['response']['content'] = verdict
    assert len(detect(events)) == 1


def test_dataset_exact_apps():
    events = [json.loads(l) for l in (ROOT / 'fixtures/dataset/v1/events.jsonl').read_text().splitlines()]
    assert {f['app_id'] for f in detect(events)} == {'systematic-review'}


@pytest.mark.parametrize('non_judges, expected', [(1, True), (2, True), (3, False)])
def test_systematic_share_boundary(non_judges, expected):
    events = pairs(count=10)
    for e in events[1::2][:non_judges]:
        e['response']['content'] = 'Un développement complémentaire.'
    assert bool(detect(events)) is expected


def test_missing_judge_input_usage_prevents_estimated_saving():
    events = pairs()
    events[1]['usage']['input_tokens'] = None
    [f] = detect(events)
    assert f['evidence']['est_saving_month_usd'] is None
    assert f['evidence']['saving_missing']
