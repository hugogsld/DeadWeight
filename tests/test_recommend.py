"""M2 : recommandations, sans réseau."""
import json
from pathlib import Path

import pytest

from catalog.capabilities import build as build_capabilities
from catalog.recommend import alternatives_modele, compatible, needs, recommend
from report.audit import build_report, render_html

DATASET = Path(__file__).resolve().parents[1] / "fixtures/dataset/v1/events.jsonl"


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Unexpected network request")
    monkeypatch.setattr("urllib.request.urlopen", forbidden)


@pytest.fixture(scope="module")
def events():
    return [json.loads(line) for line in DATASET.read_text().splitlines()]


def _event(**kw):
    e = {"error": None, "usage": {"input_tokens": 100, "output_tokens": 5},
         "request": {"tools": [], "params": {}, "messages": [{"role": "user", "content": "x"}]},
         "response": {"tool_calls": []}}
    e.update(kw)
    return e


def test_needs_reads_the_traffic():
    evts = [_event(), _event(usage={"input_tokens": 9000, "output_tokens": 100},
                             request={"tools": [{"name": "f"}], "params": {"response_format": "json_object"},
                                      "messages": [{"role": "user", "content": "x", "n_images": 1}]}),
            _event(error={"type": "x"}, usage={"input_tokens": 10 ** 6, "output_tokens": 0})]
    assert needs(evts) == {"outils": True, "json": True, "images": True, "contexte_min": 9100}


@pytest.mark.parametrize("caps, ok", [
    ({"contexte": 10000, "outils": True, "json": True, "images": True}, True),
    ({"contexte": 9000, "outils": True, "json": True, "images": True}, False),
    ({"contexte": 10000, "outils": False, "json": True, "images": True}, False),
    ({"contexte": 10000, "outils": True, "json": True, "images": False}, False),
    (None, False),
])
def test_compatible(caps, ok):
    assert compatible(caps, {"outils": True, "json": True, "images": True, "contexte_min": 9100}) is ok


def test_unknown_size_is_never_compatible():
    assert not compatible({"contexte": 10 ** 6, "outils": True, "json": True, "images": True},
                          {"outils": False, "json": False, "images": False, "contexte_min": None})


def test_capabilities_from_openrouter_models():
    table = build_capabilities([
        {"id": "a/x", "context_length": 128000, "supported_parameters": ["tools", "response_format"],
         "architecture": {"input_modalities": ["text", "image"]}},
        {"id": "a/y", "context_length": None, "top_provider": {"context_length": 8000}},
        {"id": "a/z", "context_length": 0},
    ])
    assert table == {"a/x": {"contexte": 128000, "outils": True, "json": True, "images": True},
                     "a/y": {"contexte": 8000, "outils": False, "json": False, "images": False}}


def test_only_r2_findings_get_alternatives(events):
    recs = {r["app_id"]: r for r in alternatives_modele(events)}
    # garde-fou qualité : le vrai raisonnement (eng-copilot) n'est jamais envoyé vers un petit modèle
    assert set(recs) == {"mail-triage", "reviews"}
    for rec in recs.values():
        assert rec["prouve"] is False
        for option in rec["options"].values():
            assert option["cout_mensuel_usd"] < rec["cout_mensuel_usd"]


def test_three_options_on_mail_triage(events):
    rec = next(r for r in alternatives_modele(events) if r["app_id"] == "mail-triage")
    same, sovereign = rec["options"]["meilleur_compromis"], rec["options"]["souverain"]
    assert same["editeur"] == "openai" and not same["modele"].startswith("openai/gpt-oss")
    assert same["hebergement_ue"] is True
    assert sovereign["souverain"] is True and sovereign["pays"] == "FR"
    cheapest = rec["options"]["moins_cher"]["cout_mensuel_usd"]
    assert all(o["cout_mensuel_usd"] >= cheapest for o in rec["options"].values())


def test_open_weights_do_not_inherit_editor_hosting(events):
    evts = [e for e in events if e["app_id"] == "mail-triage"]
    providers = {"openai": {"nom": "OpenAI", "pays": "US", "hebergement_ue": True, "souverain": False,
                            "option_ue": "UE", "source": "recherche", "date": "d"}}
    pricing = json.loads((DATASET.parents[3] / "fixtures/pricing.json").read_text())
    pricing = {k: v for k, v in pricing.items() if k in ("gpt-4o", "openai/gpt-4o", "openai/gpt-oss-20b")}
    caps = {"openai/gpt-oss-20b": {"contexte": 10 ** 5, "outils": True, "json": True, "images": False}}
    rec = recommend(evts, pricing, providers, caps)
    assert rec["options"]["moins_cher"]["modele"] == "openai/gpt-oss-20b"
    assert rec["options"]["moins_cher"]["hebergement_ue"] is None
    assert rec["options"]["meilleur_compromis"] is None


def test_unmeasured_cost_gives_no_option():
    evts = [_event(model="modele-inconnu", provider="openai", ts_start="2026-09-20T09:00:00Z",
                   ts_end="2026-09-20T10:30:00Z", latency_ms=1, event_id="e")]
    rec = recommend(evts)
    assert rec["options"] == {} and "non mesurable" in rec["raison"]


def test_report_shows_alternatives_only_on_r2_cards(events):
    report = build_report(events)
    with_alts = [c for c in report["constats"] if c["alternatives"]]
    assert {c["app_id"] for c in with_alts} == {"mail-triage", "reviews"}
    page = render_html(report)
    assert page.count("Autres modèles compatibles") == 2 and "qualité non prouvée" in page
