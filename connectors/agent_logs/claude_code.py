"""Journaux de session Claude Code (~/.claude/projects/<projet>/<session>.jsonl) → événements.

Format relevé sur des journaux réels (Claude Code 2.x) :

- une ligne par morceau de réponse : `type: "assistant"`, `message` = réponse de l'API Messages
  (id, model, content, stop_reason, usage). Une même réponse (texte, réflexion, appel d'outil)
  s'étale sur plusieurs lignes qui partagent `message.id` et répètent le même `usage` :
  on les regroupe, sinon le coût serait compté deux ou trois fois ;
- `type: "user"` : message de l'utilisateur ou résultat d'outil (`tool_result`) ;
- `parentUuid` chaîne les lignes : on remonte depuis la réponse pour retrouver ce qui l'a déclenchée ;
- `sessionId` : la trace ; `isSidechain` ou `agentId` : un sous-agent ;
- `model: "<synthetic>"` : message fabriqué par Claude Code (erreur, interruption), pas un appel facturé ;
- une session reprise recopie l'historique dans un nouveau fichier : dédoublonnage par `message.id`.

Ce que le journal ne garde pas : le prompt système, la liste des outils, le contexte complet
envoyé (seuls les nouveaux messages de chaque tour). Les jetons, eux, sont ceux facturés.
"""
from __future__ import annotations

import json
from pathlib import Path

from .common import Comprehension, iso, mask_secrets, num, number_steps, parse_lines, ts

FINISH = {"end_turn": "stop", "stop_sequence": "stop", "max_tokens": "length",
          "tool_use": "tool_calls", "pause_turn": "other", "refusal": "content_filter"}


def looks_like(obj: dict) -> bool:
    return obj.get("type") in ("assistant", "user") and "sessionId" in obj and "message" in obj


def _text(content) -> tuple[str | None, int]:
    """Contenu d'un message → (texte, nombre d'images)."""
    if isinstance(content, str):
        return content, 0
    parts, images = [], 0
    for block in content or []:
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind == "text":
            parts.append(block.get("text") or "")
        elif kind == "image":
            images += 1
        elif kind == "tool_result":
            text, n = _text(block.get("content"))
            images += n
            if text:
                parts.append(text)
    return ("\n".join(parts) if parts else None), images


def _user_messages(entry: dict) -> list[dict]:
    """Une ligne user → messages du schéma (role user, ou tool pour chaque résultat d'outil)."""
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, str):
        return [{"role": "user", "content": mask_secrets(content)}]
    out, plain = [], []
    for block in content or []:
        if isinstance(block, dict) and block.get("type") == "tool_result":
            text, images = _text(block.get("content"))
            msg = {"role": "tool", "content": mask_secrets(text), "tool_call_id": block.get("tool_use_id")}
            if images:
                msg["n_images"] = images
            out.append(msg)
        else:
            plain.append(block)
    if plain:
        text, images = _text(plain)
        msg = {"role": "user", "content": mask_secrets(text)}
        if images:
            msg["n_images"] = images
        out.insert(0, msg)
    return out


def _project(entry: dict, file_name: str) -> str:
    cwd = entry.get("cwd")
    if isinstance(cwd, str) and cwd:
        return Path(cwd).name
    return Path(file_name.split("!")[-1]).parent.name or "claude-code"


def read(files, report: Comprehension | None = None) -> tuple[list[dict], Comprehension]:
    """files : itérable de (nom, lignes). Renvoie les événements triés par heure."""
    report = report or Comprehension("claude-code")
    calls: dict[str, dict] = {}
    costs: dict[str, float] = {}
    copied: set[tuple[str, str]] = set()

    for name, lines in files:
        entries, bad = parse_lines(lines)
        if not any(looks_like(e) for e in entries):
            continue
        report.files += 1
        if bad:
            report.ignore("ligne illisible (JSON invalide ou tronqué)", bad)
        by_uuid = {e["uuid"]: e for e in entries if e.get("uuid")}
        for e in entries:
            if e.get("type") == "cost-state" and isinstance(e.get("totalCostUSD"), (int, float)):
                costs[e.get("sessionId") or name] = float(e["totalCostUSD"])
            if e.get("type") != "assistant":
                continue
            msg = e.get("message") or {}
            if msg.get("model") == "<synthetic>" or e.get("isApiErrorMessage"):
                report.ignore("message fabriqué par Claude Code (erreur, interruption) : pas un appel facturé")
                continue
            key = msg.get("id") or e.get("requestId")
            if not key:
                report.ignore("réponse sans identifiant")
                continue
            call = calls.get(key)
            if call is None:
                calls[key] = {"lines": [e], "by_uuid": by_uuid, "file": name}
            elif call["file"] == name:
                call["lines"].append(e)
            elif (key, name) not in copied:
                copied.add((key, name))
                report.ignore("appel recopié par une session reprise (déjà compté)")

    events = [_event(key, c, report) for key, c in calls.items()]
    events = [e for e in events if e is not None]
    events.sort(key=lambda e: e["ts_start"])
    number_steps(events, report)

    if costs:
        report.extra["cout_annonce_par_claude_code_usd"] = round(sum(costs.values()), 4)
    report.note("prompt système et outils déclarés absents du journal : request.system = null, request.tools = []")
    report.note("request.messages = nouveaux messages du tour (le contexte complet envoyé n'est pas journalisé)")
    report.note("appels internes de Claude Code non journalisés comme réponses (titres de session, résumés) : absents")
    if report.extra.get("jetons_ecrits_en_cache"):
        report.note("jetons écrits en cache comptés dans input_tokens au prix normal : "
                    "Anthropic les facture 1,25× (5 min) à 2× (1 h), le coût est donc sous-estimé sur cette part")
    return events, report


