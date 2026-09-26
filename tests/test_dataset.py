"""D0.3 : le jeu de donnees v1 est valide, et chaque regle a un cas positif et un cas negatif."""
import json
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parent.parent
V1 = ROOT / "fixtures/dataset/v1"
SCHEMA = json.loads((ROOT / "schemas/event.schema.json").read_text())
EVENTS = [json.loads(line) for line in (V1 / "events.jsonl").read_text().splitlines()]
LABELS = json.loads((V1 / "labels.json").read_text())
BY_ID = {e["event_id"]: e for e in EVENTS}
RULES = ["low_entropy_output", "oversized_model", "raw_context",
         "no_cache", "unbounded_loop", "agent_where_chain",
         "excess_reasoning", "duplicate_calls", "paid_errors", "verbose_output",
         "tool_bloat", "batch_eligible", "image_heavy", "llm_judge", "per_item_calls", "parallelizable_steps"]


def test_all_events_match_schema():
    validator = jsonschema.Draft7Validator(SCHEMA)
    errors = [(e["event_id"], err.message) for e in EVENTS for err in validator.iter_errors(e)]
    assert errors == []


def test_ids_unique_and_fully_labelled():
    labelled = [i for s in LABELS for i in s["event_ids"]]
    assert len(labelled) == len(set(labelled)) == len(BY_ID) == len(EVENTS)


def test_realistic_volume():
    assert len(EVENTS) >= 1000
    triage = next(s for s in LABELS if s["scenario"] == "mail_triage")
    assert len(triage["event_ids"]) == 400


@pytest.mark.parametrize("rule", RULES)
def test_rule_has_positive_case(rule):
    assert any(rule in s["expected_rules"] for s in LABELS)


@pytest.mark.parametrize("rule", RULES)
def test_rule_has_negative_case(rule):
    assert any(rule not in s["expected_rules"] and s["app_id"] != "*" for s in LABELS)


def test_negative_reasoning_scenario_exists():
    assert any(s["scenario"] == "eng_copilot" and s["expected_rules"] == [] for s in LABELS)


def test_traces_without_header_exist_for_d14():
    no_header = [s for s in LABELS for tid, ids in s["traces"].items()
                 if BY_ID[ids[0]]["trace"]["source"] is None]
    assert no_header, "D1.4 a besoin de traces sans en-tete pour tester l'heuristique"


def test_three_providers_and_errors_present():
    assert {e["provider"] for e in EVENTS} == {"openai", "anthropic", "gemini"}
    assert any(e["error"] for e in EVENTS)


def test_generation_is_deterministic(tmp_path, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("gen", ROOT / "fixtures/dataset/gen_dataset.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    monkeypatch.setattr(gen, "OUT", tmp_path)
    gen.main()
    assert (tmp_path / "events.jsonl").read_text() == (V1 / "events.jsonl").read_text()
    assert (tmp_path / "labels.json").read_text() == (V1 / "labels.json").read_text()


def test_trace_steps_are_chronological():
    for s in LABELS:
        for tid, ids in s["traces"].items():
            starts = [BY_ID[i]["ts_start"] for i in ids]
            assert starts == sorted(starts), tid


def test_all_rules_match_labels_without_new_false_positives():
    from report.audit import _discover_detectors
    expected = {(s['app_id'], rule) for s in LABELS for rule in s['expected_rules']}
    actual = {(f['app_id'], f['rule']) for _, detect in _discover_detectors() for f in detect(EVENTS)}
    assert actual == expected


def test_original_1332_events_are_unchanged():
    import hashlib
    original = [e for e in EVENTS if int(e['event_id'].removeprefix('ds_')) <= 1332]
    assert len(original) == 1332
    # Empreinte des événements avant l'extension #71, sérialisation indépendante de l'indentation.
    digest = hashlib.sha256(json.dumps(original, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    assert digest == '20b1a71936b3c2654815b08c29009bff393a003ac1ce1251b0bd684f84543542'
