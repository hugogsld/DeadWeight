"""Faux OpenAI local pour les tests et la mesure de latence : aucune clé, aucun réseau.

    model "slow"         : streaming avec 300 ms entre deux morceaux
    model "bad-key"      : 401 qui recopie la clé, comme le vrai OpenAI
    model "rate-limited" : 429 au format d'erreur OpenAI
    model "tools"        : appel d'outil (streamé ou non)
    model "incomplete"   : /v1/responses seulement, réponse coupée par max_output_tokens
POST /v1/responses : API Responses (formes de la spécification OpenAPI d'OpenAI), streaming compris.
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


RESP_USAGE = {"input_tokens": 30, "input_tokens_details": {"cached_tokens": 8}, "output_tokens": 11,
              "output_tokens_details": {"reasoning_tokens": 4}, "total_tokens": 41}


def _response(model, status="completed", output=None, incomplete=None, usage=True):
    return {"id": "resp_fake", "object": "response", "created_at": 1, "status": status, "error": None,
            "incomplete_details": incomplete, "model": model + "-2026", "output": output or [],
            "usage": RESP_USAGE if usage else None}


def _item(model):
    if model == "tools":
        return {"type": "function_call", "id": "fc_1", "call_id": "call_1", "name": "get_weather",
                "arguments": '{"city":"Paris"}', "status": "completed"}
    return {"type": "message", "id": "msg_1", "status": "completed", "role": "assistant",
            "content": [{"type": "output_text", "text": "".join(WORDS), "annotations": []}]}


def _ev(kind, **fields):
    return f"event: {kind}\ndata: {json.dumps({'type': kind, **fields})}\n\n".encode()


async def responses(request):
    request.app[SEEN].append(dict(request.headers))
    body = await request.json()
    model = body.get("model", "gpt-4o")
    if model == "bad-key":
        sent = request.headers.get("Authorization", "").removeprefix("Bearer ")
        return web.json_response({"error": {"message": f"Incorrect API key provided: {sent}. You can find...",
                                             "type": "invalid_request_error", "param": None,
                                             "code": "invalid_api_key"}}, status=401)
    if model == "rate-limited":
        return web.json_response({"error": {"message": "Rate limit reached", "type": "requests",
                                             "param": None, "code": "rate_limit_exceeded"}}, status=429)
    item = _item(model)
    if model == "incomplete":
        full = _response(model, "incomplete", [item], {"reason": "max_output_tokens"})
    else:
        full = _response(model, output=[item])
    if not body.get("stream"):
        return web.json_response(full)

    resp = web.StreamResponse(headers={"Content-Type": "text/event-stream; charset=utf-8"})
    await resp.prepare(request)
    pending = _response(model, "in_progress", usage=False)
    parts = [_ev("response.created", sequence_number=0, response=pending),
             _ev("response.in_progress", sequence_number=1, response=pending)]
    if model == "tools":
        parts += [_ev("response.output_item.added", output_index=0, item=dict(item, arguments="", status="in_progress")),
                  _ev("response.function_call_arguments.delta", item_id="fc_1", output_index=0, delta='{"city":'),
                  _ev("response.function_call_arguments.delta", item_id="fc_1", output_index=0, delta='"Paris"}'),
                  _ev("response.function_call_arguments.done", item_id="fc_1", output_index=0,
                      arguments=item["arguments"])]
    else:
        parts.append(_ev("response.output_item.added", output_index=0, item=dict(item, content=[], status="in_progress")))
        parts += [_ev("response.output_text.delta", item_id="msg_1", output_index=0, content_index=0, delta=w)
                  for w in WORDS]
        parts.append(_ev("response.output_text.done", item_id="msg_1", output_index=0, content_index=0,
                         text="".join(WORDS)))
    parts += [_ev("response.output_item.done", output_index=0, item=item),
              _ev("response.incomplete" if model == "incomplete" else "response.completed", response=full)]
    for p in parts:
        await resp.write(p)
        if request.app[DELAY]:
            await asyncio.sleep(request.app[DELAY])
    await resp.write_eof()
    return resp


async def models(request):
    return web.json_response({"object": "list", "data": [{"id": "gpt-4o", "object": "model"}]})


def make_app(delay=0.0):
    app = web.Application()
    app[SEEN] = []
    app[DELAY] = delay
    app.router.add_post("/v1/chat/completions", chat)
    app.router.add_post("/v1/responses", responses)
    app.router.add_get("/v1/models", models)
    return app
