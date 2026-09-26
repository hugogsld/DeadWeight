"""Latence ajoutée par la passerelle, capture activée (critère D1.1 : < 30 ms au p95).

Même requête envoyée au faux OpenAI en direct puis à travers la passerelle,
en alternance. On compare les p50/p95 des deux séries.

    python3 -m gateway.bench              # 300 requêtes par mode
    python3 -m gateway.bench 1000 20      # 1000 requêtes, 20 en parallèle
"""
import asyncio
import math
import sys
import time

import aiohttp
from aiohttp import web

from gateway import fake_openai
from gateway.proxy import make_app

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
    captured = []
    up_runner, up = await _serve(fake_openai.make_app(delay=0.002))
    gw_runner, gw = await _serve(make_app(upstream=up, on_event=captured.append))
    ok = True
    try:
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=0)) as s:
            await series(s, gw, False, 20, 1)  # chauffe
            await series(s, up, False, 20, 1)
            print(f"{n} requêtes par mode, {concurrency} en parallèle, capture activée\n")
            print(f"{'mode':26} {'direct p50':>10} {'p95':>7} {'via p50':>9} {'p95':>7} {'ajout p95':>10}")
            for stream in (False, True):
                direct, via = [], []
                for _ in range(4):  # alternance pour lisser le bruit de la machine
                    direct += await series(s, up, stream, n // 4, concurrency)
                    via += await series(s, gw, stream, n // 4, concurrency)
                for label, idx in (("total", 0), ("premier morceau", 1)):
                    if not stream and idx == 1:
                        continue
                    d = [x[idx] for x in direct]
                    v = [x[idx] for x in via]
                    added = pct(v, .95) - pct(d, .95)
                    ok &= added < 30
                    name = f"{'streaming' if stream else 'simple'} — {label}"
                    print(f"{name:26} {pct(d, .5):>8.1f}ms {pct(d, .95):>5.1f}ms "
                          f"{pct(v, .5):>7.1f}ms {pct(v, .95):>5.1f}ms {added:>+8.1f}ms")
    finally:
        await gw_runner.cleanup()
        await up_runner.cleanup()
    print(f"\n{len(captured)} événements capturés")
    print("OK : latence ajoutée < 30 ms au p95" if ok else "ÉCHEC : latence ajoutée >= 30 ms au p95")
    return ok


if __name__ == "__main__":
    args = [int(a) for a in sys.argv[1:]]
    sys.exit(0 if asyncio.run(main(args[0] if args else 300, args[1] if len(args) > 1 else 1)) else 1)
