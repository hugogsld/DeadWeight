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
- 2, contenu : seulement si le client a activé la capture (en option dans OpenTelemetry). Le contenu peut
  être dans les attributs du span, dans ses évènements, ou dans le signal « logs » (botocore, Strands,
  versions récentes des instrumentations) : ``--logs export-logs.json`` le rattache au span par
  ``traceId`` + ``spanId``.
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
DETAILS = "gen_ai.client.inference.operation.details"  # évènement récent : contenu dans ses attributs
LEGACY_MESSAGES = ("gen_ai.system.message", "gen_ai.user.message", "gen_ai.assistant.message", "gen_ai.tool.message")
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


def _format(system, model=None):
    """Format de requête (schéma) : Anthropic, Gemini, sinon OpenAI (Mistral, Groq, Ollama parlent OpenAI).
    Strands (``strands-agents``) ou un fournisseur absent : on devine d'après le nom du modèle."""
    s = (system or "").lower()
    if "anthropic" in s or "bedrock" in s:
        return "anthropic"
    if "gemini" in s or s.startswith("gcp.") or "vertex" in s:
        return "gemini"
    if s in ("", "strands-agents"):
        m = (model or "").lower()
        return "anthropic" if "claude" in m or "anthropic" in m else "gemini" if "gemini" in m else "openai"
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
    if isinstance(parts, list):  # parts GenAI ({"type": "text", "content"}) ou blocs Bedrock ({"text"})
        out = []
        for p in parts:
            if isinstance(p, str):
                out.append(p)
            elif isinstance(p, dict) and p.get("type", "text") == "text":
                text = p.get("content", p.get("text", ""))
                out.append(text if isinstance(text, str) else "")
            elif isinstance(p, dict) and p.get("type") == "tool_call_response":
                resp = p.get("response")
                out.append(resp if isinstance(resp, str) else json.dumps(resp, ensure_ascii=False))
        return "".join(out)
    if isinstance(parts, dict):
        return _text(parts.get("content", parts.get("text")))
    return None


def _calls(parts):
    """Appels d'outils d'un message : parts ``tool_call``, blocs Bedrock ``toolUse``, ou ``tool_calls`` OpenAI."""
    out = []
    if isinstance(parts, dict):
        parts = (parts.get("tool_calls") or []) + (parts.get("content") if isinstance(parts.get("content"), list) else [])
    for p in parts if isinstance(parts, list) else []:
        if not isinstance(p, dict):
            continue
        use = p.get("toolUse") or (p if p.get("type") == "tool_call" else None)
        fn = p.get("function")
        if use:
            out.append({"id": use.get("id") or use.get("toolUseId"), "name": use.get("name") or "",
                        "arguments": json.dumps(use.get("arguments", use.get("input")), ensure_ascii=False)})
        elif fn:
            args = fn.get("arguments")
            out.append({"id": p.get("id"), "name": fn.get("name") or "",
                        "arguments": args if isinstance(args, str) else json.dumps(args, ensure_ascii=False)})
    return out


def _body(ev):
    """Contenu d'un évènement : attribut ``content`` / ``message`` (Strands), ou corps du log (botocore)."""
    a = _attrs(ev.get("attributes"))
    raw = a.get("content") or a.get("message") or a.get("gen_ai.event.content") or a.get("body")
    if raw is None and ev.get("body") is not None:
        raw = _value(ev["body"])
    return _json(raw), a


def _messages(attrs, events):
    """(system, messages, réponse, appels d'outils) depuis les attributs, les évènements de span ou les logs."""
    system, messages, answer, calls = None, [], None, []
    attrs = {**attrs}
    for ev in events:  # évènement récent : mêmes attributs que le span, dans l'évènement
        if ev.get("name") == DETAILS:
            attrs.update({k: v for k, v in _attrs(ev.get("attributes")).items() if v is not None})
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
        calls = _calls(first.get("parts"))
    for ev in events:  # ancienne forme : un évènement par message (span event ou log)
        name = ev.get("name", "")
        if name != "gen_ai.choice" and name not in LEGACY_MESSAGES:
            continue
        body, a = _body(ev)
        text = _text(body)
        if name == "gen_ai.system.message":
            system = text
        elif name != "gen_ai.choice":
            messages.append({"role": name.split(".")[1], "content": text})
        elif answer is None:
            msg = body.get("message", body) if isinstance(body, dict) else body  # botocore : body.message
            answer = _text(msg.get("content", msg) if isinstance(msg, dict) else msg)
            calls = calls or _calls(msg)
            fin = a.get("finish_reason") or (body.get("finish_reason") if isinstance(body, dict) else None)
            if fin and "gen_ai.response.finish_reasons" not in attrs:
                attrs["gen_ai.response.finish_reasons"] = [fin]
    return system, messages, answer, calls, attrs.get("gen_ai.response.finish_reasons")


def _first(attrs, *keys):
    """Premier attribut présent parmi plusieurs noms (la spécification a changé de noms au fil des versions)."""
    return next((attrs[k] for k in keys if attrs.get(k) is not None), None)


