"""D1.1 : relais identique octet pour octet, streaming sans tampon, clé jamais capturée."""
import asyncio
import json
import logging
import time
from pathlib import Path

import aiohttp
import jsonschema
import openai
from aiohttp import web

from gateway import fake_openai
from gateway.proxy import make_app

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schemas/event.schema.json").read_text())
KEY = "sk-test-NE-DOIT-JAMAIS-SORTIR"


async def _serve(app):
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    return runner, f"http://127.0.0.1:{runner.addresses[0][1]}"


def run(scenario):
    """Démarre faux OpenAI + passerelle, passe (upstream_url, proxy_url, events, fake_app)."""
    async def main():
        fake = fake_openai.make_app()
        events = []
        up_runner, up = await _serve(fake)
        gw_runner, gw = await _serve(make_app(upstream=up, on_event=events.append))
        try:
            return await scenario(up, gw, events, fake)
        finally:
            await gw_runner.cleanup()
            await up_runner.cleanup()
    return asyncio.run(main())


async def _post(base, body, headers=None):
    async with aiohttp.ClientSession(auto_decompress=False) as s:
        async with s.post(base + "/v1/chat/completions", json=body,
                          headers={"Authorization": f"Bearer {KEY}", **(headers or {})}) as r:
            return r.status, await r.read()


def test_non_stream_identical_bytes_and_event():
    body = {"model": "gpt-4o", "temperature": 0, "max_tokens": 5,
            "messages": [{"role": "system", "content": "Classe le mail."},
                         {"role": "user", "content": "Gagnez un iPhone"}]}

    async def scenario(up, gw, events, fake):
        direct = await _post(up, body)
        via = await _post(gw, body, {"x-deadweight-app": "mail-triage", "x-deadweight-trace": "t-1"})
        await asyncio.sleep(0.05)
        return direct, via, events

    direct, via, events = run(scenario)
    assert via == direct
    [e] = events
    jsonschema.validate(e, SCHEMA)
    assert e["app_id"] == "mail-triage" and e["trace"] == {"id": "t-1", "source": "header", "step": None}
    assert e["request"]["system"] == "Classe le mail."
    assert e["request"]["messages"] == [{"role": "user", "content": "Gagnez un iPhone"}]
    assert e["response"]["content"] == "Bonjour le monde."
    assert e["model"] == "gpt-4o" and e["model_resolved"] == "gpt-4o-2026"
    assert e["upstream"] == "127.0.0.1"
    assert e["usage"]["input_tokens"] == 12 and e["usage"]["output_tokens"] == 6


def test_stream_identical_bytes_and_reconstructed():
    body = {"model": "gpt-4o", "stream": True, "stream_options": {"include_usage": True},
            "messages": [{"role": "user", "content": "Salut"}]}

    async def scenario(up, gw, events, fake):
        direct = await _post(up, body)
        via = await _post(gw, body)
        await asyncio.sleep(0.05)
        return direct, via, events

    direct, via, events = run(scenario)
    assert via == direct
    [e] = events
    jsonschema.validate(e, SCHEMA)
    assert e["request"]["params"]["stream"] is True
    assert e["response"]["content"] == "Bonjour le monde."
    assert e["response"]["finish_reason"] == "stop"
    assert e["usage"]["output_tokens"] == 6
    assert e["ttft_ms"] is not None and e["ttft_ms"] <= e["latency_ms"]


def test_stream_is_not_buffered():
    """Le premier morceau arrive chez le client bien avant la fin de la génération."""
    body = {"model": "slow", "stream": True, "messages": [{"role": "user", "content": "Salut"}]}

    async def scenario(up, gw, events, fake):
        async with aiohttp.ClientSession() as s:
            t0 = time.perf_counter()
            async with s.post(gw + "/v1/chat/completions", json=body,
                              headers={"Authorization": f"Bearer {KEY}"}) as r:
                arrivals = []
                async for _ in r.content.iter_any():
                    arrivals.append(time.perf_counter() - t0)
        return arrivals

    arrivals = run(scenario)
    # 9 morceaux espacés de 300 ms : ~2,7 s au total, le premier doit sortir tout de suite
    assert arrivals[0] < 0.2
    assert len(arrivals) >= 5
    assert arrivals[-1] > 2.0


