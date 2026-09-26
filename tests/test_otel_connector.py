"""B2 : connecteur OpenTelemetry. Trace réelle (SDK officiel, scripts/gen_otel_fixture.py) et spans
construits d'après la spécification GenAI pour les formes que cette version du SDK n'émet pas."""
import base64
import json
from pathlib import Path

import jsonschema

from connectors.otel import main, read
from report.audit import build_report

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schemas/event.schema.json").read_text())
REAL = json.loads((ROOT / "fixtures/otel/sdk-openai-v2.json").read_text())


def attr(key, value):
    if isinstance(value, bool):
        return {"key": key, "value": {"boolValue": value}}
    if isinstance(value, int):
        return {"key": key, "value": {"intValue": str(value)}}
    if isinstance(value, list):
        return {"key": key, "value": {"arrayValue": {"values": [{"stringValue": v} for v in value]}}}
    return {"key": key, "value": {"stringValue": value}}


def export(*spans, service="support"):
    return {"resourceSpans": [{"resource": {"attributes": [attr("service.name", service)]},
                               "scopeSpans": [{"spans": list(spans)}]}]}


def span(attrs, span_id="00f067aa0ba902b7", trace_id="4bf92f3577b34da6a3ce929d0e0e4736", start=0, events=()):
    return {"traceId": trace_id, "spanId": span_id, "name": "chat", "startTimeUnixNano": str(1790000000000000000 + start),
            "endTimeUnixNano": str(1790000000000000000 + start + 850_000_000), "status": {},
            "attributes": [attr(k, v) for k, v in attrs.items()], "events": list(events)}


def test_real_sdk_trace_gives_usage_and_structure():
    events, report = read(REAL)
    assert report["spans"] == 12 and report["appels_lus"] == 8 and report["niveaux"] == [1, 3]
    assert report["ignores"] == {"span sans appel de modèle (workflow, outil, agent)": 4}
    for e in events:
        jsonschema.validate(e, SCHEMA)
    assert {e["app_id"] for e in events} == {"tri-des-mails"}  # service.name
    pairs = [e for e in events if e["model"] in ("gpt-4o", "gpt-4o-mini") and e["http_status"] == 200]
    by_trace = {}
    for e in pairs:
        by_trace.setdefault(e["trace"]["id"], []).append((e["trace"]["step"], e["model"]))
    assert sorted(by_trace.values()) == [[(0, "gpt-4o"), (1, "gpt-4o-mini")]] * 3  # un mail = une trace de 2
    failed = [e for e in events if e["error"]]
    assert len(failed) == 1 and failed[0]["http_status"] == 502 and failed[0]["usage"]["input_tokens"] is None
    assert "NE-DOIT-JAMAIS-SORTIR" not in json.dumps(events)


def test_content_following_the_current_spec_gives_level_2():
    s = span({"gen_ai.operation.name": "chat", "gen_ai.provider.name": "anthropic",
              "gen_ai.request.model": "claude-sonnet-4-5", "gen_ai.response.model": "claude-sonnet-4-5-20250929",
              "gen_ai.usage.input_tokens": 1200, "gen_ai.usage.output_tokens": 40,
              "gen_ai.usage.cache_read.input_tokens": 1000, "gen_ai.usage.reasoning.output_tokens": 30,
              "gen_ai.response.finish_reasons": ["end_turn"],
              "gen_ai.system_instructions": json.dumps([{"type": "text", "content": "Classe le ticket."}]),
              "gen_ai.input.messages": json.dumps([{"role": "user", "parts": [{"type": "text", "content": "Mot de passe perdu"}]}]),
              "gen_ai.output.messages": json.dumps([{"role": "assistant", "parts": [{"type": "text", "content": "compte"}],
                                                     "finish_reason": "stop"}]),
              "gen_ai.tool.definitions": json.dumps([{"type": "function", "name": "reset", "description": "Réinitialise"}])})
    [e], report = read(export(s))
    jsonschema.validate(e, SCHEMA)
    assert report["niveaux"] == [1, 2]
    assert e["provider"] == "anthropic" and e["model_resolved"] == "claude-sonnet-4-5-20250929"
    assert e["request"]["system"] == "Classe le ticket."
    assert e["request"]["messages"] == [{"role": "user", "content": "Mot de passe perdu"}]
    assert e["response"]["content"] == "compte" and e["response"]["finish_reason"] == "stop"
    assert e["usage"] == {"input_tokens": 1200, "output_tokens": 40, "cached_input_tokens": 1000, "reasoning_tokens": 30}
    assert e["request"]["tools"][0]["name"] == "reset" and e["latency_ms"] == 850.0


