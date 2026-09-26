"""D1.3 : relais Anthropic et Gemini, normalisation vers le schéma commun."""
import asyncio
import json
from pathlib import Path

import aiohttp
import jsonschema
from aiohttp import web

from gateway import fake_anthropic, fake_gemini
from gateway.proxy import make_app, route

SCHEMA = json.loads((Path(__file__).resolve().parents[1] / "schemas/event.schema.json").read_text())

ANT_KEY = "sk-ant-NE-DOIT-JAMAIS-SORTIR"
GEM_KEY = "AIzaNE-DOIT-JAMAIS-SORTIR"


async def _serve(app):
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    return runner, f"http://127.0.0.1:{runner.addresses[0][1]}"


def _echo_app(seen):
    async def handler(request):
        seen.append({"path": request.path, "query": request.query_string, "headers": dict(request.headers)})
        return web.json_response({"ok": request.path})
    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", handler)
    return app


def test_route():
    assert route("/v1/chat/completions") == ("openai", "/v1/chat/completions")
    assert route("/anthropic/v1/messages") == ("anthropic", "/v1/messages")
    assert route("/gemini/v1beta/models/gemini-2.5-flash:generateContent") == (
        "gemini", "/v1beta/models/gemini-2.5-flash:generateContent")
    assert route("/anthropicfoo") == ("openai", "/anthropicfoo")


def test_relay_reaches_right_provider_with_key():
    async def main():
        seen = {"openai": [], "anthropic": [], "gemini": []}
        runners, urls = [], {}
        for name in seen:
            r, u = await _serve(_echo_app(seen[name]))
            runners.append(r)
            urls[name] = u
        gw_runner, gw = await _serve(make_app(upstream=urls["openai"], on_event=lambda e: None,
                                              upstreams={"anthropic": urls["anthropic"], "gemini": urls["gemini"]}))
        try:
            async with aiohttp.ClientSession() as s:
                async with s.post(gw + "/anthropic/v1/messages", json={},
                                  headers={"x-api-key": ANT_KEY, "anthropic-version": "2023-06-01"}) as r:
                    ant = await r.json()
                async with s.post(gw + f"/gemini/v1beta/models/gemini-2.5-flash:generateContent?key={GEM_KEY}",
                                  json={}) as r:
                    gem = await r.json()
                async with s.get(gw + "/v1/models") as r:
                    oai = await r.json()
        finally:
            await gw_runner.cleanup()
            for r in runners:
                await r.cleanup()
        return seen, ant, gem, oai

    seen, ant, gem, oai = asyncio.run(main())
    assert ant == {"ok": "/v1/messages"} and gem["ok"].endswith(":generateContent") and oai == {"ok": "/v1/models"}
    [a], [g], [o] = seen["anthropic"], seen["gemini"], seen["openai"]
    assert a["headers"]["x-api-key"] == ANT_KEY and a["headers"]["anthropic-version"] == "2023-06-01"
    assert g["query"] == f"key={GEM_KEY}"
    assert o["path"] == "/v1/models"


# ── Anthropic ───────────────────────────────────────────────────────────────
def run_anthropic(body):
    """Même requête en direct puis via la passerelle : (direct, via, events)."""
    async def main():
        events = []
        up_runner, up = await _serve(fake_anthropic.make_app())
        gw_runner, gw = await _serve(make_app(on_event=events.append, upstreams={"anthropic": up}))
        headers = {"x-api-key": ANT_KEY, "anthropic-version": "2023-06-01", "x-deadweight-app": "support"}
        try:
            out = []
            async with aiohttp.ClientSession(auto_decompress=False) as s:
                for base in (up, gw + "/anthropic"):
                    async with s.post(base + "/v1/messages", json=body, headers=headers) as r:
                        out.append((r.status, await r.read()))
            await asyncio.sleep(0.05)
            return out[0], out[1], events
        finally:
            await gw_runner.cleanup()
            await up_runner.cleanup()
    return asyncio.run(main())


def _check(e):
    jsonschema.validate(e, SCHEMA)
    assert e["provider"] == "anthropic" and e["endpoint"] == "/v1/messages" and e["app_id"] == "support"
    assert ANT_KEY not in json.dumps(e)


def test_anthropic_non_stream():
    body = {"model": "claude-sonnet-4-5", "max_tokens": 64, "temperature": 0, "stop_sequences": ["FIN"],
            "system": [{"type": "text", "text": "Tu classes."}, {"type": "text", "text": "Un mot."}],
            "messages": [{"role": "user", "content": "Gagnez un iPhone"}]}
    direct, via, [e] = run_anthropic(body)
    assert via == direct
    _check(e)
    assert e["model"] == "claude-sonnet-4-5" and e["model_resolved"] == "claude-sonnet-4-5-20260101"
    assert e["request"]["system"] == "Tu classes.\nUn mot."
    assert e["request"]["messages"] == [{"role": "user", "content": "Gagnez un iPhone"}]
    assert e["request"]["params"] == {"stream": False, "temperature": 0, "top_p": None, "max_tokens": 64,
                                      "stop": ["FIN"], "response_format": None}
    assert e["response"]["content"] == "Bonjour le monde."
    assert e["response"]["finish_reason"] == "stop" and e["response"]["finish_reason_raw"] == "end_turn"
    assert e["usage"] == {"input_tokens": 21, "output_tokens": 7, "cached_input_tokens": 5, "reasoning_tokens": None}


