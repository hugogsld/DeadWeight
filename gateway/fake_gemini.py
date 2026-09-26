"""Faux Gemini local (models/<modele>:generateContent | :streamGenerateContent) pour les tests.

Formats calqués sur l'API REST réelle : SSE avec ?alt=sse, sinon tableau JSON par morceaux.
    model "bad-key" : 400 INVALID_ARGUMENT « API key not valid »
    model "tools"   : functionCall (streamé ou non)
"""
import json

from aiohttp import web

WORDS = ["Bonjour", " le", " monde."]
USAGE = {"promptTokenCount": 9, "candidatesTokenCount": 5, "totalTokenCount": 30,
         "cachedContentTokenCount": 4, "thoughtsTokenCount": 16}


def _chunk(model, parts, finish=None, usage=None):
    cand = {"content": {"role": "model", "parts": parts}, "index": 0}
    if finish:
        cand["finishReason"] = finish
    obj = {"candidates": [cand], "modelVersion": model + "-001", "responseId": "resp_fake"}
    if usage:
        obj["usageMetadata"] = usage
    return obj


async def generate(request):
    name = request.match_info["name"]
    model, _, method = name.partition(":")
    if model == "bad-key":
        return web.json_response({"error": {"code": 400, "message": "API key not valid. Please pass a valid API key.",
                                            "status": "INVALID_ARGUMENT"}}, status=400)
    tools = model == "tools"
    call = {"functionCall": {"name": "get_weather", "args": {"city": "Paris"}}}
    if tools:
        chunks = [_chunk(model, [{"text": "Je regarde.", "thought": True}]),
                  _chunk(model, [call], "STOP", USAGE)]
    else:
        chunks = [_chunk(model, [{"text": w}]) for w in WORDS[:-1]]
        chunks.append(_chunk(model, [{"text": WORDS[-1]}], "STOP", USAGE))

    if method == "generateContent":
        parts = [call] if tools else [{"text": "".join(WORDS)}]
        return web.json_response(_chunk(model, parts, "STOP", USAGE))

    sse = request.query.get("alt") == "sse"
    resp = web.StreamResponse(headers={"Content-Type": "text/event-stream" if sse else "application/json"})
    await resp.prepare(request)
    for i, c in enumerate(chunks):
        if sse:
            await resp.write(b"data: " + json.dumps(c).encode() + b"\r\n\r\n")
        else:
            await resp.write((b"[" if i == 0 else b"\n,\r\n") + json.dumps(c).encode())
    if not sse:
        await resp.write(b"]")
    await resp.write_eof()
    return resp


def make_app():
    app = web.Application()
    app.router.add_post("/v1beta/models/{name}", generate)
    return app
