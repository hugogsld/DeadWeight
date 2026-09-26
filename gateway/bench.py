"""Latence ajoutée par la passerelle (D1.1 : < 30 ms au p95) et par SQLite (D1.2 : aucune).

Même requête envoyée au faux OpenAI en direct, à travers la passerelle, puis à
travers la passerelle qui écrit dans SQLite, en alternance.

    python3 -m gateway.bench              # 300 requêtes par mode
    python3 -m gateway.bench 1000 20      # 1000 requêtes, 20 en parallèle
"""
import asyncio
import math
import os
import shutil
import sys
import tempfile
import time

import aiohttp
from aiohttp import web

from gateway import fake_openai
from gateway.proxy import make_app
from gateway.store import EventStore, count

BODY = {"model": "gpt-4o", "messages": [{"role": "user", "content": "Classe ce mail : facture n°4471"}]}


def pct(values, q):
    s = sorted(values)
    return s[math.ceil(q * len(s)) - 1]


async def _serve(app):
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    return runner, f"http://127.0.0.1:{runner.addresses[0][1]}"


async def one(session, base, stream):
    """Durée totale et temps jusqu'au premier morceau, en ms."""
    t0 = time.perf_counter()
    first = None
    async with session.post(base + "/v1/chat/completions", json={**BODY, "stream": stream},
                            headers={"Authorization": "Bearer sk-bench"}) as r:
        async for _ in r.content.iter_any():
            if first is None:
                first = (time.perf_counter() - t0) * 1000
    return (time.perf_counter() - t0) * 1000, first


async def series(session, base, stream, n, concurrency):
    sem = asyncio.Semaphore(concurrency)

    async def job():
        async with sem:
            return await one(session, base, stream)
    return await asyncio.gather(*(job() for _ in range(n)))


async def main(n, concurrency):
    tmp = tempfile.mkdtemp()
    store = EventStore(os.path.join(tmp, "events.db"))
    up_runner, up = await _serve(fake_openai.make_app(delay=0.002))
    gw_runner, gw = await _serve(make_app(upstream=up, on_event=lambda e: None))
    db_runner, gw_db = await _serve(make_app(upstream=up, on_event=lambda e: None, store=store))
    targets = (("direct", up), ("passerelle", gw), ("passerelle + SQLite", gw_db))
    ok = True
    try:
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=0)) as s:
            for _, base in targets:  # chauffe
                await series(s, base, False, 20, 1)
            print(f"{n} requêtes par mode, {concurrency} en parallèle\n")
            print(f"{'mesure':28} {'cible':20} {'p50':>7} {'p95':>7} {'ajout p95':>10}")
            for stream in (False, True):
                runs = {name: [] for name, _ in targets}
                for _ in range(4):  # alternance pour lisser le bruit de la machine
                    for name, base in targets:
                        runs[name] += await series(s, base, stream, n // 4, concurrency)
                for label, idx in (("total", 0), ("premier morceau", 1)):
                    if not stream and idx == 1:
                        continue
                    base_p95 = pct([x[idx] for x in runs["direct"]], .95)
                    for name, _ in targets:
                        v = [x[idx] for x in runs[name]]
                        added = pct(v, .95) - base_p95
                        if name != "direct":
                            ok &= added < 30
                        title = f"{'streaming' if stream else 'simple'} — {label}"
                        print(f"{title:28} {name:20} {pct(v, .5):>5.1f}ms {pct(v, .95):>5.1f}ms "
                              + ("" if name == "direct" else f"{added:>+8.1f}ms"))
    finally:
        await db_runner.cleanup()  # ferme le store : la file est vidée
        await gw_runner.cleanup()
        await up_runner.cleanup()
    print(f"\n{count(store.path)} événements écrits dans SQLite, {store.dropped} perdu(s)")
    shutil.rmtree(tmp)
    print("OK : latence ajoutée < 30 ms au p95" if ok else "ÉCHEC : latence ajoutée >= 30 ms au p95")
    return ok


if __name__ == "__main__":
    args = [int(a) for a in sys.argv[1:]]
    sys.exit(0 if asyncio.run(main(args[0] if args else 300, args[1] if len(args) > 1 else 1)) else 1)
