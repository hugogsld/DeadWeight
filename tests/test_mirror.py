"""D4.3 : mode miroir. Les règles sont mesurées sur le trafic, jamais appliquées. Aucun réseau réel."""
import asyncio
import json
from pathlib import Path

import openai
import pytest
from aiohttp import web

from gateway import fake_openai, mirror
from gateway.proxy import make_app
from proof.replay import main as replay_main

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "fixtures/dataset/v1/events.jsonl"
EVENTS = [json.loads(line) for line in DATASET.read_text().splitlines() if line.strip()]
SYSTEM = "Classe le mail en une seule etiquette : spam, facture ou support."
KEY = "sk-test-NE-DOIT-JAMAIS-SORTIR"


@pytest.fixture(scope="module")
def proofs(tmp_path_factory):
    out = tmp_path_factory.mktemp("proofs")
    replay_main([str(DATASET), "--out", str(out)])
    return out


def test_pass_and_reject_proofs_are_both_watched(proofs):
    assert sorted(k[0] for k in mirror.load(proofs)) == ["mail-triage", "reviews"]


def test_dataset_traffic_gives_agreement_per_finding(proofs, tmp_path):
    log = tmp_path / "mirror.jsonl"
    watcher = mirror.Mirror(mirror.load(proofs), log)
    for e in EVENTS:
        watcher.observe(e)
    watcher.close()
    records = [json.loads(line) for line in log.read_text().splitlines()]
    rows = {r["app_id"]: r for r in mirror.stats(records)}
    assert set(rows) == {"mail-triage", "reviews"}  # les autres applications ne sont pas observées
    triage = rows["mail-triage"]
    assert triage["covered"] > 0 and triage["agreement"] >= mirror.THRESHOLD and triage["ready"]
    # aucun contenu client dans le journal : l'étiquette des règles et l'accord seulement
    assert set(records[0]) == {"ts", "event_id", "app_id", "finding_id", "rules_output", "agreed"}
    sample = next(e for e in EVENTS if e["app_id"] == "mail-triage")
    assert sample["request"]["messages"][-1]["content"] not in log.read_text()


async def _serve(app):
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    return runner, f"http://127.0.0.1:{runner.addresses[0][1]}"


def run(tmp_path, monkeypatch, **gateway_kwargs):
    monkeypatch.setenv("GATEWAY_MIRROR_LOG", str(tmp_path / "mirror.jsonl"))

    async def main():
        fake = fake_openai.make_app()
        up_runner, up = await _serve(fake)
        gw_runner, gw = await _serve(make_app(upstream=up, on_event=lambda e: None, **gateway_kwargs))
        try:
            client = openai.AsyncOpenAI(base_url=gw + "/v1", api_key=KEY, max_retries=0)
            raw = await client.chat.completions.with_raw_response.create(
                model="gpt-4o", extra_headers={"x-deadweight-app": "mail-triage"},
                messages=[{"role": "system", "content": SYSTEM},
                          {"role": "user", "content": "Gagnez un iPhone maintenant"}])
            await asyncio.sleep(0.05)
            return raw, fake[fake_openai.SEEN]
        finally:
            await gw_runner.cleanup()
            await up_runner.cleanup()
    return asyncio.run(main())


def test_client_always_gets_the_model_answer(proofs, tmp_path, monkeypatch):
    raw, seen = run(tmp_path, monkeypatch, mirror=proofs)
    assert len(seen) == 1                                   # OpenAI a bien été appelé
    assert raw.headers.get("x-deadweight-shortcircuit") is None
    assert raw.parse().choices[0].message.content != "spam"  # réponse du (faux) modèle, pas des règles
    [record] = [json.loads(line) for line in (tmp_path / "mirror.jsonl").read_text().splitlines()]
    assert record["rules_output"] == "spam" and record["agreed"] is False
    assert KEY not in (tmp_path / "mirror.jsonl").read_text()


def test_short_circuited_calls_are_not_mirrored(proofs, tmp_path, monkeypatch):
    raw, seen = run(tmp_path, monkeypatch, mirror=proofs, shortcut=proofs)
    assert seen == [] and raw.headers.get("x-deadweight-shortcircuit")
    assert (tmp_path / "mirror.jsonl").read_text() == ""  # aucune vraie réponse à comparer


def test_disabled_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("GATEWAY_MIRROR", raising=False)
    run(tmp_path, monkeypatch)
    assert not (tmp_path / "mirror.jsonl").exists()


def test_stats_cli(proofs, tmp_path, capsys):
    log = tmp_path / "mirror.jsonl"
    watcher = mirror.Mirror(mirror.load(proofs), log)
    for e in EVENTS:
        watcher.observe(e)
    watcher.close()
    assert mirror.main(["stats", "--log", str(log)]) == 0
    out = capsys.readouterr().out
    assert "mail-triage" in out and "prêt pour le court-circuit" in out
