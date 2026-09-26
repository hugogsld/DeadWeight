"""Normalisation d'un appel OpenAI /v1/chat/completions vers le schéma d'événement v1.

Tout ici tourne APRÈS que la réponse a été rendue au client, ou à côté du
relais en streaming : rien de ce module n'est sur le chemin critique.
Aucun en-tête n'entre dans l'événement : la clé du client ne peut pas fuiter.
"""
import json
import re
import uuid

FINISH = {"stop": "stop", "length": "length", "tool_calls": "tool_calls",
          "function_call": "tool_calls", "content_filter": "content_filter"}
RESPONSE_FORMATS = {"text", "json_object", "json_schema"}
# OpenAI recopie la clé dans ses erreurs 401 ("Incorrect API key provided: sk-...").
KEY_LIKE = re.compile(r"\b(sk|rk|pk|sess)-[A-Za-z0-9_\-*]{3,}")


def _text(content):
    """Texte d'un content OpenAI (chaîne ou liste de parts) + nombre d'images."""
    if content is None or isinstance(content, str):
        return content, 0
    texts, images = [], 0
    for part in content if isinstance(content, list) else []:
        kind = part.get("type") if isinstance(part, dict) else None
        if kind in ("text", "input_text"):
            texts.append(part.get("text") or "")
        elif kind in ("image_url", "input_image", "image"):
            images += 1
    return ("\n".join(texts) if texts else None), images


def _tool_calls(calls):
    out = []
    for c in calls or []:
        fn = c.get("function") or {}
        args = fn.get("arguments")
        out.append({"id": c.get("id"), "name": fn.get("name") or "",
                    "arguments": args if isinstance(args, str) else json.dumps(args or {})})
    return out


def normalize_request(body):
    """Corps JSON de la requête client -> (model, request au schéma)."""
    system, messages = [], []
    for m in body.get("messages") or []:
        role = m.get("role")
        text, images = _text(m.get("content"))
        if role in ("system", "developer"):
            if text:
                system.append(text)
            continue
        msg = {"role": "tool" if role in ("tool", "function") else role, "content": text}
        if msg["role"] not in ("user", "assistant", "tool"):
            msg["role"] = "user"
        if m.get("tool_calls"):
            msg["tool_calls"] = _tool_calls(m["tool_calls"])
        if msg["role"] == "tool":
            msg["tool_call_id"] = m.get("tool_call_id")
        if images:
            msg["n_images"] = images
        messages.append(msg)

    tools = []
    for t in body.get("tools") or []:
        fn = t.get("function") or {}
        if fn.get("name"):
            tools.append({"name": fn["name"], "description": fn.get("description"),
                          "parameters": fn.get("parameters")})
    for fn in body.get("functions") or []:  # ancien format
        if fn.get("name"):
            tools.append({"name": fn["name"], "description": fn.get("description"),
                          "parameters": fn.get("parameters")})

    stop = body.get("stop")
    rf = body.get("response_format")
    rf = rf.get("type") if isinstance(rf, dict) else None
    params = {
        "stream": bool(body.get("stream")),
        "temperature": body.get("temperature"),
        "top_p": body.get("top_p"),
        "max_tokens": body.get("max_completion_tokens", body.get("max_tokens")),
        "stop": [stop] if isinstance(stop, str) else stop,
        "response_format": rf if rf in RESPONSE_FORMATS else None,
    }
    request = {"system": "\n\n".join(system) or None, "messages": messages,
               "tools": tools, "params": params}
    return str(body.get("model") or "unknown"), request


def _usage(u):
    u = u or {}
    return {"input_tokens": u.get("prompt_tokens"),
            "output_tokens": u.get("completion_tokens"),
            "cached_input_tokens": (u.get("prompt_tokens_details") or {}).get("cached_tokens"),
            "reasoning_tokens": (u.get("completion_tokens_details") or {}).get("reasoning_tokens")}


def _error(payload, status):
    err = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(err, dict):
        kind, message = str(err.get("code") or err.get("type") or "http_error"), str(err.get("message") or "")
    elif isinstance(err, str):
        kind, message = "http_error", err
    else:
        kind, message = "http_error", f"HTTP {status}"
    return {"type": kind, "message": KEY_LIKE.sub("[clé masquée]", message)}


