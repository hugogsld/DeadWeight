"""M1 : catalogue, sans réseau."""
from pathlib import Path

import pytest

from catalog import (FIELDS, HOSTING, coverage, editor_index, editor_of, info, load_pricing, load_providers,
                     observed_latency)
from catalog.__main__ import main

DATASET = Path(__file__).resolve().parents[1] / "fixtures/dataset/v1/events.jsonl"


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Unexpected network request")
    monkeypatch.setattr("urllib.request.urlopen", forbidden)


@pytest.fixture(scope="module")
def tables():
    pricing = load_pricing()
    return pricing, load_providers(), editor_index(pricing)


def test_every_provider_sheet_is_complete_and_sourced(tables):
    _, providers, _ = tables
    for prefix, sheet in providers.items():
        assert set(sheet) == set(FIELDS), prefix
        assert sheet["source"] in ("recherche", "siege"), prefix
        assert sheet["hebergement_ue"] in HOSTING, prefix
        if sheet["hebergement_ue"] == "sous_conditions":  # la condition doit être dite
            assert sheet["option_ue"], prefix
        if sheet["source"] == "siege":  # non vérifié : on ne prétend rien sur l'hébergement ni la route
            assert sheet["hebergement_ue"] is None and sheet["option_ue"] is None, prefix
            assert sheet["route_openrouter"] is None, prefix


@pytest.mark.parametrize("model, editor", [
    ("gpt-4o", "openai"), ("openai/gpt-4o", "openai"), ("claude-sonnet-4-5", "anthropic"),
    ("claude-sonnet-4-5-20250929", "anthropic"), ("~anthropic/claude-x", "anthropic"),
    ("gemini-2.5-flash", "google"), ("modele-inconnu", None), (None, None),
])
def test_editor_of_client_names(tables, model, editor):
    assert editor_of(model, tables[2]) == editor


def test_info_sovereignty_facts(tables):
    pricing, providers, index = tables
    claude = info("claude-sonnet-4-5", pricing, providers, index)
    assert claude["pays"] == "US" and claude["hebergement_ue"] is False and claude["prix"]["in"] > 0
    assert info("gpt-4o", pricing, providers, index)["hebergement_ue"] == "sous_conditions"  # comptes éligibles
    assert info("gemini-2.5-flash", pricing, providers, index)["hebergement_ue"] == "sous_conditions"  # Vertex
    mistral = [k for k in pricing if k.startswith("mistralai/")][0]
    assert info(mistral, pricing, providers, index)["souverain"] is True
    unknown = info("modele-inconnu", pricing, providers, index)
    assert unknown["prix"] is None and unknown["pays"] is None and unknown["editeur"] is None


def test_observed_latency_excludes_errors_and_uses_upper_rank():
    events = [{"model": "m", "latency_ms": v, "error": None} for v in range(1, 21)]
    events.append({"model": "m", "latency_ms": 99999, "error": {"type": "http_error"}})
    lat = observed_latency(events)["m"]
    assert lat == {"n": 20, "p50_ms": 10.5, "p95_ms": 19}


def test_coverage_counts_only_full_names(tables):
    pricing, providers, _ = tables
    cov = coverage(pricing, providers)
    assert cov["part"] >= .9
    assert all(p not in providers for p in cov["editeurs_sans_fiche"])
    assert coverage({"a/x": {}, "b/y": {}, "x": {}}, {"a": {}}) == {
        "modeles": 2, "couverts": 1, "part": .5, "editeurs_sans_fiche": {"b": 1}}


def test_cli_on_dataset(capsys):
    assert main(["--events", str(DATASET)]) == 0
    out = capsys.readouterr().out
    assert "claude-opus-4-1" in out and "anthropic" in out
