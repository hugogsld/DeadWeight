"""Problème 11 : l'API Responses d'OpenAI (SDK Agents par défaut) est capturée, avec le vrai SDK ``openai``."""
import asyncio
import json
from pathlib import Path

import aiohttp
import jsonschema
import openai

from gateway.openai_responses import normalize_request
from tests.test_gateway import KEY, run

SCHEMA = json.loads((Path(__file__).resolve().parents[1] / "schemas/event.schema.json").read_text())
AUTH = {"Authorization": f"Bearer {KEY}"}


def sdk(scenario):
    """Passe un client ``openai`` réel pointé sur la passerelle (faux OpenAI en amont)."""
    async def inner(up, gw, events, fake):
        client = openai.AsyncOpenAI(api_key=KEY, base_url=gw + "/v1", max_retries=0)
        out = await scenario(client)
        await asyncio.sleep(0.05)
        return out, events
    return run(inner)


def test_sdk_non_stream_event_is_complete():
    async def go(c):
        return await c.responses.create(model="gpt-4o", instructions="Classe le mail.", input="Gagnez un iPhone",
                                        max_output_tokens=50, temperature=0)
    r, [e] = sdk(go)
    assert r.output_text == "Bonjour le monde."
    jsonschema.validate(e, SCHEMA)
    assert e["endpoint"] == "/v1/responses" and e["provider"] == "openai"
    assert e["request"]["system"] == "Classe le mail."
    assert e["request"]["messages"] == [{"role": "user", "content": "Gagnez un iPhone"}]
    assert e["request"]["params"]["max_tokens"] == 50 and e["request"]["params"]["stream"] is False
    assert e["response"]["content"] == "Bonjour le monde." and e["response"]["finish_reason"] == "stop"
    assert e["model_resolved"] == "gpt-4o-2026"
    assert e["usage"] == {"input_tokens": 30, "output_tokens": 11, "cached_input_tokens": 8, "reasoning_tokens": 4}
    assert KEY not in json.dumps(e)


def test_sdk_stream_event_matches_non_stream():
    async def go(c):
        text = []
        async with await c.responses.create(model="gpt-4o", input="Salut", stream=True) as s:
            async for ev in s:
                if ev.type == "response.output_text.delta":
                    text.append(ev.delta)
        return "".join(text)
    text, [e] = sdk(go)
    assert text == "Bonjour le monde."
    jsonschema.validate(e, SCHEMA)
    assert e["response"]["content"] == text and e["request"]["params"]["stream"] is True
    assert e["usage"]["cached_input_tokens"] == 8 and e["usage"]["reasoning_tokens"] == 4
    assert e["ttft_ms"] is not None and e["response"]["finish_reason"] == "stop"


def test_sdk_tools_stream_and_non_stream_and_multi_turn():
    tool = {"type": "function", "name": "get_weather", "description": "Météo", "strict": False,
            "parameters": {"type": "object", "properties": {"city": {"type": "string"}}}}

    async def go(c):
        first = await c.responses.create(model="tools", input="Météo ?", tools=[tool])
        async with await c.responses.create(model="tools", input="Météo ?", tools=[tool], stream=True) as s:
            async for _ in s:
                pass
        call = first.output[0]
        await c.responses.create(model="gpt-4o", tools=[tool], input=[
            {"role": "user", "content": "Météo ?"},
            {"type": "function_call", "call_id": call.call_id, "name": call.name, "arguments": call.arguments},
            {"type": "function_call_output", "call_id": call.call_id, "output": "18 degrés"}])
    _, (plain, streamed, turn2) = sdk(go)
    for e in (plain, streamed):
        jsonschema.validate(e, SCHEMA)
        assert e["response"]["finish_reason"] == "tool_calls"
        assert e["response"]["tool_calls"] == [{"id": "call_1", "name": "get_weather", "arguments": '{"city":"Paris"}'}]
        assert e["request"]["tools"] == [{"name": "get_weather", "description": "Météo",
                                          "parameters": tool["parameters"]}]
    msgs = turn2["request"]["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "tool"]
    assert msgs[1]["tool_calls"][0]["id"] == "call_1" and msgs[2]["tool_call_id"] == "call_1"
    assert msgs[2]["content"] == "18 degrés"
    jsonschema.validate(turn2, SCHEMA)


def test_incomplete_maps_to_length_for_both_modes():
    async def go(c):
        await c.responses.create(model="incomplete", input="x")
        async with await c.responses.create(model="incomplete", input="x", stream=True) as s:
            async for _ in s:
                pass
    _, (a, b) = sdk(go)
    for e in (a, b):
        assert e["response"]["finish_reason"] == "length" and e["response"]["finish_reason_raw"] == "max_output_tokens"


def test_errors_are_relayed_and_secret_is_masked():
    async def scenario(up, gw, events, fake):
        out = []
        async with aiohttp.ClientSession() as s:
            for model in ("bad-key", "rate-limited"):
                async with s.post(gw + "/v1/responses", json={"model": model, "input": "x"}, headers=AUTH) as r:
                    out.append(r.status)
        await asyncio.sleep(0.05)
        return out, events
    statuses, [bad, limited] = run(scenario)
    assert statuses == [401, 429]
    assert bad["error"]["type"] == "invalid_api_key" and KEY not in json.dumps(bad)
    assert limited["http_status"] == 429 and limited["error"]["type"] == "rate_limit_exceeded"


def test_bytes_identical_through_gateway_for_non_stream_and_stream():
    async def scenario(up, gw, events, fake):
        got = []
        async with aiohttp.ClientSession(auto_decompress=False) as s:
            for stream in (False, True):
                pair = []
                for base in (up, gw):
                    async with s.post(base + "/v1/responses", json={"model": "gpt-4o", "input": "x", "stream": stream},
                                      headers=AUTH) as r:
                        pair.append(await r.read())
                got.append(pair)
        return got, events
    got, _ = run(scenario)
    assert all(direct == via for direct, via in got)


def test_normalize_request_shapes():
    model, req = normalize_request({"model": "m", "instructions": "A", "input": [
        {"role": "developer", "content": "B"},
        {"role": "user", "content": [{"type": "input_text", "text": "t"}, {"type": "input_image", "image_url": "u"}]},
        {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "r"}]},
        {"type": "reasoning", "id": "rs_1"}, {"type": "item_reference", "id": "x"}],
        "text": {"format": {"type": "json_schema"}}, "tools": [{"type": "web_search"}]})
    assert model == "m" and req["system"] == "A\n\nB" and req["tools"] == []
    assert req["messages"] == [{"role": "user", "content": "t", "n_images": 1}, {"role": "assistant", "content": "r"}]
    assert req["params"]["response_format"] == "json_schema"