def _event(key: str, call: dict, report: Comprehension) -> dict | None:
    lines = sorted(call["lines"], key=lambda e: ts(e.get("timestamp")) or 0)
    first, last = lines[0], lines[-1]
    msg = last.get("message") or {}
    session = first.get("sessionId")

    # le même usage est répété sur chaque ligne ; on garde la sortie la plus grande (fin du flux)
    usages = [(ln.get("message") or {}).get("usage") or {} for ln in lines]
    usage = max(usages, key=lambda u: num(u.get("output_tokens")) or 0)
    if not usage:
        report.ignore("réponse sans jetons")
        return None

    blocks = [b for ln in lines for b in ((ln.get("message") or {}).get("content") or []) if isinstance(b, dict)]
    text = "".join(b.get("text") or "" for b in blocks if b.get("type") == "text") or None
    tool_calls = [{"id": b.get("id"), "name": b.get("name") or "?",
                   "arguments": mask_secrets(json.dumps(b.get("input") or {}, ensure_ascii=False))}
                  for b in blocks if b.get("type") == "tool_use"]
    raw_stop = next((ln["message"].get("stop_reason") for ln in reversed(lines)
                     if (ln.get("message") or {}).get("stop_reason")), None)

    # ce qui a déclenché l'appel : on remonte la chaîne jusqu'à la réponse précédente
    by_uuid = call["by_uuid"]
    parent, messages, start, seen = by_uuid.get(first.get("parentUuid")), [], None, 0
    while parent is not None and seen < 200:
        seen += 1
        if start is None:
            start = ts(parent.get("timestamp"))
        if parent.get("type") == "assistant" and ((parent.get("message") or {}).get("id") != key):
            break
        if parent.get("type") == "user":
            messages[:0] = _user_messages(parent)
        parent = by_uuid.get(parent.get("parentUuid"))
    end = ts(last.get("timestamp")) or 0.0
    start = start if start is not None and start <= end else ts(first.get("timestamp")) or end

    cache_write = num(usage.get("cache_creation_input_tokens")) or 0
    input_tokens = num(usage.get("input_tokens"))
    if cache_write:
        report.add("jetons_ecrits_en_cache", cache_write)
    reasoning = num((usage.get("output_tokens_details") or {}).get("thinking_tokens"))

    sub = bool(first.get("isSidechain") or first.get("agentId"))
    report.calls += 1
    report.sessions.add(session or call["file"])
    if messages or text or tool_calls:
        report.with_content += 1
    if num(usage.get("input_tokens")) is not None:
        report.with_usage += 1

    return {
        "schema_version": "1",
        "event_id": f"cc-{key}",
        "trace": {"id": f"claude-code:{session}" if session else None,
                  "source": "header" if session else None, "step": None},
        "app_id": f"claude-code:{_project(first, call['file'])}" + ("/sous-agent" if sub else ""),
        "ts_start": iso(start),
        "ts_end": iso(end),
        "latency_ms": round((end - start) * 1000),
        "ttft_ms": None,
        "provider": "anthropic",
        "upstream": "api.anthropic.com",
        "endpoint": "/v1/messages",
        "model": msg.get("model") or "unknown",
        "model_resolved": msg.get("model"),
        "request": {"system": None, "messages": messages, "tools": [],
                    "params": {"stream": True, "temperature": None, "top_p": None, "max_tokens": None,
                               "stop": None, "response_format": None}},
        "response": {"content": mask_secrets(text), "tool_calls": tool_calls,
                     "finish_reason": FINISH.get(raw_stop, "other" if raw_stop else None),
                     "finish_reason_raw": raw_stop},
        "usage": {"input_tokens": None if input_tokens is None else input_tokens + cache_write,
                  "output_tokens": num(usage.get("output_tokens")),
                  "cached_input_tokens": num(usage.get("cache_read_input_tokens")),
                  "reasoning_tokens": reasoning},
        "http_status": 200,
        "error": None,
    }
