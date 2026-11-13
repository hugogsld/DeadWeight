"""Voie Gemini de bout en bout : SDK officiel ``google-genai`` -> passerelle (/gemini) -> faux Gemini.
Aucun réseau, aucune vraie clé."""
import asyncio
import json
from pathlib import Path

import jsonschema
import pytest
from aiohttp import web

genai = pytest.importorskip("google.genai")
from google.genai import types  # noqa: E402

from gateway import fake_gemini  # noqa: E402
from gateway.proxy import make_app  # noqa: E402

SCHEMA = json.loads((Path(__file__).resolve().parents[1] / "schemas/event.schema.json").read_text())
SECRET = "AIzaNE-DOIT-JAMAIS-SORTIR-0123456789"


def with_sdk(scenario):
    async def main():
        events = []
        up_runner = web.AppRunner(fake_gemini.make_app())
        await up_runner.setup()
        await web.TCPSite(up_runner, "127.0.0.1", 0).start()
        up = f"http://127.0.0.1:{up_runner.addresses[0][1]}"
        gw_runner = web.AppRunner(make_app(upstream="http://127.0.0.1:9", on_event=events.append,
                                           upstreams={"gemini": up}))
        await gw_runner.setup()
        await web.TCPSite(gw_runner, "127.0.0.1", 0).start()
        gw = f"http://127.0.0.1:{gw_runner.addresses[0][1]}"
        client = genai.Client(api_key=SECRET, http_options=types.HttpOptions(
            base_url=gw + "/gemini", headers={"x-deadweight-app": "support"}))
        try:
            out = await scenario(client.aio)
            await asyncio.sleep(0.05)
            return out, events
        finally:
            await gw_runner.cleanup()
            await up_runner.cleanup()
    return asyncio.run(main())


def test_generate_content_event_is_complete():
    async def go(aio):
        return await aio.models.generate_content(
            model="gemini-2.5-flash", contents="Mot de passe perdu",
            config=types.GenerateContentConfig(system_instruction="Classe le ticket.", max_output_tokens=64,
                                               temperature=0.1))
    resp, [e] = with_sdk(go)
    assert resp.text == "Bonjour le monde."
    jsonschema.validate(e, SCHEMA)
    assert e["provider"] == "gemini" and e["app_id"] == "support"
    assert e["request"]["system"] == "Classe le ticket."
    assert e["request"]["messages"] == [{"role": "user", "content": "Mot de passe perdu"}]
    assert e["request"]["params"]["max_tokens"] == 64 and e["request"]["params"]["temperature"] == 0.1
    assert e["response"]["content"] == "Bonjour le monde." and e["response"]["finish_reason"] == "stop"
    assert e["usage"]["input_tokens"] == 9 and e["usage"]["cached_input_tokens"] == 4
    assert SECRET not in json.dumps(e)


def test_stream_and_function_call_multi_turn():
    tool = types.Tool(function_declarations=[types.FunctionDeclaration(
        name="get_weather", description="Météo", parameters_json_schema={"type": "object",
                                                                         "properties": {"city": {"type": "string"}}})])

    async def go(aio):
        text = []
        async for chunk in await aio.models.generate_content_stream(model="gemini-2.5-flash", contents="Salut"):
            text.append(chunk.text)
        call = await aio.models.generate_content(model="tools", contents="Météo ?",
                                                 config=types.GenerateContentConfig(
                                                     tools=[tool], automatic_function_calling=
                                                     types.AutomaticFunctionCallingConfig(disable=True)))
        await aio.models.generate_content(model="gemini-2.5-flash", config=types.GenerateContentConfig(tools=[tool]),
                                          contents=[types.Content(role="user", parts=[types.Part(text="Météo ?")]),
                                                    call.candidates[0].content,
                                                    types.Content(role="user", parts=[types.Part.from_function_response(
                                                        name="get_weather", response={"t": 18})])])
        return "".join(t or "" for t in text)
    text, (streamed, called, turn2) = with_sdk(go)
    assert text == "Bonjour le monde."
    for e in (streamed, called, turn2):
        jsonschema.validate(e, SCHEMA)
    assert streamed["request"]["params"]["stream"] is True and streamed["ttft_ms"] is not None
    assert streamed["response"]["content"] == "Bonjour le monde."
    assert called["response"]["finish_reason"] == "tool_calls"
    assert called["response"]["tool_calls"][0]["name"] == "get_weather"
    assert called["request"]["tools"][0]["name"] == "get_weather"
    assert [m["role"] for m in turn2["request"]["messages"]][-1] == "tool"