def test_anthropic_stream_reconstructed():
    direct, via, [e] = run_anthropic({"model": "claude-sonnet-4-5", "max_tokens": 64, "stream": True,
                                      "messages": [{"role": "user", "content": "Salut"}]})
    assert via == direct
    _check(e)
    assert e["request"]["params"]["stream"] is True and e["ttft_ms"] is not None
    assert e["response"]["content"] == "Bonjour le monde."
    assert e["response"]["finish_reason"] == "stop"
    assert e["usage"]["input_tokens"] == 21 and e["usage"]["output_tokens"] == 7


def test_anthropic_tools_and_history():
    body = {"model": "tools", "max_tokens": 64,
            "tools": [{"name": "get_weather", "description": "Météo", "input_schema": {"type": "object"}}],
            "messages": [
                {"role": "user", "content": [{"type": "text", "text": "Météo ?"}, {"type": "image", "source": {}}]},
                {"role": "assistant", "content": [{"type": "tool_use", "id": "toolu_0", "name": "get_weather",
                                                   "input": {"city": "Lyon"}}]},
                {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_0", "content": "12°C"},
                                             {"type": "text", "text": "Et Paris ?"}]}]}
    for stream in (False, True):
        direct, via, [e] = run_anthropic(dict(body, stream=stream))
        assert via == direct
        _check(e)
        assert e["request"]["tools"] == [{"name": "get_weather", "description": "Météo",
                                          "parameters": {"type": "object"}}]
        assert e["request"]["messages"] == [
            {"role": "user", "content": "Météo ?", "n_images": 1},
            {"role": "assistant", "content": None,
             "tool_calls": [{"id": "toolu_0", "name": "get_weather", "arguments": '{"city": "Lyon"}'}]},
            {"role": "tool", "content": "12°C", "tool_call_id": "toolu_0"},
            {"role": "user", "content": "Et Paris ?"}]
        [call] = e["response"]["tool_calls"]
        assert call["id"] == "toolu_1" and call["name"] == "get_weather"
        assert json.loads(call["arguments"]) == {"city": "Paris"}
        assert e["response"]["finish_reason"] == "tool_calls"


def test_anthropic_error_captured_without_key():
    direct, via, [e] = run_anthropic({"model": "bad-key", "max_tokens": 5,
                                      "messages": [{"role": "user", "content": "x"}]})
    assert via == direct and via[0] == 401
    _check(e)
    assert e["error"] == {"type": "authentication_error", "message": "invalid x-api-key"}
    assert e["response"]["finish_reason"] == "error" and e["http_status"] == 401


# ── Gemini ──────────────────────────────────────────────────────────────────
def run_gemini(model_path, body, query=f"key={GEM_KEY}"):
    """Même requête en direct puis via la passerelle : (direct, via, events)."""
    async def main():
        events = []
        up_runner, up = await _serve(fake_gemini.make_app())
        gw_runner, gw = await _serve(make_app(on_event=events.append, upstreams={"gemini": up}))
        try:
            out = []
            async with aiohttp.ClientSession(auto_decompress=False) as s:
                for base in (up, gw + "/gemini"):
                    async with s.post(f"{base}/v1beta/models/{model_path}?{query}", json=body) as r:
                        out.append((r.status, await r.read()))
            await asyncio.sleep(0.05)
            return out[0], out[1], events
        finally:
            await gw_runner.cleanup()
            await up_runner.cleanup()
    return asyncio.run(main())


def _check_gemini(e):
    jsonschema.validate(e, SCHEMA)
    assert e["provider"] == "gemini" and GEM_KEY not in json.dumps(e)
    assert "key=" not in e["endpoint"]


BODY = {"systemInstruction": {"parts": [{"text": "Tu classes."}]},
        "contents": [{"role": "user", "parts": [{"text": "Gagnez un iPhone"}]}],
        "generationConfig": {"temperature": 0, "maxOutputTokens": 64, "responseMimeType": "application/json"}}
USAGE_EVENT = {"input_tokens": 9, "output_tokens": 5, "cached_input_tokens": 4, "reasoning_tokens": 16}


def test_gemini_non_stream():
    direct, via, [e] = run_gemini("gemini-2.5-flash:generateContent", BODY)
    assert via == direct
    _check_gemini(e)
    assert e["model"] == "gemini-2.5-flash" and e["model_resolved"] == "gemini-2.5-flash-001"
    assert e["endpoint"] == "/v1beta/models/gemini-2.5-flash:generateContent"
    assert e["request"]["system"] == "Tu classes."
    assert e["request"]["messages"] == [{"role": "user", "content": "Gagnez un iPhone"}]
    assert e["request"]["params"] == {"stream": False, "temperature": 0, "top_p": None, "max_tokens": 64,
                                      "stop": None, "response_format": "json_object"}
    assert e["response"]["content"] == "Bonjour le monde."
    assert e["response"]["finish_reason"] == "stop" and e["response"]["finish_reason_raw"] == "STOP"
    assert e["usage"] == USAGE_EVENT


