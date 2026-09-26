"""D1.3 — Normalisation d'un appel Gemini (models/<modele>:generateContent ou
:streamGenerateContent) vers le schéma d'événement v1.

Mêmes fonctions que gateway/capture.py (OpenAI) ; correspondances dans schemas/EVENT.md.
L'API REST accepte camelCase et snake_case : on lit les deux. Le modèle vient du chemin.
Streaming : SSE avec ?alt=sse (SDK officiel), sinon un tableau JSON envoyé par morceaux.
"""
import json
import re

from gateway.capture import SSEParser, mask_keys

FINISH = {"STOP": "stop", "MAX_TOKENS": "length", "SAFETY": "content_filter", "RECITATION": "content_filter",
          "BLOCKLIST": "content_filter", "PROHIBITED_CONTENT": "content_filter", "SPII": "content_filter",
          "IMAGE_SAFETY": "content_filter"}
MODEL_IN_PATH = re.compile(r"/models/([^/:]+):")


def _get(d, camel):
    """Champ ``camel`` ou son équivalent snake_case."""
    if not isinstance(d, dict):
        return None
    if camel in d:
        return d[camel]
    return d.get(re.sub(r"([A-Z])", lambda m: "_" + m.group(1).lower(), camel))


def _args(value):
    return json.dumps(value if value is not None else {}, ensure_ascii=False)


def _parts(parts):
    """parts Gemini -> (texte, n_images, tool_calls, réponses d'outils). Les parts « thought » sont ignorées.
    Sans ``id`` (cas courant), l'appel et sa réponse sont reliés par le nom de la fonction."""
    texts, images, calls, results = [], 0, [], []
    for p in parts or []:
        if not isinstance(p, dict) or p.get("thought"):
            continue
        blob = _get(p, "inlineData") or _get(p, "fileData")
        fc, fr = _get(p, "functionCall"), _get(p, "functionResponse")
        if p.get("text") is not None:
            texts.append(p["text"])
        elif blob:
            images += str(_get(blob, "mimeType") or "").startswith("image/")
        elif fc:
            calls.append({"id": fc.get("id") or fc.get("name"), "name": fc.get("name") or "",
                          "arguments": _args(fc.get("args"))})
        elif fr:
            results.append({"role": "tool", "content": _args(fr.get("response")),
                            "tool_call_id": fr.get("id") or fr.get("name")})
    return ("".join(texts) if texts else None), images, calls, results


def _response_format(cfg):
    if _get(cfg, "responseSchema") or _get(cfg, "responseJsonSchema"):
        return "json_schema"
    return {"application/json": "json_object", "text/plain": "text"}.get(_get(cfg, "responseMimeType"))


def normalize_request(body, path=None):
    system, _, _, _ = _parts((_get(body, "systemInstruction") or {}).get("parts"))
    messages = []
    for c in _get(body, "contents") or []:
        text, images, calls, results = _parts(c.get("parts"))
        messages += results  # functionResponse -> role=tool
        if text is None and not images and not calls and results:
            continue
        msg = {"role": "assistant" if c.get("role") == "model" else "user", "content": text}
        if calls:
            msg["tool_calls"] = calls
        if images:
            msg["n_images"] = images
        messages.append(msg)

    tools = []
    for t in _get(body, "tools") or []:
        for fn in _get(t, "functionDeclarations") or []:
            if fn.get("name"):
                tools.append({"name": fn["name"], "description": fn.get("description"),
                              "parameters": fn.get("parameters") or _get(fn, "parametersJsonSchema")})
    cfg = _get(body, "generationConfig") or {}
    params = {
        "stream": bool(path and path.endswith(":streamGenerateContent")),
        "temperature": cfg.get("temperature"),
        "top_p": _get(cfg, "topP"),
        "max_tokens": _get(cfg, "maxOutputTokens"),
        "stop": _get(cfg, "stopSequences"),
        "response_format": _response_format(cfg),
    }
    m = MODEL_IN_PATH.search(path or "")
    request = {"system": system, "messages": messages, "tools": tools, "params": params}
    return (m.group(1) if m else "unknown"), request


def _usage(u):
    return {"input_tokens": _get(u, "promptTokenCount"), "output_tokens": _get(u, "candidatesTokenCount"),
            "cached_input_tokens": _get(u, "cachedContentTokenCount"),
            "reasoning_tokens": _get(u, "thoughtsTokenCount")}


def parse_error(payload, status):
    err = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(err, dict):
        return {"type": str(err.get("status") or err.get("code") or "http_error"),
                "message": mask_keys(str(err.get("message") or ""))}
    return {"type": "http_error", "message": f"HTTP {status}"}


def finish(raw, tool_calls=None):
    if raw == "STOP" and tool_calls:
        return "tool_calls"
    return FINISH.get(raw, "other")


def parse_response(payload):
    cand = (payload.get("candidates") or [{}])[0]
    text, _, calls, _ = _parts((cand.get("content") or {}).get("parts"))
    raw = _get(cand, "finishReason") or _get(_get(payload, "promptFeedback"), "blockReason")
    return text, calls, raw, _get(payload, "modelVersion"), _usage(_get(payload, "usageMetadata"))


class Accumulator(SSEParser):
    """Reconstitue la réponse streamée, SSE (?alt=sse) ou tableau JSON."""

    def __init__(self):
        self.content = []
        self.calls = []
        self.finish_raw = None
        self.model = None
        self.usage = None
        self.error = None
        self._array = None  # None = pas encore vu le premier octet utile
        self._raw = b""

    def feed(self, chunk):
        if self._array is None:
            self._raw += chunk
            head = self._raw.lstrip()
            if not head:
                return
            self._array = head[:1] in (b"[", b"{")
            chunk, self._raw = (b"", self._raw) if self._array else (self._raw, b"")
        if self._array:
            self._raw += chunk
        else:
            super().feed(chunk)

    def on_data(self, obj):
        if obj.get("error"):
            self.error = parse_error(obj, 200)
            return
        text, calls, raw, model, usage = parse_response(obj)
        if text:
            self.content.append(text)
        self.calls += calls
        self.finish_raw = raw or self.finish_raw
        self.model = model or self.model
        if _get(obj, "usageMetadata"):
            self.usage = usage

    def result(self):
        if self._array and self._raw:
            try:
                data = json.loads(self._raw)
            except ValueError:
                data = []
            for obj in data if isinstance(data, list) else [data]:
                if isinstance(obj, dict):
                    self.on_data(obj)
            self._raw = b""
        return ("".join(self.content) or None, self.calls, self.finish_raw, self.model,
                self.usage or _usage(None), self.error)
