"""B2 — Connecteur OpenTelemetry : traces d'appels d'IA (conventions GenAI) -> événements Deadweight.

    python -m connectors.otel traces.json -o out/otel-events.jsonl
    python -m report.audit out/otel-events.jsonl           # ou agent.audit : le cœur est le même

Entrée : un export OTLP/JSON (``resourceSpans``), ce qu'écrit un collecteur OpenTelemetry ou ce que reçoit
``/v1/traces``. Identifiants en hexadécimal (OTLP/JSON) ou en base64 (JSON protobuf) : les deux sont lus.

Ce qu'on garde : les spans d'inférence (``gen_ai.operation.name`` = chat, text_completion,
generate_content). Les conventions GenAI sont encore « Development » et changent : on lit l'ancienne et la
nouvelle forme (``gen_ai.system`` ou ``gen_ai.provider.name`` ; contenu dans ``gen_ai.input.messages`` /
``gen_ai.output.messages``, ou dans les évènements de span ``gen_ai.*.message`` / ``gen_ai.choice``).

Niveaux (docs/analyser-un-workflow.md) :
- 1, usage : modèle, jetons, cache, raisonnement, durée, erreurs ; toujours là.
- 2, contenu : seulement si le client a activé la capture (en option dans OpenTelemetry). Avec certaines
  versions d'instrumentation, le contenu passe par le signal « logs », non lu ici pour l'instant.
- 3, structure : ``trace.id`` = identifiant de trace OpenTelemetry (posé par le client, d'où
  ``source = "header"``), étapes numérotées dans l'ordre.

Ce qui n'existe pas dans OpenTelemetry n'est pas inventé : ``stream`` est noté faux (non transmis), le
statut HTTP d'un échec vient de ``error.type`` s'il est numérique, sinon 502 (injoignable, comme la
passerelle). Aucune clé n'est lue : OpenTelemetry n'en transporte pas.
"""
import argparse
import base64
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

INFERENCE = {"chat", "text_completion", "generate_content"}
FINISH = {"stop": "stop", "end_turn": "stop", "length": "length", "max_tokens": "length",
          "tool_calls": "tool_calls", "tool_use": "tool_calls", "content_filter": "content_filter"}


def _value(v):
    """Valeur OTLP/JSON typée -> Python."""
    if not isinstance(v, dict):
        return v
    for key in ("stringValue", "boolValue", "doubleValue"):
        if key in v:
            return v[key]
    if "intValue" in v:
        return int(v["intValue"])
    if "arrayValue" in v:
        return [_value(x) for x in v["arrayValue"].get("values", [])]
    if "kvlistValue" in v:
        return {x["key"]: _value(x.get("value")) for x in v["kvlistValue"].get("values", [])}
    return None


def _attrs(items):
    return {a["key"]: _value(a.get("value")) for a in items or []}


def _hex(ident):
    """OTLP/JSON : hexadécimal ; JSON protobuf : base64. Rend toujours de l'hexadécimal."""
    if not ident:
        return None
    try:
        int(ident, 16)
        return ident.lower()
    except ValueError:
        return base64.b64decode(ident).hex()


