"""Levier 16 : données hors d'Europe, sans réseau."""
import copy
import json
from pathlib import Path

import jsonschema
import pytest

from catalog import destination, load_hosts
from report.audit import build_report, render_html
from rules.data_outside_eu import detect

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "fixtures/dataset/v1/events.jsonl"
SCHEMA = json.loads((ROOT / "schemas/finding.schema.json").read_text())


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Unexpected network request")
    monkeypatch.setattr("urllib.request.urlopen", forbidden)


@pytest.fixture(scope="module")
def events():
    return [json.loads(line) for line in DATASET.read_text().splitlines()]


@pytest.mark.parametrize("event, ue, how", [
    ({"upstream": "api.anthropic.com"}, False, "observee"),
    ({"upstream": "api.openai.com"}, False, "observee"),
    ({"upstream": "eu.api.openai.com"}, True, "observee"),
    ({"upstream": "api.mistral.ai"}, True, "observee"),
    ({"upstream": "europe-west4-aiplatform.googleapis.com"}, True, "observee"),
    ({"upstream": "us-central1-aiplatform.googleapis.com"}, None, "observee"),  # inconnu : rien prétendu
    ({"upstream": "bedrock-runtime.eu-west-3.amazonaws.com"}, True, "observee"),
    ({"upstream": "deadweight"}, True, "observee"),  # court-circuit : reste chez le client
    ({"provider": "gemini"}, None, "deduite"),
    ({"provider": "anthropic", "upstream": None}, False, "deduite"),
])
def test_destination(event, ue, how):
    d = destination(event, load_hosts())
    assert d["ue"] is ue and d["certitude"] == how


def test_dataset_findings_follow_the_contract(events):
    findings = detect(events)
    assert findings
    for f in findings:
        jsonschema.validate(f, SCHEMA)
        assert f["proven"] is False and f["evidence"]["traitement_ue"] is not True


def test_european_model_only_named_for_simple_tasks(events):
    by_app = {f["app_id"]: f["evidence"] for f in detect(events)}
    # mail-triage et reviews : jugées simples par R2 -> un modèle européen chiffré sur la route Mistral
    for app in ("mail-triage", "reviews"):
        alt = by_app[app]["alternative_europeenne"]
        assert by_app[app]["tache_simple"] and alt["hebergeur"] == "Mistral" and alt["pays"] == "FR"
    # vrai raisonnement : aucun remplaçant désigné sans mesure
    assert by_app["eng-copilot"]["alternative_europeenne"] is None
    assert "comptes éligibles" in by_app["eng-copilot"]["meme_modele_en_ue"]


def test_eu_local_and_unknown_destinations_are_not_flagged(events):
    evts = copy.deepcopy([e for e in events if e["app_id"] == "mail-triage"])
    for host in ("eu.api.openai.com", "deadweight", "api.inconnu.example"):
        for e in evts:
            e["upstream"] = host
        assert detect(evts) == [], host


def test_anthropic_has_no_same_model_eu_route_in_direct(events):
    kb = next(f for f in detect(events) if f["app_id"] == "kb-bot")["evidence"]
    assert kb["hote"] == "api.anthropic.com" and kb["pays"] == "US"
    assert "Bedrock" in kb["meme_modele_en_ue"]


def test_report_keeps_sovereignty_apart_from_waste(events):
    report = build_report(events)
    assert all(c["titre"] != "Des données qui partent hors d'Europe" for c in report["constats"])
    assert report["souverainete"]
    page = render_html(report)
    assert page.count("Où partent vos données") == 1 and "api.anthropic.com (US)" in page
    assert "Destination déduite du format" in page  # le jeu de test n'a pas d'upstream
