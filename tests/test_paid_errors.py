"""R9 : echecs factures et relances rapides payees une seconde fois."""
import copy
import json
from pathlib import Path

from rules.paid_errors import detect

ROOT = Path(__file__).resolve().parents[1]
BASE = json.loads((ROOT / "fixtures/events.jsonl").read_text().splitlines()[0])
DATASET = [json.loads(line) for line in (ROOT / "fixtures/dataset/v1/events.jsonl").read_text().splitlines()]
LABELS = json.loads((ROOT / "fixtures/dataset/v1/labels.json").read_text())
KEYS = {"finding_id", "rule", "app_id", "model", "template", "severity",
        "title", "proven", "event_ids", "evidence"}


def ev(i, *, offset_s=0, prompt="Meme demande.", content="reponse", out_tok=50,
       finish="stop", error=None, http_status=200, app="a", model="gpt-4o"):
    e = copy.deepcopy(BASE)
    e.update(event_id=f"e{i}", app_id=app, model=model, error=error, http_status=http_status,
             ts_start=f"2026-09-01T{offset_s // 3600:02d}:{(offset_s % 3600) // 60:02d}:{offset_s % 60:02d}Z",
             ts_end=f"2026-09-01T{offset_s // 3600:02d}:{(offset_s % 3600) // 60:02d}:{offset_s % 60:02d}.500000Z")
    e["request"]["system"] = "Agent."
    e["request"]["messages"] = [{"role": "user", "content": prompt}]
    e["response"]["content"] = content
    e["response"]["finish_reason"] = finish
    e["usage"] = {"input_tokens": 100, "output_tokens": out_tok, "cached_input_tokens": 0}
    return e


def _events(n, fail_every=2, retry_gap=5, out_tok=50):
    """n paires (echec tronque puis relance identique) espacees pour ne pas se chevaucher."""
    evts = []
    for i in range(n):
        base = i * 200
        evts.append(ev(2 * i, offset_s=base, prompt=f"demande {i}", content="tronque",
                       finish="length", out_tok=out_tok))
        evts.append(ev(2 * i + 1, offset_s=base + retry_gap, prompt=f"demande {i}",
                       content="reponse complete", finish="stop", out_tok=out_tok + 100))
    return evts


def test_billed_truncated_then_retried_is_flagged_as_cut():
    events = _events(12)
    [f] = detect(events)
    assert set(f) == KEYS
    assert f["rule"] == "paid_errors" and f["proven"] is False and f["severity"] == "cut"
    assert f["evidence"]["calls"] == 24 and f["evidence"]["billed_failures"] == 12
    assert f["evidence"]["retries"] == 12
    assert f["evidence"]["est_retry_cost_month_usd"] > 0
    assert f["evidence"]["latency_lost_ms"] > 0


def test_below_min_calls_is_ignored():
    assert detect(_events(9)) == []


def test_below_min_calls_is_flagged_once_over_threshold():
    assert detect(_events(10)) != []


def test_high_failure_rate_without_retry_is_trim():
    """20 appels, 2 echecs factures (10 %) mais jamais relances : signale, severite trim."""
    evts = [ev(i, offset_s=i * 300, prompt=f"q{i}") for i in range(18)]
    evts += [ev(18, offset_s=18 * 300, prompt="q18", finish="length"),
             ev(19, offset_s=19 * 300, prompt="q19", finish="length")]
    [f] = detect(evts)
    assert f["severity"] == "trim" and f["evidence"]["retries"] == 0


def test_unbilled_upstream_errors_are_never_counted_as_paid():
    """Echec upstream (tokens absents) puis relance reussie : rien n'a ete paye deux fois."""
    evts = []
    for i in range(15):
        base = i * 200
        evts.append(ev(2 * i, offset_s=base, prompt=f"d{i}", content=None, error={"type": "e", "message": "m"},
                       http_status=503, out_tok=None))
        evts[-1]["usage"]["input_tokens"] = None
        evts.append(ev(2 * i + 1, offset_s=base + 5, prompt=f"d{i}", content="ok", finish="stop"))
    assert detect(evts) == []


def test_retry_outside_window_is_not_counted():
    evts = _events(10, retry_gap=45)
    findings = detect(evts)
    assert findings == [] or findings[0]["evidence"]["retries"] == 0


def test_retry_cost_counts_only_billed_tokens():
    events = _events(12)
    [f] = detect(events)
    assert f["evidence"]["est_retry_cost_month_usd"] is not None
    assert not f["evidence"]["retry_cost_missing"]


def test_dataset_v1_positives_and_negatives():
    flagged = {f["app_id"] for f in detect(DATASET)}
    assert "checkout-bot" in flagged
    assert "notify-bot" not in flagged
    expected = {label["app_id"] for label in LABELS if "paid_errors" in label["expected_rules"]}
    assert expected == {"checkout-bot"}
