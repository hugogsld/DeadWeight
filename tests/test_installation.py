"""D4.2 : audit en une commande et démonstration locale isolée."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys

from gateway.store import EventStore, count
from scripts.audit import audit
from scripts.demo import run_demo

ROOT = Path(__file__).resolve().parents[1]


def test_audit_missing_db_is_actionable_without_creating_it(tmp_path, capsys):
    db = tmp_path / 'missing.db'
    assert audit(db, tmp_path / 'audit.html') == 1
    message = capsys.readouterr().err
    assert 'make dev' in message and 'base_url' in message and 'make audit' in message
    assert 'Traceback' not in message and not db.exists()


def test_audit_empty_db_preserves_previous_report(tmp_path, capsys):
    db, report = tmp_path / 'events.db', tmp_path / 'audit.html'
    EventStore(str(db)).close()
    report.write_text('ancien rapport')
    assert audit(db, report) == 1
    assert 'Aucun appel' in capsys.readouterr().err
    assert report.read_text() == 'ancien rapport'


def test_audit_corrupt_db_has_no_traceback(tmp_path, capsys):
    db = tmp_path / 'events.db'
    db.write_text('not sqlite')
    assert audit(db, tmp_path / 'audit.html') == 1
    message = capsys.readouterr().err
    assert 'Traceback' not in message and 'GATEWAY_DB' in message


def test_audit_exports_real_store_and_renders_report(tmp_path, capsys):
    event = json.loads((ROOT / 'fixtures/events.jsonl').read_text().splitlines()[0])
    db = tmp_path / 'data with spaces' / 'events.db'
    store = EventStore(str(db))
    store.put(event)
    store.close()
    report = tmp_path / 'report with spaces' / 'audit.html'
    assert audit(db, report) == 0
    assert 'Audit des appels' in report.read_text()
    assert str(report) in capsys.readouterr().out
    assert count(str(db)) == 1
    assert not list(tmp_path.rglob('*.jsonl'))


def test_export_failure_does_not_publish_partial_report(tmp_path, monkeypatch, capsys):
    db, report = tmp_path / 'events.db', tmp_path / 'audit.html'
    db.touch()
    report.write_text('ancien')
    monkeypatch.setattr('scripts.audit.subprocess.run', lambda *a, **k: subprocess.CompletedProcess(a, 1))
    assert audit(db, report) == 1
    assert report.read_text() == 'ancien'
    assert 'Traceback' not in capsys.readouterr().err


def test_cli_uses_configured_database_without_traceback(tmp_path):
    env = dict(os.environ, GATEWAY_DB=str(tmp_path / 'missing.db'))
    result = subprocess.run([sys.executable, '-m', 'scripts.audit'], cwd=ROOT, env=env,
                            capture_output=True, text=True)
    assert result.returncode == 1
    assert 'make dev' in result.stderr and 'Traceback' not in result.stderr


def test_demo_captures_traffic_and_creates_report_without_client_data(tmp_path, monkeypatch):
    production = tmp_path / 'production.db'
    production.write_text('ne pas toucher')
    monkeypatch.setenv('GATEWAY_DB', str(production))
    monkeypatch.setenv('GATEWAY_OPENAI_UPSTREAM', 'https://must-not-be-used.invalid')
    monkeypatch.setenv('OPENAI_API_KEY', 'must-not-be-used')
    report = asyncio.run(run_demo(tmp_path))
    assert report.is_file() and 'Audit des appels' in report.read_text()
    assert count(str(report.parent / 'events.db')) == 36
    assert production.read_text() == 'ne pas toucher'
    assert 'must-not-be-used' not in report.read_text()
    second = asyncio.run(run_demo(tmp_path))
    assert second != report


def test_make_audit_loads_same_configuration_as_dev(tmp_path):
    event = json.loads((ROOT / 'fixtures/events.jsonl').read_text().splitlines()[0])
    db, report = tmp_path / 'custom.db', tmp_path / 'rapport personnalisé.html'
    store = EventStore(str(db))
    store.put(event)
    store.close()
    (tmp_path / '.env.local').write_text(f'GATEWAY_DB="{db}"\n')
    env = dict(os.environ, PYTHONPATH=str(ROOT), GATEWAY_DB=str(tmp_path / 'wrong.db'))
    result = subprocess.run([
        'make', '-f', str(ROOT / 'Makefile'), '-o', str(Path(sys.executable).parent / '.installed'),
        f'BIN={Path(sys.executable).parent}', f'AUDIT_OUT={report}', 'audit',
    ], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert report.is_file()
