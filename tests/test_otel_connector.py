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


def as_protobuf(payload):
    """OTLP/JSON (identifiants en hexadécimal) -> OTLP protobuf, comme l'envoie l'exportateur Python."""
    from google.protobuf.json_format import ParseDict
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

    def ids_to_base64(node):
        if isinstance(node, dict):
            return {k: (base64.b64encode(bytes.fromhex(v)).decode() if k in ("traceId", "spanId", "parentSpanId")
                        and isinstance(v, str) and v else ids_to_base64(v)) for k, v in node.items()}
        if isinstance(node, list):
            return [ids_to_base64(v) for v in node]
        return node
    return ParseDict(ids_to_base64(payload), ExportTraceServiceRequest(), ignore_unknown_fields=True).SerializeToString()


def post_traces(db, requests):
    """Passerelle neuve sur la base db ; envoie (corps, en-têtes) à /v1/traces, rend (statut, content-type)."""
    import asyncio

    import aiohttp
    from aiohttp import web

    from gateway.proxy import make_app
    from gateway.store import EventStore

    async def main():
        runner = web.AppRunner(make_app(upstream="http://127.0.0.1:9", on_event=lambda e: None, store=EventStore(db)))
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", 0).start()
        gw = f"http://127.0.0.1:{runner.addresses[0][1]}"
        out = []
        try:
            async with aiohttp.ClientSession() as s:
                for body, headers in requests:
                    async with s.post(gw + "/v1/traces", data=body, headers=headers) as r:
                        out.append((r.status, r.headers.get("content-type", "").split(";")[0]))
        finally:
            await runner.cleanup()  # ferme le store : tout est écrit
        return out
    return asyncio.run(main())


def test_gateway_receives_otlp_json_traces_into_the_store(tmp_path):
    import gzip

    from gateway.store import read_events

    db = str(tmp_path / "e.db")
    out = post_traces(db, [(gzip.compress(json.dumps(REAL).encode()),
                            {"content-type": "application/json", "content-encoding": "gzip"})])
    assert out == [(200, "application/json")]
    assert len(list(read_events(db))) == 8


def test_gateway_receives_otlp_protobuf_like_the_python_exporter(tmp_path):
    """L'exportateur OTLP/HTTP de Python n'envoie que du protobuf : même trace, mêmes événements qu'en JSON."""
    from gateway.store import read_events

    json_db, proto_db = str(tmp_path / "json.db"), str(tmp_path / "proto.db")
    post_traces(json_db, [(json.dumps(REAL).encode(), {"content-type": "application/json"})])
    out = post_traces(proto_db, [(as_protobuf(REAL), {"content-type": "application/x-protobuf"})])
    assert out == [(200, "application/x-protobuf")]  # la spécification OTLP : réponse au format de la requête
    assert list(read_events(proto_db)) == list(read_events(json_db))
    assert len(list(read_events(proto_db))) == 8


def test_gateway_rejects_unreadable_or_unknown_trace_bodies(tmp_path):
    out = post_traces(str(tmp_path / "e.db"), [
        (b"\xff\xff\xff pas du protobuf", {"content-type": "application/x-protobuf"}),
        (b"pas du json", {"content-type": "application/json"}),
        (b"x", {"content-type": "text/plain"}),
    ])
    assert [status for status, _ in out] == [400, 400, 415]
