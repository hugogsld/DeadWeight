"""Produit de vraies traces OpenTelemetry avec l'instrumentation officielle OpenAI, contre le faux
OpenAI du repo. Sert de jeu de test au connecteur OpenTelemetry (B2) : on ne fabrique pas les traces
à la main, on prend ce qu'un vrai client enverrait.

Dépendances à part, jamais dans requirements.txt :
    python -m venv /tmp/otel && /tmp/otel/bin/pip install opentelemetry-sdk \
        "opentelemetry-instrumentation-openai-v2==2.3b0" opentelemetry-exporter-otlp-proto-common "openai<3" "wrapt<2" aiohttp
    PYTHONPATH=. /tmp/otel/bin/python scripts/gen_otel_fixture.py

Écrit fixtures/otel/sdk-openai-v2.json au format OTLP/JSON (ce qu'un collecteur exporte, ou ce que
reçoit /v1/traces) : réglage par défaut du client, donc usage et structure sans contenu (niveaux 1 et 3).
Avec cette version de l'instrumentation, le contenu passe par le signal « logs », pas par les spans.
"""
import asyncio
import json
import os
import threading
from pathlib import Path

from aiohttp import web

from gateway import fake_openai

OUT = Path(__file__).resolve().parents[1] / "fixtures" / "otel"


def _serve():
    """Faux OpenAI dans un fil à part ; rend son URL."""
    ready, box = threading.Event(), {}

    def run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        runner = web.AppRunner(fake_openai.make_app())
        loop.run_until_complete(runner.setup())
        site = web.TCPSite(runner, "127.0.0.1", 0)
        loop.run_until_complete(site.start())
        box["url"] = f"http://127.0.0.1:{runner.addresses[0][1]}/v1"
        ready.set()
        loop.run_forever()

    threading.Thread(target=run, daemon=True).start()
    ready.wait(5)
    return box["url"]


def _hex_ids(payload):
    """OTLP/JSON code traceId/spanId en hexadécimal, pas en base64 comme le JSON protobuf standard."""
    import base64
    for rs in payload.get("resourceSpans", []):
        for ss in rs.get("scopeSpans", []):
            for span in ss.get("spans", []):
                for key in ("traceId", "spanId", "parentSpanId"):
                    if span.get(key):
                        span[key] = base64.b64decode(span[key]).hex()
    return payload


def generate(content):
    """Un processus par mode : l'instrumentation lit ses réglages au démarrage."""
    if content:
        os.environ["OTEL_SEMCONV_STABILITY_OPT_IN"] = "gen_ai_latest_experimental"
        os.environ["OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"] = "SPAN_ONLY"
    from google.protobuf.json_format import MessageToDict
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.common.trace_encoder import encode_spans
    from opentelemetry.instrumentation.openai_v2 import OpenAIInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    provider = TracerProvider(resource=Resource.create({"service.name": "tri-des-mails"}))
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    OpenAIInstrumentor().instrument()

    import openai
    client = openai.OpenAI(base_url=_serve(), api_key="sk-otel-NE-DOIT-JAMAIS-SORTIR", max_retries=0)
    tracer = trace.get_tracer("workflow")
    system = "Classe le mail : spam, facture ou support."
    for i, mail in enumerate(["Gagnez un iPhone", "Votre facture 42", "Mon compte est bloqué"]):
        with tracer.start_as_current_span(f"traiter-mail-{i}"):  # une trace par mail, deux appels
            client.chat.completions.create(model="gpt-4o", temperature=0, max_tokens=5,
                                           messages=[{"role": "system", "content": system},
                                                     {"role": "user", "content": mail}])
            stream = client.chat.completions.create(model="gpt-4o-mini", stream=True,
                                                    stream_options={"include_usage": True},
                                                    messages=[{"role": "user", "content": f"Résume : {mail}"}])
            for _ in stream:
                pass
    with tracer.start_as_current_span("agent"):
        client.chat.completions.create(model="tools", messages=[{"role": "user", "content": "Météo à Paris ?"}],
                                       tools=[{"type": "function", "function": {
                                           "name": "meteo", "description": "Météo d'une ville",
                                           "parameters": {"type": "object", "properties": {"ville": {"type": "string"}}}}}])
    try:
        openai.OpenAI(base_url="http://127.0.0.1:9/v1", api_key="sk-otel-NE-DOIT-JAMAIS-SORTIR",
                      max_retries=0).chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": "x"}])
    except openai.APIConnectionError:
        pass  # un appel en échec, tracé comme tel
    provider.force_flush()
    payload = _hex_ids(MessageToDict(encode_spans(exporter.get_finished_spans())))
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "sdk-openai-v2.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(exporter.get_finished_spans())} spans -> {path}")


if __name__ == "__main__":
    generate(content=False)
