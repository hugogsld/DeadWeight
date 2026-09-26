"""D1.2 : chaque appel relayé devient un événement relisible, sans bloquer le relais."""
import asyncio
import json
import threading
import time
from pathlib import Path

import aiohttp
import jsonschema
from aiohttp import web

from gateway import fake_openai
from gateway.proxy import make_app
from gateway.store import EventStore, count, read_events
from report.audit import build_report

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schemas/event.schema.json").read_text())
EVENTS = [json.loads(line) for line in (ROOT / "fixtures/events.jsonl").read_text().splitlines()]


async def _serve(app):
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    return runner, f"http://127.0.0.1:{runner.addresses[0][1]}"


def relay_calls(db, n, concurrency=50):
    """n appels à travers la passerelle (moitié en streaming), store SQLite branché."""
    async def main():
        up_runner, up = await _serve(fake_openai.make_app())
        gw_runner, gw = await _serve(make_app(upstream=up, on_event=lambda e: None, store=EventStore(db)))
        sem = asyncio.Semaphore(concurrency)

        async def call(s, i):
            async with sem:
                body = {"model": "gpt-4o", "stream": i % 2 == 1,
                        "messages": [{"role": "user", "content": f"Classe le ticket {i}"}]}
                async with s.post(gw + "/v1/chat/completions", json=body,
                                  headers={"Authorization": "Bearer sk-test", "x-deadweight-app": "triage"}) as r:
                    await r.read()
                    return r.status
        try:
            async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=0)) as s:
                return await asyncio.gather(*(call(s, i) for i in range(n)))
        finally:
            await gw_runner.cleanup()  # ferme le store : la file est vidée
            await up_runner.cleanup()
    return asyncio.run(main())


def test_1000_relayed_calls_give_1000_readable_events(tmp_path):
    db = str(tmp_path / "events.db")
    statuses = relay_calls(db, 1000)
    assert statuses == [200] * 1000
    assert count(db) == 1000
    events = list(read_events(db))
    assert len({e["event_id"] for e in events}) == 1000
    for e in events:
        jsonschema.validate(e, SCHEMA)
    assert sum(e["request"]["params"]["stream"] for e in events) == 500
    assert all(e["response"]["content"] == "Bonjour le monde." for e in events)
    assert "sk-test" not in Path(db).read_bytes().decode("latin-1")


def test_events_feed_the_audit_report(tmp_path):
    """Passerelle -> SQLite -> rapport : la chaîne du critère de réussite du weekend."""
    db = str(tmp_path / "events.db")
    relay_calls(db, 60)
    report = build_report(read_events(db, app_id="triage"))
    assert "constats" in report


def test_roundtrip_keeps_events_identical(tmp_path):
    db = str(tmp_path / "events.db")
    store = EventStore(db)
    for e in EVENTS:
        store.put(e)
    store.close()
    stored = {e["event_id"]: e for e in read_events(db)}
    assert stored == {e["event_id"]: e for e in EVENTS}
    assert count(db, app_id="mail-triage") == sum(e["app_id"] == "mail-triage" for e in EVENTS)


def test_put_never_blocks_when_database_is_stuck(tmp_path):
    release = threading.Event()

    class StuckStore(EventStore):
        def _write(self, batch):
            release.wait()
            super()._write(batch)

    store = StuckStore(str(tmp_path / "events.db"), max_pending=10)
    store.put(EVENTS[0])  # pris par le thread d'écriture, qui reste coincé
    time.sleep(0.05)
    t0 = time.perf_counter()
    for e in EVENTS[1:21]:
        store.put(e)
    assert time.perf_counter() - t0 < 0.05
    assert store.dropped == 10
    release.set()
    store.close()
    assert count(store.path) == 11


def test_close_flushes_pending_events(tmp_path):
    db = str(tmp_path / "events.db")
    store = EventStore(db)
    for i in range(1200):
        store.put({**EVENTS[0], "event_id": f"evt_{i}"})
    store.close()
    assert count(db) == 1200
