"""Genere fixtures/events.jsonl et fixtures/events.labels.json (D0.1).

50 evenements au schema schemas/event.schema.json, deterministes (pas de hasard),
couvrant les six regles avec au moins un cas positif et des cas negatifs.
Relancer : python3 fixtures/gen_events.py
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).parent
T0 = datetime(2026, 9, 20, 9, 0, 0, tzinfo=timezone.utc)


def iso(dt):
    return dt.isoformat().replace("+00:00", "Z")


def event(n, *, app, provider, model, system, messages, content, in_tok, out_tok,
          offset_s, latency_ms, tools=None, tool_calls=None, finish="stop",
          finish_raw=None, trace=(None, None, None), cached=0, stream=False,
          ttft=None, http_status=200, error=None, temperature=0.0, max_tokens=None):
    start = T0 + timedelta(seconds=offset_s)
    trace_id, trace_source, step = trace
    return {
        "schema_version": "1",
        "event_id": f"evt_{n:04d}",
        "trace": {"id": trace_id, "source": trace_source, "step": step},
        "app_id": app,
        "ts_start": iso(start),
        "ts_end": iso(start + timedelta(milliseconds=latency_ms)),
        "latency_ms": latency_ms,
        "ttft_ms": ttft,
        "provider": provider,
        "endpoint": {
            "openai": "/v1/chat/completions",
            "anthropic": "/v1/messages",
            "gemini": f"/v1beta/models/{model}:generateContent",
        }[provider],
        "model": model,
        "model_resolved": model,
        "request": {
            "system": system,
            "messages": messages,
            "tools": tools or [],
            "params": {"stream": stream, "temperature": temperature, "max_tokens": max_tokens,
                       "response_format": "text"},
        },
        "response": {
            "content": content,
            "tool_calls": tool_calls or [],
            "finish_reason": finish,
            "finish_reason_raw": finish_raw or finish,
        },
        "usage": {"input_tokens": in_tok, "output_tokens": out_tok,
                  "cached_input_tokens": cached, "reasoning_tokens": None},
        "http_status": http_status,
        "error": error,
    }


def user(text):
    return {"role": "user", "content": text}


def call(name, args, cid):
    return {"id": cid, "name": name, "arguments": json.dumps(args, ensure_ascii=False)}


class Builder:
    def __init__(self):
        self.events, self.labels, self.n = [], [], 0

    def add(self, scenario, expected, evts):
        ids = [e["event_id"] for e in evts]
        self.events.extend(evts)
        self.labels.append({"scenario": scenario, "app_id": evts[0]["app_id"],
                            "expected_rules": expected, "event_ids": ids})

    def next(self):
        self.n += 1
        return self.n


def low_entropy_classifier(b):
    """R1 + R2 positif : gpt-4o qui classe des mails en 3 etiquettes, sorties bruitees."""
    system = "Classe le mail en une seule etiquette : spam, facture ou support."
    mails = ["Gagnez un iPhone maintenant", "Votre facture n°4471 est disponible",
             "Mon mot de passe ne marche plus", "PROMO -90% cliquez ici",
             "Relance facture impayee mars", "Impossible de me connecter depuis hier",
             "Vous avez gagne 1000 euros", "Facture avoir n°88", "Bug sur l'export CSV",
             "Offre exclusive casino"]
    outs = ["spam", "facture", "support", "Spam.", "Facture", "support",
            "SPAM", "facture.", "Support", "spam"]
    return [event(b.next(), app="mail-triage", provider="openai", model="gpt-4o",
                  system=system, messages=[user(m)], content=o, in_tok=62 + i, out_tok=2,
                  offset_s=i * 37, latency_ms=610 + 13 * i, max_tokens=5)
            for i, (m, o) in enumerate(zip(mails, outs))]


def oversized_sentiment(b):
    """R2 positif : claude-opus sur un sentiment binaire, pas d'outils, sortie courte."""
    reviews = ["Chambre impeccable, personnel adorable", "Petit dejeuner froid, decu",
               "Super sejour, on reviendra", "Bruit toute la nuit", "Rien a redire", "Trop cher pour ce que c'est"]
    outs = ["positif", "negatif", "positif", "negatif", "positif", "negatif"]
    return [event(b.next(), app="reviews", provider="anthropic", model="claude-opus-4-1",
                  system="Reponds uniquement positif ou negatif.", messages=[user(r)],
                  content=o, in_tok=31 + i, out_tok=3, offset_s=600 + i * 41,
                  latency_ms=1450 + 20 * i, finish_raw="end_turn", max_tokens=10)
            for i, (r, o) in enumerate(zip(reviews, outs))]


def raw_context_chat(b):
    """R3 positif : conversation Gemini qui renvoie tout l'historique, input lineaire."""
    evts, history = [], []
    doc = "CONTRAT (extrait de 40 pages) " + "clause " * 50
    for turn in range(6):
        history = history + [user(f"Question {turn + 1} sur le contrat")]
        messages = [user(doc)] + history
        answer = f"Reponse courte a la question {turn + 1}."
        evts.append(event(b.next(), app="contract-bot", provider="gemini", model="gemini-2.5-pro",
                          system="Tu es un assistant juridique.", messages=messages, content=answer,
                          in_tok=12000 + 1800 * turn, out_tok=40, offset_s=1200 + turn * 90,
                          latency_ms=2100 + 150 * turn, finish_raw="STOP",
                          trace=("tr_contract_1", "header", turn), temperature=0.3))
        history = history + [{"role": "assistant", "content": answer}]
    return evts


