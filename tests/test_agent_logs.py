"""B1 : journaux Claude Code et Codex → événements, sur des journaux au format réel (voir tests/data/agent_logs)."""
import json
import zipfile
from pathlib import Path

import jsonschema
import pytest

from importers.agent_logs import claude_code, codex
from importers.agent_logs.__main__ import jsonl_line, lire, main
from importers.agent_logs.common import iter_files, mask_secrets
from report.audit import build_report

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "tests/data/agent_logs"
SCHEMA = json.loads((ROOT / "schemas/event.schema.json").read_text())


@pytest.fixture(scope="module")
def cc():
    return claude_code.read(list(iter_files(DATA / "claude-code")))


@pytest.fixture(scope="module")
def cx():
    return codex.read(list(iter_files(DATA / "codex")))


def by_id(events, event_id):
    return next(e for e in events if e["event_id"] == event_id)


# --- Claude Code ---

def test_une_reponse_sur_trois_lignes_est_un_seul_appel(cc):
    events, _ = cc
    first = by_id(events, "cc-msg_01")
    assert sum(e["event_id"] == "cc-msg_01" for e in events) == 1
    assert first["response"]["content"] == "Je lance le découpage."
    assert first["response"]["tool_calls"] == [
        {"id": "toolu_01", "name": "Bash", "arguments": '{"command": "modal run cut.py --run 28"}'}]
    assert first["response"]["finish_reason"] == "tool_calls" and first["response"]["finish_reason_raw"] == "tool_use"


def test_jetons_claude_code(cc):
    first = by_id(cc[0], "cc-msg_01")
    # entrée = input + écritures en cache (pas de champ dédié dans le schéma) ; lecture du cache à part
    assert first["usage"] == {"input_tokens": 20003, "output_tokens": 120, "cached_input_tokens": 0, "reasoning_tokens": 40}
    assert by_id(cc[0], "cc-msg_02")["usage"]["cached_input_tokens"] == 20003
    assert cc[1].as_dict()["jetons_ecrits_en_cache"] == 20000 + 500 + 300


def test_ce_qui_a_declenche_l_appel(cc):
    first, second = by_id(cc[0], "cc-msg_01"), by_id(cc[0], "cc-msg_02")
    assert first["request"]["messages"] == [{"role": "user", "content": "Produis les shorts du run 28 (trois formats)"}]
    assert second["request"]["messages"][0]["role"] == "tool"
    assert second["request"]["messages"][0]["tool_call_id"] == "toolu_01"
    # heure de départ = arrivée du résultat d'outil, fin = dernière ligne de la réponse
    assert (second["ts_start"], second["ts_end"], second["latency_ms"]) == (
        "2026-09-26T10:00:35.000Z", "2026-09-26T10:00:41.000Z", 6000)
    assert first["latency_ms"] == 5000


def test_la_cle_affichee_par_un_outil_est_masquee(cc):
    text = json.dumps(cc[0])
    assert "sk-ant-api03" not in text and "[secret]" in text


def test_trace_sous_agent_et_projet(cc):
    events, _ = cc
    main_calls = [e for e in events if e["trace"]["id"] == "claude-code:11111111-aaaa-4bbb-8ccc-000000000001"]
    assert [e["trace"]["step"] for e in main_calls] == [0, 1, 2]
    assert {e["trace"]["source"] for e in events} == {"header"}
    haiku = by_id(events, "cc-msg_03")
    assert haiku["app_id"] == "claude-code:shorts-factory/sous-agent" and haiku["model"] == "claude-haiku-4-5-20251001"
    assert by_id(events, "cc-msg_01")["app_id"] == "claude-code:shorts-factory"


def test_rien_n_est_compte_deux_fois(cc):
    events, report = cc
    assert sorted(e["event_id"] for e in events) == ["cc-msg_01", "cc-msg_02", "cc-msg_03", "cc-msg_04"]
    r = report.as_dict()
    assert r["ignores"] == {
        "appel recopié par une session reprise (déjà compté)": 1,
        "ligne illisible (JSON invalide ou tronqué)": 1,
        "message fabriqué par Claude Code (erreur, interruption) : pas un appel facturé": 1,
    }
    assert (r["fichiers"], r["sessions"], r["appels_lus"], r["niveau"]) == (2, 2, 4, 3)
    assert r["cout_annonce_par_claude_code_usd"] == 0.5


# --- Codex ---

