"""M2.2 : les options de recommend() passées au banc, verdict dans le rapport. Aucun réseau."""
import json
from pathlib import Path

import pytest

from bench import m2
from bench.__main__ import main
from bench.client import CallResult
from bench.testset import build_test_cases
from catalog.recommend import recommend
from report.audit import build_report, render_html
from rules.oversized_model import detect

DATASET = Path(__file__).resolve().parents[1] / "fixtures/dataset/v1/events.jsonl"
FINDING = "f_mail-triage_cc8b13da25_oversized"


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


def fake_client(answers, wrong=()):
    """Client du banc : répond la réponse d'origine (ou « autre » pour les modèles de ``wrong``)."""
    seen = []

    class Client:
        def __init__(self, base_url, api_key, model, route=None):
            self.model, self.route = model, route

        def complete(self, messages):
            seen.append((self.model, self.route, messages))
            content = "autre" if self.model in wrong else answers[json.dumps(messages)]
            return CallResult(content, 5.0, 60, 2, None)

    return Client, seen


def answers(events, finding):
    return {json.dumps(list(c.messages)): c.reference
            for c in build_test_cases(events, finding["app_id"], finding["model"], finding["template"], 10 ** 6)}


def test_bench_tests_exactly_the_options_recommend_returns(events, finding):
    Client, seen = fake_client(answers(events, finding))
    result = m2.prove(events, finding, max_cases=20, client_cls=Client)
    group = [e for e in events if e["event_id"] in set(finding["event_ids"])]
    expected = {k: o["modele"] for k, o in recommend(group)["options"].items() if o}
    assert {k: r["model"] for k, r in result["options"].items()} == expected
    assert all(r["verdict"] == "pass" and r["score"] == 1 for r in result["options"].values())
    # chaque option est testée sur la route qu'elle recommande (Mistral via Mistral), sans repli
    routes = {model: route for model, route, _ in seen}
    assert routes[expected["souverain"]] == "Mistral" and routes[expected["moins_cher"]] is None


def test_candidate_gets_the_task_instruction(events, finding):
    Client, seen = fake_client(answers(events, finding))
    m2.prove(events, finding, max_cases=5, client_cls=Client)
    assert seen[0][2][0] == {"role": "system",
                             "content": "Classe le mail en une seule etiquette : spam, facture ou support."}


def test_route_option_is_priced_at_its_route(events, finding):
    Client, _ = fake_client(answers(events, finding))
    result = m2.prove(events, finding, max_cases=5, client_cls=Client)
    sovereign = result["options"]["souverain"]
    cheapest_host = m2.prove(events, finding, max_cases=5, client_cls=Client, capabilities={})["options"]["souverain"]
    assert sovereign["cost_per_1000_calls_usd"] > cheapest_host["cost_per_1000_calls_usd"]


def test_report_shows_measured_verdicts(events, finding):
    group = [e for e in events if e["event_id"] in set(finding["event_ids"])]
    options = recommend(group)["options"]
    Client, _ = fake_client(answers(events, finding), wrong={options["meilleur_compromis"]["modele"]})
    banc = {FINDING: m2.prove(events, finding, max_cases=20, client_cls=Client)}
    page = render_html(build_report(events, banc=banc))
    assert "qualité mesurée au banc sur votre trafic" in page
    assert "Banc : accord de 100 % sur 20 requêtes réelles, validé." in page
    assert "Banc : accord de 0 % sur 20 requêtes réelles, refusé" in page
    # sans banc, rien ne change
    assert "qualité non prouvée : à tester au banc" in render_html(build_report(events))


def test_cli_dry_run_calls_nothing(capsys):
    assert main(["m2", str(DATASET), "--finding", FINDING, "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "aucun appel effectue" in out and "via Mistral" in out


def test_cli_unknown_finding(capsys):
    assert main(["m2", str(DATASET), "--finding", "inconnu"]) == 1
