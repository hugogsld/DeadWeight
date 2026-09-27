"""Démo avec la seule clé OPENAI_API_KEY (pas d'OpenRouter, pas d'Anthropic, pas de Gemini) :
- les options dont la route de l'éditeur est OpenAI (fixtures/capabilities.json) sont appelées en
  direct, testables avec cette seule clé ;
- les autres (OpenRouter, un autre éditeur) restent proprement « non testé », sans plantage ni
  appel réel ;
- le rejeu reste bon marché : échantillon plafonné par une constante, affiché.
Aucun réseau réel dans ce fichier.
"""
import json
from pathlib import Path

import pytest

from bench import m2
from bench.__main__ import main
from bench.client import CallResult
from bench.testset import DEFAULT_MAX_CASES, build_test_cases
from catalog.recommend import recommend
from rules.oversized_model import detect

DATASET = Path(__file__).resolve().parents[1] / "fixtures/dataset/v1/events.jsonl"
FINDING = "f_mail-triage_cc8b13da25_oversized"  # gpt-4o (éditeur openai)
FINDING_CLAUDE = "f_reviews_0f58871bd8_oversized"  # claude-opus-4-1 (éditeur anthropic)


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Unexpected network request")
    monkeypatch.setattr("urllib.request.urlopen", forbidden)


@pytest.fixture(scope="module")
def events():
    return [json.loads(line) for line in DATASET.read_text().splitlines()]


@pytest.fixture(scope="module")
def finding(events):
    return next(f for f in detect(events) if f["finding_id"] == FINDING)


@pytest.fixture(scope="module")
def finding_claude(events):
    return next(f for f in detect(events) if f["finding_id"] == FINDING_CLAUDE)


def test_the_openai_editor_route_is_a_real_openai_model_with_a_real_price(events, finding):
    """« meilleur_compromis » pour un constat sur gpt-4o (éditeur openai) : un vrai modèle OpenAI
    du catalogue (fixtures/pricing.json), jamais inventé, hébergé chez « OpenAI » (fixtures/
    capabilities.json, route de l'éditeur)."""
    group = [e for e in events if e["event_id"] in set(finding["event_ids"])]
    option = recommend(group)["options"]["meilleur_compromis"]
    assert option["hebergeur"] == "OpenAI" and option["editeur"] == "openai"
    from report.cost import lookup
    from bench.pricing import load_prices
    assert lookup(load_prices(), option["modele"]) is not None  # prix réel du repo, pas inventé


def test_openai_editor_route_builds_a_direct_candidate_not_openrouter(events, finding):
    group = [e for e in events if e["event_id"] in set(finding["event_ids"])]
    option = recommend(group)["options"]["meilleur_compromis"]
    candidate = m2.candidate_for("meilleur_compromis", option)
    assert candidate.kind == "openai" and candidate.api_key_env == "OPENAI_API_KEY"
    assert candidate.route is None  # jamais de provider OpenRouter pour un appel direct


def test_only_openai_api_key_is_enough_to_measure_the_openai_route(events, finding, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    answers = {json.dumps(list(c.messages)): c.reference
              for c in build_test_cases(events, finding["app_id"], finding["model"], finding["template"], 10 ** 6)}
    seen = []

    class Client:
        def __init__(self, base_url, api_key, model, route=None, max_tokens=None):
            seen.append((base_url, api_key, model, route))

        def complete(self, messages):
            return CallResult(answers[json.dumps(messages)], 5.0, 60, 2, None)

    result = m2.prove(events, finding, max_cases=10, client_cls=Client, keys={"meilleur_compromis"})
    option = result["options"]["meilleur_compromis"]
    assert option["verdict"] == "pass" and option["score"] == 1.0
    base_url, api_key, model, route = seen[0]
    assert base_url == "https://api.openai.com/v1" and api_key == "sk-test" and route is None


def test_options_needing_openrouter_stay_cleanly_not_tested_without_that_key(events, finding, monkeypatch):
    """Sans OPENROUTER_API_KEY, les options « moins_cher » et « souverain » (OpenRouter) ne
    plantent pas et ne comptent pas comme un échec de qualité : verdict « not_tested »."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    class Refused:  # ce que renverrait réellement OpenRouter sans Authorization : 401
        def __init__(self, *a, **k):
            pass

        def complete(self, messages):
            return CallResult(None, 20.0, None, None, "http_401")

    result = m2.prove(events, finding, max_cases=5, client_cls=Refused,
                      keys={"moins_cher", "souverain"})
    for key in ("moins_cher", "souverain"):
        option = result["options"][key]
        assert option["verdict"] == "not_tested" and option["score"] is None


def test_meilleur_compromis_for_a_non_openai_editor_is_not_reachable_with_only_an_openai_key(events, finding_claude):
    """reviews/claude-opus-4-1 : le « meilleur_compromis » est un modèle Anthropic (même éditeur),
    pas OpenAI — la clé OpenAI seule ne peut pas le tester, ce que candidate_for reflète bien."""
    group = [e for e in events if e["event_id"] in set(finding_claude["event_ids"])]
    option = recommend(group)["options"]["meilleur_compromis"]
    assert option["hebergeur"] != "OpenAI"
    candidate = m2.candidate_for("meilleur_compromis", option)
    assert candidate.kind == "openrouter" and candidate.api_key_env == "OPENROUTER_API_KEY"


def test_sample_size_is_bounded_by_a_constant_and_displayed(capsys, monkeypatch):
    """Le nombre de cas rejoués (échantillon plafonné par --max-cases, défaut
    bench.testset.DEFAULT_MAX_CASES) est affiché, pas seulement borné en silence."""
    from bench import __main__ as bench_main

    def fake_prove(events, finding, max_cases, max_calls, min_interval, keys=None):
        return {"n_cases": max_cases, "raison": None, "options": {}}

    monkeypatch.setattr(bench_main.m2, "prove", fake_prove)
    assert main(["m2", str(DATASET), "--finding", FINDING]) == 0
    out = capsys.readouterr().out
    assert f"{DEFAULT_MAX_CASES} cas de test (plafond --max-cases {DEFAULT_MAX_CASES})" in out
