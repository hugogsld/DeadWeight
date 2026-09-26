"""CLI `python -m bench run` : dry-run, execution reelle contre des faux serveurs
locaux, plafond d'appels, et jamais de fuite de cle dans les sorties."""
import json
from pathlib import Path

import pytest

from bench.__main__ import main
from tests.bench_servers import FakeCandidateServer

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / 'fixtures/dataset/v1/events.jsonl'


@pytest.fixture
def echo_server():
    server = FakeCandidateServer(behavior='echo')
    yield server
    server.stop()


def _write_events(path, n=40):
    """Jeu synthetique ou le message utilisateur EST le label : un candidat qui
    echo est alors, par construction, un candidat qui repond juste."""
    labels = ('spam', 'facture')
    lines = []
    for i in range(n):
        label = labels[i % 2]
        event = {
            'event_id': f'e{i}', 'app_id': 'demo-app', 'model': 'demo-model', 'error': None,
            'usage': {'input_tokens': 60, 'output_tokens': 2},
            'request': {'system': 'Classe.', 'messages': [{'role': 'user', 'content': label}]},
            'response': {'content': label},
        }
        lines.append(json.dumps(event))
    path.write_text('\n'.join(lines))
    return path


@pytest.fixture
def candidates_file(tmp_path, echo_server, monkeypatch):
    catalog = {'version': 1, 'candidates': [
        {'id': 'fixture-echo', 'kind': 'openai', 'model': 'gpt-5-nano',
         'base_url_env': 'DW_BENCH_TEST_UNSET_BASE', 'default_base_url': echo_server.base_url,
         'api_key_env': 'DW_BENCH_TEST_UNSET_KEY', 'size_class': 'small', 'origin': 'US',
         'note': 'fixture de test'},
        {'id': 'fixture-local', 'kind': 'ollama', 'model': 'llama3.3:70b',
         'base_url_env': 'DW_BENCH_TEST_UNSET_BASE', 'default_base_url': echo_server.base_url,
         'api_key_env': None, 'size_class': 'local', 'origin': 'US', 'note': 'fixture de test'},
    ]}
    path = tmp_path / 'candidates.json'
    path.write_text(json.dumps(catalog))
    monkeypatch.setattr('bench.catalog.CANDIDATES_PATH', path)
    monkeypatch.delenv('DW_BENCH_TEST_UNSET_KEY', raising=False)
    return path


def test_dry_run_makes_no_call_and_prints_estimate(candidates_file, capsys):
    assert main(['run', str(DATASET), '--app', 'mail-triage', '--model', 'gpt-4o', '--dry-run']) == 0
    out = capsys.readouterr().out
    assert 'aucun appel effectue' in out
    assert 'fixture-local' in out and '0.0000 $' in out


def test_run_writes_report_with_pass_verdict_for_agreeing_candidate(candidates_file, tmp_path, capsys):
    events_path = _write_events(tmp_path / 'events.jsonl')
    out_path = tmp_path / 'report.json'
    code = main(['run', str(events_path), '--app', 'demo-app', '--model', 'demo-model',
                '--max-cases', '40', '--out', str(out_path)])
    assert code == 0
    report = json.loads(out_path.read_text())
    assert report['task_type'] == 'classification'
    by_id = {c['candidate_id']: c for c in report['candidates']}
    assert by_id['fixture-echo']['verdict'] == 'pass'
    assert by_id['fixture-local']['cost_per_1000_calls_usd'] == 0.0
    captured = capsys.readouterr().out
    assert 'DW_BENCH_TEST_UNSET_KEY' not in captured


def test_max_calls_caps_real_calls(candidates_file, tmp_path):
    events_path = _write_events(tmp_path / 'events.jsonl')
    out_path = tmp_path / 'report.json'
    main(['run', str(events_path), '--app', 'demo-app', '--model', 'demo-model',
         '--max-cases', '40', '--max-calls', '5', '--min-interval', '0', '--out', str(out_path)])
    report = json.loads(out_path.read_text())
    by_id = {c['candidate_id']: c for c in report['candidates']}
    assert by_id['fixture-echo']['n_calls'] == 5


def test_unknown_group_exits_with_error(candidates_file, capsys):
    code = main(['run', str(DATASET), '--app', 'inconnu', '--model', 'inconnu'])
    assert code == 1
    assert 'aucun cas exploitable' in capsys.readouterr().err