class StreamAccumulator:
    """Reconstitue la complétion à partir des octets SSE relayés, sans les retenir."""

    def __init__(self):
        self._buf = b""
        self.content = []
        self.tools = {}
        self.finish_raw = None
        self.model = None
        self.usage = None
        self.error = None

    def feed(self, chunk):
        self._buf += chunk
        while True:
            # séparateur d'événement SSE : ligne vide, quelle que soit la fin de ligne
            idx = [i for i in (self._buf.find(b"\n\n"), self._buf.find(b"\r\n\r\n")) if i >= 0]
            if not idx:
                return
            cut = min(idx)
            sep = 4 if self._buf[cut:cut + 4] == b"\r\n\r\n" else 2
            raw, self._buf = self._buf[:cut], self._buf[cut + sep:]
            self._event(raw)

    def _event(self, raw):
        data = "\n".join(line[5:].lstrip() for line in raw.decode("utf-8", "replace").splitlines()
                         if line.startswith("data:"))
        if not data or data == "[DONE]":
            return
        try:
            obj = json.loads(data)
        except ValueError:
            return
        if obj.get("error"):
            self.error = _error(obj, 200)
            return
        self.model = obj.get("model") or self.model
        if obj.get("usage"):
            self.usage = obj["usage"]
        for choice in obj.get("choices") or []:
            if choice.get("index", 0) != 0:
                continue
            delta = choice.get("delta") or {}
            if delta.get("content"):
                self.content.append(delta["content"])
            for tc in delta.get("tool_calls") or []:
                slot = self.tools.setdefault(tc.get("index", 0), {"id": None, "name": "", "arguments": ""})
                slot["id"] = tc.get("id") or slot["id"]
                fn = tc.get("function") or {}
                slot["name"] += fn.get("name") or ""
                slot["arguments"] += fn.get("arguments") or ""
            if choice.get("finish_reason"):
                self.finish_raw = choice["finish_reason"]


def build_event(*, req_body, status, resp_body=None, stream=None, upstream, app_id, trace_id,
                endpoint, ts_start, ts_end, latency_ms, ttft_ms, transport_error=None):
    """Assemble l'événement v1. ``resp_body`` : octets de la réponse non streamée."""
    try:
        model, request = normalize_request(json.loads(req_body) if req_body else {})
    except (ValueError, AttributeError):
        model, request = "unknown", {"system": None, "messages": [], "tools": [],
                                     "params": {"stream": False}}

    content, tool_calls, finish_raw, model_resolved, usage, error = None, [], None, None, {}, None
    if stream is not None:
        content = "".join(stream.content) or None
        tool_calls = [stream.tools[i] for i in sorted(stream.tools)]
        finish_raw, model_resolved, usage, error = stream.finish_raw, stream.model, stream.usage, stream.error
    elif resp_body:
        try:
            payload = json.loads(resp_body)
        except ValueError:
            payload = {}
        if status >= 400:
            error = _error(payload, status)
        elif isinstance(payload, dict):
            choice = (payload.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            content, _ = _text(message.get("content"))
            tool_calls = _tool_calls(message.get("tool_calls"))
            finish_raw = choice.get("finish_reason")
            model_resolved, usage = payload.get("model"), payload.get("usage")
    if transport_error:
        error = transport_error
    if status >= 400 and error is None:
        error = {"type": "http_error", "message": f"HTTP {status}"}

    return {
        "schema_version": "1",
        "event_id": "evt_" + uuid.uuid4().hex,
        "trace": {"id": trace_id, "source": "header" if trace_id else None, "step": None},
        "app_id": app_id,
        "ts_start": ts_start,
        "ts_end": ts_end,
        "latency_ms": round(latency_ms, 3),
        "ttft_ms": None if ttft_ms is None else round(ttft_ms, 3),
        "provider": "openai",
        "upstream": upstream,
        "endpoint": endpoint,
        "model": model,
        "model_resolved": model_resolved,
        "request": request,
        "response": {"content": content, "tool_calls": tool_calls,
                     "finish_reason": "error" if error else (FINISH.get(finish_raw, "other") if finish_raw else None),
                     "finish_reason_raw": "error" if error and not finish_raw else finish_raw},
        "usage": _usage(usage),
        "http_status": status,
        "error": error,
    }