def _time(nanos):
    return datetime.fromtimestamp(int(nanos) / 1e9, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _format(system):
    """Format de requête (schéma) : Anthropic, Gemini, sinon OpenAI (Mistral, Groq, Ollama parlent OpenAI)."""
    s = (system or "").lower()
    if "anthropic" in s or s == "aws.bedrock":
        return "anthropic"
    if "gemini" in s or s.startswith("gcp.") or "vertex" in s:
        return "gemini"
    return "openai"


def _json(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def _text(parts):
    """Messages GenAI (nouvelle forme : parts) ou ancienne forme (content) -> texte."""
    if isinstance(parts, str):
        return parts
    if isinstance(parts, list):
        return "".join(p.get("content", "") for p in parts if isinstance(p, dict) and p.get("type", "text") == "text")
    return None


def _messages(attrs, events):
    """(system, messages, réponse, appels d'outils) depuis les attributs ou les évènements de span."""
    system, messages, answer, calls = None, [], None, []
    raw_in = _json(attrs.get("gen_ai.input.messages"))
    raw_out = _json(attrs.get("gen_ai.output.messages"))
    system_attr = _json(attrs.get("gen_ai.system_instructions"))
    if system_attr is not None:
        system = _text(system_attr) if not isinstance(system_attr, str) else system_attr
    if isinstance(raw_in, list):
        for m in raw_in:
            role, text = m.get("role"), _text(m.get("parts", m.get("content")))
            if role == "system":
                system = (system + "\n" if system else "") + (text or "")
            elif role in ("user", "assistant", "tool"):
                messages.append({"role": role, "content": text})
    if isinstance(raw_out, list) and raw_out:
        first = raw_out[0]
        answer = _text(first.get("parts", first.get("content")))
        for part in first.get("parts", []) if isinstance(first.get("parts"), list) else []:
            if part.get("type") == "tool_call":
                calls.append({"id": part.get("id"), "name": part.get("name"),
                              "arguments": json.dumps(part.get("arguments"), ensure_ascii=False)})
    for ev in events:  # ancienne forme : un évènement par message
        a, name = _attrs(ev.get("attributes")), ev.get("name", "")
        body = _json(a.get("content") or a.get("gen_ai.event.content") or a.get("body"))
        text = body.get("content") if isinstance(body, dict) else body
        if name == "gen_ai.system.message":
            system = text
        elif name in ("gen_ai.user.message", "gen_ai.assistant.message", "gen_ai.tool.message"):
            messages.append({"role": name.split(".")[1], "content": text})
        elif name == "gen_ai.choice" and answer is None:
            msg = body.get("message") if isinstance(body, dict) else None
            answer = msg.get("content") if isinstance(msg, dict) else text
    return system, messages, answer, calls


def _event(span, service):
    attrs = _attrs(span.get("attributes"))
    system, messages, answer, calls = _messages(attrs, span.get("events", []))
    start, end = int(span["startTimeUnixNano"]), int(span["endTimeUnixNano"])
    failed = span.get("status", {}).get("code") in ("STATUS_CODE_ERROR", 2) or "error.type" in attrs
    err_type = str(attrs.get("error.type") or "error")
    finish_raw = (attrs.get("gen_ai.response.finish_reasons") or [None])[0]
    tools = [{"name": t.get("name") or (t.get("function") or {}).get("name"),
              "description": t.get("description") or (t.get("function") or {}).get("description"),
              "parameters": t.get("parameters") or (t.get("function") or {}).get("parameters")}
             for t in _json(attrs.get("gen_ai.tool.definitions")) or [] if isinstance(t, dict)]
    return {
        "schema_version": "1",
        "event_id": "otel_" + _hex(span["spanId"]),
        "trace": {"id": _hex(span.get("traceId")), "source": "header", "step": None},
        "app_id": service,
        "ts_start": _time(start), "ts_end": _time(end),
        "latency_ms": round((end - start) / 1e6, 2), "ttft_ms": None,
        "provider": _format(attrs.get("gen_ai.provider.name") or attrs.get("gen_ai.system")),
        "upstream": attrs.get("server.address"),
        "model": attrs.get("gen_ai.request.model") or attrs.get("gen_ai.response.model"),
        "model_resolved": attrs.get("gen_ai.response.model"),
        "request": {"system": system, "messages": messages, "tools": [t for t in tools if t["name"]],
                    "params": {"stream": False, "temperature": attrs.get("gen_ai.request.temperature"),
                               "top_p": attrs.get("gen_ai.request.top_p"),
                               "max_tokens": attrs.get("gen_ai.request.max_tokens"), "stop": None,
                               "response_format": None}},
        "response": {"content": None if failed else answer, "tool_calls": calls,
                     "finish_reason": "error" if failed else FINISH.get(finish_raw, "other" if finish_raw else None),
                     "finish_reason_raw": finish_raw},
        "usage": {"input_tokens": attrs.get("gen_ai.usage.input_tokens"),
                  "output_tokens": attrs.get("gen_ai.usage.output_tokens"),
                  "cached_input_tokens": attrs.get("gen_ai.usage.cache_read.input_tokens"),
                  "reasoning_tokens": attrs.get("gen_ai.usage.reasoning.output_tokens")},
        "http_status": (int(err_type) if err_type.isdigit() else 502) if failed else 200,
        "error": {"type": err_type, "message": span.get("status", {}).get("message") or err_type} if failed else None,
    }


def read(payload, app_id=None):
    """Export OTLP/JSON -> (événements, rapport de compréhension)."""
    events, skipped, total = [], Counter(), 0
    for rs in payload.get("resourceSpans", []):
        service = app_id or _attrs(rs.get("resource", {}).get("attributes")).get("service.name") or "otel"
        for ss in rs.get("scopeSpans", []):
            for span in ss.get("spans", []):
                total += 1
                attrs = _attrs(span.get("attributes"))
                op = attrs.get("gen_ai.operation.name")
                if op not in INFERENCE:
                    skipped["span sans appel de modèle (workflow, outil, agent)" if not op
                            else f"opération {op} non prise en charge"] += 1
                    continue
                if not (attrs.get("gen_ai.request.model") or attrs.get("gen_ai.response.model")):
                    skipped["appel sans modèle"] += 1
                    continue
                events.append(_event(span, service))
    by_trace = defaultdict(list)
    for e in sorted(events, key=lambda e: e["ts_start"]):
        by_trace[e["trace"]["id"]].append(e)
    for evts in by_trace.values():
        for step, e in enumerate(evts):
            e["trace"]["step"] = step
    with_usage = sum(e["usage"]["input_tokens"] is not None for e in events)
    with_content = sum(bool(e["request"]["messages"]) or e["response"]["content"] is not None for e in events)
    levels = [1] if with_usage else []
    if with_content:
        levels.append(2)
    if any(len(v) > 1 for v in by_trace.values()):
        levels.append(3)
    report = {"spans": total, "appels_lus": len(events), "ignores": dict(skipped),
              "avec_jetons": with_usage, "avec_contenu": with_content, "niveaux": levels}
    return events, report


def main(argv=None):
    ap = argparse.ArgumentParser(description="Traces OpenTelemetry -> événements Deadweight")
    ap.add_argument("traces", help="export OTLP/JSON")
    ap.add_argument("-o", "--out", default="out/otel-events.jsonl")
    ap.add_argument("--app", help="app_id à utiliser (sinon service.name)")
    args = ap.parse_args(argv)
    try:
        payload = json.loads(Path(args.traces).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        sys.exit(f"Lecture impossible de {args.traces} : {type(exc).__name__}")
    events, report = read(payload, args.app)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events), encoding="utf-8")
    print(f"{report['appels_lus']} appel(s) lus sur {report['spans']} span(s), niveaux {report['niveaux']} -> {out}")
    for reason, n in report["ignores"].items():
        print(f"  ignorés : {n} — {reason}")
    if report["appels_lus"] and not report["avec_contenu"]:
        print("  sans contenu : chiffrage et pistes seulement. Pour les preuves, activer la capture du contenu.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
