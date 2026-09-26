"""Journaux de session Codex (~/.codex/sessions/AAAA/MM/JJ/rollout-*.jsonl) → événements.

Format relevé sur des journaux réels (Codex CLI 0.15x) ; chaque ligne est {timestamp, type, payload} :

- `session_meta` : id de session, fournisseur (`model_provider`) ;
- `turn_context` : le modèle utilisé pour les appels qui suivent ;
- `response_item` : messages (developer, user, assistant), appels d'outils
  (`function_call`, `custom_tool_call`) et leurs résultats (`*_output`) ;
- `token_usage_record` : **une ligne par appel du modèle**, avec `response_id` et `usage`
  (input_tokens cache compris, cached_input_tokens, output_tokens, reasoning_output_tokens).
  Les anciennes versions n'ont que `event_msg/token_count` (cumul + `last_token_usage`, parfois
  répété) : utilisé seulement en l'absence de `token_usage_record`, jamais en plus.

Les sorties d'un appel (texte, appels d'outils) sont écrites avant sa ligne de jetons ; les
résultats d'outils après, ils forment l'entrée de l'appel suivant. On découpe donc le
journal en tranches, d'une ligne de jetons à la suivante.
"""
from __future__ import annotations

import json

from .common import Comprehension, iso, mask_secrets, num, parse_lines, ts

# fournisseur Codex → hôte appelé ; le format reste celui d'OpenAI
UPSTREAMS = {"openai": "api.openai.com", "azure": "azure", "ollama": "localhost:11434",
             "lmstudio": "localhost:1234", "openrouter": "openrouter.ai", "mistral": "api.mistral.ai"}

OUTPUTS = ("function_call_output", "custom_tool_call_output", "local_shell_call_output")
CALLS = ("function_call", "custom_tool_call", "local_shell_call")


def looks_like(obj: dict) -> bool:
    return obj.get("type") in ("session_meta", "turn_context", "response_item", "token_usage_record", "event_msg") \
        and "payload" in obj


def _text(content) -> str | None:
    if isinstance(content, str):
        return content
    parts = [c.get("text") or "" for c in content or [] if isinstance(c, dict) and "text" in c]
    return "\n".join(parts) if parts else None


def _images(content) -> int:
    return sum(1 for c in content or [] if isinstance(c, dict) and "image" in str(c.get("type")))


def read(files, report: Comprehension | None = None) -> tuple[list[dict], Comprehension]:
    report = report or Comprehension("codex")
    events, seen = [], set()
    for name, lines in files:
        entries, bad = parse_lines(lines)
        if not any(looks_like(e) for e in entries):
            continue
        report.files += 1
        if bad:
            report.ignore("ligne illisible (JSON invalide ou tronqué)", bad)
        events.extend(_read_session(entries, name, report, seen))
    events.sort(key=lambda e: e["ts_start"])
    steps: dict[str, int] = {}
    for ev in events:
        tid = ev["trace"]["id"]
        ev["trace"]["step"] = steps.get(tid, 0)
        steps[tid] = ev["trace"]["step"] + 1
    report.note("outils déclarés absents du journal : request.tools = []")
    report.note("request.messages = nouveaux messages du tour (le contexte complet envoyé n'est pas journalisé)")
    return events, report


