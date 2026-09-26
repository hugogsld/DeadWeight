"""D0.1 : les fixtures d'evenements respectent le schema et couvrent les six regles."""
import json
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = json.loads((ROOT / "schemas/event.schema.json").read_text())
EVENTS = [json.loads(line) for line in (ROOT / "fixtures/events.jsonl").read_text().splitlines()]
LABELS = json.loads((ROOT / "fixtures/events.labels.json").read_text())
RULES = {"low_entropy_output", "oversized_model", "raw_context",
                        "no_cache", "unbounded_loop", "agent_where_chain"}
FORBIDDEN_KEYS = {"authorization", "api_key", "x-api-key", "x-goog-api-key", "headers"}


def test_at_least_50_events():
    assert len(EVENTS) >= 50


@pytest.mark.parametrize("event", EVENTS, ids=lambda e: e["event_id"])
def test_event_matches_schema(event):
    jsonschema.validate(event, SCHEMA)


def test_event_ids_unique():
    ids = [e["event_id"] for e in EVENTS]
    assert len(ids) == len(set(ids))


def test_every_rule_has_a_positive_case():
    covered = {r for label in LABELS for r in label["expected_rules"]}
    assert covered == RULES


def test_negative_cases_exist():
    assert any(not label["expected_rules"] for label in LABELS)


def test_labels_reference_existing_events():
    ids = {e["event_id"] for e in EVENTS}
    labelled = [i for label in LABELS for i in label["event_ids"]]
    assert set(labelled) == ids and len(labelled) == len(ids)


def test_three_providers_present():
    assert {e["provider"] for e in EVENTS} == {"openai", "anthropic", "gemini"}


def _keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k.lower()
            yield from _keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _keys(v)


def test_schema_forbids_credentials():
    bad = dict(EVENTS[0], authorization="Bearer sk-xxx")
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, SCHEMA)
    assert FORBIDDEN_KEYS.isdisjoint(set(_keys(EVENTS)))
