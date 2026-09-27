"""#105 : aiguillage par appel d'outil et classifieurs qui répondent en JSON (règle low_entropy_output).

Cas réels : le triage officiel OpenAI (handoffs = appels d'outil sans texte, rien n'était vu) et le
modèle n8n #7399 (classifieur qui répond en JSON, variations de format et score de confiance).
"""
import json

from proof.replay import replay
from rules.low_entropy import canon, detect, output_of


def _ev(i, content=None, tools=(), system="Tu es l'agent de triage.", last_role="user"):
    msgs = [{"role": "user", "content": f"demande client numero {i} sur le sujet {i * 7}"}]
    if last_role == "tool":
        msgs += [{"role": "assistant", "content": None,
                  "tool_calls": [{"id": f"p{i}", "name": "search", "arguments": "{}"}]},
                 {"role": "tool", "content": "résultat", "tool_call_id": f"p{i}"}]
    t = f"2026-09-27T{10 + i // 60:02d}:{i % 60:02d}:00Z"
    return {"schema_version": "1", "event_id": f"e{i}", "trace": {"id": None, "source": None, "step": None},
            "app_id": "a", "ts_start": t, "ts_end": t.replace(":00Z", ":01Z"), "latency_ms": 800,
            "ttft_ms": None, "provider": "openai", "endpoint": "/v1/chat/completions",
            "model": "gpt-4o", "model_resolved": "gpt-4o",
            "request": {"system": system, "messages": msgs, "tools": [],
                        "params": {"stream": False, "temperature": 0.0, "max_tokens": None,
                                   "response_format": "text"}},
            "response": {"content": content,
                         "tool_calls": [{"id": f"c{i}", "name": n, "arguments": a} for n, a in tools],
                         "finish_reason": "tool_calls" if tools else "stop", "finish_reason_raw": None},
            "usage": {"input_tokens": 100, "output_tokens": 5, "cached_input_tokens": 0, "reasoning_tokens": None},
            "http_status": 200, "error": None}


HANDOFFS = ["transfer_to_faq_agent", "transfer_to_seat_booking_agent", "transfer_to_refund_agent"]


def _triage(n=54):
    return [_ev(i, tools=[(HANDOFFS[i % 3], "{}")]) for i in range(n)]


# --- 1. aiguillage par appel d'outil ---------------------------------------------------------

def test_handoff_tool_calls_are_a_routing_decision():
    [f] = detect(_triage())
    assert f["rule"] == "low_entropy_output" and f["severity"] == "cut"
    assert f["evidence"]["distinct_outputs"] == 3
    assert f["evidence"]["output_kind"] == "appel_outil"
    assert set(f["evidence"]["output_distribution"]) == {f"outil {h}" for h in HANDOFFS}
    assert "appel d'outil" in f["title"]


def test_routing_tool_with_enumerated_argument():
    dests = ["billing", "technical", "account", "other"]
    evts = [_ev(i, tools=[("route", json.dumps({"destination": dests[i % 4].upper() if i % 2 else dests[i % 4]}))])
            for i in range(40)]
    [f] = detect(evts)
    assert set(f["evidence"]["output_distribution"]) == {f"outil route destination={d}" for d in dests}


def test_tool_call_doing_real_work_is_not_flagged():
    # arguments riches et variés : le modèle extrait une requête de chaque demande, ce n'est pas un aiguillage
    evts = [_ev(i, tools=[("search_orders", json.dumps({"query": f"commande {1000 + i} de {n}", "limit": 5}))])
            for i, n in enumerate(["Mme Martin", "M. Dupont", "Léa", "Paul", "Nora"] * 10)]
    assert detect(evts) == []


def test_tool_calls_inside_an_agent_loop_are_not_routing():
    # après un résultat d'outil, l'appel suivant continue un travail : ce n'est pas un choix de branche
    evts = [_ev(i, tools=[("search", "{}")], last_role="tool") for i in range(50)]
    assert detect(evts) == []