def test_codex_un_appel_par_token_usage_record(cx):
    events, report = cx
    recent = [e for e in events if e["trace"]["id"] == "codex:22222222-bbbb-4ccc-8ddd-000000000001"]
    # deux token_count répétés et un cumulé n'ajoutent aucun appel
    assert [e["event_id"] for e in recent] == ["codex-resp_1", "codex-resp_2"]
    a, b = recent
    assert a["usage"] == {"input_tokens": 1000, "output_tokens": 50, "cached_input_tokens": 0, "reasoning_tokens": 20}
    assert b["usage"]["cached_input_tokens"] == 1000
    assert a["model"] == "gpt-5-codex" and a["upstream"] == "api.openai.com" and a["endpoint"] == "/v1/responses"
    assert a["app_id"] == "codex:shorts-factory"
    assert report.as_dict()["ignores"] == {}


def test_codex_contenu_decoupe_par_appel(cx):
    a = by_id(cx[0], "codex-resp_1")
    b = by_id(cx[0], "codex-resp_2")
    assert a["request"]["messages"] == [{"role": "user", "content": "Encode les trois clips"}]
    assert a["request"]["system"].startswith("Tu es Codex") and "sk-proj" not in a["request"]["system"]
    assert a["response"]["content"] == "J'encode."
    assert a["response"]["tool_calls"] == [{"id": "call_1", "name": "shell", "arguments": '{"cmd": ["ffmpeg", "-i", "a.mp4"]}'}]
    assert b["request"]["messages"] == [{"role": "tool", "content": "3 fichiers encodés", "tool_call_id": "call_1"}]
    assert b["response"]["content"] == "Terminé." and b["response"]["finish_reason"] is None
    assert (a["ts_start"], a["ts_end"]) == ("2026-09-26T12:00:01.500Z", "2026-09-26T12:00:04.200Z")


def test_codex_ancienne_version_sans_token_usage_record(cx):
    old = [e for e in cx[0] if e["trace"]["id"] == "codex:22222222-bbbb-4ccc-8ddd-000000000002"]
    assert len(old) == 1  # token_count répété : un seul appel
    assert old[0]["model"] == "o4-mini" and old[0]["usage"]["reasoning_tokens"] == 64
    assert any("token_count" in n for n in cx[1].as_dict()["limites"])


# --- contrat du connecteur ---

def test_schema_et_rapport(tmp_path):
    events, reports = lire([DATA])
    assert len(events) == 7 and set(reports) == {"claude-code", "codex"}
    for e in events:
        jsonschema.validate(e, SCHEMA)
    report = build_report(events)
    assert report["resume"]["nb_appels"] == 7
    assert {"claude-code:shorts-factory", "codex:shorts-factory"} <= {e["app_id"] for e in events}


def test_archive_zip(tmp_path):
    archive = tmp_path / "run28.zip"
    with zipfile.ZipFile(archive, "w") as z:
        for path in DATA.rglob("*.jsonl"):
            z.write(path, path.relative_to(DATA))
        z.writestr("__MACOSX/._x.jsonl", "binaire")
    events, _ = lire([archive])
    assert len(events) == 7


def test_ligne_ecrite_relisible_meme_coupee_par_splitlines():
    line = jsonl_line({"t": "a b c"})
    assert len(line.splitlines()) == 1 and json.loads(line) == {"t": "a b c"}


@pytest.mark.parametrize("secret", [
    "sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUVWXYZ012345",
    "sk-proj-ABCDEFGHIJKLMNOPQRSTUVWXYZ012345",
    "AIzaSyABCDEFGHIJKLMNOPQRSTUVWXYZ0123456",
    "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789",
    "AKIAABCDEFGHIJKLMNOP",
    "Bearer eyJhbGciOiJIUzI1NiJ9.abcdefghijklmnop",
])
def test_cles_masquees(secret):
    assert mask_secrets(f"x {secret} y") == "x [secret] y"


def test_texte_ordinaire_intact():
    text = "sk-learn, task-1234, le modèle gpt-4o et claude-sonnet-4-5"
    assert mask_secrets(text) == text


def test_commande(tmp_path, capsys):
    assert main([str(DATA), "--out", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "claude-code : 2 fichier(s), 2 session(s), 4 appel(s) lus, 3 ignoré(s), niveau 3" in out
    assert "codex : 2 fichier(s), 2 session(s), 3 appel(s) lus, 0 ignoré(s), niveau 3" in out
    assert len((tmp_path / "events.jsonl").read_text().split("\n")) == 8
    assert json.loads((tmp_path / "comprehension.json").read_text())["codex"]["appels_lus"] == 3
    assert main([str(tmp_path / "absent")]) == 1
    empty = tmp_path / "vide"
    empty.mkdir()
    (empty / "autre.jsonl").write_text('{"x": 1}\n')
    assert main([str(empty)]) == 1
