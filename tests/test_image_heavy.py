"""R15 : ratio élevé avec texte bref ; aucune résolution réelle n'est inventée."""
import copy
import json
from pathlib import Path

import pytest

from rules.image_heavy import detect

ROOT = Path(__file__).resolve().parents[1]


def images():
    base = json.loads((ROOT / 'fixtures/events.jsonl').read_text().splitlines()[0])
    events = []
    for i in range(6):
        e = copy.deepcopy(base)
        e.update(event_id=f'i{i}', app_id='vision')
        e['request']['messages'] = [{'role': 'user', 'content': f'Lis le titre {i}', 'n_images': 1}]
        e['usage'].update(input_tokens=4096, output_tokens=10)
        e['response']['content'] = f'Titre {i}'
        events.append(e)
    return events


@pytest.mark.parametrize('provider', ['openai', 'anthropic', 'gemini'])
def test_high_ratio_short_answers_and_unknown_saving(provider):
    events = images()
    for e in events:
        e['provider'] = provider
    before = copy.deepcopy(events)
    [f] = detect(events)
    assert f['proven'] is False and f['severity'] == 'candidate'
    assert f['evidence']['median_input_tokens_per_image_upper_bound'] == 4096
    assert f['evidence']['provider'] == provider
    assert f['evidence']['est_saving_month_usd'] is None and f['evidence']['saving_missing']
    assert events == before and detect(events[::-1]) == [f]


@pytest.mark.parametrize('change', ['no_images', 'small_input', 'long_text', 'complex_output', 'missing', 'error', 'few'])
def test_negatives(change):
    events = images()
    if change == 'few':
        events = events[:4]
    for i, e in enumerate(events):
        if change == 'no_images':
            e['request']['messages'][0]['n_images'] = 0
        if change == 'small_input':
            e['usage']['input_tokens'] = 500
        if change == 'long_text':
            e['request']['system'] = 'Document ' * 3000
        if change == 'complex_output':
            e['response']['content'] = f'Analyse approfondie différente {i}'
            e['usage']['output_tokens'] = 500
        if change == 'missing':
            e['usage']['input_tokens'] = None
        if change == 'error':
            e['error'] = {'type': 'error', 'message': 'failure'}
    assert detect(events) == []


def test_low_variation_is_an_alternative_to_short_output():
    events = images()
    for e in events:
        e['usage']['output_tokens'] = 100
        e['response']['content'] = 'Toujours la même réponse longue.'
    assert len(detect(events)) == 1


def test_tokens_per_image_divides_by_actual_count():
    events = images()
    for e in events:
        e['request']['messages'][0]['n_images'] = 4
    assert detect(events) == []


def test_only_high_ratio_events_enter_finding():
    events = images()
    events[0]['usage']['input_tokens'] = 100
    [f] = detect(events)
    assert 'i0' not in f['event_ids']
    assert f['evidence']['calls'] == 5


def test_dataset_exact_apps():
    events = [json.loads(l) for l in (ROOT / 'fixtures/dataset/v1/events.jsonl').read_text().splitlines()]
    assert {f['app_id'] for f in detect(events)} == {'image-titles'}
