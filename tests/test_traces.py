"""D1.4 : les appels d'un même workflow se retrouvent dans une trace, avec ou sans en-tête."""
import asyncio
import collections
import copy
import json
import random
from pathlib import Path

import openai
from aiohttp import web

from gateway import fake_openai
from gateway.proxy import make_app
from gateway.store import EventStore, read_events
from gateway.traces import assign_traces
from report.audit import build_report

ROOT = Path(__file__).resolve().parents[1]
DATASET = [json.loads(line) for line in (ROOT / "fixtures/dataset/v1/events.jsonl").read_text().splitlines()]
LABELS = json.loads((ROOT / "fixtures/dataset/v1/labels.json").read_text())
TRUTH = {t: set(ids) for s in LABELS for t, ids in s["traces"].items()}


def bare(event, keep_tool_ids=True):
    """L'événement tel qu'un client qui ne pose aucun en-tête l'aurait produit."""
    e = copy.deepcopy(event)
    e["trace"] = {"id": None, "source": None, "step": None}
    if not keep_tool_ids:
        for m in e["request"]["messages"]:
            for c in m.get("tool_calls") or []:
                c["id"] = None
            if m.get("tool_call_id"):
                m["tool_call_id"] = None
        for c in e["response"]["tool_calls"]:
            c["id"] = None
    return e


def groups(events):
    out = collections.defaultdict(list)
    for e in events:
        if e["trace"]["id"]:
            out[e["trace"]["id"]].append(e)
    return out


def assert_matches_truth(events, without_headers=False):
    found = groups(events)
    assert sorted(map(sorted, ({e["event_id"] for e in g} for g in found.values()))) == \
        sorted(map(sorted, (
            set(ids) for s in LABELS if not (without_headers and s.get("requires_header"))
            for ids in s["traces"].values())))
    for g in found.values():
        g.sort(key=lambda e: e["ts_start"])
        assert [e["trace"]["step"] for e in g] == list(range(len(g)))


def test_dataset_traces_recovered_without_any_header():
    out = assign_traces(bare(e) for e in DATASET)
    assert_matches_truth(out, without_headers=True)
    assert {e["trace"]["source"] for e in out} == {"heuristic", None}


def test_dataset_traces_with_headers_kept_and_rest_recovered():
    out = assign_traces(DATASET)
    assert_matches_truth(out)
    by_id = {e["event_id"]: e for e in out}
    for e in DATASET:
        if e["trace"]["source"] == "header":
            assert by_id[e["event_id"]]["trace"]["id"] == e["trace"]["id"]


def test_robust_to_missing_tool_ids_and_input_order():
    events = [bare(e, keep_tool_ids=False) for e in DATASET]
    random.Random(1).shuffle(events)
    out = assign_traces(events)
    assert [e["event_id"] for e in out] == [e["event_id"] for e in events]  # ordre d'entrée conservé
    assert_matches_truth(out, without_headers=True)


def test_isolated_calls_stay_out_of_traces():
    classifier = [bare(e) for e in DATASET if e["app_id"] == "mail-triage"]
    assert len(classifier) >= 400
    assert all(e["trace"]["id"] is None for e in assign_traces(classifier))


def test_too_far_apart_is_not_the_same_trace():
    chain = sorted((bare(e) for e in DATASET if e["event_id"] in TRUTH["order-t0"]), key=lambda e: e["ts_start"])
    late = chain[1]
    late["ts_start"], late["ts_end"] = "2026-09-21T09:00:00Z", "2026-09-21T09:00:01Z"
    out = assign_traces(chain[:2])
    assert all(e["trace"]["id"] is None for e in out)


def test_audit_finds_raw_context_only_once_traces_are_grouped():
    """Sans en-tête, le constat « historique renvoyé » n'existe que grâce à D1.4."""
    no_header = [bare(e) for e in DATASET]
    raw_context = "Tout l'historique renvoyé à chaque message"
    titles = lambda events: {c["titre"] for c in build_report(events)["constats"]}  # noqa: E731
    assert raw_context in titles(DATASET)
    assert raw_context not in titles(no_header)
    assert raw_context in titles(assign_traces(no_header))


def agent_loop_through_gateway(db, header):
    """Boucle d'agent de 8 appels avec le SDK OpenAI, à travers la vraie passerelle."""
    async def serve(app):
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        return runner, f"http://127.0.0.1:{runner.addresses[0][1]}"

    async def main():
        up_runner, up = await serve(fake_openai.make_app())
        gw_runner, gw = await serve(make_app(upstream=up, on_event=lambda e: None, store=EventStore(db)))
        extra = {"x-deadweight-trace": "run-42"} if header else {}
        client = openai.AsyncOpenAI(base_url=gw + "/v1", api_key="sk-test", default_headers=extra)
        tools = [{"type": "function", "function": {"name": "get_weather", "parameters": {"type": "object"}}}]
        messages = [{"role": "system", "content": "Tu es un agent météo."},
                    {"role": "user", "content": "Quel temps à Paris ?"}]
        try:
            for step in range(8):
                r = await client.chat.completions.create(model="tools", messages=messages, tools=tools)
                call = r.choices[0].message.tool_calls[0]
                messages.append(r.choices[0].message.model_dump(exclude_none=True))
                messages.append({"role": "tool", "tool_call_id": call.id, "content": f"résultat {step}"})
        finally:
            await client.close()
            await gw_runner.cleanup()
            await up_runner.cleanup()
    asyncio.run(main())
    return assign_traces(read_events(db))


def test_agent_loop_of_eight_is_one_trace_of_eight_with_header(tmp_path):
    events = agent_loop_through_gateway(str(tmp_path / "e.db"), header=True)
    [(trace_id, calls)] = groups(events).items()
    assert trace_id == "run-42" and len(calls) == 8
    assert [e["trace"]["step"] for e in calls] == list(range(8))
    assert {e["trace"]["source"] for e in calls} == {"header"}


def test_agent_loop_of_eight_is_one_trace_of_eight_without_header(tmp_path):
    events = agent_loop_through_gateway(str(tmp_path / "e.db"), header=False)
    [calls] = groups(events).values()
    assert len(calls) == 8
    assert [e["trace"]["step"] for e in calls] == list(range(8))
    assert {e["trace"]["source"] for e in calls} == {"heuristic"}
