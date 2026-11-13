"""B1 : journaux Claude Code et Codex → événements, sur des journaux au format réel (voir tests/data/agent_logs)."""
import json
import zipfile
from pathlib import Path

import jsonschema
import pytest

from connectors.agent_logs import claude_code, codex
from connectors.agent_logs.__main__ import jsonl_line, lire, main
from connectors.agent_logs.common import iter_files, mask_secrets
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
    assert (r["fichiers"], r["sessions"], r["appels_lus"], r["avec_jetons"], r["avec_contenu"]) == (2, 2, 4, 4, 4)
    assert r["niveaux"] == [1, 2, 3]
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
    assert a["model"] == "gpt-5-codex" and a["upstream"] is None and a["endpoint"] == "/v1/responses"
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
    assert main([str(DATA), "-o", str(tmp_path / "events.jsonl")]) == 0
    out = capsys.readouterr().out
    assert "claude-code : 2 fichier(s), 2 session(s), 4 appel(s) lus, 3 ignoré(s), niveaux [1, 2, 3]" in out
    assert "codex : 2 fichier(s), 2 session(s), 3 appel(s) lus, 0 ignoré(s), niveaux [1, 2, 3]" in out
    assert len((tmp_path / "events.jsonl").read_text().split("\n")) == 8
    assert json.loads((tmp_path / "comprehension.json").read_text())["codex"]["appels_lus"] == 3
    assert main([str(tmp_path / "absent"), "-o", str(tmp_path / "x.jsonl")]) == 1
    empty = tmp_path / "vide"
    empty.mkdir()
    (empty / "autre.jsonl").write_text('{"x": 1}\n')
    assert main([str(empty), "-o", str(tmp_path / "x.jsonl")]) == 1


def test_commande_expose_le_mode_de_facturation_par_outil(tmp_path, capsys):
    """D2.6 (Problème 1) : jamais deviné — ici forcé par --billing, faute de vraie config Claude/Codex
    dans l'environnement de test."""
    assert main([str(DATA), "-o", str(tmp_path / "events.jsonl"), "--billing", "abonnement"]) == 0
    out = capsys.readouterr().out
    assert "facturation : abonnement (--billing (forcé))" in out
    comprehension = json.loads((tmp_path / "comprehension.json").read_text())
    assert comprehension["claude-code"]["billing"] == {"mode": "abonnement", "source": "--billing (forcé)"}
    assert comprehension["codex"]["billing"] == {"mode": "abonnement", "source": "--billing (forcé)"}


def test_commande_detecte_la_facturation_sans_override(tmp_path, monkeypatch):
    """Sans --billing, la détection lit la configuration de l'outil : ici un HOME de test (jamais les
    vrais fichiers de la machine), abonnement Claude Code, rien pour Codex."""
    home = tmp_path / "home"
    home.mkdir()
    (home / ".claude.json").write_text(json.dumps({"oauthAccount": {"billingType": "stripe_subscription"}}))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert main([str(DATA), "-o", str(tmp_path / "events.jsonl")]) == 0
    comprehension = json.loads((tmp_path / "comprehension.json").read_text())
    assert comprehension["claude-code"]["billing"]["mode"] == "abonnement"
    assert comprehension["codex"]["billing"] == {"mode": "inconnu", "source": None}


def _projets(tmp_path):
    root = tmp_path / "projects"
    src = next((DATA / "claude-code").rglob("*.jsonl"))
    for name in ("-Users-moi-client-a", "-Users-moi-perso-b"):
        (root / name).mkdir(parents=True)
        (root / name / "s.jsonl").write_text(src.read_text())
    return root


def test_dossier_de_plusieurs_projets_demande_un_choix(tmp_path, capsys):
    root = _projets(tmp_path)
    assert main([str(root), "-o", str(tmp_path / "e.jsonl")]) == 2
    err = capsys.readouterr().err
    assert "2 projets" in err and "-Users-moi-client-a (1 session(s))" in err and "--project" in err
    assert not (tmp_path / "e.jsonl").exists()


def test_filtre_par_projet_et_tous_les_projets(tmp_path, capsys):
    root = _projets(tmp_path)
    assert main([str(root), "--project", "client-a", "-o", str(tmp_path / "a.jsonl")]) == 0
    assert "1 fichier(s)" in capsys.readouterr().out
    assert main([str(root), "--all-projects", "-o", str(tmp_path / "all.jsonl")]) == 0
    assert "2 fichier(s)" in capsys.readouterr().out
    assert main([str(root), "--project", "inconnu", "-o", str(tmp_path / "x.jsonl")]) == 1
    assert "pour le projet « inconnu »" in capsys.readouterr().err