def _event(span, service, extra=()):
    attrs = _attrs(span.get("attributes"))
    system, messages, answer, calls, finishes = _messages(attrs, [*span.get("events", []), *extra])
    start, end = int(span["startTimeUnixNano"]), int(span["endTimeUnixNano"])
    failed = span.get("status", {}).get("code") in ("STATUS_CODE_ERROR", 2) or "error.type" in attrs
    err_type = str(attrs.get("error.type") or "error")
    finish_raw = (finishes or [None])[0]
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
        "provider": _format(attrs.get("gen_ai.provider.name") or attrs.get("gen_ai.system"),
                            attrs.get("gen_ai.request.model") or attrs.get("gen_ai.response.model")),
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
        "usage": {"input_tokens": _first(attrs, "gen_ai.usage.input_tokens", "gen_ai.usage.prompt_tokens"),
                  "output_tokens": _first(attrs, "gen_ai.usage.output_tokens", "gen_ai.usage.completion_tokens"),
                  "cached_input_tokens": _first(attrs, "gen_ai.usage.cache_read.input_tokens",
                                                "gen_ai.usage.cache_read_input_tokens"),
                  "reasoning_tokens": attrs.get("gen_ai.usage.reasoning.output_tokens")},
        "http_status": (int(err_type) if err_type.isdigit() else 502) if failed else 200,
        "error": {"type": err_type, "message": span.get("status", {}).get("message") or err_type} if failed else None,
    }


def ensure_otlp(payload, signal="resourceSpans"):
    """Refuse ce qui n'est pas un export OTLP/JSON : sinon « 0 appel » ferait croire à un trafic vide."""
    if not isinstance(payload, dict) or not isinstance(payload.get(signal), list):
        raise ValueError(f"ce n'est pas un export OTLP/JSON de traces (clé « {signal} » absente)"
                         if signal == "resourceSpans" else f"ce n'est pas un export OTLP/JSON de logs (clé « {signal} » absente)")
    return payload


def load(path):
    """Fichier OTLP/JSON -> charge utile. Accepte aussi une ligne JSON par export (fichier du collecteur
    OpenTelemetry, exportateur ``file``) : les listes ``resourceSpans`` / ``resourceLogs`` sont fusionnées."""
    text = Path(path).read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except ValueError:
        merged = {}
        for n, line in enumerate(filter(str.strip, text.splitlines()), 1):
            obj = json.loads(line)  # ValueError si une ligne n'est pas du JSON : le fichier n'est pas du NDJSON
            if not isinstance(obj, dict):
                raise ValueError(f"ligne {n} : pas un objet JSON")
            for key, value in obj.items():
                merged.setdefault(key, []).extend(value if isinstance(value, list) else [])
        return merged


def log_events(logs):
    """Export OTLP/JSON de logs -> {(trace, span): [évènements gen_ai.*]}. Même forme que les évènements de
    span : le contenu d'un appel peut y être déposé séparément (botocore, Strands, instrumentations récentes)."""
    out = defaultdict(list)
    for rl in (logs or {}).get("resourceLogs", []):
        for sl in rl.get("scopeLogs", []):
            for rec in sl.get("logRecords", []):
                attrs = _attrs(rec.get("attributes"))
                name = rec.get("eventName") or attrs.get("event.name")
                if name and str(name).startswith("gen_ai.") and rec.get("spanId"):
                    out[(_hex(rec.get("traceId")), _hex(rec["spanId"]))].append(
                        {"name": name, "attributes": rec.get("attributes"), "body": rec.get("body")})
    return out


def read(payload, app_id=None, logs=None):
    """Export OTLP/JSON -> (événements, rapport de compréhension). ``logs`` : export OTLP/JSON de logs."""
    events, skipped, total = [], Counter(), 0
    from_logs = log_events(logs)
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
                events.append(_event(span, service, from_logs.get((_hex(span.get("traceId")), _hex(span["spanId"]))) or ()))
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
    ap.add_argument("traces", help="export OTLP/JSON (un objet, ou une ligne JSON par export)")
    ap.add_argument("-o", "--out", default="out/otel-events.jsonl")
    ap.add_argument("--app", help="app_id à utiliser (sinon service.name)")
    ap.add_argument("--logs", help="export OTLP/JSON des logs : contenu des appels (botocore, Strands…)")
    args = ap.parse_args(argv)
    try:
        payload = ensure_otlp(load(args.traces))
        logs = ensure_otlp(load(args.logs), "resourceLogs") if args.logs else None
    except (OSError, ValueError) as exc:
        detail = str(exc) if isinstance(exc, ValueError) and "OTLP" in str(exc) else type(exc).__name__
        sys.exit(f"erreur : lecture impossible de {args.traces} ({detail}). Attendu : un export OTLP/JSON "
                 "(fichier du collecteur OpenTelemetry, exportateur « file » ou « debug »).")
    events, report = read(payload, args.app, logs)
    if not report["spans"]:
        sys.exit(f"erreur : {args.traces} ne contient aucun span (« resourceSpans » vide). Rien à analyser.")
    if not events:
        why = "".join(f"\n  ignorés : {n} — {r}" for r, n in report["ignores"].items())
        sys.exit(f"erreur : {report['spans']} span(s) lus, aucun appel de modèle reconnu (il faut "
                 f"gen_ai.operation.name = chat, text_completion ou generate_content).{why}")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events), encoding="utf-8")
    print(f"{report['appels_lus']} appel(s) lus sur {report['spans']} span(s), niveaux {report['niveaux']} -> {out}")
    for reason, n in report["ignores"].items():
        print(f"  ignorés : {n} — {reason}")
    if not report["avec_contenu"]:
        print("  sans contenu : chiffrage et pistes seulement. Pour les preuves, activer la capture du contenu "
              "(OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true), et passer le signal logs avec --logs.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
