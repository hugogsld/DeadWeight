"""Démo sans clé : faux OpenAI, vraie passerelle, SQLite et même commande d'audit."""
import argparse
import asyncio
from contextlib import AsyncExitStack
from pathlib import Path
import sys
import tempfile
import time

from aiohttp import ClientSession, ClientTimeout, web

from gateway.fake_openai import make_app as fake_app
from gateway.proxy import make_app as gateway_app
from gateway.store import EventStore
from scripts.audit import audit


async def _serve(app, stack):
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    stack.push_async_callback(runner.cleanup)
    site = web.TCPSite(runner, '127.0.0.1', 0)
    await site.start()
    return f'http://127.0.0.1:{runner.addresses[0][1]}'


async def run_demo(output_root='out'):
    """Chaque lancement a son dossier et ses ports ; jamais de clé ni de trafic externe."""
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix='demo-', dir=output_root))
    store = EventStore(str(directory / 'events.db'))
    try:
        async with AsyncExitStack() as stack:
            upstream = await _serve(fake_app(), stack)
            # Le sink enregistre les événements sans lire GATEWAY_DB ni les clés client.
            gateway = await _serve(gateway_app(upstream=upstream, on_event=store.put), stack)
            async with ClientSession(timeout=ClientTimeout(total=10)) as client:
                # 36 entrées distinctes dépassent le seuil de détection de R1 (30).
                for i in range(36):
                    body = {'model': 'gpt-4o', 'messages': [
                        {'role': 'system', 'content': 'Réponds brièvement.'},
                        {'role': 'user', 'content': f'Exemple de démonstration numéro {i}'}]}
                    async with client.post(gateway + '/v1/chat/completions', json=body,
                                           headers={'x-deadweight-app': 'demo'}) as response:
                        response.raise_for_status()
                        await response.read()
    finally:
        # Vider le thread d'écriture avant l'export, y compris après une erreur HTTP.
        await asyncio.to_thread(store.close)
    report = directory / 'audit.html'
    if audit(directory / 'events.db', report):
        raise RuntimeError('Rapport de démonstration non généré.')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out-dir', default='out')
    args = parser.parse_args()
    start = time.perf_counter()
    try:
        asyncio.run(run_demo(args.out_dir))
    except (Exception, KeyboardInterrupt):
        print('Démo interrompue ou impossible : vérifiez les droits d’écriture dans out/ '
              'et que votre environnement autorise les connexions locales, puis relancez make demo.',
              file=sys.stderr)
        return 1
    print(f'Démo terminée en {time.perf_counter() - start:.1f} s : 36 appels fictifs, '
          'aucune clé utilisée. Les chiffres du rapport sont synthétiques.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