def test_port_deja_pris_message_clair_sans_trace(monkeypatch, tmp_path):
    import socket

    from gateway import proxy

    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        monkeypatch.setenv("GATEWAY_HOST", "127.0.0.1")
        monkeypatch.setenv("GATEWAY_PORT", str(busy.getsockname()[1]))
        monkeypatch.chdir(tmp_path)  # la base par défaut (out/events.db) est créée ici, pas dans le dépôt
        with pytest.raises(SystemExit) as exc:
            proxy.main()
    assert "déjà utilisé" in str(exc.value) and "GATEWAY_PORT" in str(exc.value)


def _rollout_recent(path, with_usage=True):
    """Journal synthétique à la forme observée sur un vrai Codex 0.16x (rien de réel : textes inventés) :
    outils personnalisés (custom_tool_call), raisonnement, world_state, compacted, additional_tools, item_completed."""
    t = "2026-11-12T10:00:%02d.000Z"
    rows = [
        {"timestamp": t % 0, "type": "session_meta", "payload": {"id": "s-1", "cwd": "/Users/x/projet-demo",
                                                                   "model_provider": "openai", "cli_version": "0.164.0-alpha.1"}},
        {"timestamp": t % 1, "type": "turn_context", "payload": {"model": "gpt-demo", "cwd": "/Users/x/projet-demo"}},
        {"timestamp": t % 1, "type": "event_msg", "payload": {"type": "task_started"}},
        {"timestamp": t % 1, "type": "world_state", "payload": {"anything": 1}},
        {"timestamp": t % 1, "type": "response_item", "payload": {"type": "additional_tools", "tools": []}},
        {"timestamp": t % 2, "type": "response_item", "payload": {"type": "message", "role": "user",
                                                                   "content": [{"type": "input_text", "text": "liste les fichiers"}]}},
        {"timestamp": t % 3, "type": "response_item", "payload": {"type": "reasoning", "summary": [], "encrypted_content": "x"}},
        {"timestamp": t % 4, "type": "response_item", "payload": {"type": "custom_tool_call", "call_id": "c1",
                                                                   "name": "exec", "input": "ls -la"}},
        {"timestamp": t % 4, "type": "event_msg", "payload": {"type": "item_completed"}},
        {"timestamp": t % 5, "type": "event_msg", "payload": {"type": "token_count", "info": {
            "total_token_usage": {"input_tokens": 100}, "last_token_usage": {"input_tokens": 100}}}},
    ]
    if with_usage:
        rows.append({"timestamp": t % 5, "type": "token_usage_record", "payload": {
            "session_id": "s-1", "thread_id": "s-1", "response_id": "resp_1",
            "usage": {"input_tokens": 100, "cached_input_tokens": 80, "output_tokens": 12, "reasoning_output_tokens": 9}}})
    rows += [
        {"timestamp": t % 6, "type": "response_item", "payload": {"type": "custom_tool_call_output", "call_id": "c1",
                                                                   "output": "a.txt b.txt"}},
        {"timestamp": t % 7, "type": "response_item", "payload": {"type": "message", "role": "assistant",
                                                                   "content": [{"type": "output_text", "text": "deux fichiers"}]}},
        {"timestamp": t % 8, "type": "compacted", "payload": {"message": "résumé"}},
    ]
    if with_usage:
        rows.append({"timestamp": t % 8, "type": "token_usage_record", "payload": {
            "session_id": "s-1", "thread_id": "s-1", "response_id": "resp_2",
            "usage": {"input_tokens": 140, "cached_input_tokens": 100, "output_tokens": 5, "reasoning_output_tokens": 0}}})
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def test_codex_recent_shape_tool_calls_and_usage(tmp_path):
    f = tmp_path / "rollout-2026-11-12T10-00-00-s-1.jsonl"
    _rollout_recent(f)
    events, report = codex.read(list(iter_files(f)))
    assert [e["event_id"] for e in events] == ["codex-resp_1", "codex-resp_2"]
    first, second = events
    jsonschema.validate(first, SCHEMA)
    assert first["response"]["tool_calls"] == [{"id": "c1", "name": "exec", "arguments": "ls -la"}]
    assert first["response"]["finish_reason"] == "tool_calls"
    assert first["usage"] == {"input_tokens": 100, "output_tokens": 12, "cached_input_tokens": 80, "reasoning_tokens": 9}
    assert second["request"]["messages"] == [{"role": "tool", "content": "a.txt b.txt", "tool_call_id": "c1"}]
    assert second["response"]["content"] == "deux fichiers" and second["app_id"] == "codex:projet-demo"
    assert not any("sans token_usage_record" in n for n in report.notes)