def test_legacy_span_events_and_old_system_attribute():
    events = [{"name": "gen_ai.user.message", "attributes": [attr("content", "Bonjour")]},
              {"name": "gen_ai.choice", "attributes": [attr("message", json.dumps({"content": "Salut"}))]}]
    s = span({"gen_ai.operation.name": "chat", "gen_ai.system": "gcp.vertex_ai", "gen_ai.request.model": "gemini-2.5-flash",
              "gen_ai.usage.input_tokens": 5, "gen_ai.usage.output_tokens": 2}, events=events)
    [e], _ = read(export(s))
    assert e["provider"] == "gemini" and e["request"]["messages"] == [{"role": "user", "content": "Bonjour"}]


def test_base64_ids_and_numeric_error_type():
    tid = base64.b64encode(bytes.fromhex("4bf92f3577b34da6a3ce929d0e0e4736")).decode()
    sid = base64.b64encode(bytes.fromhex("00f067aa0ba902b7")).decode()
    s = span({"gen_ai.operation.name": "chat", "gen_ai.request.model": "gpt-4o", "error.type": "429"},
             span_id=sid, trace_id=tid)
    s["status"] = {"code": "STATUS_CODE_ERROR", "message": "Rate limit"}
    [e], _ = read(export(s))
    assert e["trace"]["id"] == "4bf92f3577b34da6a3ce929d0e0e4736" and e["event_id"] == "otel_00f067aa0ba902b7"
    assert e["http_status"] == 429 and e["error"] == {"type": "429", "message": "Rate limit"}


def test_converted_events_go_through_the_same_core():
    events, _ = read(REAL)
    report = build_report(events)
    assert report["resume"]["nb_appels"] == 8 and report["resume"]["global"]["nb_erreurs"] == 1


def test_cli_writes_events_and_explains_what_is_missing(tmp_path, capsys):
    src = tmp_path / "traces.json"
    src.write_text(json.dumps(REAL))
    assert main([str(src), "-o", str(tmp_path / "ev.jsonl")]) == 0
    assert len((tmp_path / "ev.jsonl").read_text().splitlines()) == 8
    out = capsys.readouterr().out
    assert "8 appel(s) lus sur 12 span(s)" in out and "activer la capture du contenu" in out


def test_gateway_receives_otlp_json_traces_into_the_store(tmp_path):
    import asyncio
    import gzip

    import aiohttp
    from aiohttp import web

    from gateway.proxy import make_app
    from gateway.store import EventStore, read_events

    db = str(tmp_path / "e.db")

    async def main():
        runner = web.AppRunner(make_app(upstream="http://127.0.0.1:9", on_event=lambda e: None, store=EventStore(db)))
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", 0).start()
        gw = f"http://127.0.0.1:{runner.addresses[0][1]}"
        try:
            async with aiohttp.ClientSession() as s:
                async with s.post(gw + "/v1/traces", data=gzip.compress(json.dumps(REAL).encode()),
                                  headers={"content-type": "application/json", "content-encoding": "gzip"}) as r:
                    ok = r.status
                async with s.post(gw + "/v1/traces", data=b"\x0a\x00",
                                  headers={"content-type": "application/x-protobuf"}) as r:
                    proto = (r.status, (await r.json())["message"])
        finally:
            await runner.cleanup()
        return ok, proto

    ok, proto = asyncio.run(main())
    assert ok == 200 and proto[0] == 415 and "http/json" in proto[1]
    assert len(list(read_events(db))) == 8
