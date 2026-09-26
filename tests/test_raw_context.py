"""D2.3 : croissance du contexte, sans confondre corrélation et preuve."""
import copy
import json
from pathlib import Path

import pytest

from rules.raw_context import _detect_traces as detect
from rules.raw_context import detect as detect_merged

DATA = Path(__file__).resolve().parents[1] / 'fixtures/dataset/v1'
KEYS = {'finding_id', 'rule', 'app_id', 'model', 'template', 'severity',
        'title', 'proven', 'event_ids', 'evidence'}


def conversation(inputs=(1000, 1500, 2000, 2500), outputs=None):
    outputs = outputs or [50] * len(inputs)
    return [{'event_id': f'e{i}', 'app_id': 'app', 'model': 'model', 'error': None,
             'trace': {'id': 'trace', 'step': i},
             'usage': {'input_tokens': value, 'output_tokens': outputs[i]}}
            for i, value in enumerate(inputs)]


def test_linear_growth_evidence_sorted_by_step_and_no_mutation():
    events = list(reversed(conversation()))
    before = copy.deepcopy(events)
    [f] = detect(events)
    assert set(f) == KEYS
    assert f['rule'] == 'raw_context' and f['severity'] == 'trim' and f['proven'] is False
    assert f['event_ids'] == ['e0', 'e1', 'e2', 'e3']
    assert f['evidence']['slope_tokens_per_turn'] == pytest.approx(500)
    assert f['evidence']['turns'] == 4
    assert f['evidence']['first_input_tokens'] == 1000
    assert f['evidence']['last_input_tokens'] == 2500
    assert f['evidence']['estimated_unused_input_share'] == pytest.approx(3000 / 7000)
    assert 'estimate_method' in f['evidence']
    assert events == before


@pytest.mark.parametrize('inputs', [(1000, 1000, 1000, 1000), (2500, 2000, 1500, 1000),
                                   (1000, 1010, 1020, 1030), (1000, 8000, 1200, 9000),
                                   (1000, 1500, 2000)])
def test_insufficient_flat_decreasing_or_irregular_growth_is_ignored(inputs):
    assert detect(conversation(inputs)) == []


@pytest.mark.parametrize('outputs', [[500] * 4, [50, 50, 50, 800], [200] * 4])
def test_outputs_must_remain_small_in_absolute_and_relative_terms(outputs):
    assert detect(conversation(outputs=outputs)) == []


@pytest.mark.parametrize('field', ['input_tokens', 'output_tokens'])
def test_unknown_usage_does_not_become_zero(field):
    events = conversation()
    events[0]['usage'][field] = None
    assert detect(events) == []


@pytest.mark.parametrize('trace', [{'id': None, 'step': 0}, {'id': 'trace'}, {'id': 'trace', 'step': None}])
def test_missing_trace_or_step_is_ignored(trace):
    events = conversation()
    for e in events:
        e['trace'] = trace.copy()
    assert detect(events) == []


def test_duplicate_steps_do_not_invent_turn_order():
    events = conversation()
    events[-1]['trace']['step'] = 0
    assert detect(events) == []


def test_errors_excluded_and_groups_isolated():
    events = conversation()
    bad = copy.deepcopy(events[-1])
    bad.update(event_id='bad', error={'type': 'error'}, usage={'input_tokens': None, 'output_tokens': None})
    [f] = detect(events + [bad])
    assert 'bad' not in f['event_ids']
    for field in ('app_id', 'model'):
        split = copy.deepcopy(events)
        split[-1][field] = 'other'
        assert detect(split) == []
    split = copy.deepcopy(events)
    split[-1]['trace']['id'] = 'other'
    assert detect(split) == []


def test_step_spacing_is_used_for_slope():
    events = conversation()
    for e in events:
        e['trace']['step'] *= 2
    # 250 tokens / tour est sous le seuil de 256.
    assert detect(events) == []


def test_dataset_exact_apps_and_trace_membership():
    events = [json.loads(line) for line in (DATA / 'events.jsonl').read_text().splitlines()]
    labels = json.loads((DATA / 'labels.json').read_text())
    expected = {label['app_id'] for label in labels if 'raw_context' in label['expected_rules']}
    findings = detect(events)
    assert {f['app_id'] for f in findings} == expected == {'contract-bot'}
    assert len(findings) == 10
    by_id = {e['event_id']: e for e in events}
    for f in findings:
        assert len({by_id[i]['trace']['id'] for i in f['event_ids']}) == 1
        assert f['evidence']['slope_tokens_per_turn'] == pytest.approx(1700, abs=20)


def test_empty():
    assert detect([]) == []


def test_dataset_one_finding_per_app_for_the_report():
    events = [json.loads(line) for line in (DATA / 'events.jsonl').read_text().splitlines()]
    merged = detect_merged(events)
    assert [f['app_id'] for f in merged] == ['contract-bot']
    assert merged[0]['evidence']['traces'] == 10 and len(merged[0]['event_ids']) == 80
