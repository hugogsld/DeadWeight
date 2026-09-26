"""D2.4 R6 : un agent qui suit toujours le même chemin, sans condamner un agent qui choisit."""
import json
from pathlib import Path

import pytest

from rules.agent_where_chain import MIN_TRACES, detect

ROOT = Path(__file__).resolve().parents[1]
DATASET = [json.loads(line) for line in (ROOT / "fixtures/dataset/v1/events.jsonl").read_text().splitlines()]
LABELS = json.loads((ROOT / "fixtures/dataset/v1/labels.json").read_text())
KEYS = {"finding_id", "rule", "app_id", "model", "template", "severity", "title", "proven", "event_ids", "evidence"}


def run(tools, trace, final="Réponse.", app="agent"):
    """Une exécution posée par en-tête : un appel d'outil par étape, puis la réponse."""
    steps = [(None, [{"id": f"{trace}_{i}", "name": n, "arguments": json.dumps({"id": trace})}])
             for i, n in enumerate(tools)]
    if final:
        steps.append((final, []))
    return [{"event_id": f"{trace}_{i}", "app_id": app, "model": "gpt-4.1", "error": None,
             "ts_start": f"2026-09-20T10:{i:02d}:00Z", "ts_end": f"2026-09-20T10:{i:02d}:01Z",
             "trace": {"id": trace, "source": "header", "step": i},
             "request": {"system": "Agent.", "messages": [{"role": "user", "content": "go"}],
                         "tools": [{"name": n} for n in ("get_order", "check_stock", "send_email", "refund")]},
             "response": {"content": content, "tool_calls": calls}}
            for i, (content, calls) in enumerate(steps)]


def runs(paths, **kw):
    return [e for i, p in enumerate(paths) for e in run(p, f"t{i}", **kw)]


CHAIN = ["get_order", "check_stock", "send_email"]


@pytest.mark.parametrize("scenario", LABELS, ids=lambda s: s["scenario"])
def test_dataset_verdict_matches_labels(scenario):
    expected = "agent_where_chain" in scenario["expected_rules"]
    assert (scenario["app_id"] in {f["app_id"] for f in detect(DATASET)}) == expected


def test_dataset_chain_found_without_any_header():
    bare = [{**e, "trace": {"id": None, "source": None, "step": None}} for e in DATASET]
    [f] = detect(bare)
    assert f["app_id"] == "order-agent" and f["evidence"]["traces"] == 30
    assert f["evidence"]["dominant_path"] == CHAIN


def test_finding_shape():
    [f] = detect(runs([CHAIN] * 12))
    assert set(f) == KEYS and f["rule"] == "agent_where_chain" and f["proven"] is False
    assert f["evidence"]["dominant_share"] == 1.0 and f["evidence"]["distinct_paths"] == 1
    assert len(f["event_ids"]) == 12 * 4


def test_one_deviation_in_ten_is_still_a_chain():
    [f] = detect(runs([CHAIN] * 9 + [["get_order", "refund", "send_email"]]))
    assert f["evidence"]["dominant_share"] == 0.9


def test_agent_that_really_chooses_is_kept():
    assert detect(runs([CHAIN, ["get_order", "refund"]] * 10)) == []


def test_too_few_executions_to_conclude():
    assert detect(runs([CHAIN] * (MIN_TRACES - 1))) == []


def test_unfinished_traces_are_ignored():
    assert detect(runs([CHAIN] * 12, final=None)) == []


def test_single_lookup_then_answer_is_not_an_agent_to_replace():
    assert detect(runs([["search_docs"]] * 20)) == []
