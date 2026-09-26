"""A1 : agent auditeur. Faux LLM scripté, aucun réseau."""
import json
from pathlib import Path

from agent.audit import audit
from agent.loop import run_agent, unknown_numbers
from agent.tools import AuditTools
from report.audit import render_html

ROOT = Path(__file__).resolve().parents[1]
EVENTS = [json.loads(line) for line in (ROOT / "fixtures/dataset/v1/events.jsonl").read_text().splitlines()
          if line.strip()]
TRIAGE = "f_mail-triage_cc8b13da25_low_entropy"


def call(name, args=None, i=[0]):
    i[0] += 1
    return {"id": f"c{i[0]}", "type": "function", "function": {"name": name, "arguments": json.dumps(args or {})}}


def plan(resume, justification):
    return {"resume": resume, "actions": [{"priorite": 1, "finding_id": TRIAGE,
                                           "action": "Remplacer le tri des mails par des règles fixes",
                                           "justification": justification}]}


class ScriptedLLM:
    """Rejoue une suite de réponses ; garde les messages reçus pour les vérifier."""

    def __init__(self, replies):
        self.replies, self.seen = list(replies), []

    def chat(self, messages, tools):
        self.seen.append(json.loads(json.dumps(messages)))
        content, calls = self.replies.pop(0)
        return {"role": "assistant", "content": content, "tool_calls": calls}, {"prompt_tokens": 1000,
                                                                                "completion_tokens": 100}


def happy_script(first_plan_justification="Accord de 100.0 % au rejeu, coût divisé par 3.5."):
    return [
        ("Je commence par la vue d'ensemble.", [call("vue_ensemble")]),
        (None, [call("lancer_regles")]),
        ("Le tri des mails ne produit que trois réponses : je le prouve.", [call("prouver", {"finding_id": TRIAGE})]),
        (None, [call("publier_plan", plan("Le tri des mails peut passer en règles fixes.", first_plan_justification))]),
    ]


def test_agent_investigates_proves_and_publishes_a_plan():
    llm = ScriptedLLM(happy_script())
    result = run_agent(AuditTools(EVENTS), llm, model_name="gpt-5-mini")
    assert result["statut"] == "terminé" and result["plan"]["actions"][0]["finding_id"] == TRIAGE
    assert [j["outil"] for j in result["journal"]] == ["vue_ensemble", "lancer_regles", "prouver", "publier_plan"]
    proof = result["journal"][2]["resultat"]
    assert proof["verdict"] == "pass" and proof["accord_pct"] == 100.0 and proof["facteur_cout"] == 3.5
    assert result["cout_audit_usd"] > 0  # 4 appels au modèle, prix gpt-5-mini du catalogue


def test_plan_with_an_invented_number_is_refused_then_corrected():
    script = happy_script("Économie de 4200 dollars par an garantie.")
    script.append((None, [call("publier_plan", plan("Le tri des mails peut passer en règles fixes.",
                                                    "Accord de 100.0 % au rejeu."))]))
    llm = ScriptedLLM(script)
    result = run_agent(AuditTools(EVENTS), llm)
    assert result["statut"] == "terminé"
    refused = next(j for j in result["journal"] if j["outil"] == "publier_plan" and "erreur" in j["resultat"])
    assert "4200" in refused["resultat"]["erreur"]
    assert "4200" not in json.dumps(result["plan"])


def test_unknown_numbers_accepts_rounding_and_small_counts():
    outputs = [{"accord_pct": 100.0, "cout_avant_mensuel_usd": 0.3, "facteur_cout": 3.5, "p95_avant_ms": 764.3}]
    ok = plan("Trois actions.", "Accord 100 %, coût 0,3 $ divisé par 3.5, p95 764 ms.")
    assert unknown_numbers(ok, outputs) == []
    assert unknown_numbers(plan("x", "Gain de 87 %"), outputs) == [87.0]