def _read_session(entries: list[dict], name: str, report: Comprehension, seen: set) -> list[dict]:
    has_records = any(e.get("type") == "token_usage_record" for e in entries)
    if not has_records:
        report.note("version de Codex sans token_usage_record : jetons pris dans token_count (last_token_usage)")

    session, provider, model, cwd = None, "openai", None, None
    seg_in: list[dict] = []
    seg_out: list[dict] = []
    system: list[str] = []
    start = last_input = None
    last_total = None
    events = []

    for e in entries:
        kind, p, when = e.get("type"), e.get("payload") or {}, ts(e.get("timestamp"))
        if kind == "session_meta":
            session = p.get("id") or p.get("session_id") or session
            provider = p.get("model_provider") or provider
            cwd = p.get("cwd") or cwd
            continue
        if kind == "turn_context":
            model = p.get("model") or model
            cwd = p.get("cwd") or cwd
            continue
        if kind == "response_item":
            item = p.get("type")
            if item == "message" and p.get("role") in ("developer", "system"):
                text = _text(p.get("content"))
                if text:
                    system.append(text)
            elif item == "message" and p.get("role") == "user" or item in OUTPUTS:
                seg_in.append(p)
            elif item == "message" and p.get("role") == "assistant" or item in CALLS:
                if not seg_out and start is None:
                    start = last_input
                seg_out.append(p)
            elif item == "reasoning":
                pass
            if not seg_out:
                last_input = when
            continue

        usage, response_id = None, None
        if kind == "token_usage_record":
            usage, response_id = p.get("usage") or {}, p.get("response_id")
            session = p.get("session_id") or session
            sub = bool(p.get("thread_id") and p.get("session_id") and p.get("thread_id") != p.get("session_id"))
        elif kind == "event_msg" and p.get("type") == "token_count" and not has_records:
            info = p.get("info") or {}
            total = json.dumps(info.get("total_token_usage"), sort_keys=True)
            if not info.get("last_token_usage") or total == last_total:
                continue  # événement répété : pas un nouvel appel
            last_total = total
            usage, sub = info["last_token_usage"], False
        else:
            if last_input is None and not seg_out:
                last_input = when
            continue

        key = response_id or f"{session}-{e.get('timestamp')}"
        if key in seen:
            report.ignore("appel déjà lu dans un autre fichier (session reprise)")
        else:
            seen.add(key)
            ev = _event(key, session, provider, model, cwd, sub, system, seg_in, seg_out,
                        start if start is not None else last_input, when, usage, report)
            if ev:
                events.append(ev)
        seg_in, seg_out, system, start, last_input = [], [], [], None, when
    if seg_out:
        report.ignore("réponse sans ligne de jetons (session interrompue)")
    return events


def _event(key, session, provider, model, cwd, sub, system, seg_in, seg_out, start, end, usage, report):
    if not isinstance(usage, dict) or num(usage.get("input_tokens")) is None:
        report.ignore("appel sans jetons")
        return None
    end = end or start or 0.0
    start = start if start is not None and start <= end else end

    messages = []
    for p in seg_in:
        if p.get("type") == "message":
            msg = {"role": "user", "content": mask_secrets(_text(p.get("content")))}
            if _images(p.get("content")):
                msg["n_images"] = _images(p.get("content"))
        else:
            out = p.get("output")
            msg = {"role": "tool", "content": mask_secrets(out if isinstance(out, str) else _text(out)),
                   "tool_call_id": p.get("call_id")}
        messages.append(msg)
    text = "".join(_text(p.get("content")) or "" for p in seg_out if p.get("type") == "message") or None
    calls = []
    for p in seg_out:
        if p.get("type") in CALLS:
            args = p.get("arguments", p.get("input", p.get("action")))
            calls.append({"id": p.get("call_id"), "name": p.get("name") or p.get("type"),
                          "arguments": mask_secrets(args if isinstance(args, str) else json.dumps(args, ensure_ascii=False))})

    report.calls += 1
    report.sessions.add(session or "?")
    if messages or text or calls:
        report.with_content += 1
    if session:
        report.with_trace += 1
    if not model:
        report.add("modele_inconnu", 1)
    project = (cwd or "").rstrip("/").split("/")[-1] or "codex"

    return {
        "schema_version": "1",
        "event_id": f"codex-{key}",
        "trace": {"id": f"codex:{session}" if session else None, "source": "header" if session else None, "step": None},
        "app_id": f"codex:{project}" + ("/sous-agent" if sub else ""),
        "ts_start": iso(start),
        "ts_end": iso(end),
        "latency_ms": round((end - start) * 1000),
        "ttft_ms": None,
        "provider": "openai",
        "upstream": UPSTREAMS.get(provider, provider),
        "endpoint": "/v1/responses",
        "model": model or "unknown",
        "model_resolved": None,
        "request": {"system": mask_secrets("\n\n".join(system)) or None, "messages": messages, "tools": [],
                    "params": {"stream": True, "temperature": None, "top_p": None, "max_tokens": None,
                               "stop": None, "response_format": None}},
        "response": {"content": mask_secrets(text), "tool_calls": calls,
                     "finish_reason": "tool_calls" if calls else None, "finish_reason_raw": None},
        "usage": {"input_tokens": num(usage.get("input_tokens")), "output_tokens": num(usage.get("output_tokens")),
                  "cached_input_tokens": num(usage.get("cached_input_tokens")),
                  "reasoning_tokens": num(usage.get("reasoning_output_tokens"))},
        "http_status": 200,
        "error": None,
    }
