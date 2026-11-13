"""Voie Anthropic de bout en bout : SDK officiel ``anthropic`` -> passerelle (/anthropic) -> faux Anthropic.
Aucun réseau, aucune vraie clé. Vérifie la capture complète puis le passage dans le cœur (règles, rapport)."""
import asyncio
import json
from pathlib import Path

import anthropic
import jsonschema
from aiohttp import web

from gateway import fake_anthropic
from gateway.proxy import make_app
from report.audit import build_report

SCHEMA = json.loads((Path(__file__).resolve().parents[1] / "schemas/event.schema.json").read_text())
SECRET = "sk-ant-NE-DOIT-JAMAIS-SORTIR"
TOOL = {"name": "get_weather", "description": "Météo", "input_schema": {"type": "object",
                                                                          "properties": {"city": {"type": "string"}}}}


def with_sdk(scenario):
    """Faux Anthropic + passerelle + client officiel ; rend (résultat du scénario, événements capturés)."""
    async def main():
        events = []
        up_runner = web.AppRunner(fake_anthropic.make_app())
        await up_runner.setup()
        await web.TCPSite(up_runner, "127.0.0.1", 0).start()
        up = f"http://127.0.0.1:{up_runner.addresses[0][1]}"
        gw_runner = web.AppRunner(make_app(upstream="http://127.0.0.1:9", on_event=events.append,
                                           upstreams={"anthropic": up}))
        await gw_runner.setup()
        await web.TCPSite(gw_runner, "127.0.0.1", 0).start()
        gw = f"http://127.0.0.1:{gw_runner.addresses[0][1]}"
        client = anthropic.AsyncAnthropic(api_key=SECRET, base_url=gw + "/anthropic", max_retries=0,
                                          default_headers={"x-deadweight-app": "support"})
        try:
            out = await scenario(client)
            await asyncio.sleep(0.05)
            return out, events
        finally:
            await gw_runner.cleanup()
            await up_runner.cleanup()
    return asyncio.run(main())


def test_non_stream_event_has_everything():
    async def go(c):
        return await c.messages.create(model="claude-sonnet-4-5", max_tokens=100,
                                       system="Classe le ticket.", tools=[TOOL],
                                       messages=[{"role": "user", "content": "Mot de passe perdu"}])
    msg, [e] = with_sdk(go)
    assert msg.content[0].text == "Bonjour le monde."
    jsonschema.validate(e, SCHEMA)
    assert e["provider"] == "anthropic" and e["app_id"] == "support" and e["endpoint"] == "/v1/messages"
    assert e["request"]["system"] == "Classe le ticket."
    assert e["request"]["messages"] == [{"role": "user", "content": "Mot de passe perdu"}]
    assert e["request"]["tools"][0]["name"] == "get_weather" and e["request"]["tools"][0]["parameters"]
    assert e["request"]["params"]["max_tokens"] == 100
    assert e["response"]["content"] == "Bonjour le monde." and e["response"]["finish_reason"] == "stop"
    assert e["response"]["finish_reason_raw"] == "end_turn" and e["model_resolved"] == "claude-sonnet-4-5-20260101"
    assert e["usage"] == {"input_tokens": 21, "output_tokens": 7, "cached_input_tokens": 5, "reasoning_tokens": None}
    assert SECRET not in json.dumps(e)


def test_stream_with_sdk_helper_and_create_stream():
    async def go(c):
        async with c.messages.stream(model="cache", max_tokens=50,
                                     messages=[{"role": "user", "content": "Salut"}]) as s:
            text = await s.get_final_text()
        raw = await c.messages.create(model="claude-sonnet-4-5", max_tokens=50, stream=True,
                                      messages=[{"role": "user", "content": "Salut"}])
        async for _ in raw:
            pass
        return text
    text, (cached, plain) = with_sdk(go)
    assert text == "Bonjour le monde."
    for e in (cached, plain):
        jsonschema.validate(e, SCHEMA)
        assert e["request"]["params"]["stream"] is True and e["ttft_ms"] is not None
        assert e["response"]["content"] == "Bonjour le monde." and e["response"]["finish_reason"] == "stop"
    # lu dans message_start (cache) puis complété par message_delta (jetons de sortie)
    assert cached["usage"] == {"input_tokens": 9, "output_tokens": 7, "cached_input_tokens": 100, "reasoning_tokens": None}


def test_tool_use_then_tool_result_multi_turn():
    async def go(c):
        first = await c.messages.create(model="tools", max_tokens=50, tools=[TOOL],
                                        messages=[{"role": "user", "content": "Météo ?"}])
        use = next(b for b in first.content if b.type == "tool_use")
        history = [{"role": "user", "content": "Météo ?"},
                   {"role": "assistant", "content": [b.model_dump() for b in first.content]},
                   {"role": "user", "content": [{"type": "tool_result", "tool_use_id": use.id, "content": "18 degrés"}]}]
        await c.messages.create(model="claude-sonnet-4-5", max_tokens=50, tools=[TOOL], messages=history)
        async with c.messages.stream(model="tools", max_tokens=50, tools=[TOOL], messages=history[:1]) as s:
            async for _ in s:
                pass
    _, (plain, turn2, streamed) = with_sdk(go)
    for e in (plain, streamed):
        jsonschema.validate(e, SCHEMA)
        assert e["response"]["finish_reason"] == "tool_calls" and e["response"]["finish_reason_raw"] == "tool_use"
        [call] = e["response"]["tool_calls"]
        assert (call["id"], call["name"]) == ("toolu_1", "get_weather")
        assert json.loads(call["arguments"]) == {"city": "Paris"}
    jsonschema.validate(turn2, SCHEMA)
    assert [m["role"] for m in turn2["request"]["messages"]] == ["user", "assistant", "tool"]
    tool_msg = turn2["request"]["messages"][-1]
    assert tool_msg["tool_call_id"] == "toolu_1" and tool_msg["content"] == "18 degrés"


def test_pipeline_runs_on_captured_events():
    """Les événements Anthropic capturés traversent les règles et le rapport sans erreur, coût compris."""
    async def go(c):
        for i in range(6):
            await c.messages.create(model="claude-sonnet-4-5", max_tokens=20, system="Classe.",
                                    messages=[{"role": "user", "content": f"ticket {i}"}])
    _, events = with_sdk(go)
    report = build_report(events)
    assert report["resume"]["nb_appels"] == 6 and report["resume"]["global"]["nb_erreurs"] == 0
    assert report["resume"]["global"]["cout_observe_usd"] > 0  # modèle chiffré, jetons lus


def test_error_is_relayed_and_secret_never_captured():
    async def go(c):
        try:
            await c.messages.create(model="bad-key", max_tokens=5, messages=[{"role": "user", "content": "x"}])
        except anthropic.AuthenticationError as exc:
            return exc.status_code
    status, [e] = with_sdk(go)
    assert status == 401 and e["http_status"] == 401 and e["error"]["type"] == "authentication_error"
    assert SECRET not in json.dumps(e)
