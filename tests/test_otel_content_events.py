"""B2 : contenu des appels porté par les évènements de span ou par le signal logs, et erreurs de lecture.
Formes calquées sur ce qu'émettent opentelemetry-instrumentation-botocore (système ``aws.bedrock``), Strands
Agents / AgentCore (``strands-agents``) et la spécification GenAI récente (``gen_ai.client.inference.operation.details``)."""
import json

import jsonschema
import pytest

from connectors.otel import ensure_otlp, load, main, read
from tests.test_otel_connector import SCHEMA, attr, export, span

TRACE, SPAN = "4bf92f3577b34da6a3ce929d0e0e4736", "00f067aa0ba902b7"


def kv(obj):
    """Valeur Python -> valeur OTLP/JSON typée (ce que fait le SDK pour un corps de log structuré)."""
    if isinstance(obj, dict):
        return {"kvlistValue": {"values": [{"key": k, "value": kv(v)} for k, v in obj.items()]}}
    if isinstance(obj, list):
        return {"arrayValue": {"values": [kv(v) for v in obj]}}
    if isinstance(obj, bool):
        return {"boolValue": obj}
    if isinstance(obj, int):
        return {"intValue": str(obj)}
    return {"stringValue": obj}


def logs(*records):
    return {"resourceLogs": [{"scopeLogs": [{"logRecords": list(records)}]}]}


def record(name, body=None, attrs=None, span_id=SPAN, trace_id=TRACE):
    return {"traceId": trace_id, "spanId": span_id, "eventName": name, "body": kv(body) if body is not None else None,
            "attributes": [attr(k, v) for k, v in (attrs or {}).items()]}


BEDROCK = {"gen_ai.system": "aws.bedrock", "gen_ai.operation.name": "chat",
           "gen_ai.request.model": "anthropic.claude-3-5-sonnet-20241022-v2:0",
           "gen_ai.usage.input_tokens": 210, "gen_ai.usage.output_tokens": 18,
           "gen_ai.response.finish_reasons": ["end_turn"], "server.address": "bedrock-runtime.eu-west-3.amazonaws.com"}


def test_botocore_bedrock_content_from_logs():
    recs = logs(record("gen_ai.system.message", {"content": "Tu classes des tickets."}, {"gen_ai.system": "aws.bedrock"}),
                record("gen_ai.user.message", {"content": [{"text": "Mot de passe perdu"}]}),
                record("gen_ai.choice", {"finish_reason": "end_turn", "index": 0,
                                         "message": {"content": [{"text": "compte"}], "role": "assistant"}}),
                record("gen_ai.user.message", {"content": [{"text": "AUTRE SPAN"}]}, span_id="1111111111111111"))
    [e], report = read(export(span(BEDROCK)), logs=recs)
    jsonschema.validate(e, SCHEMA)
    assert report["niveaux"] == [1, 2] and report["avec_contenu"] == 1
    assert e["provider"] == "anthropic" and e["upstream"].startswith("bedrock-runtime")
    assert e["request"]["system"] == "Tu classes des tickets."
    assert e["request"]["messages"] == [{"role": "user", "content": "Mot de passe perdu"}]
    assert e["response"]["content"] == "compte" and e["response"]["finish_reason"] == "stop"
    assert "AUTRE SPAN" not in json.dumps(e)  # rattachement par (trace, span), jamais par proximité


def test_without_logs_bedrock_stays_level_1():
    [e], report = read(export(span(BEDROCK)))
    assert report["niveaux"] == [1] and e["request"]["messages"] == [] and e["usage"]["input_tokens"] == 210


def test_log_tool_call_from_choice():
    choice = record("gen_ai.choice", {"finish_reason": "tool_use", "index": 0, "message": {
        "content": [{"toolUse": {"toolUseId": "tu_1", "name": "get_weather", "input": {"city": "Paris"}}}]}})
    [e], _ = read(export(span({**BEDROCK, "gen_ai.response.finish_reasons": ["tool_use"]})), logs=logs(choice))
    assert e["response"]["finish_reason"] == "tool_calls"
    assert e["response"]["tool_calls"] == [{"id": "tu_1", "name": "get_weather", "arguments": '{"city": "Paris"}'}]


def strands_span(events, **extra):
    attrs = {"gen_ai.system": "strands-agents", "gen_ai.operation.name": "chat",
             "gen_ai.request.model": "eu.anthropic.claude-sonnet-4-5-20250929-v1:0",
             "gen_ai.usage.prompt_tokens": 320, "gen_ai.usage.completion_tokens": 25,
             "gen_ai.usage.cache_read_input_tokens": 256, **extra}
    return span(attrs, events=events)


def test_strands_span_events_and_legacy_usage_names():
    evs = [{"name": "gen_ai.user.message", "attributes": [attr("content", json.dumps([{"text": "Bonjour"}]))]},
           {"name": "gen_ai.choice", "attributes": [attr("message", json.dumps([{"text": "Salut"}])),
                                                    attr("finish_reason", "end_turn")]}]
    agent = span({"gen_ai.operation.name": "invoke_agent", "gen_ai.agent.name": "support"}, span_id="2222222222222222")
    [e], report = read(export(strands_span(evs), agent))
    jsonschema.validate(e, SCHEMA)
    assert report["spans"] == 2 and report["appels_lus"] == 1
    assert e["provider"] == "anthropic"  # strands-agents ne dit pas le fournisseur : deviné d'après le modèle
    assert e["usage"] == {"input_tokens": 320, "output_tokens": 25, "cached_input_tokens": 256, "reasoning_tokens": None}
    assert e["request"]["messages"] == [{"role": "user", "content": "Bonjour"}]
    assert e["response"]["content"] == "Salut" and e["response"]["finish_reason"] == "stop"


