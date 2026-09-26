"""D1.3 — Normalisation d'un appel Anthropic POST /v1/messages vers le schéma d'événement v1.

Mêmes fonctions que gateway/capture.py (OpenAI) ; correspondances dans schemas/EVENT.md.
usage.input_tokens reste celui d'Anthropic, cache non inclus : report/cost.py en tient compte.
"""
import json

from gateway.capture import SSEParser, mask_keys

FINISH = {"end_turn": "stop", "stop_sequence": "stop", "max_tokens": "length",
          "tool_use": "tool_calls", "refusal": "content_filter"}


def _args(value):
    return json.dumps(value if value is not None else {}, ensure_ascii=False)


def _blocks(content):
    """content Anthropic (chaîne ou blocs) -> (texte, n_images, tool_calls, tool_results)."""
    if content is None or isinstance(content, str):
        return content, 0, [], []
    texts, images, calls, results = [], 0, [], []
    for b in content if isinstance(content, list) else []:
        kind = b.get("type") if isinstance(b, dict) else None
        if kind == "text":
            texts.append(b.get("text") or "")
        elif kind == "image":
            images += 1
        elif kind == "tool_use":
            calls.append({"id": b.get("id"), "name": b.get("name") or "", "arguments": _args(b.get("input"))})
        elif kind == "tool_result":
            text, n, _, _ = _blocks(b.get("content"))
            results.append({"role": "tool", "content": text, "tool_call_id": b.get("tool_use_id"),
                            **({"n_images": n} if n else {})})
    return ("\n".join(texts) if texts else None), images, calls, results


def normalize_request(body, path=None):
    system, _, _, _ = _blocks(body.get("system"))
    messages = []
    for m in body.get("messages") or []:
        text, images, calls, results = _blocks(m.get("content"))
        messages += results  # tool_result -> role=tool, avant le reste du tour
        if text is None and not images and not calls and results:
            continue
        msg = {"role": "assistant" if m.get("role") == "assistant" else "user", "content": text}
        if calls:
            msg["tool_calls"] = calls
        if images:
            msg["n_images"] = images
        messages.append(msg)

    tools = [{"name": t["name"], "description": t.get("description"), "parameters": t.get("input_schema")}
             for t in body.get("tools") or [] if isinstance(t, dict) and t.get("name")]
    params = {
        "stream": bool(body.get("stream")),
        "temperature": body.get("temperature"),
        "top_p": body.get("top_p"),
        "max_tokens": body.get("max_tokens"),
        "stop": body.get("stop_sequences"),
        "response_format": None,
    }
    request = {"system": system, "messages": messages, "tools": tools, "params": params}
    return str(body.get("model") or "unknown"), request


def _usage(u):
    u = u or {}
    return {"input_tokens": u.get("input_tokens"), "output_tokens": u.get("output_tokens"),
            "cached_input_tokens": u.get("cache_read_input_tokens"), "reasoning_tokens": None}


def parse_error(payload, status):
    err = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(err, dict):
        return {"type": str(err.get("type") or "http_error"), "message": mask_keys(str(err.get("message") or ""))}
    return {"type": "http_error", "message": f"HTTP {status}"}


def finish(raw, tool_calls=None):
    return FINISH.get(raw, "other")


def parse_response(payload):
    text, _, calls, _ = _blocks(payload.get("content"))
    return text, calls, payload.get("stop_reason"), payload.get("model"), _usage(payload.get("usage"))


class Accumulator(SSEParser):
    """Reconstitue le message à partir des événements SSE Anthropic relayés."""

    def __init__(self):
        self.content = []
        self.tools = {}
        self.finish_raw = None
        self.model = None
        self.usage = {}
        self.error = None

    def on_data(self, obj):
        kind = obj.get("type")
        if kind == "message_start":
            msg = obj.get("message") or {}
            self.model = msg.get("model")
            self.usage.update(msg.get("usage") or {})
        elif kind == "content_block_start":
            block = obj.get("content_block") or {}
            if block.get("type") == "tool_use":
                self.tools[obj.get("index", 0)] = {"id": block.get("id"), "name": block.get("name") or "",
                                                   "arguments": ""}
            elif block.get("type") == "text" and block.get("text"):
                self.content.append(block["text"])
        elif kind == "content_block_delta":
            delta = obj.get("delta") or {}
            if delta.get("type") == "text_delta":
                self.content.append(delta.get("text") or "")
            elif delta.get("type") == "input_json_delta" and obj.get("index", 0) in self.tools:
                self.tools[obj.get("index", 0)]["arguments"] += delta.get("partial_json") or ""
        elif kind == "message_delta":
            self.finish_raw = (obj.get("delta") or {}).get("stop_reason") or self.finish_raw
            self.usage.update({k: v for k, v in (obj.get("usage") or {}).items() if v is not None})
        elif kind == "error":
            self.error = parse_error(obj, 200)

    def result(self):
        calls = [dict(t, arguments=t["arguments"] or "{}") for _, t in sorted(self.tools.items())]
        return ("".join(self.content) or None, calls, self.finish_raw, self.model,
                _usage(self.usage), self.error)
