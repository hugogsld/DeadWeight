"""Faux OpenAI local pour les tests et la mesure de latence : aucune clé, aucun réseau.

    model "slow"         : streaming avec 300 ms entre deux morceaux
    model "bad-key"      : 401 qui recopie la clé, comme le vrai OpenAI
    model "rate-limited" : 429 au format d'erreur OpenAI
    model "tools"        : appel d'outil (streamé ou non)
"""
import asyncio
import json

from aiohttp import web

SEEN = web.AppKey("seen_headers", list)
DELAY = web.AppKey("delay", float)
WORDS = ["Bonjour", " ", "le", " ", "monde", "."]


def _sse(model, **fields):
    obj = {"id": "chatcmpl-fake", "object": "chat.completion.chunk", "created": 1, "model": model + "-2026", **fields}
    return ("data: " + json.dumps(obj) + "\n\n").encode()


def _chunk(model, delta, finish=None):
    return _sse(model, choices=[{"index": 0, "delta": delta, "finish_reason": finish}])


USAGE = {"prompt_tokens": 12, "completion_tokens": 6, "total_tokens": 18,
         "prompt_tokens_details": {"cached_tokens": 0}, "completion_tokens_details": {"reasoning_tokens": 0}}


async def chat(request):
    request.app[SEEN].append(dict(request.headers))
    body = await request.json()
    model = body.get("model", "gpt-4o")
    if model == "bad-key":
        key = request.headers.get("Authorization", "").removeprefix("Bearer ")
        return web.json_response({"error": {"message": f"Incorrect API key provided: {key}. You can find...",
                                             "type": "invalid_request_error", "param": None,
                                             "code": "invalid_api_key"}}, status=401)
    if model == "rate-limited":
        return web.json_response({"error": {"message": "Rate limit reached", "type": "requests",
                                             "param": None, "code": "rate_limit_exceeded"}}, status=429)
    tool = {"id": "call_1", "type": "function", "function": {"name": "get_weather", "arguments": '{"city":"Paris"}'}}

    if not body.get("stream"):
        message = ({"role": "assistant", "content": None, "tool_calls": [tool]} if model == "tools"
                   else {"role": "assistant", "content": "".join(WORDS)})
        return web.json_response({
            "id": "chatcmpl-fake", "object": "chat.completion", "created": 1, "model": model + "-2026",
            "choices": [{"index": 0, "message": message, "logprobs": None,
                         "finish_reason": "tool_calls" if model == "tools" else "stop"}],
            "usage": USAGE})

    resp = web.StreamResponse(headers={"Content-Type": "text/event-stream; charset=utf-8"})
    await resp.prepare(request)
    delay = 0.3 if model == "slow" else request.app[DELAY]
    if model == "tools":
        parts = [_chunk(model, {"role": "assistant", "tool_calls": [
                     {"index": 0, "id": "call_1", "type": "function", "function": {"name": "get_weather", "arguments": ""}}]}),
                 _chunk(model, {"tool_calls": [{"index": 0, "function": {"arguments": '{"city":'}}]}),
                 _chunk(model, {"tool_calls": [{"index": 0, "function": {"arguments": '"Paris"}'}}]}),
                 _chunk(model, {}, "tool_calls")]
    else:
        parts = [_chunk(model, {"role": "assistant", "content": ""})]
        parts += [_chunk(model, {"content": w}) for w in WORDS]
        parts.append(_chunk(model, {}, "stop"))
    if (body.get("stream_options") or {}).get("include_usage"):
        parts.append(_sse(model, choices=[], usage=USAGE))
    parts.append(b"data: [DONE]\n\n")
    for p in parts:
        await resp.write(p)
        if delay:
            await asyncio.sleep(delay)
    await resp.write_eof()
    return resp


async def models(request):
    return web.json_response({"object": "list", "data": [{"id": "gpt-4o", "object": "model"}]})


def make_app(delay=0.0):
    app = web.Application()
    app[SEEN] = []
    app[DELAY] = delay
    app.router.add_post("/v1/chat/completions", chat)
    app.router.add_get("/v1/models", models)
    return app
