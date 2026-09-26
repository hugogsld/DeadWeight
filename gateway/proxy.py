"""D1.1 — Passerelle passe-plat OpenAI, streaming compris.

Le client change seulement son base_url (http://127.0.0.1:8080/v1) : chaque
requête part telle quelle chez OpenAI et la réponse revient octet pour octet.
Les morceaux de streaming sont relayés dès leur arrivée, sans tampon ; la
complétion est reconstituée à côté pour la capture.

L'en-tête Authorization du client est relayé tel quel. Il n'est jamais
stocké, jamais journalisé, jamais mis dans l'événement.

Chaque événement est écrit dans SQLite par gateway.store (D1.2), hors du
chemin critique ; GATEWAY_DB en donne le chemin.
"""
import asyncio
import gzip
import json
import logging
import os
import time
from datetime import datetime, timezone

from aiohttp import ClientError, ClientSession, ClientTimeout, TCPConnector, web
from yarl import URL

from connectors import otel
from gateway import mirror as mirror_mode
from gateway import shortcircuit
from gateway.capture import StreamAccumulator, build_event, fmt
from gateway.store import EventStore

log = logging.getLogger("deadweight.gateway")

UPSTREAM = os.environ.get("GATEWAY_OPENAI_UPSTREAM", "https://api.openai.com").rstrip("/")
# D1.3 : le client pointe son SDK sur /anthropic ou /gemini ; tout le reste part chez OpenAI.
UPSTREAMS = {
    "anthropic": os.environ.get("GATEWAY_ANTHROPIC_UPSTREAM", "https://api.anthropic.com").rstrip("/"),
    "gemini": os.environ.get("GATEWAY_GEMINI_UPSTREAM", "https://generativelanguage.googleapis.com").rstrip("/"),
}

# En-têtes propres à un saut HTTP : jamais relayés.
HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te",
       "trailer", "trailers", "transfer-encoding", "upgrade", "host", "content-length"}
# Côté amont on demande du non compressé : les octets relayés sont ceux qu'on capture.
REQ_DROP = HOP | {"accept-encoding"}
RESP_DROP = HOP | {"content-encoding"}


UPSTREAM_KEY = web.AppKey("upstreams", dict)
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


def route(path):
    """Chemin reçu -> (fournisseur, chemin à appeler chez lui)."""
    for provider in UPSTREAMS:
        prefix = "/" + provider
        if path == prefix or path.startswith(prefix + "/"):
            return provider, path[len(prefix):] or "/"
    return "openai", path


def is_captured(provider, method, path):
    if method != "POST":
        return False
    if provider == "openai":
        return path == "/v1/chat/completions"
    if provider == "anthropic":
        return path == "/v1/messages"
    # Gemini : /v1beta/models/<modele>:generateContent ou :streamGenerateContent
    return path.endswith((":generateContent", ":streamGenerateContent")) and "/models/" in path


def _ask_usage(provider, path, body):
    """Streaming OpenAI sans ``stream_options.include_usage`` : OpenAI ne dit pas combien de
    jetons il facture. On le demande à la place du client, qui n'en voit rien (_DropUsage).
    Renvoie (corps à envoyer en amont, demandé ?). Si le client a choisi, on respecte."""
    if provider != "openai" or path != "/v1/chat/completions":
        return body, False
    try:
        req = json.loads(body)
    except ValueError:
        return body, False
    opts = req.get("stream_options") if isinstance(req, dict) else None
    if not isinstance(req, dict) or not req.get("stream") or not isinstance(opts, (dict, type(None))):
        return body, False
    if opts and "include_usage" in opts:
        return body, False
    req["stream_options"] = {**(opts or {}), "include_usage": True}
    return json.dumps(req, ensure_ascii=False).encode(), True


class _DropUsage:
    """Retire du flux rendu au client le seul morceau qu'on a ajouté : celui de l'usage
    (``choices: []``). Découpe par évènement SSE, quelles que soient les coupures réseau."""

    def __init__(self):
        self.buf = b""

    def feed(self, chunk):
        self.buf += chunk
        out = []
        while True:
            cuts = [(i, len(sep)) for sep in (b"\n\n", b"\r\n\r\n") if (i := self.buf.find(sep)) >= 0]
            if not cuts:
                return b"".join(out)
            i, n = min(cuts)
            event, self.buf = self.buf[:i + n], self.buf[i + n:]
            if not self._usage_only(event):
                out.append(event)

    def flush(self):
        rest, self.buf = self.buf, b""
        return rest

    @staticmethod
    def _usage_only(event):
        for line in event.splitlines():
            if line.startswith(b"data:"):
                try:
                    obj = json.loads(line[5:])
                except ValueError:
                    return False
                return isinstance(obj, dict) and obj.get("choices") == [] and obj.get("usage") is not None
        return False


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


async def receive_traces(request):
    """B2 : réception OpenTelemetry (OTLP/HTTP, JSON). Le client ajoute cette adresse comme destination
    de ses traces ; les appels d'IA qu'elles décrivent entrent dans la même capture que le trafic relayé."""
    if "json" not in request.headers.get("content-type", ""):
        return web.json_response({"message": "Deadweight lit OTLP/HTTP en JSON : réglez "
                                  "OTEL_EXPORTER_OTLP_PROTOCOL=http/json côté client."}, status=415)
    body = await request.read()
    if body[:2] == b"\x1f\x8b":  # aiohttp décompresse déjà en général ; au cas où il reste du gzip
        body = gzip.decompress(body)
    try:
        events, report = otel.read(json.loads(body))
    except (ValueError, KeyError, TypeError):
        return web.json_response({"message": "export OTLP/JSON illisible"}, status=400)
    for event in events:
        _emit(request.app, event)
    log.info("otel : %d appel(s) sur %d span(s), niveaux %s", report["appels_lus"], report["spans"], report["niveaux"])
    return web.json_response({"partialSuccess": {}})


