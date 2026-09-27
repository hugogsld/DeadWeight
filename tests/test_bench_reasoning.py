"""R7/levier 03 : banc de l'effort de raisonnement (bench.reasoning), aucun réseau réel."""
import json
from pathlib import Path

import pytest

from bench import reasoning
from bench.client import CallResult
from rules.excess_reasoning import detect
from tests.bench_servers import FakeCandidateServer

DATASET = Path(__file__).resolve().parents[1] / "fixtures/dataset/v1/events.jsonl"


@pytest.fixture(scope="module")
def events():
    return [json.loads(line) for line in DATASET.read_text().splitlines() if line.strip()]


@pytest.fixture(scope="module")
def finding(events):
    [f] = detect(events)
    return f


@pytest.fixture
def forbid_network(monkeypatch):
    """Sur demande seulement : le test d'intégration a besoin du réseau local (loopback)."""
    def forbidden(*args, **kwargs):
        raise AssertionError("Unexpected network request")
    monkeypatch.setattr("urllib.request.urlopen", forbidden)


def _fake_client_cls(score_fn=lambda case: case.reference):
    """Client injecté : renvoie soit la référence (accord parfait), soit une autre réponse."""
    seen = []

    class Client:
        def __init__(self, base_url, api_key, model, extra=None):
            self.base_url, self.api_key, self.model, self.extra = base_url, api_key, model, extra

        def complete(self, messages):
            seen.append((self.model, self.extra, messages))
            return CallResult(score_fn(messages), 12.0, 40, 8, None)

    return Client, seen


def test_without_openai_api_key_nothing_is_called(events, finding, monkeypatch, forbid_network):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = reasoning.prove(events, finding, client_cls=_fake_client_cls()[0])
    assert result["verdict"] == "not_tested" and result["score"] is None
    assert "clé OPENAI_API_KEY absente" in result["reasons"][0]


def test_with_a_key_the_effort_parameter_is_sent_and_score_is_measured(events, finding, monkeypatch, forbid_network):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    def reply_with_reference(messages):
        # bench.testset.build_test_cases : le contenu original de l'événement sert de référence,
        # mais le faux client ne voit que les messages ; on répond toujours "spam" (référence unique
        # du jeu trivia-bot, classification) pour simuler un accord parfait.
        return "spam"

    Client, seen = _fake_client_cls(lambda messages: reply_with_reference(messages))
    result = reasoning.prove(events, finding, client_cls=Client)
    assert result["n_calls"] > 0 and result["verdict"] in ("pass", "reject")
    assert all(extra == {"reasoning_effort": "low"} for _, extra, _ in seen)


def test_low_agreement_is_rejected_not_fabricated_as_a_pass(events, finding, monkeypatch, forbid_network):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    Client, _ = _fake_client_cls(lambda messages: "toujours autre chose, jamais la reference")
    result = reasoning.prove(events, finding, client_cls=Client)
    assert result["verdict"] == "reject" and result["score"] is not None and result["score"] < result["threshold"]
    assert any("sous le seuil" in r for r in result["reasons"])


def test_no_cases_is_not_tested_not_a_silent_pass(monkeypatch, forbid_network):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    empty_finding = {"finding_id": "f_x", "app_id": "no-such-app", "model": "gpt-5", "template": None,
                     "event_ids": []}
    result = reasoning.prove([], empty_finding, client_cls=_fake_client_cls()[0])
    assert result["verdict"] == "not_tested" and result["n_cases"] == 0


def test_extra_body_param_actually_reaches_the_http_request(events, finding, monkeypatch):
    """Intégration légère : un vrai CandidateLLM, contre un serveur local (jamais le réseau réel)."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    server = FakeCandidateServer(behavior="echo")
    monkeypatch.setenv("OPENAI_BASE_URL", server.base_url)
    try:
        result = reasoning.prove(events, finding, max_cases=3)
    finally:
        server.stop()
    assert result["n_calls"] > 0
    assert all(body.get("reasoning_effort") == "low" for body in server.received)
