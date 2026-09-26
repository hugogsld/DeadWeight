"""Streaming OpenAI : la passerelle obtient le nombre de jetons sans que le client voie de différence."""
import asyncio
import json

import aiohttp
import openai
from aiohttp import web

from gateway import fake_openai
from gateway.proxy import _DropUsage, make_app

KEY = "sk-test-NE-DOIT-JAMAIS-SORTIR"
MESSAGES = [{"role": "user", "content": "Bonjour"}]


async def _serve(app):
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    return runner, f"http://127.0.0.1:{runner.addresses[0][1]}"


def run(scenario):
    async def main():
        events = []
        up_runner, up = await _serve(fake_openai.make_app())
        gw_runner, gw = await _serve(make_app(upstream=up, on_event=events.append))
        try:
            result = await scenario(up, gw)
            await asyncio.sleep(0.05)
            return result, events
        finally:
            await gw_runner.cleanup()
            await up_runner.cleanup()
    return asyncio.run(main())


async def _sdk_chunks(base, **kwargs):
    client = openai.AsyncOpenAI(base_url=base + "/v1", api_key=KEY, max_retries=0)
    stream = await client.chat.completions.create(model="gpt-4o", messages=MESSAGES, stream=True, **kwargs)
    return [c async for c in stream]


def test_client_sees_the_same_stream_and_usage_is_captured():
    async def scenario(up, gw):
        return await _sdk_chunks(up), await _sdk_chunks(gw)

    (direct, via), [event] = run(scenario)
    assert [c.choices for c in via] == [c.choices for c in direct]  # aucun morceau en plus
    assert all(c.choices for c in via)                             # pas de morceau d'usage
    assert event["usage"]["input_tokens"] is not None and event["usage"]["output_tokens"] is not None
    assert "stream_options" not in json.dumps(event["request"])     # la requête du client, telle quelle


def test_raw_bytes_are_identical_to_a_direct_call():
    body = {"model": "gpt-4o", "messages": MESSAGES, "stream": True}

    async def scenario(up, gw):
        out = []
        async with aiohttp.ClientSession(auto_decompress=False) as s:
            for base in (up, gw):
                async with s.post(base + "/v1/chat/completions", json=body,
                                  headers={"Authorization": f"Bearer {KEY}"}) as r:
                    out.append(await r.read())
        return out

    (direct, via), [event] = run(scenario)
    assert via == direct
    assert event["usage"]["input_tokens"] is not None


def test_client_asking_for_usage_still_gets_it():
    async def scenario(up, gw):
        return await _sdk_chunks(gw, stream_options={"include_usage": True})

    chunks, [event] = run(scenario)
    assert chunks[-1].choices == [] and chunks[-1].usage.prompt_tokens > 0
    assert event["usage"]["input_tokens"] is not None


def test_client_refusing_usage_is_respected():
    async def scenario(up, gw):
        return await _sdk_chunks(gw, stream_options={"include_usage": False})

    chunks, [event] = run(scenario)
    assert all(c.choices for c in chunks)
    assert event["usage"]["input_tokens"] is None


def _usage_stream(sep=b"\n\n"):
    chunk = {"choices": [{"index": 0, "delta": {"content": "ok"}}]}
    usage = {"choices": [], "usage": {"prompt_tokens": 3, "completion_tokens": 1}}
    return b"".join(b"data: " + json.dumps(x).encode() + sep for x in (chunk, usage)) + b"data: [DONE]" + sep


def test_filter_is_indifferent_to_network_cuts():
    raw = _usage_stream()
    expected = raw.replace(b'data: {"choices": [], "usage": {"prompt_tokens": 3, "completion_tokens": 1}}\n\n', b"")
    drop = _DropUsage()
    assert b"".join(drop.feed(raw[i:i + 1]) for i in range(len(raw))) + drop.flush() == expected


def test_filter_handles_crlf_separators():
    drop = _DropUsage()
    out = drop.feed(_usage_stream(b"\r\n\r\n")) + drop.flush()
    assert b'"usage"' not in out and out.endswith(b"data: [DONE]\r\n\r\n") and b'"ok"' in out