async def relay(request):
    app = request.app
    t0 = time.perf_counter()
    ts_start = _now()
    provider, path = route(request.path)
    captured = is_captured(provider, request.method, path)
    body = await request.read()

    headers = {k: v for k, v in request.headers.items()
               if k.lower() not in REQ_DROP and not k.lower().startswith("x-deadweight-")}
    headers["Accept-Encoding"] = "identity"
    base = app[UPSTREAM_KEY][provider]
    # la requête part telle quelle, ?key= de Gemini compris ; seul `path` (sans requête) va dans l'événement
    url = base + path + ("?" + request.query_string if request.query_string else "")

    meta = dict(req_body=body, upstream=URL(base).host, app_id=request.headers.get("x-deadweight-app") or "default",
                trace_id=request.headers.get("x-deadweight-trace") or None,
                endpoint=path, ts_start=ts_start, provider=provider)

    # D3.3 ne sait répondre qu'au format OpenAI
    hit = shortcircuit.match(app[SHORTCUT], body, meta["app_id"]) if captured and provider == "openai" else None
    if hit is not None:
        return await _answer(request, meta, t0, *hit)

    # l'événement garde la requête du client ; seul l'amont reçoit la demande d'usage
    sent, asked_usage = _ask_usage(provider, path, body) if captured else (body, False)
    try:
        upstream = await app[SESSION].request(request.method, url, headers=headers,
                                                data=sent or None, allow_redirects=False)
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
        # Gemini sans ?alt=sse streame un tableau JSON : relayé morceau par morceau lui aussi
        streaming = (upstream.headers.get("content-type", "").startswith("text/event-stream")
                     or path.endswith(":streamGenerateContent"))
        acc = fmt(provider).Accumulator() if streaming and captured else None

        if streaming:
            await resp.prepare(request)
            drop = _DropUsage() if asked_usage else None
            try:
                async for chunk in upstream.content.iter_any():
                    if ttft is None:
                        ttft = (time.perf_counter() - t0) * 1000
                    out = drop.feed(chunk) if drop else chunk
                    if out:
                        await resp.write(out)
                    if acc is not None:
                        acc.feed(chunk)
                if drop and (rest := drop.flush()):
                    await resp.write(rest)
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


def make_app(upstream=None, on_event=None, store=None, shortcut=None, upstreams=None, mirror=None):
    """``store`` : EventStore où persister ; ``on_event`` : sink supplémentaire (log par défaut) ;
    ``shortcut`` : preuves du court-circuit D3.3 (sinon GATEWAY_SHORTCIRCUIT, sinon désactivé) ;
    ``mirror`` : preuves du mode miroir D4.3 (sinon GATEWAY_MIRROR, sinon désactivé) ;
    ``upstream`` : OpenAI ; ``upstreams`` : {"anthropic": url, "gemini": url} (tests)."""
    app = web.Application(client_max_size=64 * 1024 * 1024)
    app[UPSTREAM_KEY] = {"openai": (upstream or UPSTREAM).rstrip("/"), **UPSTREAMS,
                         **{k: v.rstrip("/") for k, v in (upstreams or {}).items()}}
    sink = on_event or log_event
    if store is None:
        app[SINK] = sink
    else:
        def both(event):
            store.put(event)
            sink(event)
        app[SINK] = both

        async def close_store(app):
            await asyncio.get_running_loop().run_in_executor(None, store.close)
        app.on_cleanup.append(close_store)
    mirror_path = mirror or os.environ.get("GATEWAY_MIRROR")
    if mirror_path:
        # D4.3 : branché sur la capture, jamais sur la réponse rendue au client
        watcher = mirror_mode.Mirror(mirror_mode.load(mirror_path))
        inner = app[SINK]

        def mirrored(event):
            watcher.observe(event)
            inner(event)
        app[SINK] = mirrored

        async def close_mirror(app):
            watcher.close()
        app.on_cleanup.append(close_mirror)
        log.info("miroir actif sur %d constat(s), journal %s", len(watcher.table), watcher.path)
    path = shortcut or os.environ.get("GATEWAY_SHORTCIRCUIT")
    app[SHORTCUT] = shortcircuit.load(path) if path else {}
    if app[SHORTCUT]:
        log.info("court-circuit actif sur %d constat(s) prouvé(s)", len(app[SHORTCUT]))
    app.on_startup.append(_open)
    app.on_cleanup.append(_close)
    app.router.add_post("/v1/traces", receive_traces)  # avant le relais : OpenAI n'a pas cette route
    app.router.add_route("*", "/{tail:.*}", relay)
    return app


def main():
    logging.basicConfig(level=os.environ.get("GATEWAY_LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(name)s %(message)s")
    host = os.environ.get("GATEWAY_HOST", "127.0.0.1")
    port = int(os.environ.get("GATEWAY_PORT", "8080"))
    store = EventStore()
    print(f"Deadweight gateway   OpenAI: http://{host}:{port}/v1   Anthropic: http://{host}:{port}/anthropic"
          f"   Gemini: http://{host}:{port}/gemini   events: {store.path}", flush=True)
    web.run_app(make_app(store=store), host=host, port=port, access_log=None, print=None)


if __name__ == "__main__":
    main()
