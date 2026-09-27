"""Recette ``regles`` sur une source n8n : Switch déterministe + secours, aucun appel LLM."""
import json

import pytest

from optimize.patch_n8n import apply_regles_n8n, build_patched_workflow

ORIGINAL = {
    "id": "wf1", "name": "Email triage (test)",
    "nodes": [
        {"name": "Trigger", "type": "n8n-nodes-base.manualTrigger", "position": [0, 0], "parameters": {}},
        {"name": "Classifier", "type": "@n8n/n8n-nodes-langchain.textClassifier", "position": [200, 0],
         "parameters": {"inputText": "={{ $json.email_body }}"}},
        {"name": "Model", "type": "@n8n/n8n-nodes-langchain.lmChatOpenAi", "position": [200, 200],
         "parameters": {"model": {"value": "gpt-4.1-mini"}}},
        {"name": "Label A", "type": "n8n-nodes-base.noOp", "position": [400, -50], "parameters": {}},
        {"name": "Label B", "type": "n8n-nodes-base.noOp", "position": [400, 50], "parameters": {}},
    ],
    "connections": {
        "Trigger": {"main": [[{"node": "Classifier", "type": "main", "index": 0}]]},
        "Model": {"ai_languageModel": [[{"node": "Classifier", "type": "ai_languageModel", "index": 0}]]},
        "Classifier": {"main": [
            [{"node": "Label A", "type": "main", "index": 0}],
            [{"node": "Label B", "type": "main", "index": 0}],
        ]},
    },
}
RULES = {"categories": [{"key": "Agency Lead", "regex": "agency|build"}, {"key": "Miscellaneous", "regex": "unsubscribe"}]}


def test_classifier_and_its_model_are_replaced_by_a_switch_and_fallback():
    patched = build_patched_workflow(ORIGINAL, "Classifier", RULES, "gpt-4.1-mini")
    names = {n["name"] for n in patched["nodes"]}
    assert "Classifier" not in names and "Model" not in names
    assert "Classifier (rules)" in names
    assert "Classifier fallback (gpt-4.1-mini)" in names
    assert "OpenAI Chat Model (gpt-4.1-mini)" in names


def test_original_dict_is_never_mutated():
    before = json.dumps(ORIGINAL, sort_keys=True)
    build_patched_workflow(ORIGINAL, "Classifier", RULES, "gpt-4.1-mini")
    assert json.dumps(ORIGINAL, sort_keys=True) == before


def test_upstream_now_points_to_the_switch():
    patched = build_patched_workflow(ORIGINAL, "Classifier", RULES, "gpt-4.1-mini")
    assert patched["connections"]["Trigger"]["main"][0][0]["node"] == "Classifier (rules)"


def test_switch_has_one_branch_per_rule_plus_an_unmatched_branch_to_the_fallback():
    patched = build_patched_workflow(ORIGINAL, "Classifier", RULES, "gpt-4.1-mini")
    switch_out = patched["connections"]["Classifier (rules)"]["main"]
    assert len(switch_out) == len(RULES["categories"]) + 1
    for branch in switch_out[:-1]:
        assert branch[0]["node"] in ("Label A", "Label B")
    assert switch_out[-1][0]["node"] == "Classifier fallback (gpt-4.1-mini)"
    assert patched["connections"]["Classifier fallback (gpt-4.1-mini)"]["main"][0][0]["node"] in ("Label A", "Label B")


def test_fallback_model_node_feeds_the_fallback_chain():
    patched = build_patched_workflow(ORIGINAL, "Classifier", RULES, "gpt-4.1-mini")
    link = patched["connections"]["OpenAI Chat Model (gpt-4.1-mini)"]["ai_languageModel"][0][0]
    assert link["node"] == "Classifier fallback (gpt-4.1-mini)"


def test_missing_node_raises_a_clear_error():
    with pytest.raises(ValueError, match="introuvable"):
        build_patched_workflow(ORIGINAL, "Does Not Exist", RULES, "gpt-4.1-mini")


def test_apply_regles_n8n_writes_original_and_patched_into_the_repo(tmp_path):
    wf_path = tmp_path / "workflow.json"
    wf_path.write_text(json.dumps(ORIGINAL), encoding="utf-8")
    repo = tmp_path / "demo-repo"
    repo.mkdir()
    proposal = {
        "app_id": "n8n:Email triage (test)/Classifier", "model": "gpt-4.1-mini",
        "n8n_workflow_path": str(wf_path), "preuve": {"rules": RULES["categories"]},
    }
    notes = apply_regles_n8n(repo, proposal)
    out = repo / "n8n-email-triage"
    original = json.loads((out / "workflow.original.json").read_text())
    patched = json.loads((out / "workflow.patched.json").read_text())
    assert original == ORIGINAL
    assert any(n["name"] == "Classifier (rules)" for n in patched["nodes"])
    assert notes and "Classifier" in notes[0]


def test_apply_regles_n8n_without_proven_rules_writes_nothing(tmp_path):
    wf_path = tmp_path / "workflow.json"
    wf_path.write_text(json.dumps(ORIGINAL), encoding="utf-8")
    repo = tmp_path / "demo-repo"
    repo.mkdir()
    proposal = {"app_id": "n8n:Email triage (test)/Classifier", "model": "gpt-4.1-mini",
                "n8n_workflow_path": str(wf_path), "preuve": {"rules": []}}
    notes = apply_regles_n8n(repo, proposal)
    assert not (repo / "n8n-email-triage").exists()
    assert notes == ["aucune règle prouvée : rien à patcher"]
