"""Clones d'OpenAI : Azure OpenAI (URL par déploiement, ?api-version=, en-tête api-key), Groq (/openai/v1),
OpenRouter (/api/v1), Ollama et Mistral (/v1, amont réglé par GATEWAY_OPENAI_UPSTREAM). Faux amont, aucun réseau."""
import asyncio
import json
from pathlib import Path

import aiohttp
import jsonschema
import openai

from gateway import fake_openai
from gateway.capture import is_chat_path, is_responses_path
from tests.test_gateway import run

SCHEMA = json.loads((Path(__file__).resolve().parents[1] / "schemas/event.schema.json").read_text())
SECRET = "azure-secret-NE-DOIT-JAMAIS-SORTIR"


def test_path_detection():
    for path in ("/v1/chat/completions", "/openai/v1/chat/completions", "/api/v1/chat/completions",
                 "/openai/deployments/gpt4o/chat/completions"):
        assert is_chat_path(path)
    assert is_responses_path("/v1/responses") and is_responses_path("/openai/v1/responses")
    assert not is_chat_path("/v1/models") and not is_chat_path("/v1/embeddings") and not is_responses_path("/v1/models")


def test_azure_sdk_is_relayed_and_captured_with_deployment_as_model():
    async def scenario(up, gw, events, fake):
        client = openai.AsyncAzureOpenAI(azure_endpoint=gw, api_key=SECRET, api_version="2024-10-21", max_retries=0)
        r1 = await client.chat.completions.create(model="gpt4o-prod", messages=[{"role": "user", "content": "Salut"}])
        stream = await client.chat.completions.create(model="gpt4o-prod", stream=True,
                                                      messages=[{"role": "user", "content": "Salut"}])
        async for _ in stream:
            pass
        async with aiohttp.ClientSession() as s:  # corps sans "model" : seul le déploiement de l'URL le donne
            url = gw + "/openai/deployments/gpt4o-prod/chat/completions?api-version=2024-10-21"
            async with s.post(url, json={"messages": [{"role": "user", "content": "x"}]},
                              headers={"api-key": SECRET}) as r:
                assert r.status == 200
        await asyncio.sleep(0.05)
        return r1, events, fake
    r1, events, fake = run(scenario)
    assert r1.choices[0].message.content == "Bonjour le monde."
    assert len(events) == 3
    for e in events:
        jsonschema.validate(e, SCHEMA)
        assert e["model"] == "gpt4o-prod" and e["endpoint"].startswith("/openai/deployments/gpt4o-prod/")
        assert e["response"]["content"] == "Bonjour le monde."
        assert SECRET not in json.dumps(e)
    assert events[1]["request"]["params"]["stream"] is True and events[1]["usage"]["input_tokens"] == 12
    # la requête amont garde ?api-version= et l'en-tête api-key, la passerelle n'en retient rien
    seen = [h for h in fake[fake_openai.SEEN] if "path" in h]  # entrées posées par la route Azure
    assert len(seen) == 3 and all("api-version=2024-10-21" in h["path"] and h["api-key"] == SECRET for h in seen)


def test_azure_error_is_relayed_untouched():
    async def scenario(up, gw, events, fake):
        async with aiohttp.ClientSession() as s:
            async with s.post(gw + "/openai/deployments/d/chat/completions", json={"model": "d", "messages": []}) as r:
                status = r.status  # pas d'api-version : 400 de l'amont
            async with s.post(gw + "/openai/deployments/d/chat/completions?api-version=1", json={"messages": []}) as r:
                status2 = r.status  # pas de clé : 401 de l'amont
        await asyncio.sleep(0.05)
        return (status, status2), events
    (s1, s2), events = run(scenario)
    assert (s1, s2) == (400, 401)
    assert [e["http_status"] for e in events] == [400, 401]


def test_groq_and_openrouter_prefixes_are_captured():
    async def scenario(up, gw, events, fake):
        for prefix in ("/openai/v1", "/api/v1"):
            client = openai.AsyncOpenAI(api_key=SECRET, base_url=gw + prefix, max_retries=0)
            stream = await client.chat.completions.create(model="llama-3.3-70b", stream=True,
                                                          messages=[{"role": "user", "content": "Salut"}])
            async for _ in stream:
                pass
        await asyncio.sleep(0.05)
        return None, events
    _, events = run(scenario)
    assert [e["endpoint"] for e in events] == ["/openai/v1/chat/completions", "/api/v1/chat/completions"]
    # le flux a reçu include_usage ajouté par la passerelle : les jetons sont lus aussi sur ces chemins
    assert all(e["usage"]["input_tokens"] == 12 and e["model"] == "llama-3.3-70b" for e in events)
