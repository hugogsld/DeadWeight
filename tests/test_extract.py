"""D3.1 : extraction de données uniquement, aucun appel réseau réel."""
import copy
import io
import json
from pathlib import Path

import pytest

from proof.extract import OpenAICompatibleLLM, build_router, extract_rules
from rules.low_entropy import detect


class FakeLLM:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, []

    def complete(self, system, user, schema):
        self.calls.append((system, json.loads(user), schema))
        if self.error:
            raise self.error
        return self.result


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Unexpected network request')
    monkeypatch.setattr('urllib.request.urlopen', forbidden)


def example_data():
    samples = [{'event_id': 'a', 'output': 'facture'}, {'event_id': 'b', 'output': 'support'}]
    finding = {'rule': 'low_entropy_output', 'evidence': {
        'samples': samples, 'output_distribution': {'facture': 1, 'support': 1}}}
    events = [
        {'event_id': 'a', 'request': {'messages': [
            {'role': 'system', 'content': 'SECRET SYSTEM'},
            {'role': 'user', 'content': 'Facture'},
            {'role': 'assistant', 'content': 'SECRET ASSISTANT'},
            {'role': 'tool', 'content': 'SECRET TOOL'},
            {'role': 'user', 'content': 'paiement'}]}},
        {'event_id': 'b', 'request': {'messages': [{'role': 'user', 'content': 'Support connexion'}]}},
    ]
    return finding, events


def test_offline_fallback_and_router():
    finding, events = example_data()
    result = extract_rules(finding, events)
    assert set(result) == {'categories', 'coverage', 'method', 'reasoning', 'gabarit'}
    assert result['method'] == 'offline' and result['coverage'] == 1
    assert build_router(result)('FACTURE paiement') == 'facture'
    assert build_router(result)('Support connexion') == 'support'
    assert build_router(result)('texte inconnu') is None


def test_llm_exception_falls_back_without_leaking_error_details():
    finding, events = example_data()
    result = extract_rules(finding, events, FakeLLM(error=RuntimeError('secret-api-key')))
    assert result['method'] == 'offline' and result['coverage'] == 1
    assert 'secret-api-key' not in json.dumps(result)


def test_only_user_messages_are_reconstructed_by_event_id_without_mutation():
    finding, events = example_data()
    before = copy.deepcopy((finding, events))
    llm = FakeLLM({'categories': [], 'reasoning': 'test'})
    extract_rules(finding, reversed(events), llm)
    system, payload, schema = llm.calls[0]
    assert [s['input'] for s in payload['samples']] == ['Facture\npaiement', 'Support connexion']
    assert 'SECRET' not in json.dumps(payload)
    assert 'code' in system.lower()
    assert schema['additionalProperties'] is False
    assert (finding, events) == before


def test_invalid_regex_and_invented_key_are_discarded():
    finding, events = example_data()
    llm = FakeLLM({'categories': [{'key': 'facture', 'regex': '['},
                                  {'key': 'invented', 'regex': '.*'},
                                  {'key': 'support', 'regex': 'support'}],
                   'reasoning': 'Validé', 'coverage_estimate': 1})
    result = extract_rules(finding, events, llm)
    assert result['method'] == 'llm'
    assert result['categories'] == [{'key': 'support', 'regex': 'support'}]
    assert result['coverage'] == .5


def test_coverage_counts_correct_labels_not_just_matches_and_honors_order():
    finding, events = example_data()
    llm = FakeLLM({'categories': [{'key': 'support', 'regex': '.*'},
                                  {'key': 'facture', 'regex': 'facture'}],
                   'coverage': .99, 'coverage_estimate': .99, 'reasoning': 'test'})
    result = extract_rules(finding, events, llm)
    assert result['coverage'] == .5
    assert build_router(result)('facture') == 'support'


@pytest.mark.parametrize('bad', [None, [], 'code', {}, {'categories': None}, {'categories': 'bad'}])
def test_malformed_llm_response_falls_back(bad):
    finding, events = example_data()
    result = extract_rules(finding, events, FakeLLM(bad))
    assert result['method'] == 'offline' and result['coverage'] == 1


def test_category_types_are_validated_and_extra_fields_not_returned():
    finding, events = example_data()
    result = extract_rules(finding, events, FakeLLM({'categories': [
        None, 3, {'key': [], 'regex': 'x'}, {'key': 'support', 'regex': None},
        {'key': 'facture', 'regex': 'facture', 'code': 'do_not_execute()'}],
        'reasoning': ['not a string']}))
    assert result['categories'] == [{'key': 'facture', 'regex': 'facture'}]
    assert isinstance(result['reasoning'], str)


def test_missing_events_and_null_user_content_are_not_invented():
    finding, events = example_data()
    events[1]['request']['messages'][0]['content'] = None
    result = extract_rules(finding, events)
    assert result['coverage'] == 1
    assert {c['key'] for c in result['categories']} == {'facture'}
    result = extract_rules(finding, [])
    assert result['categories'] == [] and result['coverage'] == 0
    assert result['method'] == 'offline'


