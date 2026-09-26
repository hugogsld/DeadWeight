"""Bloc M dans l'agent A1 : outil alternatives_modele. Faux LLM scripté, aucun réseau."""
import json
from pathlib import Path

import pytest

from agent.loop import SYSTEM, run_agent, unknown_numbers
from agent.tools import SPECS, AuditTools

ROOT = Path(__file__).resolve().parents[1]
EVENTS = [json.loads(line) for line in (ROOT / "fixtures/dataset/v1/events.jsonl").read_text().splitlines()
          if line.strip()]
TRIAGE_R2 = "f_mail-triage_cc8b13da25_oversized"
TRIAGE_R1 = "f_mail-triage_cc8b13da25_low_entropy"
REVIEWS_R1 = "f_reviews_0f58871bd8_low_entropy"


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Unexpected network request")
    monkeypatch.setattr("urllib.request.urlopen", forbidden)


def call(name, args=None, i=[0]):
    i[0] += 1
    return {"id": f"a{i[0]}", "type": "function", "function": {"name": name, "arguments": json.dumps(args or {})}}


class ScriptedLLM:
    def __init__(self, replies):
        self.replies = list(replies)

    def chat(self, messages, tools):
        content, calls = self.replies.pop(0)
        return {"role": "assistant", "content": content, "tool_calls": calls}, {}


def test_tool_is_declared_and_explained_to_the_agent():
    assert "alternatives_modele" in {s["name"] for s in SPECS}
    assert "alternatives_modele" in SYSTEM and "cout_sous_estime" in SYSTEM


def test_rules_tell_which_findings_have_alternatives():
    flags = {c["finding_id"]: c["autres_modeles_disponibles"] for c in AuditTools(EVENTS).lancer_regles()["constats"]}
    assert flags[TRIAGE_R2] is True and flags[TRIAGE_R1] is False


def test_alternatives_for_an_oversized_model():
    out = AuditTools(EVENTS).call("alternatives_modele", {"pourquoi": "x", "finding_id": TRIAGE_R2})
    assert out["modele_actuel"] == "gpt-4o"
    by_option = {o["option"]: o for o in out["options"]}
    assert set(by_option) == {"le moins cher", "même éditeur", "éditeur européen"}
    assert by_option["éditeur européen"]["donnees_en_europe"] == "oui"
    assert by_option["le moins cher"]["donnees_en_europe"] == "non garanti"  # hébergeur quelconque
    assert by_option["même éditeur"]["cout_sous_estime"] is True  # gpt-5-nano réfléchit
    for o in out["options"]:
        assert 0 < o["cout_mensuel_usd"] < out["cout_mensuel_actuel_usd"]  # jamais arrondi à 0


def test_refused_outside_simple_tasks():
    out = AuditTools(EVENTS).call("alternatives_modele", {"finding_id": TRIAGE_R1})
    assert "erreur" in out
    assert "erreur" in AuditTools(EVENTS).call("alternatives_modele", {"finding_id": "inconnu"})


def test_agent_can_cite_alternative_figures_without_tripping_the_guard():
    tools = AuditTools(EVENTS)
    out = tools.call("alternatives_modele", {"finding_id": TRIAGE_R2})
    europe = next(o for o in out["options"] if o["option"] == "éditeur européen")
    plan = {"resume": "Le tri des mails peut passer sur un modèle européen.", "actions": [{
        "priorite": 1, "finding_id": TRIAGE_R2, "action": f"Tester {europe['modele']}",
        "justification": f"{europe['facteur_cout']} fois moins cher, {europe['economie_pct']} % d'économie, "
                         f"{europe['cout_mensuel_usd']} $ par mois, piste non prouvée."}]}
    assert unknown_numbers(plan, [out]) == []


def test_agent_loop_uses_the_tool_and_the_action_stays_a_lead():
    tools = AuditTools(EVENTS)
    script = [
        (None, [call("lancer_regles")]),
        (None, [call("prouver", {"finding_id": TRIAGE_R1})]),
        (None, [call("prouver", {"finding_id": REVIEWS_R1})]),
        ("gpt-4o sert à trier des mails : je cherche un modèle plus adapté.",
         [call("alternatives_modele", {"pourquoi": "tâche simple sur un gros modèle", "finding_id": TRIAGE_R2})]),
        (None, [call("publier_plan", {"resume": "Tester un modèle européen pour le tri des mails.", "actions": [
            {"priorite": 1, "finding_id": TRIAGE_R2, "action": "Tester un modèle européen",
             "justification": "Piste non prouvée, à tester sur une partie du trafic."}]})]),
    ]
    result = run_agent(tools, ScriptedLLM(script), model_name="gpt-5-mini")
    assert result["statut"] == "terminé"
    assert "alternatives_modele" in [step["outil"] for step in result["journal"]]
    assert result["plan"]["actions"][0]["statut"] == "piste à vérifier"  # jamais « prouvé »


def test_guard_accepts_exact_figures_with_many_decimals_but_not_invented_ones():
    out = {"cout_mensuel_usd": 0.0021}
    ok = {"resume": "", "actions": [{"action": "", "justification": "0.0021 $ par mois"}]}
    bad = {"resume": "", "actions": [{"action": "", "justification": "0.0023 $ par mois"}]}
    assert unknown_numbers(ok, [out]) == [] and unknown_numbers(bad, [out]) == [0.0023]
