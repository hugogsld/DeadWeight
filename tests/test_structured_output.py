"""Sortie structurée n8n (outil format_final_json_response) : dépliée en réponse JSON avant les règles."""
import json

from report.audit import build_report
from rules.oversized_model import detect
from rules.structured_output import unwrap, unwrap_all
from tests.test_oversized_model import PRICES, ev

FORMAT = "format_final_json_response"


def n8n(i, verdict=True, **kw):
    """Un appel d'agent n8n + Structured Output Parser, tel que la passerelle le capture."""
    e = ev(i, tools=[FORMAT], **kw)
    e["response"].update(content=None, finish_reason="tool_calls", tool_calls=[
        {"id": f"call_{i}", "name": FORMAT, "arguments": json.dumps({"output": {"passesQuality": verdict}})}])
    return e


def test_unwrap_turns_the_format_tool_into_a_json_answer():
    e = unwrap(n8n(1))
    assert e["request"]["tools"] == [] and e["response"]["tool_calls"] == []
    assert json.loads(e["response"]["content"]) == {"passesQuality": True}
    assert e["response"]["finish_reason"] == "stop"


def test_unwrap_leaves_real_tools_and_the_original_untouched():
    real = ev(1, tools=["search", FORMAT])
    assert unwrap(real) is real
    other = n8n(2)
    other["response"]["tool_calls"][0]["name"] = "search"
    assert unwrap(other) is other
    original = n8n(3)
    unwrap(original)
    assert original["request"]["tools"] == [{"name": FORMAT}]


def test_unwrap_keeps_a_broken_call_as_is():
    e = n8n(1)
    e["response"]["tool_calls"][0]["arguments"] = "{pas du json"
    assert unwrap(e) is e


def test_rules_see_n8n_structured_calls_once_unwrapped():
    calls = [n8n(i) for i in range(40)]
    assert detect(calls, PRICES) == []
    [f] = detect(unwrap_all(calls), PRICES)
    assert f["rule"] == "oversized_model"


def test_audit_report_unwraps_before_the_rules():
    calls = [n8n(i) for i in range(40)]
    seen = []
    build_report(calls, detectors=[("espion", lambda events: seen.extend(events) or [])])
    assert seen and all(not e["request"]["tools"] for e in seen)
