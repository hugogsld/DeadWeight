"""D3.2 : rejeu et seuil, aucun appel réseau réel."""
import json
from pathlib import Path

import jsonschema
import pytest

from proof.extract import extract_rules
from proof.replay import HARD_MAX_CALLS, MIN_REPLAY, Throttle, main, replay
from rules.low_entropy import detect

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / 'fixtures/dataset/v1/events.jsonl'
PROOF_SCHEMA = json.loads((ROOT / 'schemas/proof.schema.json').read_text())


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Unexpected network request')
    monkeypatch.setattr('urllib.request.urlopen', forbidden)


@pytest.fixture(scope='module')
def dataset():
    events = [json.loads(line) for line in DATASET.read_text().splitlines()]
    return events, {f['app_id']: f for f in detect(events)}


class FakeFallback:
    def __init__(self, answer='spam', error=None):
        self.answer, self.error, self.calls = answer, error, 0

    def classify(self, text, keys):
        self.calls += 1
        if self.error:
            raise self.error
        return self.answer, 50, 1


def _events(n, label='spam', text='gagnez un iphone'):
    return [{'event_id': f'e{i}', 'model': 'gpt-4o', 'provider': 'openai', 'latency_ms': 600,
             'ts_start': f'2026-09-20T09:{i // 60:02d}:{i % 60:02d}Z',
             'ts_end': f'2026-09-20T09:{i // 60:02d}:{i % 60:02d}.5Z', 'error': None,
             'request': {'messages': [{'role': 'user', 'content': f'{text} {i}'}]},
             'response': {'content': label}, 'usage': {'input_tokens': 60, 'output_tokens': 2}}
            for i in range(n)]


def _finding(events, samples=()):
    return {'finding_id': 'f', 'event_ids': [e['event_id'] for e in events],
            'evidence': {'samples': [{'event_id': s, 'output': 'spam'} for s in samples]}}


RULES = {'categories': [{'key': 'spam', 'regex': 'gagnez'}]}


def test_dataset_mail_triage_passes_on_held_out_events(dataset):
    events, findings = dataset
    finding = findings['mail-triage']
    proof = replay(finding, events, extract_rules(finding, events))
    assert proof['verdict'] == 'pass' and proof['reasons'] == []
    assert proof['n_replayed'] == finding['evidence']['calls'] - len(finding['evidence']['samples'])
    assert proof['agreement_rate'] >= .95 and proof['n_replaced'] >= MIN_REPLAY
    assert proof['cost_after_month_usd'] < proof['cost_before_month_usd']
    for field in ('patch_id', 'finding_id', 'n_replayed', 'agreement_rate', 'threshold',
                  'p95_before_ms', 'p95_after_ms', 'cost_before_month_usd', 'cost_after_month_usd'):
        assert proof[field] is not None


def test_dataset_reviews_rejected_as_a_result(dataset):
    events, findings = dataset
    finding = findings['reviews']
    proof = replay(finding, events, extract_rules(finding, events))
    assert proof['verdict'] == 'reject' and proof['reasons']
    assert proof['cost_before_month_usd'] > 0  # claude-opus-4-1 est au catalogue


def test_unmeasured_cost_is_null_never_a_default(dataset):
    events, findings = dataset
    finding = findings['reviews']
    unknown = [{**e, 'model': 'modele-maison-inconnu'} if e['app_id'] == 'reviews' else e for e in events]
    finding = {**finding, 'model': 'modele-maison-inconnu'}
    proof = replay(finding, unknown, extract_rules(finding, unknown))
    assert proof['cost_before_month_usd'] is None and proof['cost_factor'] is None
    assert any('catalogue' in m for m in proof['cost_missing'])
    jsonschema.validate(proof, PROOF_SCHEMA)


def test_extraction_samples_are_excluded():
    events = _events(40)
    proof = replay(_finding(events, samples=['e0', 'e1']), events, RULES)
    assert proof['n_replayed'] == 38 and proof['n_excluded_extraction_samples'] == 2


def test_below_threshold_rejects_with_reason():
    events = _events(40)
    for e in events[:5]:
        e['response']['content'] = 'Facture.'
    proof = replay(_finding(events), events, RULES)
    assert proof['agreement_rate'] == pytest.approx(35 / 40)
    assert proof['verdict'] == 'reject'
    assert any('sous le seuil' in r for r in proof['reasons'])
    assert proof['disagreements'][0] == {'event_id': 'e0', 'input': 'gagnez un iphone 0',
                                        'expected': 'facture', 'got': 'spam', 'via': 'regles'}


