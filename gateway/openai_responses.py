"""Normalisation d'un appel OpenAI POST /v1/responses (API Responses) vers le schéma d'événement v1.

C'est l'API par défaut du SDK Agents d'OpenAI et celle que le SDK ``openai`` recommande aujourd'hui.
Mêmes fonctions que gateway/capture.py (chat/completions) ; formes d'après la spécification OpenAPI
publiée par OpenAI (``Response``, ``ResponseUsage``, ``response.completed``…).

Limite connue : avec ``previous_response_id`` le contexte reste chez OpenAI, la requête ne contient que le
nouveau tour. Les vérifications qui lisent l'historique envoyé (contexte brut, relecture) le voient tronqué.
"""
import json

from gateway.capture import SSEParser, mask_keys, parse_error  # noqa: F401  (parse_error : même forme d'erreur)

RESPONSE_FORMATS = {"text", "json_object", "json_schema"}


def _parts(content):
    """content d'un item (chaîne ou liste de parts) -> (texte, nombre d'images)."""
    if content is None or isinstance(content, str):
        return content, 0
    texts, images = [], 0
    for p in content if isinstance(content, list) else []:
        kind = p.get("type") if isinstance(p, dict) else None
        if kind in ("input_text", "output_text", "text"):
            texts.append(p.get("text") or "")
        elif kind == "input_image":
            images += 1
    return ("\n".join(texts) if texts else None), images


def _output_text(output):
    """``output`` d'un function_call_output : chaîne, ou liste de parts."""
    return output if isinstance(output, str) or output is None else _parts(output)[0]


def normalize_request(body, path=None):
    """Corps JSON de la requête client -> (model, request au schéma)."""
    system, messages = [], []
    if isinstance(body.get("instructions"), str) and body["instructions"]:
        system.append(body["instructions"])
    items = body.get("input")
    for item in [{"role": "user", "content": items}] if isinstance(items, str) else items or []:
        if not isinstance(item, dict):
            continue
        kind = item.get("type") or "message"
        if kind == "message":
            role, (text, images) = item.get("role"), _parts(item.get("content"))
            if role in ("system", "developer"):
                if text:
                    system.append(text)
                continue
            msg = {"role": "assistant" if role == "assistant" else "user", "content": text}
            if images:
                msg["n_images"] = images
            messages.append(msg)
        elif kind == "function_call":
            args = item.get("arguments")
            messages.append({"role": "assistant", "content": None, "tool_calls": [
                {"id": item.get("call_id"), "name": item.get("name") or "",
                 "arguments": args if isinstance(args, str) else json.dumps(args or {})}]})
        elif kind == "function_call_output":
            messages.append({"role": "tool", "content": _output_text(item.get("output")),
                             "tool_call_id": item.get("call_id")})
    tools = [{"name": t["name"], "description": t.get("description"), "parameters": t.get("parameters")}
             for t in body.get("tools") or [] if isinstance(t, dict) and t.get("type") == "function" and t.get("name")]
    fmt_ = (body.get("text") or {}).get("format") if isinstance(body.get("text"), dict) else None
    fmt_ = fmt_.get("type") if isinstance(fmt_, dict) else None
    params = {"stream": bool(body.get("stream")), "temperature": body.get("temperature"),
              "top_p": body.get("top_p"), "max_tokens": body.get("max_output_tokens"), "stop": None,
              "response_format": fmt_ if fmt_ in RESPONSE_FORMATS else None}
    request = {"system": "\n\n".join(system) or None, "messages": messages, "tools": tools, "params": params}
    return str(body.get("model") or "unknown"), request


def _usage(u):
    u = u or {}
    return {"input_tokens": u.get("input_tokens"), "output_tokens": u.get("output_tokens"),
            "cached_input_tokens": (u.get("input_tokens_details") or {}).get("cached_tokens"),
            "reasoning_tokens": (u.get("output_tokens_details") or {}).get("reasoning_tokens")}


def finish(raw, tool_calls=None):
    """``raw`` : ``incomplete_details.reason`` si la réponse est incomplète, sinon le statut."""
    if raw == "completed":
        return "tool_calls" if tool_calls else "stop"
    return {"max_output_tokens": "length", "content_filter": "content_filter"}.get(raw, "other")


def parse_response(payload):
    """Réponse non streamée (ou ``response`` d'un évènement final) ->
    (content, tool_calls, finish_raw, model_resolved, usage au schéma)."""
    texts, calls = [], []
    for item in payload.get("output") or []:
        if item.get("type") == "message":
            text, _ = _parts(item.get("content"))
            if text:
                texts.append(text)
        elif item.get("type") == "function_call":
            args = item.get("arguments")
            calls.append({"id": item.get("call_id") or item.get("id"), "name": item.get("name") or "",
                          "arguments": args if isinstance(args, str) else json.dumps(args or {})})
    status = payload.get("status")
    raw = (payload.get("incomplete_details") or {}).get("reason") if status == "incomplete" else status
    return ("\n".join(texts) or None, calls, raw or status, payload.get("model"), _usage(payload.get("usage")))


class Accumulator(SSEParser):
    """Reconstitue la réponse à partir des évènements SSE Responses. L'évènement final (``response.completed``,
    ``response.incomplete``, ``response.failed``) porte la réponse entière : c'est lui qui fait foi. Si le flux
    est coupé avant, on garde ce qui a été reçu (texte et arguments des deltas)."""

    def __init__(self):
        self.final = None
        self.deltas = []
        self.calls = {}
        self.model = None
        self.error = None

    def on_data(self, obj):
        kind = obj.get("type") or ""
        if kind in ("response.completed", "response.incomplete", "response.failed") and obj.get("response"):
            self.final = obj["response"]
        elif kind == "response.created":
            self.model = (obj.get("response") or {}).get("model")
        elif kind == "response.output_text.delta":
            self.deltas.append(obj.get("delta") or "")
        elif kind == "response.output_item.added" and (obj.get("item") or {}).get("type") == "function_call":
            item = obj["item"]
            self.calls[obj.get("output_index", 0)] = {"id": item.get("call_id") or item.get("id"),
                                                      "name": item.get("name") or "", "arguments": ""}
        elif kind == "response.function_call_arguments.delta" and obj.get("output_index", 0) in self.calls:
            self.calls[obj.get("output_index", 0)]["arguments"] += obj.get("delta") or ""
        elif kind == "error":
            self.error = {"type": str(obj.get("code") or "http_error"), "message": mask_keys(str(obj.get("message") or ""))}

    def result(self):
        if self.final is not None:
            content, calls, raw, model, usage = parse_response(self.final)
            err = self.final.get("error")
            if self.final.get("status") == "failed" and not self.error:
                err = err or {}
                self.error = {"type": str(err.get("code") or "failed"), "message": mask_keys(str(err.get("message") or ""))}
            return content, calls, raw, model or self.model, usage, self.error
        calls = [dict(c, arguments=c["arguments"] or "{}") for _, c in sorted(self.calls.items())]
        return "".join(self.deltas) or None, calls, None, self.model, _usage(None), self.error