def test_report_shows_plan_and_how_the_agent_worked():
    report = audit(EVENTS, llm=ScriptedLLM(happy_script()), model_name="gpt-5-mini")
    page = render_html(report)
    assert "Plan d'action" in page and "Remplacer le tri des mails par des règles fixes" in page
    assert "Comment l'agent a mené l'audit" in page and "accord 100.0 %" in page
    assert page.index("Plan d'action") < page.index("Constats, du plus coûteux")


def test_without_key_the_report_is_unchanged():
    report = audit(EVENTS)
    assert "agent" not in report and "Plan d'action" not in render_html(report)


def test_unreachable_model_keeps_the_report_and_never_echoes_the_error():
    class Down:
        def chat(self, messages, tools):
            raise OSError("401 Incorrect API key provided: sk-secret-NE-DOIT-PAS-SORTIR")

    report = audit(EVENTS, llm=Down())
    assert report["agent"]["plan"] is None and "injoignable" in report["agent"]["statut"]
    page = render_html(report)
    assert "sk-secret" not in page and "n'a pas conclu" in page and "Constats" in page


def test_budget_is_bounded():
    llm = ScriptedLLM([(None, [call("vue_ensemble")])] * 5)
    result = run_agent(AuditTools(EVENTS), llm, max_steps=5)
    assert result["plan"] is None and "budget" in result["statut"] and result["appels_modele"] == 5


def test_tool_errors_reach_the_agent_not_the_user():
    llm = ScriptedLLM([(None, [call("prouver", {"finding_id": "inconnu"})]),
                       (None, [call("outil_fantome")]),
                       (None, [call("publier_plan", plan("Rien de prouvé.", "Piste à observer."))])])
    result = run_agent(AuditTools(EVENTS), llm)
    assert [("erreur" in j["resultat"]) for j in result["journal"][:2]] == [True, True]
    assert result["statut"] == "terminé"


def test_thousands_are_one_number_but_words_stay_apart():
    outputs = [{"cout_mensuel_usd": 315220.0, "p95_avant_ms": 764.3}]
    assert unknown_numbers(plan("x", "Coût de 315 220 $, p95 764 ms."), outputs) == []


def test_proof_status_is_decided_by_code_not_by_the_model():
    two = {"resume": "Deux pistes.", "actions": [
        {"priorite": 1, "finding_id": TRIAGE, "action": "Règles fixes", "justification": "Accord 100.0 %."},
        {"priorite": 2, "finding_id": "f_c1fe9dd8fa5ffbdfba75_raw_context", "action": "Envoyer moins",
         "justification": "Le modèle affirme que c'est prouvé."}]}
    llm = ScriptedLLM([(None, [call("prouver", {"finding_id": TRIAGE, "pourquoi": "le plus clair"})]),
                       (None, [call("publier_plan", two)])])
    result = run_agent(AuditTools(EVENTS), llm)
    assert [a["statut"] for a in result["plan"]["actions"]] == ["prouvé par rejeu", "piste à vérifier"]
    assert "[piste à vérifier]" in render_html({**audit(EVENTS), "agent": result})


def test_why_goes_to_the_journal_not_to_the_tool():
    llm = ScriptedLLM([(None, [call("detail_constat", {"finding_id": TRIAGE, "pourquoi": "le plus fréquent"})]),
                       (None, [call("publier_plan", plan("Rien de prouvé.", "Piste."))])])
    result = run_agent(AuditTools(EVENTS), llm)
    first = result["journal"][0]
    assert first["pensee"] == "le plus fréquent" and "erreur" not in first["resultat"]
    assert "pourquoi" not in first["arguments"]


def test_saving_is_computed_even_when_nothing_is_left_to_pay():
    from agent.tools import _saving
    assert _saving(0.3, 0.0) == 100.0 and _saving(0.3, 0.08) == 73.3 and _saving(None, 0.1) is None