def test_gemini_stream_sse_and_json_array():
    for query in (f"alt=sse&key={GEM_KEY}", f"key={GEM_KEY}"):
        direct, via, [e] = run_gemini("gemini-2.5-flash:streamGenerateContent", BODY, query)
        assert via == direct
        _check_gemini(e)
        assert e["request"]["params"]["stream"] is True and e["ttft_ms"] is not None
        assert e["response"]["content"] == "Bonjour le monde."
        assert e["usage"] == USAGE_EVENT


def test_gemini_tools_and_history_snake_case():
    body = {"system_instruction": {"parts": [{"text": "Assistant météo."}]},
            "tools": [{"function_declarations": [{"name": "get_weather", "description": "Météo",
                                                  "parameters": {"type": "object"}}]}],
            "generation_config": {"max_output_tokens": 32, "stop_sequences": ["FIN"]},
            "contents": [
                {"role": "user", "parts": [{"text": "Météo ?"},
                                           {"inline_data": {"mime_type": "image/png", "data": "iVBOR"}}]},
                {"role": "model", "parts": [{"function_call": {"name": "get_weather", "args": {"city": "Lyon"}}}]},
                {"role": "user", "parts": [{"function_response": {"name": "get_weather",
                                                                  "response": {"temp": 12}}}]}]}
    for path in ("tools:generateContent", "tools:streamGenerateContent"):
        direct, via, [e] = run_gemini(path, body, f"alt=sse&key={GEM_KEY}")
        assert via == direct
        _check_gemini(e)
        assert e["request"]["system"] == "Assistant météo."
        assert e["request"]["tools"] == [{"name": "get_weather", "description": "Météo",
                                          "parameters": {"type": "object"}}]
        assert e["request"]["params"]["max_tokens"] == 32 and e["request"]["params"]["stop"] == ["FIN"]
        assert e["request"]["messages"] == [
            {"role": "user", "content": "Météo ?", "n_images": 1},
            {"role": "assistant", "content": None,
             "tool_calls": [{"id": "get_weather", "name": "get_weather", "arguments": '{"city": "Lyon"}'}]},
            {"role": "tool", "content": '{"temp": 12}', "tool_call_id": "get_weather"}]
        [call] = e["response"]["tool_calls"]
        assert call["name"] == "get_weather" and json.loads(call["arguments"]) == {"city": "Paris"}
        assert e["response"]["content"] is None  # la part « thought » n'est pas du contenu
        assert e["response"]["finish_reason"] == "tool_calls" and e["response"]["finish_reason_raw"] == "STOP"


def test_gemini_error_captured_without_key():
    for path in ("bad-key:generateContent", "bad-key:streamGenerateContent"):
        direct, via, [e] = run_gemini(path, BODY)
        assert via == direct and via[0] == 400
        _check_gemini(e)
        assert e["error"] == {"type": "INVALID_ARGUMENT", "message": "API key not valid. Please pass a valid API key."}
        assert e["response"]["finish_reason"] == "error" and e["http_status"] == 400


# ── Persistance (D1.2 + D1.3) ────────────────────────────────────────────────
def test_anthropic_and_gemini_calls_land_in_the_store_without_keys(tmp_path):
    from gateway.store import EventStore, read_events

    db = str(tmp_path / "events.db")

    async def main():
        ant_runner, ant = await _serve(fake_anthropic.make_app())
        gem_runner, gem = await _serve(fake_gemini.make_app())
        gw_runner, gw = await _serve(make_app(on_event=lambda e: None, store=EventStore(db),
                                              upstreams={"anthropic": ant, "gemini": gem}))
        try:
            async with aiohttp.ClientSession() as s:
                async with s.post(gw + "/anthropic/v1/messages",
                                  json={"model": "claude-sonnet-4-5", "max_tokens": 16,
                                        "messages": [{"role": "user", "content": "Salut"}]},
                                  headers={"x-api-key": ANT_KEY, "anthropic-version": "2023-06-01"}) as r:
                    assert r.status == 200
                async with s.post(gw + f"/gemini/v1beta/models/gemini-2.5-flash:generateContent?key={GEM_KEY}",
                                  json=BODY) as r:
                    assert r.status == 200
        finally:
            await gw_runner.cleanup()  # ferme le store : les événements en attente sont écrits
            await gem_runner.cleanup()
            await ant_runner.cleanup()

    asyncio.run(main())
    events = read_events(db)
    assert sorted(e["provider"] for e in events) == ["anthropic", "gemini"]
    for e in events:
        jsonschema.validate(e, SCHEMA)
    for f in tmp_path.iterdir():  # events.db et ses fichiers annexes (-wal, -shm)
        raw = f.read_bytes()
        assert ANT_KEY.encode() not in raw and GEM_KEY.encode() not in raw, f.name
