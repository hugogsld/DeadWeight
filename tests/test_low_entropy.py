"""D2.1 : regle low_entropy_output, portee du prototype (detector/scan.py)."""
import json
from pathlib import Path

from rules.low_entropy import detect, normalize, shannon

ROOT = Path(__file__).resolve().parent.parent
V1 = ROOT / "fixtures/dataset/v1"
EVENTS = [json.loads(line) for line in (V1 / "events.jsonl").read_text().splitlines()]
FINDING_KEYS = {"finding_id", "rule", "app_id", "model", "template", "severity",
                "title", "proven", "event_ids", "evidence"}


def _ev(i, out, app="a", model="gpt-4o", system="S", error=None):
    return {"event_id": f"e{i}", "app_id": app, "model": model, "error": error,
            "request": {"system": system, "messages": [{"role": "user", "content": f"entree {i}"}]},
            "response": {"content": out, "tool_calls": []}}


def test_normalize_merges_case_space_and_punctuation():
    assert normalize("Spam.") == normalize(" spam ") == normalize("SPAM!") == "spam"
    assert normalize("Tres  bien, merci") == "tres bien, merci"


def test_shannon():
    assert shannon({"a": 5}) == 0
    assert shannon({"a": 1, "b": 1}) == 1


def test_prototype_parity_hackathon_verdict():
    # Hackathon : "Support ticket triage", 125 appels, 4 sorties -> CUT.
    labels = ["billing"] * 50 + ["technical"] * 40 + ["account"] * 25 + ["other"] * 10
    [f] = detect([_ev(i, o) for i, o in enumerate(labels)])
    assert f["severity"] == "cut"
    assert f["evidence"]["distinct_outputs"] == 4 and f["evidence"]["calls"] == 125


def test_below_min_calls_is_ignored():
    assert detect([_ev(i, "oui") for i in range(10)]) == []


def test_many_distinct_outputs_is_kept():
    assert detect([_ev(i, f"sortie {i}") for i in range(100)]) == []


def test_errors_and_tool_calls_are_ignored():
    evts = [_ev(i, None, error={"type": "x", "message": "y"}) for i in range(50)]
    assert detect(evts) == []


def test_groups_by_app_model_and_template():
    evts = [_ev(i, "oui", system="A") for i in range(40)] + \
           [_ev(100 + i, f"texte {i}", system="B") for i in range(40)]
    found = detect(evts)
    assert len(found) == 1 and found[0]["template"] is not None


def test_template_ignores_numbers_in_system_prompt():
    evts = [_ev(i, "oui", system=f"Ticket {i}: classe") for i in range(40)]
    assert len(detect(evts)) == 1


def test_finding_format():
    [f] = detect([_ev(i, "oui" if i % 2 else "non") for i in range(40)])
    assert set(f) == FINDING_KEYS
    assert f["rule"] == "low_entropy_output" and f["proven"] is False
    assert len(f["event_ids"]) == 40


def test_dataset_v1_positives_and_negatives():
    flagged = {f["app_id"] for f in detect(EVENTS)}
    assert {"mail-triage", "reviews"} <= flagged
    assert flagged.isdisjoint({"eng-copilot", "ticket-summary", "translate",
                               "support-chat", "contract-bot", "faq-bot"})


def test_mail_triage_needs_normalisation():
    [f] = [f for f in detect(EVENTS) if f["app_id"] == "mail-triage"]
    assert f["evidence"]["distinct_outputs"] == 3
    assert f["evidence"]["distinct_raw_outputs"] > 3
    assert f["severity"] == "cut"


def test_repeated_inputs_are_left_to_no_cache():
    evts = [_ev(i, "oui") for i in range(40)]
    for e in evts:
        e["request"]["messages"] = [{"role": "user", "content": "toujours la meme question"}]
    assert detect(evts) == []


def test_canon_json_precede_de_json_sans_backticks():
    # sortie d'agent n8n vue chez un testeur : l'étiquette de langue reste, les ``` ont disparu
    from rules.low_entropy import canon
    assert canon('json\n{"isitaccepted":false}') == "isitaccepted=false"
    assert canon('json {"isitaccepted": true}') == "isitaccepted=true"
    assert canon("json est un format") == "json est un format"
