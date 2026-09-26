"""D2.4 R5 : un agent qui relance la même action, sans condamner un agent qui avance."""
import json
from pathlib import Path

import pytest

from rules.unbounded_loop import MIN_REPEATS, detect

ROOT = Path(__file__).resolve().parents[1]
DATASET = [json.loads(line) for line in (ROOT / "fixtures/dataset/v1/events.jsonl").read_text().splitlines()]
FIXTURES = [json.loads(line) for line in (ROOT / "fixtures/events.jsonl").read_text().splitlines()]
LABELS = json.loads((ROOT / "fixtures/dataset/v1/labels.json").read_text())
KEYS = {"finding_id", "rule", "app_id", "model", "template", "severity", "title", "proven", "event_ids", "evidence"}


def agent_run(calls, final=None, trace="t1", app="agent"):
    """Une trace posée par en-tête : un appel de modèle par action, puis la réponse éventuelle."""
    steps = [(None, [{"id": f"c{i}", "name": n, "arguments": json.dumps(a)}]) for i, (n, a) in enumerate(calls)]
    if final:
        steps.append((final, []))
    return [{"event_id": f"{trace}_{i}", "app_id": app, "model": "gpt-4.1", "error": None,
             "ts_start": f"2026-09-20T10:00:{i:02d}Z", "ts_end": f"2026-09-20T10:00:{i:02d}.5Z",
             "trace": {"id": trace, "source": "header", "step": i},
             "request": {"system": "Agent.", "messages": [{"role": "user", "content": "go"}], "tools": []},
             "response": {"content": content, "tool_calls": tool_calls}}
            for i, (content, tool_calls) in enumerate(steps)]


def rules_by_app(events):
    return {f["app_id"] for f in detect(events)}


@pytest.mark.parametrize("scenario", LABELS, ids=lambda s: s["scenario"])
def test_dataset_verdict_matches_labels(scenario):
    expected = "unbounded_loop" in scenario["expected_rules"]
    assert (scenario["app_id"] in rules_by_app(DATASET)) == expected


def test_dataset_loops_found_without_any_header():
    bare = [{**e, "trace": {"id": None, "source": None, "step": None}} for e in DATASET]
    [f] = detect(bare)
    assert f["app_id"] == "sales-agent" and f["evidence"]["traces"] == 3


def test_fixture_loop_of_eight():
    [f] = detect(FIXTURES)
    assert f["app_id"] == "sales-agent"
    assert f["event_ids"] == [f"evt_{i:04d}" for i in range(29, 37)]


def test_finding_shape_and_severity():
    queries = ["tarif entreprise", "tarifs entreprise", "tarif entreprise 2026"] * 3
    [f] = detect(agent_run([("search", {"q": q}) for q in queries]))
    assert set(f) == KEYS and f["rule"] == "unbounded_loop" and f["proven"] is False
    assert f["severity"] == "cut"  # jamais de réponse finale
    assert f["evidence"]["per_trace"][0]["repeated_calls"] == 8
    [f] = detect(agent_run([("search", {"q": q}) for q in queries], final="Voici le tarif."))
    assert f["severity"] == "trim" and f["evidence"]["unfinished_traces"] == 0


def test_a_few_retries_are_normal():
    calls = [("search", {"q": "tarif"})] * MIN_REPEATS  # soit MIN_REPEATS - 1 répétitions
    assert detect(agent_run(calls, final="ok")) == []


def test_pagination_progresses():
    calls = [("read_page", {"page": str(p)}) for p in range(1, 21)]
    assert detect(agent_run(calls, final="synthèse")) == []


def test_progressing_agent_with_varied_arguments():
    calls = [("search_web", {"q": q}) for q in
             ["prix pétrole", "production opep 2025", "stocks américains", "demande chinoise",
              "taux de change dollar", "prévisions agence énergie", "coûts de raffinage", "marges distributeurs"]]
    assert detect(agent_run(calls, final="analyse")) == []


def test_repeats_must_be_the_majority():
    varied = [("tool_" + str(i), {"x": i}) for i in range(20)]
    same = [("search", {"q": "tarif entreprise"})] * 7  # 6 répétitions sur 27 actions
    assert detect(agent_run(varied + same, final="ok")) == []
