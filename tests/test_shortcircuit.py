"""D3.3 : court-circuit depuis la passerelle, sur une preuve PASS du jeu D0.3. Aucun réseau réel."""
import asyncio
import json
from pathlib import Path

import jsonschema
import openai
import pytest
from aiohttp import web

from gateway import fake_openai
from gateway.proxy import make_app
from proof.replay import main as replay_main

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schemas/event.schema.json").read_text())
SYSTEM = "Classe le mail en une seule etiquette : spam, facture ou support."
KEY = "sk-test-NE-DOIT-JAMAIS-SORTIR"


@pytest.fixture(scope="module")
def proofs(tmp_path_factory):
    out = tmp_path_factory.mktemp("proofs")
    replay_main([str(ROOT / "fixtures/dataset/v1/events.jsonl"), "--out", str(out)])
    return out


async def _serve(app):
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    return runner, f"http://127.0.0.1:{runner.addresses[0][1]}"


def run(proofs, scenario):
    async def main():
        fake = fake_openai.make_app()
        events = []
        up_runner, up = await _serve(fake)
        gw_runner, gw = await _serve(make_app(upstream=up, on_event=events.append, shortcut=proofs))
        try:
            client = openai.AsyncOpenAI(base_url=gw + "/v1", api_key=KEY, max_retries=0)
            result = await scenario(client)
            await asyncio.sleep(0.05)
            return result, events, fake[fake_openai.SEEN]
        finally:
            await gw_runner.cleanup()
            await up_runner.cleanup()
    return asyncio.run(main())


def _messages(text, system=SYSTEM):
    return [{"role": "system", "content": system}, {"role": "user", "content": text}]


def test_only_pass_proofs_are_loaded(proofs):
    app = make_app(upstream="http://127.0.0.1:9", shortcut=proofs)
    from gateway.proxy import SHORTCUT
    assert [k[0] for k in app[SHORTCUT]] == ["mail-triage"]  # reviews est REJECT


def test_covered_request_is_answered_without_upstream(proofs):
    async def scenario(client):
        raw = await client.chat.completions.with_raw_response.create(
            model="gpt-4o", messages=_messages("Gagnez un iPhone maintenant"),
            extra_headers={"x-deadweight-app": "mail-triage"})
        return raw.headers.get("x-deadweight-shortcircuit"), raw.parse()

    (header, completion), events, seen = run(proofs, scenario)
    assert seen == []  # OpenAI n'a jamais été appelé
    assert header.startswith("f_mail-triage_")
    assert completion.choices[0].message.content == "spam"
    assert completion.usage.total_tokens == 0
    [event] = events
    jsonschema.validate(event, SCHEMA)
    assert event["upstream"] == "deadweight" and event["model_resolved"] == "deadweight-rules"
    assert event["response"]["content"] == "spam" and event["usage"]["input_tokens"] == 0
    assert KEY not in json.dumps(event)


def test_covered_request_streams(proofs):
    async def scenario(client):
        stream = await client.chat.completions.create(
            model="gpt-4o", messages=_messages("Gagnez un iPhone maintenant"), stream=True,
            extra_headers={"x-deadweight-app": "mail-triage"})
        return "".join([c.choices[0].delta.content or "" async for c in stream if c.choices])

    text, events, seen = run(proofs, scenario)
    assert text == "spam" and seen == []
    jsonschema.validate(events[0], SCHEMA)
    assert events[0]["response"]["content"] == "spam" and events[0]["request"]["params"]["stream"]


@pytest.mark.parametrize("kwargs, headers", [
    ({"messages": _messages("Bonjour, rien à voir")}, {"x-deadweight-app": "mail-triage"}),  # non couvert
    ({"messages": _messages("Gagnez un iPhone maintenant")}, {"x-deadweight-app": "autre-app"}),
    ({"messages": _messages("Gagnez un iPhone maintenant", system="Autre tâche.")},
     {"x-deadweight-app": "mail-triage"}),
    ({"messages": _messages("Gagnez un iPhone maintenant"),
      "tools": [{"type": "function", "function": {"name": "f", "parameters": {"type": "object"}}}]},
     {"x-deadweight-app": "mail-triage"}),
    ({"messages": _messages("Gagnez un iPhone maintenant"),
      "response_format": {"type": "json_object"}}, {"x-deadweight-app": "mail-triage"}),
])
def test_everything_else_is_relayed(proofs, kwargs, headers):
    async def scenario(client):
        return await client.chat.completions.create(model="gpt-4o", extra_headers=headers, **kwargs)

    completion, events, seen = run(proofs, scenario)
    assert len(seen) == 1 and completion.model != "deadweight-rules"
    assert events[0]["upstream"] != "deadweight"


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("GATEWAY_SHORTCIRCUIT", raising=False)
    from gateway.proxy import SHORTCUT
    assert make_app(upstream="http://127.0.0.1:9")[SHORTCUT] == {}