@pytest.mark.parametrize('finding, events', [(None, None), ({}, []), ({'evidence': None}, []),
                                            ({'evidence': {'samples': [None]}}, [None])])
def test_invalid_inputs_never_escape(finding, events):
    result = extract_rules(finding, events)
    assert result['categories'] == [] and result['coverage'] == 0
    assert result['method'] == 'offline'


def test_router_skips_invalid_data_and_snapshots_rules():
    rules = {'categories': [{'key': 'a', 'regex': '['}, {'key': 'b', 'regex': 'bonjour'}]}
    router = build_router(rules)
    rules['categories'].clear()
    assert router('BONJOUR') == 'b'
    assert router('inconnu') is None


def test_dataset_mail_triage_offline_coverage():
    path = Path(__file__).resolve().parents[1] / 'fixtures/dataset/v1/events.jsonl'
    events = [json.loads(line) for line in path.read_text().splitlines()]
    [finding] = [f for f in detect(events) if f['app_id'] == 'mail-triage']
    result = extract_rules(finding, events)
    assert result['method'] == 'offline' and result['coverage'] >= .8
    router = build_router(result)
    by_id = {e['event_id']: e for e in events}
    samples = finding['evidence']['samples']
    correct = sum(router('\n'.join(m['content'] for m in by_id[s['event_id']]['request']['messages']
                                  if m['role'] == 'user')) == s['output'] for s in samples)
    assert result['coverage'] == pytest.approx(correct / len(samples))


def test_openai_adapter_request_and_response_are_structured(monkeypatch):
    expected = {'categories': [{'key': 'facture', 'regex': 'facture'}], 'reasoning': 'test'}
    seen = []
    def fake_urlopen(request, timeout):
        seen.append((request, timeout))
        return io.BytesIO(json.dumps({'choices': [{'message': {'content': json.dumps(expected)}}]}).encode())
    monkeypatch.setattr('urllib.request.urlopen', fake_urlopen)
    client = OpenAICompatibleLLM('https://example.invalid/v1/', 'caller-key', 'caller-model')
    assert client.complete('system', 'user', {'type': 'object'}) == expected
    request, timeout = seen[0]
    assert request.full_url == 'https://example.invalid/v1/chat/completions'
    assert request.get_header('Authorization') == 'Bearer caller-key'
    assert request.get_method() == 'POST' and timeout > 0
    body = json.loads(request.data)
    assert body['model'] == 'caller-model'
    assert body['messages'] == [{'role': 'system', 'content': 'system'}, {'role': 'user', 'content': 'user'}]
    assert body['response_format'] == {'type': 'json_schema', 'json_schema': {
        'name': 'rules', 'strict': True, 'schema': {'type': 'object'}}}
    assert 'caller-key' not in request.data.decode()


def test_adapter_bad_json_triggers_offline_fallback(monkeypatch):
    monkeypatch.setattr('urllib.request.urlopen', lambda *a, **k: io.BytesIO(b'not json'))
    finding, events = example_data()
    result = extract_rules(finding, events, OpenAICompatibleLLM('https://example.invalid/v1', 'key', 'model'))
    assert result['method'] == 'offline' and result['coverage'] == 1


def test_les_regles_ignorent_la_consigne_fixe_du_prompt():
    # vu sur un vrai n8n : « Classe ce ticket parmi billing, technical… » est dans chaque appel ;
    # une règle « technical » matchait donc tous les tickets
    from proof.extract import build_router, extract_rules
    consigne = "Classe ce ticket parmi billing, technical, account, other. Reponds uniquement par le mot.\n\nTicket: "
    tickets = [("Ma facture est fausse", "billing"), ("Remboursez ma facture", "billing"),
               ("L'appli plante au démarrage", "technical"), ("Erreur 500 sur l'export", "technical")] * 3
    events = [{"event_id": f"e{i}", "error": None, "request": {"messages": [{"role": "user", "content": consigne + t}]},
               "response": {"content": o}} for i, (t, o) in enumerate(tickets)]
    finding = {"event_ids": [e["event_id"] for e in events],
               "evidence": {"samples": [{"event_id": e["event_id"], "output": o} for e, (_, o) in zip(events, tickets)],
                            "output_distribution": {"billing": 6, "technical": 6}}}
    rules = extract_rules(finding, events)
    assert rules["gabarit"]["prefixe"].startswith("Classe ce ticket")
    route = build_router({**rules, "categories": [{"key": "technical", "regex": "technical|plante"},
                                                 {"key": "billing", "regex": "facture"}]})
    assert route(consigne + "Ma facture est fausse") == "billing"  # « technical » de la consigne ignoré
    assert route(consigne + "L'appli plante") == "technical"
