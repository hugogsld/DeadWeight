"""R7 : raisonnement invisible facture pour une reponse triviale."""
import copy
import json
from pathlib import Path

from rules.excess_reasoning import detect

ROOT = Path(__file__).resolve().parents[1]
BASE = json.loads((ROOT / "fixtures/events.jsonl").read_text().splitlines()[0])
DATASET = [json.loads(line) for line in (ROOT / "fixtures/dataset/v1/events.jsonl").read_text().splitlines()]
LABELS = json.loads((ROOT / "fixtures/dataset/v1/labels.json").read_text())
PRICES = {"gpt-5": {"in": 1.25, "out": 10.0}}
KEYS = {"finding_id", "rule", "app_id", "model", "template", "severity",
        "title", "proven", "event_ids", "evidence"}


def ev(i, *, provider="openai", model="gpt-5", reasoning=2000, visible=8, content=None,
       app="a", error=None, system="Reponds brievement."):
    e = copy.deepcopy(BASE)
    e.update(event_id=f"e{i}", app_id=app, model=model, provider=provider, error=error,
             ts_start=f"2026-09-01T00:{i // 60:02d}:{i % 60:02d}Z",
             ts_end=f"2026-09-01T00:{i // 60:02d}:{i % 60:02d}.900000Z")
    e["request"]["system"] = system
    e["request"]["messages"] = [{"role": "user", "content": f"question {i}"}]
    e["response"]["content"] = content if content is not None else f"reponse {i % 3}"
    e["usage"] = {"input_tokens": 40, "output_tokens": (reasoning or 0) + visible if reasoning is not None else visible,
                  "cached_input_tokens": 0, "reasoning_tokens": reasoning}
    return e


def test_trivial_reasoning_is_flagged_as_candidate():
    events = [ev(i) for i in range(30)]
    [f] = detect(events, PRICES)
    assert set(f) == KEYS
    assert f["rule"] == "excess_reasoning" and f["proven"] is False and f["severity"] == "candidate"
    assert f["evidence"]["calls"] == 30
    assert f["evidence"]["median_reasoning_share"] >= 0.6
    assert f["evidence"]["median_visible_output_tokens"] == 8
    assert f["evidence"]["est_saving_month_usd"] > 0
    assert "non démontré" in f["title"]


def test_below_min_calls_is_ignored():
    assert detect([ev(i) for i in range(29)], PRICES) == []


def test_low_reasoning_share_is_ignored():
    assert detect([ev(i, reasoning=100, visible=900) for i in range(30)], PRICES) == []


def test_long_and_varied_visible_output_is_ignored():
    """Meme part de raisonnement elevee (0.6) : reponse visible longue et variee, pas un candidat."""
    events = [ev(i, reasoning=600, visible=400, content=f"reponse detaillee et unique {i}") for i in range(30)]
    assert detect(events, PRICES) == []


def test_non_openai_provider_is_excluded():
    """Gemini facture le raisonnement a part de output_tokens (thoughtsTokenCount) : hors perimetre."""
    assert detect([ev(i, provider="gemini") for i in range(30)], PRICES) == []


def test_zero_reasoning_tokens_is_not_a_reasoning_call():
    assert detect([ev(i, reasoning=0, visible=10) for i in range(30)], PRICES) == []


def test_null_reasoning_tokens_is_unknown_not_zero():
    assert detect([ev(i, reasoning=None, visible=10) for i in range(30)], PRICES) == []


def test_errors_are_excluded():
    events = [ev(i, error={"type": "x", "message": "y"}) for i in range(30)]
    assert detect(events, PRICES) == []


def test_unknown_price_gives_null_saving_with_reason():
    [f] = detect([ev(i) for i in range(30)], {})
    assert f["evidence"]["est_saving_month_usd"] is None
    assert f["evidence"]["saving_missing"]


def test_dataset_v1_positives_and_negatives():
    flagged = {f["app_id"] for f in detect(DATASET)}
    assert "trivia-bot" in flagged
    assert "analysis-bot" not in flagged
    expected = {label["app_id"] for label in LABELS if "excess_reasoning" in label["expected_rules"]}
    assert expected == {"trivia-bot"}
