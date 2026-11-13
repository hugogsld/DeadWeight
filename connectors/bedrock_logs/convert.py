"""Enregistrement d'invocation Bedrock → événement au schéma v1 (schemas/EVENT.md).

Deux formes de corps selon l'opération :

- Converse / ConverseStream : requête `messages` / `system` / `toolConfig` / `inferenceConfig`,
  réponse `output.message`, `stopReason`, `usage` (inputTokens, outputTokens, cacheReadInputTokens,
  cacheWriteInputTokens) ;
- InvokeModel / InvokeModelWithResponseStream avec un modèle Anthropic : corps de l'API Messages
  (`anthropic_version`, `messages`, `tools[].input_schema`, `usage.cache_read_input_tokens`...).
  Un modèle Nova (corps de type Converse) est lu comme Converse. Titan, Llama, Mistral :
  les jetons sont comptés, le contenu est marqué manquant. Embeddings : ignorés avec leur raison.

Les jetons viennent d'abord des compteurs de l'enregistrement (`input.inputTokenCount`,
`cacheReadInputTokenCount`...), toujours présents même quand le corps manque, puis de l'usage du corps.
`input_tokens` exclut le cache (comme Anthropic) : voir report/cost.py.

Aucun ARN n'est gardé dans l'événement ; les chaînes qui ressemblent à une clé sont masquées.
"""
from __future__ import annotations

import base64
import gzip
import json
import re

from connectors.agent_logs.common import Comprehension, iso, mask_secrets, num, ts

from .source import body_key

OPERATIONS = {"Converse", "ConverseStream", "InvokeModel", "InvokeModelWithResponseStream"}
FINISH = {"end_turn": "stop", "stop_sequence": "stop", "max_tokens": "length", "tool_use": "tool_calls",
          "content_filtered": "content_filter", "guardrail_intervened": "content_filter",
          "pause_turn": "other", "refusal": "content_filter", "model_context_window_exceeded": "length"}
HTTP_BY_ERROR = {"ThrottlingException": 429, "ValidationException": 400, "ModelTimeoutException": 408,
                 "AccessDeniedException": 403, "ServiceUnavailableException": 503}
# étiquettes posées par l'appelant (requestMetadata) ; comparées sans casse ni séparateur
TRACE_TAGS = ("workflowid", "workflow", "traceid", "runid", "sessionid", "conversationid", "executionid")
APP_TAGS = ("appid", "app", "application", "agent", "agentname", "service")
PROFILE_PREFIX = re.compile(r"^(eu|us|us-gov|apac|jp|au|ca|global)\.")


def _tag(metadata, names) -> str | None:
    flat = {re.sub(r"[^a-z0-9]", "", str(k).lower()): v for k, v in (metadata or {}).items()}
    for name in names:
        value = flat.get(name)
        if isinstance(value, (str, int)) and not isinstance(value, bool) and str(value):
            return str(value)
    return None


def profile_kind(model_id: str | None) -> str | None:
    """'global' ou 'geo' (eu., us., apac...) pour un profil d'inférence ; None pour un modèle direct."""
    m = PROFILE_PREFIX.match((model_id or "").split("/")[-1])
    return None if not m else ("global" if m.group(1) == "global" else "geo")


def _role_name(arn: str | None) -> str | None:
    m = re.search(r":(?:assumed-role|role)/([^/]+)", arn or "")
    return m.group(1) if m else None


def _body(section: dict, key: str, bodies: dict[str, bytes], report: Comprehension):
    """Corps JSON d'une section input/output : en ligne, via objet S3 local, ou None (manquant)."""
    if key + "Json" in section:
        value = section[key + "Json"]
        if isinstance(value, str):  # certains exports sérialisent le corps en chaîne
            try:
                return json.loads(value)
            except ValueError:
                return None
        return value
    path = section.get(key + "S3Path")
    if not path:
        return None
    data = bodies.get(body_key(path)) if isinstance(path, str) else None
    if data is None:
        report.add("corps_externes_absents", 1)
        return None
    try:
        if data[:2] == b"\x1f\x8b":
            data = gzip.decompress(data)
        value = json.loads(data.decode("utf-8", errors="replace"))
    except (OSError, ValueError):
        report.add("corps_externes_absents", 1)
        return None
    report.add("corps_externes_suivis", 1)
    return value


