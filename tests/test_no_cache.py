"""D2.3 : répétitions après masquage des métadonnées volatiles."""
import copy
import json
from pathlib import Path

import pytest

from rules.no_cache import detect

DATA = Path(__file__).resolve().parents[1] / 'fixtures/dataset/v1'
KEYS = {'finding_id', 'rule', 'app_id', 'model', 'template', 'severity',
        'title', 'proven', 'event_ids', 'evidence'}


def repeated(texts=None, cached=None):
    texts = texts or ['Question identique'] * 4
    cached = cached or [0] * len(texts)
    return [{'event_id': f'e{i}', 'app_id': 'app', 'model': 'model', 'error': None,
             'request': {'system': 'Support', 'messages': [{'role': 'user', 'content': text}]},
             'usage': {'input_tokens': 1850, 'cached_input_tokens': cached[i]}}
            for i, text in enumerate(texts)]


def test_repetitions_format_evidence_and_no_mutation():
    events = repeated()
    before = copy.deepcopy(events)
    [f] = detect(events)
    assert set(f) == KEYS
    assert f['rule'] == 'no_cache' and f['proven'] is False
    assert isinstance(f['template'], str)
    assert f['severity'] == 'candidate'
    assert f['event_ids'] == ['e0', 'e1', 'e2', 'e3']
    assert f['evidence']['calls'] == 4 and f['evidence']['repetitions'] == 3
    assert f['evidence']['cached_calls'] == 0
    assert events == before


@pytest.mark.parametrize('texts', [
    ['Rapport 2026-09-20', 'Rapport 2026-09-21', 'Rapport 2026-09-22'],
    ['Rapport 2026-09-20T08:00:00Z', 'Rapport 2026-09-21T09:12:00.123+02:00', 'Rapport 2026-09-22T11:00:00-04:00'],
    ['Heure 08:00', 'Heure 09:15:20', 'Heure 23:59:59'],
    ['ID 550e8400-e29b-41d4-a716-446655440000', 'ID 550e8400-e29b-41d4-a716-446655440001', 'ID 550E8400-E29B-41D4-A716-446655440002'],
    ['ID 123456', 'ID 9876543210', 'ID 654321'],
])
def test_normalizes_volatile_values_in_system_and_messages(texts):
    assert len(detect(repeated(texts))) == 1
    events = repeated()
    for e, text in zip(events, texts):
        e['request']['system'] = text
    assert len(detect(events[:3])) == 1


@pytest.mark.parametrize('cached, flagged', [([1, 1, 1, 0], False), ([1, 1, 0, 0], True),
                                            ([None, None, None, None], True)])
def test_cache_strict_majority_and_unknown_count(cached, flagged):
    findings = detect(repeated(cached=cached))
    assert bool(findings) is flagged
    if findings:
        assert findings[0]['evidence']['unknown_cache_calls'] == cached.count(None)


def test_absent_cache_is_unknown_not_measured_zero():
    events = repeated()
    for e in events:
        e['usage'] = {'input_tokens': 1850}
    [f] = detect(events)
    assert f['evidence']['unknown_cache_calls'] == 4


@pytest.mark.parametrize('texts', [['Prix 10', 'Prix 20', 'Prix 30'], ['Bonjour', 'Au revoir', 'Merci'],
                                  ['Même début ' + 'x' * 300 + str(i) for i in range(3)]])
def test_preserves_meaningful_numbers_and_full_content(texts):
    assert detect(repeated(texts)) == []


def test_errors_and_too_few_repeats_are_ignored():
    events = repeated()[:3]
    events[-1]['error'] = {'type': 'error'}
    assert detect(events) == []
    assert detect([]) == []


def test_grouping_respects_app_model_and_message_role():
    for field in ('app_id', 'model'):
        events = repeated()[:3]
        events[-1][field] = 'other'
        assert detect(events) == []
    events = repeated()[:3]
    events[-1]['request']['messages'][0]['role'] = 'assistant'
    assert detect(events) == []


def test_message_boundaries_are_preserved():
    events = repeated()[:3]
    events[-1]['request']['messages'] = [{'role': 'user', 'content': 'Question'},
                                        {'role': 'user', 'content': 'identique'}]
    assert detect(events) == []


def test_finding_ids_are_unique_across_models_and_stable_under_input_order():
    events = repeated()
    other = copy.deepcopy(events)
    for e in other:
        e['model'] = 'other'
        e['event_id'] += 'other'
    findings = detect(events + other)
    assert len({f['finding_id'] for f in findings}) == 2
    assert detect(list(reversed(events + other))) == findings


def test_dataset_exact_apps_and_expected_events():
    events = [json.loads(line) for line in (DATA / 'events.jsonl').read_text().splitlines()]
    labels = json.loads((DATA / 'labels.json').read_text())
    expected_labels = [label for label in labels if 'no_cache' in label['expected_rules']]
    findings = detect(events)
    assert {f['app_id'] for f in findings} == {l['app_id'] for l in expected_labels} == {'faq-bot', 'daily-report'}
    assert len(findings) == 6
    assert {i for f in findings for i in f['event_ids']} == {i for l in expected_labels for i in l['event_ids']}


@pytest.mark.parametrize('tokens, flagged', [(1023, False), (1024, True), (None, False)])
def test_requires_measured_substantial_input(tokens, flagged):
    events = repeated()
    for e in events:
        e['usage']['input_tokens'] = tokens
    assert bool(detect(events)) is flagged
