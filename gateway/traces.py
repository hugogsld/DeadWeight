"""D1.4 — Regroupement des appels en traces.

Deux voies, dans cet ordre :

1. En-tête ``x-deadweight-trace`` posé par le client : la trace est donnée
   (``source = "header"``), on ne fait que numéroter les étapes par ordre
   chronologique.

2. Heuristique de repli, sans coopération du client (``source = "heuristic"``).
   Un appel B continue un appel A quand B contient, à la suite :
       - le dernier message que A avait reçu,
       - puis la réponse que A a rendue (message assistant : texte ou appels d'outils).
   C'est ce que fait tout client de chat ou boucle d'agent : il renvoie
   l'historique, allongé de la réponse précédente et du résultat des outils.
   On exige en plus : même application, même prompt système, et B démarre
   au plus WINDOW_S secondes après la fin de A.

   Seul le DERNIER message assistant de B est regardé : il désigne le parent
   immédiat. Ne pas exiger que tout l'historique de A soit un préfixe de B
   garde les conversations à fenêtre glissante (historique tronqué).
   Entre plusieurs candidats, on préfère : historique de A préfixe exact de B,
   puis identifiants d'appels d'outils identiques, puis le plus récent.

   Un appel sans parent ni enfant reste hors trace (``id = null``) : un
   classifieur appelé 400 fois n'est pas 400 traces d'un appel.

   Passage de main entre agents (handoff, #105) : l'agent suivant a un AUTRE prompt système mais
   renvoie tout l'historique (triage officiel OpenAI : triage → agent FAQ). Sans prompt système
   commun, on exige la preuve la plus forte : l'historique entier de A, puis sa réponse, est
   exactement le début de B (même application, même fenêtre de temps). Le prompt système identique
   reste préféré quand les deux candidats existent.

Ce que l'heuristique ne voit pas : un client qui réécrit l'historique
(résumé, reformulation), ou deux conversations strictement identiques au
mot près menées en parallèle. Un agent qui change de prompt système ET
tronque l'historique au même tour coupe la trace.
"""
import json
from datetime import datetime

WINDOW_S = 30 * 60   # un humain peut mettre plusieurs minutes à répondre dans un chat
CLOCK_SKEW_S = 1.0   # ts_start de B légèrement avant ts_end de A : horloges, arrondis


def _ts(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def _args(arguments):
    try:
        return json.dumps(json.loads(arguments), sort_keys=True, ensure_ascii=False)
    except (TypeError, ValueError):
        return arguments


def _fp(role, content, tool_calls, tool_call_id=None):
    """Empreinte d'un message, sans les identifiants d'appels d'outils."""
    return json.dumps([role, (content or "").strip() or None,
                       [[c.get("name"), _args(c.get("arguments"))] for c in tool_calls or []],
                       tool_call_id], ensure_ascii=False)


def _msg_fp(m):
    return _fp(m["role"], m.get("content"), m.get("tool_calls"), m.get("tool_call_id"))


def _call_ids(tool_calls):
    return [c.get("id") for c in tool_calls or []]


def assign_traces(events):
    """Renvoie des copies des événements, champ ``trace`` rempli. Ordre d'entrée conservé."""
    events = [{**e, "trace": dict(e.get("trace") or {"id": None, "source": None})} for e in events]
    order = sorted(range(len(events)), key=lambda i: (_ts(events[i]["ts_start"]), i))

    # Index des parents possibles : (app, dernier message reçu, réponse rendue) -> [(système, i)].
    index = {}
    parent = {}
    for i in order:
        e = events[i]
        msgs = e["request"]["messages"]
        last_assistant = max((p for p, m in enumerate(msgs) if m["role"] == "assistant"), default=None)
        if last_assistant is not None and last_assistant > 0:
            key = (e["app_id"], _msg_fp(msgs[last_assistant - 1]), _msg_fp(msgs[last_assistant]))
            best = None
            head = [_msg_fp(m) for m in msgs[:last_assistant]]
            for system, j in index.get(key, ()):
                a = events[j]
                gap = _ts(e["ts_start"]) - _ts(a["ts_end"])
                if not -CLOCK_SKEW_S <= gap <= WINDOW_S:
                    continue
                a_msgs = a["request"]["messages"]
                same_system = system == e["request"]["system"]
                exact = len(a_msgs) == last_assistant and (
                    msgs[:last_assistant] == a_msgs or head == [_msg_fp(m) for m in a_msgs])
                if not same_system and not exact:
                    continue  # autre agent (handoff) : seul l'historique exact prouve la conversation
                score = (same_system, exact,
                         _call_ids(a["response"]["tool_calls"]) == _call_ids(msgs[last_assistant].get("tool_calls")),
                         _ts(a["ts_end"]))
                if best is None or score > best[0]:
                    best = (score, j)
            if best is not None:
                parent[i] = best[1]

        resp = e["response"]
        if e.get("error") is None and msgs and (resp.get("content") or resp.get("tool_calls")):
            key = (e["app_id"], _msg_fp(msgs[-1]), _fp("assistant", resp.get("content"), resp.get("tool_calls")))
            index.setdefault(key, []).append((e["request"]["system"], i))

    has_child = set(parent.values())
    header_steps = {}
    for i in order:
        t = events[i]["trace"]
        if t.get("id") and t.get("source") == "header":
            t["step"] = header_steps.get(t["id"], 0)
            header_steps[t["id"]] = t["step"] + 1
        elif i in parent:
            p = events[parent[i]]["trace"]
            events[i]["trace"] = {"id": p["id"], "source": "heuristic", "step": p["step"] + 1}
        elif i in has_child:
            events[i]["trace"] = {"id": "h_" + events[i]["event_id"], "source": "heuristic", "step": 0}
        else:
            events[i]["trace"] = {"id": None, "source": None, "step": None}
    return events