def _result_text(blocks) -> tuple[str | None, int]:
    """Contenu d'un résultat d'outil (Converse : text/json ; Anthropic : texte ou blocs) → (texte, images)."""
    if isinstance(blocks, str):
        return blocks, 0
    parts, images = [], 0
    for b in blocks or []:
        if not isinstance(b, dict):
            continue
        if "text" in b:
            parts.append(b.get("text") or "")
        elif "json" in b:
            parts.append(json.dumps(b["json"], ensure_ascii=False))
        elif "image" in b or b.get("type") == "image":
            images += 1
    return ("\n".join(parts) if parts else None), images


def _blocks(content) -> list[dict]:
    if isinstance(content, str):
        return [{"text": content}]
    return [b for b in content or [] if isinstance(b, dict)]


def _call(block: dict) -> dict:
    tu = block.get("toolUse") or block
    return {"id": tu.get("toolUseId") or tu.get("id"), "name": tu.get("name") or "?",
            "arguments": mask_secrets(json.dumps(tu.get("input") or {}, ensure_ascii=False))}


def _is_call(b: dict) -> bool:
    return "toolUse" in b or b.get("type") == "tool_use"


def _is_result(b: dict) -> bool:
    return "toolResult" in b or b.get("type") == "tool_result"


def _is_image(b: dict) -> bool:
    return "image" in b or b.get("type") == "image"


def _tool_message(b: dict) -> dict:
    tr = b.get("toolResult") or b
    text, n = _result_text(tr.get("content"))
    msg = {"role": "tool", "content": mask_secrets(text),
           "tool_call_id": tr.get("toolUseId") or tr.get("tool_use_id")}
    if n:
        msg["n_images"] = n
    return msg


def _messages(raw) -> list[dict]:
    """Messages Converse ou Anthropic → messages du schéma (un résultat d'outil devient role=tool)."""
    out = []
    for m in raw if isinstance(raw, list) else []:
        if not isinstance(m, dict):
            continue
        blocks = _blocks(m.get("content"))
        texts = [b["text"] for b in blocks if isinstance(b.get("text"), str) and b.get("type") in (None, "text")]
        calls = [_call(b) for b in blocks if _is_call(b)]
        images = sum(_is_image(b) for b in blocks)
        tools = [_tool_message(b) for b in blocks if _is_result(b)]
        if texts or calls or images or not tools:
            msg = {"role": "assistant" if m.get("role") == "assistant" else "user",
                   "content": mask_secrets("\n".join(texts)) if texts else None}
            if calls:
                msg["tool_calls"] = calls
            if images:
                msg["n_images"] = images
            out.append(msg)
        out.extend(tools)
    return out


def _system(raw) -> str | None:
    if isinstance(raw, str):
        return mask_secrets(raw) or None
    text = "\n".join(b.get("text", "") for b in _blocks(raw) if "text" in b)
    return mask_secrets(text) or None


def _tools(request: dict) -> list[dict]:
    out = []
    declared = ((request.get("toolConfig") or {}).get("tools") or []) + (request.get("tools") or [])
    for t in declared:
        if not isinstance(t, dict):
            continue
        spec = t.get("toolSpec") or t
        schema = spec.get("input_schema") or (spec.get("inputSchema") or {}).get("json")
        if spec.get("name"):
            out.append({"name": spec["name"], "description": spec.get("description"),
                        "parameters": schema if isinstance(schema, dict) else None})
    return out


def _reply_blocks(blocks) -> tuple[str | None, list[dict]]:
    bl = _blocks(blocks)
    text = "".join(b["text"] for b in bl if isinstance(b.get("text"), str) and b.get("type") in (None, "text"))
    return (mask_secrets(text) if text else None), [_call(b) for b in bl if _is_call(b)]


def _chunk(item):
    """Un morceau de flux : dict direct, ou {"chunk": {"bytes": base64}} (InvokeModelWithResponseStream)."""
    if isinstance(item, dict) and isinstance(item.get("chunk"), dict) and "bytes" in item["chunk"]:
        try:
            return json.loads(base64.b64decode(item["chunk"]["bytes"]))
        except ValueError:
            return None
    return item