def no_cache_repeats(b):
    """R4 positif : meme prompt exact rejoue 6 fois, aucun token en cache."""
    prompt = "Resume en 3 puces la politique de remboursement ci-dessous : ..."
    return [event(b.next(), app="faq-bot", provider="openai", model="gpt-4o-mini",
                  system="Tu es le support client.", messages=[user(prompt)],
                  content="- Remboursement sous 14 jours\n- Produit non ouvert\n- Frais de retour offerts",
                  in_tok=1850, out_tok=28, offset_s=2000 + i * 300, latency_ms=900 + 7 * i,
                  cached=0, temperature=0.2)
            for i in range(6)]


SEARCH_TOOL = {"name": "search_docs", "description": "Cherche dans la doc interne",
               "parameters": {"type": "object", "properties": {"q": {"type": "string"}}}}


def unbounded_loop(b):
    """R5 positif : agent qui relance search_docs 8 fois avec une requete quasi identique."""
    queries = ["tarif entreprise", "tarif entreprise 2026", "tarifs entreprise",
               "tarif entreprise", "tarif offre entreprise", "tarif entreprise",
               "tarifs entreprise 2026", "tarif entreprise"]
    evts, messages = [], [user("Quel est le tarif entreprise ?")]
    for i, q in enumerate(queries):
        tc = call("search_docs", {"q": q}, f"toolu_{i:02d}")
        evts.append(event(b.next(), app="sales-agent", provider="anthropic", model="claude-sonnet-4-5",
                          system="Agent commercial. Utilise les outils.", messages=list(messages),
                          content=None, tool_calls=[tc], tools=[SEARCH_TOOL],
                          in_tok=900 + 210 * i, out_tok=35, offset_s=3000 + i * 4,
                          latency_ms=1300 + 30 * i, finish="tool_calls", finish_raw="tool_use",
                          trace=("tr_loop_1", "header", i)))
        messages = messages + [{"role": "assistant", "content": None, "tool_calls": [tc]},
                               {"role": "tool", "content": "Aucun resultat", "tool_call_id": tc["id"]}]
    return evts


ORDER_TOOLS = [{"name": n} for n in ("get_order", "check_stock", "send_email")]


def agent_where_chain(b):
    """R6 positif : 3 traces sans en-tete, toujours get_order -> check_stock -> send_email."""
    evts = []
    for t, order in enumerate(["A-101", "A-102", "A-103"]):
        messages = [user(f"Ou en est ma commande {order} ?")]
        for step, name in enumerate(["get_order", "check_stock", "send_email"]):
            tc = call(name, {"order_id": order}, f"call_{t}_{step}")
            evts.append(event(b.next(), app="order-agent", provider="openai", model="gpt-4.1",
                              system="Agent SAV.", messages=list(messages), content=None,
                              tool_calls=[tc], tools=ORDER_TOOLS, in_tok=400 + 120 * step,
                              out_tok=22, offset_s=4000 + t * 600 + step * 3,
                              latency_ms=800 + 40 * step, finish="tool_calls",
                              trace=(f"tr_order_{t}", "heuristic", step)))
            messages = messages + [{"role": "assistant", "content": None, "tool_calls": [tc]},
                                   {"role": "tool", "content": "ok", "tool_call_id": tc["id"]}]
    return evts


def real_reasoning(b):
    """Negatif pour toutes les regles : vrai raisonnement, sorties longues et variees, streaming."""
    tasks = [("Compare deux strategies de pricing SaaS pour un marche B2B hotelier.", 640),
             ("Redige un plan de migration Postgres 12 -> 16 sans interruption.", 820),
             ("Analyse ce log d'erreur Kubernetes et propose un diagnostic.", 510),
             ("Explique le compromis biais-variance a un junior avec un exemple.", 430)]
    return [event(b.next(), app="eng-copilot", provider="openai", model="gpt-4o",
                  system="Tu es un ingenieur senior.", messages=[user(q)],
                  content=f"[reponse detaillee {i + 1} : {out} tokens de raisonnement specifique]",
                  in_tok=150 + 40 * i, out_tok=out, offset_s=6000 + i * 997,
                  latency_ms=9000 + 1100 * i, stream=True, ttft=380 + 25 * i, temperature=0.7)
            for i, (q, out) in enumerate(tasks)]


def upstream_error(b):
    """Negatif : un 429 du fournisseur doit etre capture sans etre compte comme gaspillage."""
    return [event(b.next(), app="eng-copilot", provider="openai", model="gpt-4o",
                  system="Tu es un ingenieur senior.", messages=[user("Relis cette PR")],
                  content=None, in_tok=None, out_tok=None, offset_s=9000, latency_ms=120,
                  finish="error", finish_raw=None, http_status=429,
                  error={"type": "rate_limit_exceeded", "message": "Rate limit reached"})]


def main():
    b = Builder()
    b.add("low_entropy_classifier", ["low_entropy_output", "oversized_model"], low_entropy_classifier(b))
    b.add("oversized_sentiment", ["oversized_model", "low_entropy_output"], oversized_sentiment(b))
    b.add("raw_context_chat", ["raw_context"], raw_context_chat(b))
    b.add("no_cache_repeats", ["no_cache"], no_cache_repeats(b))
    b.add("unbounded_loop", ["unbounded_loop"], unbounded_loop(b))
    b.add("agent_where_chain", ["agent_where_chain"], agent_where_chain(b))
    b.add("real_reasoning", [], real_reasoning(b))
    b.add("upstream_error", [], upstream_error(b))

    with open(HERE / "events.jsonl", "w") as f:
        for e in b.events:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    (HERE / "events.labels.json").write_text(json.dumps(b.labels, ensure_ascii=False, indent=2) + "\n")
    print(f"{len(b.events)} evenements, {len(b.labels)} scenarios")


if __name__ == "__main__":
    main()