def test_stream_tool_calls_reconstructed():
    body = {"model": "tools", "stream": True, "messages": [{"role": "user", "content": "Météo ?"}],
            "tools": [{"type": "function", "function": {"name": "get_weather", "description": "meteo",
                                                        "parameters": {"type": "object"}}}]}

    async def scenario(up, gw, events, fake):
        await _post(gw, body)
        await asyncio.sleep(0.05)
        return events

    [e] = run(scenario)
    jsonschema.validate(e, SCHEMA)
    assert e["response"]["tool_calls"] == [{"id": "call_1", "name": "get_weather", "arguments": '{"city":"Paris"}'}]
    assert e["response"]["finish_reason"] == "tool_calls"
    assert e["request"]["tools"][0]["name"] == "get_weather"


def test_upstream_error_passed_through():
    body = {"model": "rate-limited", "messages": [{"role": "user", "content": "x"}]}

    async def scenario(up, gw, events, fake):
        direct = await _post(up, body)
        via = await _post(gw, body)
        await asyncio.sleep(0.05)
        return direct, via, events

    direct, via, [e] = run(scenario)
    assert via == direct and via[0] == 429
    jsonschema.validate(e, SCHEMA)
    assert e["error"] == {"type": "rate_limit_exceeded", "message": "Rate limit reached"}
    assert e["response"]["finish_reason"] == "error"


def test_key_echoed_in_upstream_error_is_masked():
    body = {"model": "bad-key", "messages": [{"role": "user", "content": "x"}]}

    async def scenario(up, gw, events, fake):
        via = await _post(gw, body)
        await asyncio.sleep(0.05)
        return via, events

    (status, raw), [e] = run(scenario)
    assert status == 401 and KEY in raw.decode()  # le client reçoit l'erreur intacte
    assert KEY not in json.dumps(e)
    assert e["error"]["type"] == "invalid_api_key" and "[clé masquée]" in e["error"]["message"]


def test_other_routes_relayed_not_captured():
    async def scenario(up, gw, events, fake):
        async with aiohttp.ClientSession() as s:
            async with s.get(gw + "/v1/models", headers={"Authorization": f"Bearer {KEY}"}) as r:
                return r.status, await r.json(), events

    status, payload, events = run(scenario)
    assert status == 200 and payload["data"][0]["id"] == "gpt-4o"
    assert events == []


def test_authorization_relayed_never_captured_nor_logged(caplog):
    caplog.set_level(logging.DEBUG)
    body = {"model": "gpt-4o", "messages": [{"role": "user", "content": "x"}]}

    async def scenario(up, gw, events, fake):
        await _post(gw, body, {"x-deadweight-app": "a"})
        await asyncio.sleep(0.05)
        return events, fake[fake_openai.SEEN]

    events, seen = run(scenario)
    assert seen[-1]["Authorization"] == f"Bearer {KEY}"
    assert not any(k.lower().startswith("x-deadweight-") for k in seen[-1])
    assert KEY not in json.dumps(events)
    assert KEY not in caplog.text


def test_official_openai_sdk_works_unchanged():
    """Une application existante : seul le base_url change."""
    async def scenario(up, gw, events, fake):
        out = {}
        for name, base in (("direct", up), ("via", gw)):
            client = openai.AsyncOpenAI(base_url=base + "/v1", api_key=KEY)
            r = await client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": "hi"}])
            stream = await client.chat.completions.create(model="gpt-4o", stream=True,
                                                          messages=[{"role": "user", "content": "hi"}])
            text = "".join([c.choices[0].delta.content or "" async for c in stream if c.choices])
            out[name] = (r.choices[0].message.content, r.usage.total_tokens, text)
            await client.close()
        await asyncio.sleep(0.05)
        return out, events

    out, events = run(scenario)
    assert out["via"] == out["direct"] == ("Bonjour le monde.", 18, "Bonjour le monde.")
    assert len(events) == 2
    for e in events:
        jsonschema.validate(e, SCHEMA)


def test_upstream_down_gives_502():
    async def scenario(up, gw, events, fake):
        events_bad = []
        runner, bad_gw = await _serve(make_app(upstream="http://127.0.0.1:9", on_event=events_bad.append))
        try:
            status, raw = await _post(bad_gw, {"model": "gpt-4o", "messages": []})
        finally:
            await runner.cleanup()
        return status, raw, events_bad

    status, raw, [e] = run(scenario)
    assert status == 502 and json.loads(raw)["error"]["type"] == "deadweight_upstream_error"
    jsonschema.validate(e, SCHEMA)
