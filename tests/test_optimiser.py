"""make optimiser : de la base capturée au diff de micro-PR, en une commande."""
import json
import subprocess
from pathlib import Path

from gateway.store import EventStore
from scripts.optimiser import main

ROOT = Path(__file__).resolve().parents[1]
EVENTS = [json.loads(line) for line in (ROOT / "fixtures/dataset/v1/events.jsonl").read_text().splitlines()]


def _db(tmp_path):
    db = tmp_path / "events.db"
    store = EventStore(str(db))
    for event in EVENTS:
        store.put(event)
    store.close()
    return db


def _repo(tmp_path):
    repo = tmp_path / "client"
    repo.mkdir()
    (repo / "app.py").write_text('client = OpenAI(default_headers={"x-deadweight-app": "mail-triage"})\n')
    for cmd in (["git", "init", "-q"], ["git", "add", "-A"],
                ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"]):
        subprocess.run(cmd, cwd=repo, check=True)
    return repo


def test_one_command_goes_from_capture_to_micro_pr_diffs(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-ne-doit-pas-servir")  # sans --banc, jamais transmise
    out, repo = tmp_path / "res", _repo(tmp_path)
    assert main(["--db", str(_db(tmp_path)), "--out", str(out), "--repo", str(repo)]) == 0
    assert (out / "audit.html").is_file()
    assert (out / "propositions" / "propositions.html").is_file()
    diffs = list((out / "propositions").glob("*-regles-mail-triage.diff"))
    assert diffs and "deadweight/preuves/proof-mail-triage.json" in diffs[0].read_text()
    assert subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True,
                          text=True).stdout == ""  # sans --pr, le dépôt du client n'est pas touché
    assert "relancez avec PR=oui" in capsys.readouterr().out


def test_clear_errors_before_doing_anything(tmp_path, capsys):
    assert main(["--db", str(tmp_path / "absente.db")]) == 1
    assert main(["--db", str(_db(tmp_path)), "--pr"]) == 1
    assert main(["--db", str(_db(tmp_path)), "--repo", str(tmp_path)]) == 1
    err = capsys.readouterr().err
    assert "Base absente" in err and "--pr demande un dépôt" in err and "n'est pas un dépôt git" in err
