"""R8 : la meme demande payee plusieurs fois, avec la meme reponse."""
import copy
import json
from pathlib import Path

from rules.duplicate_calls import detect

ROOT = Path(__file__).resolve().parents[1]
BASE = json.loads((ROOT / "fixtures/events.jsonl").read_text().splitlines()[0])
DATASET = [json.loads(line) for line in (ROOT / "fixtures/dataset/v1/events.jsonl").read_text().splitlines()]
LABELS = json.loads((ROOT / "fixtures/dataset/v1/labels.json").read_text())
KEYS = {"finding_id", "rule", "app_id", "model", "template", "severity",
        "title", "proven", "event_ids", "evidence"}


def ev(i, *, offset_s=0, content="Reponse identique.", prompt="Meme question ?",
       app="a", model="m", error=None, temperature=0.0, max_tokens=None):
    e = copy.deepcopy(BASE)
    e.update(event_id=f"e{i}", app_id=app, model=model, error=error,
             ts_start=f"2026-09-01T{offset_s // 3600:02d}:{(offset_s % 3600) // 60:02d}:{offset_s % 60:02d}Z",
             ts_end=f"2026-09-01T{offset_s // 3600:02d}:{(offset_s % 3600) // 60:02d}:{offset_s % 60:02d}.500000Z")
    e["request"]["system"] = "Support."
    e["request"]["messages"] = [{"role": "user", "content": prompt}]
    e["request"]["params"] = {"stream": False, "temperature": temperature, "max_tokens": max_tokens,
                              "response_format": "text"}
    e["response"]["content"] = content
    e["usage"] = {"input_tokens": 100, "output_tokens": 10, "cached_input_tokens": 0}
    return e


def test_identical_request_and_response_are_wasted_after_the_first():
    events = [ev(i, offset_s=i * 300) for i in range(3)]
    [f] = detect(events)
    assert set(f) == KEYS
    assert f["rule"] == "duplicate_calls" and f["proven"] is False and f["severity"] == "candidate"
    assert f["evidence"]["calls"] == 3 and f["evidence"]["wasted_calls"] == 2
    assert len(f["event_ids"]) == 3


def test_single_repeat_is_enough_evidence():
    """Contrairement a no_cache (3 repetitions), une reponse identique suffit des 2 occurrences."""
    events = [ev(i, offset_s=i * 60) for i in range(2)]
    [f] = detect(events)
    assert f["evidence"]["wasted_calls"] == 1


def test_different_response_each_time_is_not_flagged():
    events = [ev(i, offset_s=i * 60, content=f"Reponse {i}, differente.") for i in range(4)]
    assert detect(events) == []


def test_repeats_far_outside_the_window_are_not_clustered():
    events = [ev(0, offset_s=0), ev(1, offset_s=2 * 3600 + 1)]
    assert detect(events) == []


def test_different_params_is_not_the_same_request():
    events = [ev(0, offset_s=0, temperature=0.0), ev(1, offset_s=60, temperature=0.8)]
    assert detect(events) == []


def test_different_prompt_is_not_grouped():
    events = [ev(0, offset_s=0, prompt="A"), ev(1, offset_s=60, prompt="B")]
    assert detect(events) == []


def test_errors_and_tool_only_responses_are_excluded():
    events = [ev(i, offset_s=i * 60, error={"type": "x", "message": "y"}) for i in range(3)]
    assert detect(events) == []
    events = [ev(i, offset_s=i * 60, content=None) for i in range(3)]
    assert detect(events) == []


def test_finding_is_scoped_per_app_and_model():
    """Deux appels identiques dans 'a' sont un doublon ; les memes textes dans 'b' isolement ne
    forment pas de paire (un seul evenement par app la-bas), la portee reste bien par application."""
    events = [ev(0, offset_s=0, app="a"), ev(1, offset_s=60, app="a"),
              ev(2, offset_s=120, app="b", content="Autre chose.")]
    findings = detect(events)
    assert {f["app_id"] for f in findings} == {"a"}


def test_dataset_v1_positives_and_negatives():
    flagged = {f["app_id"] for f in detect(DATASET)}
    assert "status-poll" in flagged
    assert "status-poll-live" not in flagged
    expected = {label["app_id"] for label in LABELS if "duplicate_calls" in label["expected_rules"]}
    assert expected == {"status-poll"}
