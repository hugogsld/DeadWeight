"""#105 : conversations sans en-tête de trace quand l'agent change de prompt système (handoff).

Dans le triage officiel OpenAI (Agents SDK), l'agent de triage passe la main à un autre agent :
l'appel suivant porte un autre prompt système, mais renvoie tout l'historique, allongé de l'appel
d'outil de passage de main et de son résultat. Même application, historique exact : même conversation.
"""
from gateway.traces import assign_traces

USER = {"role": "user", "content": "Je voudrais changer de siège sur mon vol"}
HANDOFF = [{"id": "call_1", "name": "transfer_to_seat_booking_agent", "arguments": "{}"}]


def _ev(eid, system, messages, content=None, tool_calls=(), t0=0, app="airline"):
    return {"event_id": eid, "app_id": app, "error": None, "trace": {"id": None, "source": None},
            "ts_start": f"2026-09-27T10:00:{t0:02d}Z", "ts_end": f"2026-09-27T10:00:{t0 + 1:02d}Z",
            "request": {"system": system, "messages": messages},
            "response": {"content": content, "tool_calls": list(tool_calls)}}


def _handoff_pair(b_history=None, app_b="airline"):
    a = _ev("a", "Tu es l'agent de triage.", [USER], tool_calls=HANDOFF, t0=0)
    history = b_history if b_history is not None else [USER]
    b = _ev("b", "Tu es l'agent de réservation de sièges.",
            history + [{"role": "assistant", "content": None, "tool_calls": HANDOFF},
                       {"role": "tool", "content": '{"assistant": "Seat Booking Agent"}', "tool_call_id": "call_1"}],
            content="Quel est votre numéro de confirmation ?", t0=3, app=app_b)
    return a, b


def test_handoff_to_another_system_prompt_is_the_same_conversation():
    a, b = assign_traces(_handoff_pair())
    assert a["trace"]["id"] is not None and a["trace"]["id"] == b["trace"]["id"]
    assert (a["trace"]["step"], b["trace"]["step"]) == (0, 1)
    assert b["trace"]["source"] == "heuristic"


def test_different_system_prompt_needs_the_exact_history():
    # l'historique de B ne commence pas par celui de A : rien ne prouve que c'est la même conversation
    other = [{"role": "user", "content": "Bonjour"}, {"role": "assistant", "content": "Bonjour !"}, USER]
    a, b = assign_traces(_handoff_pair(b_history=other))
    assert a["trace"]["id"] is None and b["trace"]["id"] is None


def test_different_application_is_never_linked():
    a, b = assign_traces(_handoff_pair(app_b="autre"))
    assert a["trace"]["id"] is None and b["trace"]["id"] is None


def test_parallel_handoffs_with_the_same_first_message_are_not_crossed():
    # deux clients écrivent la même phrase au même moment : les identifiants d'appel départagent
    evts = []
    for k in (1, 2):
        call = [{"id": f"call_{k}", "name": "transfer_to_seat_booking_agent", "arguments": "{}"}]
        evts.append(_ev(f"a{k}", "Tu es l'agent de triage.", [USER], tool_calls=call, t0=k))
        evts.append(_ev(f"b{k}", "Tu es l'agent de réservation de sièges.",
                        [USER, {"role": "assistant", "content": None, "tool_calls": call},
                         {"role": "tool", "content": "ok", "tool_call_id": f"call_{k}"}],
                        content="Votre numéro ?", t0=4 + k))
    by_id = {e["event_id"]: e["trace"]["id"] for e in assign_traces(evts)}
    assert by_id["a1"] == by_id["b1"] and by_id["a2"] == by_id["b2"] and by_id["a1"] != by_id["a2"]


def test_handoff_outside_the_time_window_is_not_linked():
    a, b = _handoff_pair()
    b = {**b, "ts_start": "2026-09-27T11:00:00Z", "ts_end": "2026-09-27T11:00:01Z"}
    a, b = assign_traces([a, b])
    assert a["trace"]["id"] is None and b["trace"]["id"] is None


def test_same_system_prompt_is_preferred_over_a_handoff_candidate():
    # même historique chez deux parents possibles : celui du même agent l'emporte
    reply = [{"role": "assistant", "content": "Bonjour, que puis-je faire ?"}]
    same = _ev("same", "Agent A", [USER], content=reply[0]["content"], t0=0)
    other = _ev("other", "Agent B", [USER], content=reply[0]["content"], t0=1)
    child = _ev("child", "Agent A", [USER] + reply + [{"role": "user", "content": "Un hublot"}],
                content="C'est noté.", t0=5)
    by_id = {e["event_id"]: e["trace"] for e in assign_traces([same, other, child])}
    assert by_id["child"]["id"] == by_id["same"]["id"] != by_id["other"]["id"]
