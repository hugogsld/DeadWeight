"""Faux OpenAI / Anthropic / Gemini sur des ports fixes, pour la boucle de bout en bout."""
import asyncio
import sys

from aiohttp import web

from gateway import fake_anthropic, fake_gemini, fake_openai


async def main(base):
    runners = []
    for i, app in enumerate((fake_openai.make_app(), fake_anthropic.make_app(), fake_gemini.make_app())):
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", base + i).start()
        runners.append(runner)
    print("fakes prêts", flush=True)
    await asyncio.Event().wait()


asyncio.run(main(int(sys.argv[1])))
