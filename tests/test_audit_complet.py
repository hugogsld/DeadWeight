"""make audit-complet : détection de la source, audit, micro-PR, Slack. Webhook simulé : aucun appel réseau."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

import optimize.__main__ as optimize_cli
from gateway.store import EventStore
from optimize.send import SECTION_MAX, payload, send
from scripts import audit_complet
from scripts.audit_complet import detect, notify, run

ROOT = Path(__file__).resolve().parents[1]
EVENTS = ROOT / "fixtures/dataset/v1/events.jsonl"
N8N = ROOT / "tests/data/n8n/support"
AGENT_LOGS = ROOT / "tests/data/agent_logs"
PR_URL = "https://github.com/client/app/pull/7"


@pytest.fixture(autouse=True)
def no_keys(monkeypatch):
    for key in ("DW_LLM_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY", "SLACK_WEBHOOK_URL"):
        monkeypatch.delenv(key, raising=False)


class Sender:
    def __init__(self, fail=None):
        self.calls, self.fail = [], fail

    def __call__(self, url, data):
        if self.fail:
            raise self.fail
        self.calls.append((url, data))


# --- détection ---

def test_un_fichier_d_evenements_est_pris_tel_quel(tmp_path):
    assert detect(str(EVENTS), tmp_path) == EVENTS


def test_dossier_n8n_deja_telecharge_est_converti(tmp_path):
    folder = shutil.copytree(N8N, tmp_path / "wf")
    out = detect(str(folder), tmp_path / "out")
    assert out == folder / "events.jsonl" and out.read_text().strip()


def test_n8n_id_enchaine_check_fetch_convert(tmp_path, monkeypatch):
    seen = []

    def fake_n8n(argv):
        seen.append(argv[0])
        if argv[0] == "fetch":
            shutil.copytree(N8N, Path(argv[argv.index("--out") + 1]) / "42")
        return 0

    monkeypatch.setattr(audit_complet, "n8n_main", fake_n8n)
    out = detect("n8n:42", tmp_path)
    assert seen == ["check", "fetch"] and out == tmp_path / "n8n/42/events.jsonl" and out.is_file()


def test_n8n_injoignable_arrete_la_chaine(tmp_path, monkeypatch):
    monkeypatch.setattr(audit_complet, "n8n_main", lambda argv: 1)
    assert detect("n8n:42", tmp_path) is None


def test_base_de_la_passerelle_est_exportee(tmp_path, monkeypatch):
    db = tmp_path / "events.db"
    store = EventStore(str(db))
    lines = [json.loads(line) for line in EVENTS.read_text().splitlines() if line.strip()]
    for e in lines:
        store.put(e)
    store.close()
    monkeypatch.setenv("GATEWAY_DB", str(db))
    out = detect("gateway", tmp_path / "out")
    assert len(out.read_text().splitlines()) == len(lines)
    assert detect(str(db), tmp_path / "out2").is_file()


def test_base_absente(tmp_path, capsys):
    assert detect(str(tmp_path / "rien.db"), tmp_path) is None
    assert "make dev" in capsys.readouterr().err


def test_journaux_claude_code_et_codex(tmp_path):
    out = detect(str(AGENT_LOGS), tmp_path)
    events = [json.loads(line) for line in out.read_text().splitlines()]
    assert events and {e["app_id"].split(":")[0] for e in events} >= {"claude-code", "codex"}


def test_source_inconnue(tmp_path, capsys):
    (tmp_path / "vide").mkdir()
    assert detect(str(tmp_path / "vide"), tmp_path / "out") is None
    assert "ni un workflow n8n" in capsys.readouterr().err


# --- Slack ---

def test_payload_un_bouton_lien_par_pr_jamais_de_fusion():
    data = payload("*titre*", [{"app_id": "mail-triage", "changement": "règles", "url": PR_URL}])
    assert data["text"] == "*titre*" and data["blocks"][0]["text"]["text"] == "*titre*"
    button = data["blocks"][1]["elements"][0]
    assert button["type"] == "button" and button["url"] == PR_URL and "mail-triage" in button["text"]["text"]
    assert "value" not in button                      # un lien : Slack ne rappelle aucun serveur


def test_payload_sans_pr_et_texte_long():
    data = payload("x" * (SECTION_MAX + 10))
    assert len(data["blocks"]) == 1 and len(data["blocks"][0]["text"]["text"]) == SECTION_MAX


class Response:
    def __init__(self, status, body):
        self.status, self.body = status, body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_send_poste_du_json_au_webhook():
    requests = []
    send("https://hooks.slack.test/x", {"text": "a"}, opener=lambda r, timeout: requests.append(r) or Response(200, b"ok"))
    assert requests[0].full_url == "https://hooks.slack.test/x" and json.loads(requests[0].data) == {"text": "a"}
    assert requests[0].get_header("Content-type") == "application/json"


def test_send_refus_slack_lisible():
    with pytest.raises(RuntimeError, match="invalid_payload"):
        send("https://hooks.slack.test/x", {}, opener=lambda r, timeout: Response(200, b"invalid_payload"))


def _optim(tmp_path, verdicts, prs=()):
    (tmp_path / "slack.md").write_text("*Deadweight*\n")
    (tmp_path / "propositions.json").write_text(json.dumps([{"verdict": v} for v in verdicts]))
    (tmp_path / "prs.json").write_text(json.dumps(list(prs)))
    return tmp_path


def test_sans_webhook_le_message_reste_dans_le_fichier(tmp_path, capsys):
    sender = Sender()
    assert notify(_optim(tmp_path, ["pass"]), webhook=None, sender=sender) == "fichier"
    assert not sender.calls and "NON envoyé" in capsys.readouterr().out


def test_slack_reserve_aux_gains_prouves(tmp_path):
    sender = Sender()
    folder = _optim(tmp_path, ["reject", "non_teste"])
    assert notify(folder, webhook="https://hooks.slack.test/x", sender=sender) == "rien" and not sender.calls
    assert notify(folder, demo=True, webhook="https://hooks.slack.test/x", sender=sender) == "envoye"


def test_envoi_avec_boutons_pr(tmp_path):
    sender = Sender()
    folder = _optim(tmp_path, ["pass"], [{"app_id": "mail-triage", "changement": "règles", "url": PR_URL}])
    assert notify(folder, webhook="https://hooks.slack.test/x", sender=sender) == "envoye"
    url, data = sender.calls[0]
    assert url == "https://hooks.slack.test/x" and data["blocks"][1]["elements"][0]["url"] == PR_URL


def test_echec_d_envoi_signale(tmp_path, capsys):
    sender = Sender(fail=OSError("réseau coupé"))
    assert notify(_optim(tmp_path, ["pass"]), webhook="https://hooks.slack.test/x", sender=sender) == "erreur"
    assert "réseau coupé" in capsys.readouterr().err


# --- chaîne complète ---

def _repo(tmp_path):
    repo = tmp_path / "client"
    repo.mkdir()
    (repo / "app.py").write_text(
        'client = OpenAI(default_headers={"x-deadweight-app": "mail-triage"})\n'
        'r = client.chat.completions.create(model="gpt-4o", messages=m)\n')
    for cmd in (["git", "init", "-q"], ["git", "add", "-A"], ["git", "-c", "user.email=t@t", "-c", "user.name=t",
                                                               "commit", "-qm", "init"]):
        subprocess.run(cmd, cwd=repo, check=True)
    return repo


def test_chaine_complete_audit_pr_slack(tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(optimize_cli, "open_pr", lambda repo, p, branch: opened.append(branch) or PR_URL)
    sender = Sender()
    out = tmp_path / "out"
    assert run(str(EVENTS), out, repo=_repo(tmp_path), webhook="https://hooks.slack.test/x", sender=sender) == 0
    assert (out / "audit.html").is_file() and (out / "optim/slack.md").is_file() and opened
    prs = json.loads((out / "optim/prs.json").read_text())
    assert [pr["url"] for pr in prs] == [PR_URL] * len(opened)
    _, data = sender.calls[0]
    assert data["text"] == (out / "optim/slack.md").read_text().strip()
    assert [b["url"] for b in data["blocks"][1]["elements"]] == [PR_URL] * len(opened)


def test_chaine_sans_repo_ni_webhook(tmp_path):
    out = tmp_path / "out"
    assert run(str(EVENTS), out, webhook=None) == 0
    assert json.loads((out / "optim/prs.json").read_text()) == []


def test_source_invalide_code_retour(tmp_path):
    assert run(str(tmp_path / "absent.db"), tmp_path / "out") == 1