def test_codex_session_without_usage_lines_is_not_a_false_alarm(tmp_path):
    """Une session courte sans aucune ligne de jetons ne doit pas annoncer « version sans token_usage_record »."""
    f = tmp_path / "rollout-2026-11-12T10-00-00-s-2.jsonl"
    f.write_text("".join(json.dumps(r) + "\n" for r in [
        {"timestamp": "2026-11-12T10:00:00.000Z", "type": "session_meta", "payload": {"id": "s-2"}},
        {"timestamp": "2026-11-12T10:00:01.000Z", "type": "event_msg", "payload": {"type": "task_started"}}]))
    events, report = codex.read(list(iter_files(f)))
    assert events == [] and not any("token_usage_record" in n for n in report.notes)


def _claude_log(with_request=True):
    """Journal Claude Code synthétique (textes inventés) : une entrée api-request précède chaque réponse."""
    def line(**kw):
        return {"sessionId": "s1", "cwd": "/Users/x/demo", "version": "9.9.9", **kw}
    rows = [
        line(type="api-request-shape", shapeHash="h1", timestamp="2026-11-12T10:00:00.000Z",
             shape={"system": [{"type": "text", "text": "Tu es un assistant de test."},
                               {"type": "text", "text": "Réponds en français."}],
                    "tools": [{"name": "Bash", "description": "Lance une commande",
                               "input_schema": {"type": "object"}, "eager_input_streaming": True}]}),
        line(type="user", uuid="u1", parentUuid=None, timestamp="2026-11-12T10:00:01.000Z",
             message={"role": "user", "content": "bonjour"}),
    ]
    if with_request:
        rows.append(line(type="api-request", id="r1", shapeHash="h1", timestamp="2026-11-12T10:00:01.500Z",
                         params={"model": "claude-demo", "max_tokens": 32000, "thinking": {"type": "adaptive"}}))
    rows += [
        line(type="assistant", uuid="a1", parentUuid="u1", timestamp="2026-11-12T10:00:03.000Z", requestId="req_1",
             message={"id": "msg_1", "model": "claude-demo", "role": "assistant", "stop_reason": "end_turn",
                      "content": [{"type": "text", "text": "salut"}],
                      "usage": {"input_tokens": 10, "output_tokens": 4}}),
        line(type="user", uuid="u2", parentUuid="a1", timestamp="2026-11-12T10:00:04.000Z",
             message={"role": "user", "content": "merci"}),
        line(type="assistant", uuid="a2", parentUuid="u2", timestamp="2026-11-12T10:00:06.000Z", requestId="req_2",
             message={"id": "msg_2", "model": "claude-demo", "role": "assistant", "stop_reason": "end_turn",
                      "content": [{"type": "text", "text": "de rien"}],
                      "usage": {"input_tokens": 12, "output_tokens": 3}}),
    ]
    return [json.dumps(r) for r in rows]


def test_claude_code_request_params_system_and_tools_when_logged():
    events, report = claude_code.read([("s.jsonl", _claude_log())])
    first, second = events
    jsonschema.validate(first, SCHEMA)
    assert first["request"]["params"]["max_tokens"] == 32000
    assert first["request"]["system"] == "Tu es un assistant de test.\n\nRéponds en français."
    assert first["request"]["tools"] == [{"name": "Bash", "description": "Lance une commande",
                                          "parameters": {"type": "object"}}]
    # la 2e réponse n'a pas sa propre entrée api-request : rien n'est reporté de la 1re, rien n'est inventé
    assert second["request"]["params"]["max_tokens"] is None and second["request"]["system"] is None
    assert second["request"]["tools"] == []
    assert report.extra["appels_avec_requete_journalisee"] == 1


def test_claude_code_unknown_is_null_not_a_default():
    [first, second], _ = claude_code.read([("s.jsonl", _claude_log(with_request=False))])
    for e in (first, second):
        jsonschema.validate(e, SCHEMA)
        assert e["upstream"] is None  # jamais api.anthropic.com par défaut
        assert e["request"]["params"]["stream"] is None and e["request"]["params"]["max_tokens"] is None
        assert e["request"]["system"] is None and e["request"]["tools"] == []


def test_codex_unknown_upstream_and_stream_are_null(tmp_path):
    f = tmp_path / "rollout-2026-11-12T10-00-00-s-1.jsonl"
    _rollout_recent(f)
    [first, _], _ = codex.read(list(iter_files(f)))
    assert first["upstream"] is None and first["request"]["params"]["stream"] is None
    assert first["request"]["params"]["max_tokens"] is None


def test_batch_rule_does_not_treat_unknown_stream_as_batchable():
    from rules.batch_eligible import detect

    [first, _], _ = claude_code.read([("s.jsonl", _claude_log(with_request=False))])
    assert detect([first]) == []