def test_strands_tool_use_choice():
    evs = [{"name": "gen_ai.choice", "attributes": [
        attr("message", json.dumps([{"toolUse": {"toolUseId": "t1", "name": "calc", "input": {"x": 2}}}])),
        attr("finish_reason", "tool_use")]}]
    [e], _ = read(export(strands_span(evs)))
    assert e["response"]["finish_reason"] == "tool_calls" and e["response"]["tool_calls"][0]["name"] == "calc"


def test_recent_spec_details_event_in_logs_and_in_span_events():
    msgs = {"gen_ai.input.messages": [{"role": "user", "parts": [{"type": "text", "content": "Résume"}]},
                                      {"role": "tool", "parts": [{"type": "tool_call_response", "id": "c1",
                                                                  "response": "ok"}]}],
            "gen_ai.output.messages": [{"role": "assistant", "finish_reason": "stop",
                                        "parts": [{"type": "text", "content": "Voici"},
                                                  {"type": "tool_call", "id": "c2", "name": "save",
                                                   "arguments": {"a": 1}}]}],
            "gen_ai.system_instructions": [{"type": "text", "content": "Sois bref."}]}
    base = {"gen_ai.operation.name": "chat", "gen_ai.provider.name": "openai", "gen_ai.request.model": "gpt-4o-mini",
            "gen_ai.usage.input_tokens": 50, "gen_ai.usage.output_tokens": 9}
    rec = record("gen_ai.client.inference.operation.details", None, {})
    rec["attributes"] = [{"key": k, "value": kv(v)} for k, v in msgs.items()]
    [from_log], _ = read(export(span(base)), logs=logs(rec))
    ev = {"name": "gen_ai.client.inference.operation.details", "attributes": rec["attributes"]}
    [from_span], _ = read(export(span(base, events=[ev])))
    for e in (from_log, from_span):
        jsonschema.validate(e, SCHEMA)
        assert e["request"]["system"] == "Sois bref."
        assert e["request"]["messages"] == [{"role": "user", "content": "Résume"}, {"role": "tool", "content": "ok"}]
        assert e["response"]["content"] == "Voici" and e["response"]["tool_calls"][0]["name"] == "save"


def test_log_records_without_span_or_not_genai_are_ignored():
    recs = logs({"traceId": TRACE, "eventName": "gen_ai.user.message", "body": kv({"content": "orphelin"})},
                record("http.request", {"content": "bruit"}))
    [e], _ = read(export(span(BEDROCK)), logs=recs)
    assert e["request"]["messages"] == []


def test_ensure_otlp_refuses_other_json():
    for bad in ({}, {"data": []}, [], "x", {"resourceSpans": "non"}):
        with pytest.raises(ValueError):
            ensure_otlp(bad)
    assert ensure_otlp({"resourceSpans": []}) == {"resourceSpans": []}


def test_load_accepts_collector_file_exporter_lines(tmp_path):
    f = tmp_path / "traces.jsonl"
    f.write_text("\n".join(json.dumps(export(span(BEDROCK, span_id=f"{i:016x}", start=i * 10**9))) for i in range(1, 4)))
    events, report = read(load(f))
    assert report["appels_lus"] == 3 and [e["trace"]["step"] for e in events] == [0, 1, 2]


def run(tmp_path, content, name="t.json", extra=()):
    f = tmp_path / name
    f.write_text(content, encoding="utf-8")
    return main([str(f), "-o", str(tmp_path / "ev.jsonl"), *extra])


@pytest.mark.parametrize("content, expected", [
    ("{}", "ce n'est pas un export OTLP/JSON"),
    ('{"hello": "world"}', "ce n'est pas un export OTLP/JSON"),
    ("pas du json", "lecture impossible"),
    ('{"resourceSpans": []}', "aucun span"),
])
def test_cli_clear_error_and_nonzero_exit(tmp_path, content, expected):
    with pytest.raises(SystemExit) as exc:
        run(tmp_path, content)
    assert expected in str(exc.value) and exc.value.code not in (0, None)
    assert not (tmp_path / "ev.jsonl").exists()


def test_cli_spans_without_model_calls_is_an_error_with_reason(tmp_path):
    with pytest.raises(SystemExit) as exc:
        run(tmp_path, json.dumps(export(span({"http.method": "GET"}))))
    assert "aucun appel de modèle" in str(exc.value) and "span sans appel de modèle" in str(exc.value)


def test_cli_with_logs_gives_level_2(tmp_path, capsys):
    (tmp_path / "l.json").write_text(json.dumps(logs(record("gen_ai.user.message", {"content": "salut"}))))
    assert run(tmp_path, json.dumps(export(span(BEDROCK))), extra=["--logs", str(tmp_path / "l.json")]) == 0
    assert "niveaux [1, 2]" in capsys.readouterr().out


def test_gateway_rejects_json_that_is_not_otlp(tmp_path):
    from tests.test_otel_connector import post_traces

    out = post_traces(str(tmp_path / "e.db"), [(b'{"hello": "world"}', {"content-type": "application/json"}),
                                                (b'{"resourceSpans": []}', {"content-type": "application/json"})])
    assert [status for status, _ in out] == [400, 200]
