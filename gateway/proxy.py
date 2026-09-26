"""D1.1 — Passerelle passe-plat OpenAI, streaming compris.

Le client change seulement son base_url (http://127.0.0.1:8080/v1) : chaque
requête part telle quelle chez OpenAI et la réponse revient octet pour octet.
Les morceaux de streaming sont relayés dès leur arrivée, sans tampon ; la
complétion est reconstituée à côté pour la capture.

L'en-tête Authorization du client est relayé tel quel. Il n'est jamais
stocké, jamais journalisé, jamais mis dans l'événement.
"""
import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone

from aiohttp import ClientError, ClientSession, ClientTimeout, TCPConnector, web
from yarl import URL

from gateway import shortcircuit
from gateway.capture import StreamAccumulator, build_event

log = logging.getLogger("deadweight.gateway")

UPSTREAM = os.environ.get("GATEWAY_OPENAI_UPSTREAM", "https://api.openai.com").rstrip("/")
CAPTURED = {("POST", "/v1/chat/completions")}

# En-têtes propres à un saut HTTP : jamais relayés.
HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te",
       "trailer", "trailers", "transfer-encoding", "upgrade", "host", "content-length"}
# Côté amont on demande du non compressé : les octets relayés sont ceux qu'on capture.
REQ_DROP = HOP | {"accept-encoding"}
RESP_DROP = HOP | {"content-encoding"}


UPSTREAM_KEY = web.AppKey("upstream", str)
SINK = web.AppKey("on_event", object)
SESSION = web.AppKey("session", ClientSession)
SHORTCUT = web.AppKey("shortcut", dict)


def _now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def log_event(event):
    """Sink par défaut : une ligne de résumé, sans contenu ni en-tête. D1.2 persiste."""
    u = event["usage"]
    log.info("%s %s %s %d %.0fms tokens=%s/%s", event["app_id"], event["endpoint"], event["model"],
             event["http_status"], event["latency_ms"], u["input_tokens"], u["output_tokens"])


def _emit(app, event):
    try:
        app[SINK](event)
    except Exception:  # la capture ne doit jamais casser le relais
        log.exception("capture: sink en échec")


async def _answer(request, meta, t0, finding_id, output):
    """D3.3 : réponse rendue par les règles prouvées, sans appel amont. Capturée quand même."""
    streaming = bool(json.loads(meta["req_body"]).get("stream"))
    payload = shortcircuit.stream(output) if streaming else shortcircuit.completion(output)
    resp = web.Response(status=200, body=payload, headers={"x-deadweight-shortcircuit": finding_id},
                        content_type="text/event-stream" if streaming else "application/json")
    acc = None
    if streaming:
        acc = StreamAccumulator()
        acc.feed(payload)
    latency = (time.perf_counter() - t0) * 1000
    _emit(request.app, build_event(**{**meta, "upstream": "deadweight"}, status=200,
                                   resp_body=None if streaming else payload, stream=acc,
                                   ts_end=_now(), latency_ms=latency,
                                   ttft_ms=latency if streaming else None))
    log.info("court-circuit %s %s", meta["app_id"], finding_id)
    return resp


async def relay(request):
    app = request.app
    t0 = time.perf_counter()
    ts_start = _now()
    captured = (request.method, request.path) in CAPTURED
    body = await request.read()

    headers = {k: v for k, v in request.headers.items()
               if k.lower() not in REQ_DROP and not k.lower().startswith("x-deadweight-")}
    headers["Accept-Encoding"] = "identity"
    url = app[UPSTREAM_KEY] + request.path_qs

    meta = dict(req_body=body, upstream=URL(app[UPSTREAM_KEY]).host, app_id=request.headers.get("x-deadweight-app") or "default",
                trace_id=request.headers.get("x-deadweight-trace") or None,
                endpoint=request.path, ts_start=ts_start)

    hit = shortcircuit.match(app[SHORTCUT], body, meta["app_id"]) if captured else None
    if hit is not None:
        return await _answer(request, meta, t0, *hit)

    try:
        upstream = await app[SESSION].request(request.method, url, headers=headers,
                                                data=body or None, allow_redirects=False)
    except (ClientError, asyncio.TimeoutError, OSError) as exc:
        payload = ('{"error":{"message":"deadweight: upstream unreachable","type":"deadweight_upstream_error",'
                   '"param":null,"code":null}}').encode()
        if captured:
            _emit(app, build_event(**meta, status=502, resp_body=payload, ts_end=_now(),
                                   latency_ms=(time.perf_counter() - t0) * 1000, ttft_ms=None,
                                   transport_error={"type": "upstream_unreachable", "message": type(exc).__name__}))
        return web.Response(status=502, body=payload, content_type="application/json")

    ttft, transport_error, raw, acc = None, None, None, None
    try:
        resp = web.StreamResponse(status=upstream.status, reason=upstream.reason)
        for k, v in upstream.headers.items():
            if k.lower() not in RESP_DROP:
                resp.headers.add(k, v)
        streaming = upstream.headers.get("content-type", "").startswith("text/event-stream")
        acc = StreamAccumulator() if streaming and captured else None

        if streaming:
            await resp.prepare(request)
            try:
                async for chunk in upstream.content.iter_any():
                    if ttft is None:
                        ttft = (time.perf_counter() - t0) * 1000
                    await resp.write(chunk)
                    if acc is not None:
                        acc.feed(chunk)
                await resp.write_eof()
            except (ConnectionResetError, ClientError) as exc:
                transport_error = {"type": "stream_interrupted", "message": type(exc).__name__}
        else:
            raw = await upstream.read()
            resp.content_length = len(raw)
            await resp.prepare(request)
            await resp.write(raw)
            await resp.write_eof()
        return resp
    finally:
        upstream.release()
        if captured:
            _emit(app, build_event(**meta, status=upstream.status, resp_body=raw, stream=acc,
                                   ts_end=_now(), latency_ms=(time.perf_counter() - t0) * 1000,
                                   ttft_ms=ttft, transport_error=transport_error))


async def _open(app):
    # Pas de délai total : une génération longue peut durer plusieurs minutes.
    app[SESSION] = ClientSession(connector=TCPConnector(limit=0, ttl_dns_cache=300),
                                   timeout=ClientTimeout(total=None, sock_connect=10),
                                   auto_decompress=False, skip_auto_headers=("User-Agent",))


async def _close(app):
    await app[SESSION].close()


def make_app(upstream=None, on_event=None, shortcut=None):
    app = web.Application(client_max_size=64 * 1024 * 1024)
    app[UPSTREAM_KEY] = (upstream or UPSTREAM).rstrip("/")
    app[SINK] = on_event or log_event
    path = shortcut or os.environ.get("GATEWAY_SHORTCIRCUIT")
    app[SHORTCUT] = shortcircuit.load(path) if path else {}
    if app[SHORTCUT]:
        log.info("court-circuit actif sur %d constat(s) prouvé(s)", len(app[SHORTCUT]))
    app.on_startup.append(_open)
    app.on_cleanup.append(_close)
    app.router.add_route("*", "/{tail:.*}", relay)
    return app


def main():
    logging.basicConfig(level=os.environ.get("GATEWAY_LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(name)s %(message)s")
    host = os.environ.get("GATEWAY_HOST", "127.0.0.1")
    port = int(os.environ.get("GATEWAY_PORT", "8080"))
    print(f"Deadweight gateway -> {UPSTREAM}   base_url: http://{host}:{port}/v1", flush=True)
    web.run_app(make_app(), host=host, port=port, access_log=None, print=None)


if __name__ == "__main__":
    main()