def test_fixture_events_match_the_event_schema():
    import jsonschema
    from pathlib import Path
    schema = json.loads((Path(__file__).resolve().parent.parent / "schemas/event.schema.json").read_text())
    for e in (_triage(2) + [_ev(9, content="x"), _ev(8, tools=[("s", "{}")], last_role="tool")]):
        jsonschema.validate(e, schema)


def test_parallel_tool_calls_are_one_ordered_signature():
    a = _ev(1, tools=[("b", "{}"), ("a", '{"x": 1}')])
    b = _ev(2, tools=[("a", '{"x":1}'), ("b", "{}")])
    assert output_of(a) == output_of(b) == "outil a x=1 + outil b"


def test_triage_that_mostly_answers_in_free_text_is_not_flagged():
    # un agent qui répond lui-même la plupart du temps et ne passe la main que parfois n'est pas un aiguillage
    evts = [_ev(i, tools=[(HANDOFFS[0], "{}")]) if i % 5 == 0 else
            _ev(i, content=f"Votre vol {100 + i} part à {i % 24}h, porte {i}.") for i in range(60)]
    assert detect(evts) == []


def test_same_request_every_time_is_a_cache_problem_not_routing():
    # entrées aussi répétitives que les sorties : relève de no_cache, pas de cette règle
    evts = _triage(60)
    for e in evts:
        e["request"]["messages"] = [{"role": "user", "content": "je veux un remboursement"}]
    assert detect(evts) == []


# --- 2. classifieurs qui répondent en JSON ------------------------------------------------------

def test_json_formats_are_merged():
    assert canon('{"category": "Spam"}') == canon('{"category":"spam"}') == canon(
        '```json\n{ "category" : "spam" }\n```') == "category=spam"
    assert canon('{"b": true, "a": {"c": 2}}') == "a.c=2, b=true"


def test_json_confidence_scores_are_ignored_but_not_other_numbers():
    assert canon('{"category": "spam", "confidence": 0.93}') == "category=spam"
    assert canon('{"amount": 12.5, "currency": "EUR"}') == "amount=12.5, currency=eur"


def test_json_classifier_with_four_values_is_flagged():
    # n8n #7399 : 4 JSON distincts, écrits de façon irrégulière, avec un score de confiance
    cats = ["spam", "urgent", "newsletter", "personnel"]
    evts = [_ev(i, content=(json.dumps({"category": cats[i % 4], "confidence": round(0.5 + i / 100, 2)})
                            if i % 2 else f'{{"category":"{cats[i % 4].title()}"}}'))
            for i in range(60)]
    [f] = detect(evts)
    assert f["severity"] == "cut" and f["evidence"]["distinct_outputs"] == 4
    assert f["evidence"]["output_kind"] == "json"
    assert f["evidence"]["distinct_raw_outputs"] > 4


def test_json_extraction_with_varied_fields_is_not_flagged():
    evts = [_ev(i, content=json.dumps({"client": f"client {i}", "montant": 10 + i})) for i in range(60)]
    assert detect(evts) == []


def test_json_classifier_with_many_categories_is_not_flagged():
    # au-delà de MAX_DISTINCT catégories, le modèle apporte de l'information : pas d'aiguillage signalé
    evts = [_ev(i, content=json.dumps({"category": f"theme_{i % 12}"})) for i in range(60)]
    assert detect(evts) == []


def test_plain_text_outputs_unchanged():
    assert canon("Spam.") == "spam"
    assert canon("{pas du json") == "pas du json"


# --- proposition « règles fixes » -------------------------------------------------------------

def test_replay_compares_tool_routing_with_the_same_signature():
    evts = _triage(90)
    [f] = detect(evts)
    rules = {"categories": [{"key": f"outil {h}", "regex": "numero"} for h in HANDOFFS[:1]]}
    proof = replay(f, evts, rules)
    # une seule règle, qui envoie tout vers la FAQ : 1/3 d'accord, comparé sur les signatures d'outil
    assert proof["n_replayed"] > 0 and 0.2 < proof["agreement_rate"] < 0.5


def test_propose_handles_tool_routing():
    from optimize.propose import propose
    out = [p for p in propose(_triage(90)) if p["type"] == "regles"]
    assert len(out) == 1 and "outil transfer_to" in out[0]["changement"]