def test_unmatched_stays_on_original_and_is_not_compared():
    events = _events(30) + _events(10, text='bonjour')
    for i, e in enumerate(events[30:]):
        e['event_id'] = f'u{i}'
    proof = replay(_finding(events), events, RULES)
    assert proof['n_replaced'] == 30 and proof['agreement_rate'] == 1
    assert proof['verdict'] == 'pass'
    assert proof['cost_after_month_usd'] == pytest.approx(proof['cost_before_month_usd'] / 4, rel=1e-3)


def test_too_few_replaced_rejects_even_at_full_agreement():
    events = _events(MIN_REPLAY - 1)
    proof = replay(_finding(events), events, RULES)
    assert proof['agreement_rate'] == 1 and proof['verdict'] == 'reject'


def test_fallback_is_capped_and_spaced():
    events = _events(40, text='bonjour')
    clock, sleeps = [0.0], []
    throttle = Throttle(max_calls=3, min_interval_s=2, clock=lambda: clock[0], sleep=sleeps.append)
    fallback = FakeFallback()
    proof = replay(_finding(events), events, RULES, fallback, 'gpt-4o-mini', throttle)
    assert fallback.calls == 3 and proof['sent_to_fallback'] == 3 and proof['capped'] == 37
    assert sleeps == [2, 2]
    assert Throttle(max_calls=10 ** 6).max_calls == HARD_MAX_CALLS


def test_fallback_error_counts_as_disagreement_without_leaking():
    events = _events(35, text='bonjour')
    fallback = FakeFallback(error=RuntimeError('secret-api-key'))
    proof = replay(_finding(events), events, RULES, fallback, 'gpt-4o-mini',
                   Throttle(max_calls=50, min_interval_s=0))
    assert proof['agreement_rate'] == 0 and proof['verdict'] == 'reject'
    assert proof['cost_after_month_usd'] is None
    assert 'secret-api-key' not in json.dumps(proof)


def test_cli_writes_proofs_and_exits_zero_on_reject(tmp_path, capsys):
    assert main([str(DATASET), '--out', str(tmp_path)]) == 0
    written = {p.name for p in tmp_path.glob('proof-*.json')}
    assert len(written) == 2
    out = capsys.readouterr().out
    assert 'VERDICT   PASS' in out and 'VERDICT   REJECT' in out


def test_pass_and_reject_proofs_match_the_contract(dataset):
    events, findings = dataset
    for app in ('mail-triage', 'reviews'):  # PASS et REJECT
        finding = findings[app]
        jsonschema.validate(replay(finding, events, extract_rules(finding, events)), PROOF_SCHEMA)


def test_jeu_de_test_a_une_seule_reponse_rien_n_est_prouve():
    # vu chez un testeur : tous les « true » servent à apprendre, il ne reste que des « false » à
    # vérifier ; une règle qui répond toujours « false » ferait 100 % sans rien prouver
    events = _events(40, label='false', text='idée de campagne')
    rules = {'categories': [{'key': 'false', 'regex': 'idée'}, {'key': 'true', 'regex': 'excellente'}]}
    proof = replay(_finding(events), events, rules)
    assert proof['verdict'] == 'reject'
    assert any('une seule réponse' in r for r in proof['reasons'])


def test_une_regle_qui_ne_trouve_jamais_la_reponse_minoritaire_est_refusee():
    # 38 « false » et 2 « true » : répondre toujours « false » donne 95 %, sans rien prouver
    events = _events(38, label='false', text='idée de campagne') + [
        {**e, 'event_id': f't{i}'} for i, e in enumerate(_events(2, label='true', text='idée géniale'))]
    rules = {'categories': [{'key': 'false', 'regex': 'idée'}, {'key': 'true', 'regex': 'jamaisvu'}]}
    proof = replay(_finding(events), events, rules)
    assert proof['verdict'] == 'reject'
    assert any('true' in r and 'jamais' in r for r in proof['reasons'])


def test_regles_justes_sur_chaque_reponse_passent_toujours():
    events = _events(20, label='spam', text='gagnez un iphone') + [
        {**e, 'event_id': f'h{i}'} for i, e in enumerate(_events(20, label='ham', text='réunion demain'))]
    rules = {'categories': [{'key': 'spam', 'regex': 'gagnez'}, {'key': 'ham', 'regex': 'réunion'}]}
    assert replay(_finding(events), events, rules)['verdict'] == 'pass'