def _stream_event(e: dict, blocks: dict, reply: dict) -> None:
    """Applique un évènement de flux (Converse ou Anthropic) à l'état en cours de reconstitution."""
    new = {"text": "", "tool": None, "json": ""}
    if "contentBlockStart" in e or "contentBlockDelta" in e:  # Converse
        part = e.get("contentBlockStart") or e["contentBlockDelta"]
        b = blocks.setdefault(part.get("contentBlockIndex", 0), new)
        tool = ((part.get("start") or {}).get("toolUse"))
        if tool:
            b["tool"] = {"toolUseId": tool.get("toolUseId"), "name": tool.get("name")}
        delta = part.get("delta") or {}
        b["text"] += delta.get("text") or ""
        b["json"] += (delta.get("toolUse") or {}).get("input") or ""
    elif "messageStop" in e:
        reply["stop_reason"] = e["messageStop"].get("stopReason")
    elif "metadata" in e:
        reply["usage"] = e["metadata"].get("usage") or {}
    elif e.get("type") == "message_start":  # Anthropic
        reply["usage"] = dict((e.get("message") or {}).get("usage") or {})
    elif e.get("type") == "content_block_start":
        cb = e.get("content_block") or {}
        tool = {"id": cb.get("id"), "name": cb.get("name")} if cb.get("type") == "tool_use" else None
        blocks[e.get("index", 0)] = {"text": cb.get("text") or "", "tool": tool, "json": ""}
    elif e.get("type") == "content_block_delta":
        b = blocks.setdefault(e.get("index", 0), new)
        d = e.get("delta") or {}
        b["text"] += d.get("text") or ""
        b["json"] += d.get("partial_json") or ""
    elif e.get("type") == "message_delta":
        reply["stop_reason"] = (e.get("delta") or {}).get("stop_reason") or reply["stop_reason"]
        reply["usage"].update(e.get("usage") or {})


def _assemble_stream(events) -> dict | None:
    """Flux (liste d'évènements) → réponse équivalente non streamée, ou None si rien d'exploitable.

    La forme exacte du flux dans un journal réel n'est pas confirmée : voir la note du rapport.
    """
    blocks: dict[int, dict] = {}
    reply = {"content": [], "stop_reason": None, "usage": {}}
    seen = False
    for item in events if isinstance(events, list) else []:
        e = _chunk(item)
        if isinstance(e, dict):
            seen = True
            _stream_event(e, blocks, reply)
    if not seen:
        return None
    for _, b in sorted(blocks.items()):
        if b["tool"]:
            try:
                args = json.loads(b["json"]) if b["json"] else {}
            except ValueError:
                args = {}
            reply["content"].append({"toolUse": {**b["tool"], "input": args}})
        elif b["text"]:
            reply["content"].append({"text": b["text"]})
    return reply


def _reply(out_body, stream: bool):
    """Corps de sortie → (blocs, stopReason brut, usage du corps) quelle que soit la forme."""
    if stream or isinstance(out_body, list):
        r = _assemble_stream(out_body)
        return (r["content"], r["stop_reason"], r["usage"]) if r else (None, None, {})
    if not isinstance(out_body, dict):
        return None, None, {}
    if "output" in out_body:  # Converse
        content = ((out_body.get("output") or {}).get("message") or {}).get("content")
        return content, out_body.get("stopReason"), out_body.get("usage") or {}
    return out_body.get("content"), out_body.get("stop_reason"), out_body.get("usage") or {}


def _usage(record: dict, body_usage: dict) -> dict:
    """Compteurs de l'enregistrement d'abord, usage du corps en secours."""
    inp, out = record.get("input") or {}, record.get("output") or {}

    def pick(*values):
        return next((v for v in map(num, values) if v is not None), None)

    usage = {"input_tokens": pick(inp.get("inputTokenCount"), body_usage.get("inputTokens"),
                                  body_usage.get("input_tokens")),
             "output_tokens": pick(out.get("outputTokenCount"), body_usage.get("outputTokens"),
                                   body_usage.get("output_tokens")),
             "cached_input_tokens": pick(inp.get("cacheReadInputTokenCount"),
                                         body_usage.get("cacheReadInputTokens"),
                                         body_usage.get("cache_read_input_tokens")),
             "reasoning_tokens": None}
    write = pick(inp.get("cacheWriteInputTokenCount"), body_usage.get("cacheWriteInputTokens"),
                 body_usage.get("cache_creation_input_tokens"))
    if write is not None:
        usage["cache_write_input_tokens"] = write
    return usage


