"""D2.2 : regle oversized_model — signal de candidature, jamais une preuve."""
import copy
import json
from pathlib import Path

from rules.oversized_model import detect, is_premium, suggest_model

ROOT = Path(__file__).resolve().parent.parent
EVENTS = [json.loads(line) for line in (ROOT / "fixtures/dataset/v1/events.jsonl").read_text().splitlines()]
BASE = json.loads((ROOT / "fixtures/events.jsonl").read_text().splitlines()[0])
PRICES = {"gpt-4o": {"in": 2.5, "out": 10.0}, "gpt-4.1-nano": {"in": 0.1, "out": 0.4},
          "gpt-4o-mini": {"in": 0.15, "out": 0.6}}


def ev(i, model="gpt-4o", out_tok=3, in_tok=80, tools=(), app="a"):
    e = copy.deepcopy(BASE)
    e.update(event_id=f"e{i}", app_id=app, model=model, provider="openai",
             ts_start=f"2026-09-01T00:{i // 60:02d}:{i % 60:02d}Z",
             ts_end=f"2026-09-01T00:{i // 60:02d}:{i % 60:02d}.500000Z")
    e["usage"] = {"input_tokens": in_tok, "output_tokens": out_tok, "cached_input_tokens": 0}
    e["request"]["tools"] = [{"name": t} for t in tools]
    e["response"]["content"] = f"sortie {i % 3}"
    return e


def test_premium_by_price_then_by_name():
    assert is_premium("gpt-4o", PRICES) and not is_premium("gpt-4o-mini", PRICES)
    assert is_premium("claude-opus-4-1", {}) and not is_premium("claude-haiku-4-5", {})


def test_suggest_cheapest_same_family_in_catalogue():
    assert suggest_model("openai", "gpt-4o", PRICES) == "gpt-4.1-nano"


def test_short_outputs_on_premium_model_are_candidates():
    [f] = detect([ev(i) for i in range(40)], PRICES)
    assert f["rule"] == "oversized_model" and f["severity"] == "candidate" and f["proven"] is False
    assert f["evidence"]["suggested_model"] == "gpt-4.1-nano"
    assert f["evidence"]["est_saving_month_usd"] > 0
    assert "non démontrée" in f["title"]


def test_negatives():
    assert detect([ev(i, model="gpt-4o-mini") for i in range(40)], PRICES) == []
    assert detect([ev(i, out_tok=600) for i in range(40)], PRICES) == []
    assert detect([ev(i, tools=["search"]) for i in range(40)], PRICES) == []
    assert detect([ev(i, in_tok=9000) for i in range(40)], PRICES) == []
    assert detect([ev(i) for i in range(10)], PRICES) == []


def test_unknown_price_gives_null_saving_with_reason():
    [f] = detect([ev(i, model="claude-opus-4-1") for i in range(40)], PRICES)
    assert f["evidence"]["est_saving_month_usd"] is None
    assert f["evidence"]["saving_missing"]


def test_dataset_v1():
    flagged = {f["app_id"] for f in detect(EVENTS)}
    assert flagged == {"mail-triage", "reviews"}
