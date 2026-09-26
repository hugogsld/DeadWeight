"""M2.2 : banc de modèles. Faux modèle candidat, aucun réseau réel."""
import io
import json
from pathlib import Path

import pytest

from bench import MIN_SAMPLE, OpenAICompatibleBench, messages_of, run, sample
from bench.__main__ import main
from catalog import load_pricing
from catalog.recommend import recommend
from proof.replay import Throttle
from rules.low_entropy import normalize

DATASET = Path(__file__).resolve().parents[1] / "fixtures/dataset/v1/events.jsonl"
PRICE = {"in": 0.1, "out": 0.3}


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Unexpected network request")
    monkeypatch.setattr("urllib.request.urlopen", forbidden)


@pytest.fixture(scope="module")
def data():
    events = [json.loads(line) for line in DATASET.read_text().splitlines()]
    return {app: [e for e in events if e["app_id"] == app] for app in ("mail-triage", "eng-copilot")}


class FakeModel:
    """Répond comme l'original (ou se trompe une fois sur ``wrong_every``), avec ``reasoning`` jetons de réflexion."""

    def __init__(self, truth, wrong_every=None, reasoning=0, error=None):
        self.truth, self.wrong_every, self.reasoning, self.error, self.calls = truth, wrong_every, reasoning, error, []

    def complete(self, model, messages):
        self.calls.append(messages)
        if self.error:
            raise self.error
        answer = self.truth[json.dumps(messages)]
        if self.wrong_every and len(self.calls) % self.wrong_every == 0:
            answer = "autre"
        return {"content": answer, "input_tokens": 60, "output_tokens": 2 + self.reasoning,
                "reasoning_tokens": self.reasoning or None}


def truth(events):
    return {json.dumps(messages_of(e)): e["response"]["content"] for e in events}


def fast():
    return Throttle(max_calls=200, min_interval_s=0)


def test_messages_are_the_clients_request(data):
    msgs = messages_of(data["mail-triage"][0])
    assert msgs[0]["role"] == "system" and "etiquette" in msgs[0]["content"]
    assert msgs[1]["role"] == "user"


def test_sample_spreads_over_every_observed_output(data):
    picked = sample(data["mail-triage"], 9)
    assert {normalize(e["response"]["content"]) for e in picked} == {"spam", "facture", "support"}


def test_faithful_candidate_passes_with_measured_cost(data):
    evts = data["mail-triage"]
    res = run(evts, "mistralai/x", FakeModel(truth(evts)), PRICE, load_pricing(), fast(), size=40)
    assert res["verdict"] == "pass" and res["accord"] == 1 and res["n"] == 40
    assert res["facteur_mesure"] > 1 and res["cout_mensuel_mesure_usd"] > 0
    assert res["jetons_reflexion_moyens"] is None


def test_reasoning_tokens_are_billed_and_shrink_the_saving(data):
    """Ce que M2 ne peut qu'estimer : un modèle qui réfléchit coûte plus que ses réponses courtes."""
    evts = data["mail-triage"]
    plain = run(evts, "m", FakeModel(truth(evts)), PRICE, load_pricing(), fast(), size=30)
    thinker = run(evts, "m", FakeModel(truth(evts), reasoning=300), PRICE, load_pricing(), fast(), size=30)
    assert thinker["jetons_reflexion_moyens"] == 300
    assert thinker["facteur_mesure"] < plain["facteur_mesure"] / 5


def test_unfaithful_candidate_is_rejected_with_its_disagreements(data):
    evts = data["mail-triage"]
    res = run(evts, "m", FakeModel(truth(evts), wrong_every=5), PRICE, load_pricing(), fast(), size=40)
    assert res["verdict"] == "reject" and res["accord"] == 0.8
    assert res["desaccords"] and any("sous le seuil" in r for r in res["raisons"])


def test_free_text_is_not_measured_by_exact_match(data):
    evts = data["eng-copilot"]
    model = FakeModel(truth(evts))
    res = run(evts, "m", model, PRICE, load_pricing(), fast())
    assert res["verdict"] == "non_mesurable" and res["accord"] is None and model.calls == []


def test_hard_cap_holds_and_too_few_answers_conclude_nothing(data):
    evts = data["mail-triage"]
    model = FakeModel(truth(evts))
    res = run(evts, "m", model, PRICE, load_pricing(), Throttle(max_calls=MIN_SAMPLE - 1, min_interval_s=0), size=50)
    assert len(model.calls) == MIN_SAMPLE - 1 and res["plafonnes"] == 50 - (MIN_SAMPLE - 1)
    assert res["verdict"] == "non_mesurable" and res["accord"] is None


def test_errors_never_leak_the_key(data):
    evts = data["mail-triage"]
    res = run(evts, "m", FakeModel(truth(evts), error=RuntimeError("sk-secret")), PRICE, load_pricing(), fast(), size=25)
    assert res["erreurs"] == 25 and res["verdict"] == "non_mesurable"
    assert "sk-secret" not in json.dumps(res)


def test_client_forces_the_tested_route(monkeypatch):
    seen = []

    def fake_urlopen(request, timeout):
        seen.append(request)
        return io.BytesIO(json.dumps({"choices": [{"message": {"content": "spam"}}], "usage": {
            "prompt_tokens": 60, "completion_tokens": 40,
            "completion_tokens_details": {"reasoning_tokens": 38}}}).encode())
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    out = OpenAICompatibleBench("https://openrouter.ai/api/v1/", "sk-BANC-SECRET", route="Mistral").complete("mistralai/x", [])
    body = json.loads(seen[0].data)
    assert body["provider"] == {"order": ["Mistral"], "allow_fallbacks": False}
    assert out == {"content": "spam", "input_tokens": 60, "output_tokens": 40, "reasoning_tokens": 38}
    assert b"sk-BANC-SECRET" not in seen[0].data  # la clé n'est que dans l'en-tête
    assert seen[0].get_header("Authorization") == "Bearer sk-BANC-SECRET"


def test_m2_recommendation_can_go_straight_to_the_bench(data):
    evts = data["mail-triage"]
    option = recommend(evts)["options"]["souverain"]
    res = run(evts, option["modele"], FakeModel(truth(evts)), PRICE, load_pricing(), fast(), size=20)
    assert res["modele"] == option["modele"] and res["verdict"] == "pass"


def test_cli_needs_a_key(monkeypatch, capsys):
    monkeypatch.delenv("DW_LLM_API_KEY", raising=False)
    assert main([str(DATASET), "--finding", "f", "--model", "m"]) == 2
    assert "DW_LLM_API_KEY" in capsys.readouterr().err