def _refused(record: dict) -> str | None:
    """Raison d'ignorer un enregistrement (validation à la frontière), ou None."""
    model = record.get("modelId")
    if record.get("operation") not in OPERATIONS:
        return f"opération non prise en charge : {record.get('operation')!r}"
    if not isinstance(model, str) or not model:
        return "enregistrement sans modelId"
    if ts(record.get("timestamp")) is None:
        return "enregistrement sans horodatage lisible"
    if "embed" in model.lower():
        return "appel d'embedding : pas un appel de génération"
    return None


def convert(record: dict, bodies: dict[str, bytes], report: Comprehension) -> dict | None:
    """Un enregistrement → événement v1, ou None si ignoré (raison notée dans le rapport)."""
    reason = _refused(record)
    if reason:
        report.ignore(reason)
        return None
    op, model, when = record["operation"], record["modelId"], ts(record["timestamp"])
    inp, out = record.get("input") or {}, record.get("output") or {}
    in_body = _body(inp, "inputBody", bodies, report)
    out_body = _body(out, "outputBody", bodies, report)
    stream = "Stream" in op
    request = in_body if isinstance(in_body, dict) else {}
    chat_format = "messages" in request or op in ("Converse", "ConverseStream")
    blocks, raw_stop, body_usage = _reply(out_body, stream)
    usage = _usage(record, body_usage)
    if usage["input_tokens"] is None and usage["output_tokens"] is None:
        report.ignore("enregistrement sans compteur de jetons")
        return None

    text, calls = _reply_blocks(blocks)
    messages = _messages(request.get("messages")) if chat_format else []
    has_content = bool(messages or text or calls)
    if in_body is None and out_body is None:
        report.add("appels_sans_contenu", 1)
    elif not has_content and not chat_format:
        report.add("appels_format_non_reconnu", 1)
    tags = record.get("requestMetadata") if isinstance(record.get("requestMetadata"), dict) else {}
    role = _role_name((record.get("identity") or {}).get("arn"))
    trace_id = _tag(tags, TRACE_TAGS)
    region = record.get("inferenceRegion") or record.get("region")
    metrics = out_body.get("metrics") if isinstance(out_body, dict) else None
    latency = num((metrics or {}).get("latencyMs")) or 0
    error_code = record.get("errorCode")
    inference = request.get("inferenceConfig") or {}
    stop = inference.get("stopSequences") or request.get("stop_sequences")
    resolved = out_body.get("model") if isinstance(out_body, dict) else None

    if usage.get("cache_write_input_tokens"):
        report.add("jetons_ecrits_en_cache", usage["cache_write_input_tokens"])
    report.calls += 1
    report.sessions.add(trace_id or record.get("requestId") or "")
    if usage["input_tokens"] is not None:
        report.with_usage += 1
    if has_content:
        report.with_content += 1
    return {
        "schema_version": "1",
        "event_id": f"bedrock-{record.get('requestId') or int(when * 1000)}",
        "trace": {"id": f"bedrock:{trace_id}" if trace_id else None,
                  "source": "header" if trace_id else None, "step": None},
        "app_id": f"bedrock:{_tag(tags, APP_TAGS) or role or 'default'}",
        "ts_start": iso(when),
        "ts_end": iso(when + latency / 1000),
        "latency_ms": latency,
        "ttft_ms": None,
        "provider": "anthropic",
        "upstream": f"bedrock-runtime.{region}.amazonaws.com" if region else "bedrock-runtime.amazonaws.com",
        "endpoint": f"/{op}",
        "model": model,
        "model_resolved": resolved if isinstance(resolved, str) else None,
        "request": {"system": _system(request.get("system")), "messages": messages, "tools": _tools(request),
                    "params": {"stream": stream,
                               "temperature": inference.get("temperature", request.get("temperature")),
                               "top_p": inference.get("topP", request.get("top_p")),
                               "max_tokens": num(inference.get("maxTokens", request.get("max_tokens"))),
                               "stop": stop if isinstance(stop, list) else None, "response_format": None}},
        "response": {"content": text, "tool_calls": calls,
                     "finish_reason": "error" if error_code else FINISH.get(raw_stop, "other" if raw_stop else None),
                     "finish_reason_raw": raw_stop},
        "usage": usage,
        "http_status": HTTP_BY_ERROR.get(error_code, 500) if error_code else 200,
        "error": {"type": str(error_code), "message": str(error_code)} if error_code else None,
    }
