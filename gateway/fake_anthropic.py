"""Faux Anthropic local (POST /v1/messages) pour les tests : aucune clé, aucun réseau.

Formats calqués sur l'API Messages réelle, streaming SSE compris (event: + data:).
    model "bad-key" : 401 authentication_error
    model "tools"   : bloc tool_use (streamé ou non)
"""
import json

from aiohttp import web

WORDS = ["Bonjour", " le", " monde."]
USAGE = {"input_tokens": 21, "output_tokens": 7, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 5}


def _sse(kind, **fields):
    return f"event: {kind}\ndata: {json.dumps({'type': kind, **fields})}\n\n".encode()


async def messages(request):
    body = await request.json()
    model = body.get("model", "claude-sonnet-4-5")
    if model == "bad-key":
        return web.json_response({"type": "error", "error": {"type": "authentication_error",
                                                             "message": "invalid x-api-key"}}, status=401)
    tools = model == "tools"
    resolved = model + "-20260101"
    if not body.get("stream"):
        content = ([{"type": "text", "text": "Je regarde."},
                    {"type": "tool_use", "id": "toolu_1", "name": "get_weather", "input": {"city": "Paris"}}]
                   if tools else [{"type": "text", "text": "".join(WORDS)}])
        return web.json_response({"id": "msg_fake", "type": "message", "role": "assistant", "model": resolved,
                                  "content": content, "stop_reason": "tool_use" if tools else "end_turn",
                                  "stop_sequence": None, "usage": USAGE})

    resp = web.StreamResponse(headers={"Content-Type": "text/event-stream; charset=utf-8"})
    await resp.prepare(request)
    start_usage = dict(USAGE, output_tokens=1)
    parts = [_sse("message_start", message={"id": "msg_fake", "type": "message", "role": "assistant",
                                            "model": resolved, "content": [], "stop_reason": None,
                                            "stop_sequence": None, "usage": start_usage}),
             _sse("ping")]
    if tools:
        parts += [_sse("content_block_start", index=0, content_block={"type": "tool_use", "id": "toolu_1",
                                                                      "name": "get_weather", "input": {}}),
                  _sse("content_block_delta", index=0, delta={"type": "input_json_delta", "partial_json": '{"city":'}),
                  _sse("content_block_delta", index=0, delta={"type": "input_json_delta", "partial_json": ' "Paris"}'}),
                  _sse("content_block_stop", index=0)]
    else:
        parts.append(_sse("content_block_start", index=0, content_block={"type": "text", "text": ""}))
        parts += [_sse("content_block_delta", index=0, delta={"type": "text_delta", "text": w}) for w in WORDS]
        parts.append(_sse("content_block_stop", index=0))
    parts += [_sse("message_delta", delta={"stop_reason": "tool_use" if tools else "end_turn", "stop_sequence": None},
                   usage={"output_tokens": USAGE["output_tokens"]}),
              _sse("message_stop")]
    for p in parts:
        await resp.write(p)
    await resp.write_eof()
    return resp


def make_app():
    app = web.Application()
    app.router.add_post("/v1/messages", messages)
    return app
