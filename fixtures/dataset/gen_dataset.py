"""D0.3 — jeu de donnees realiste, versionne (v1).

Sept jours de trafic simule sur 13 applications. Chaque regle a au moins un cas
positif et un cas negatif ; les negatifs sont concus pour ressembler aux positifs
(c'est eux qui empechent un detecteur de tout condamner).

Sorties : fixtures/dataset/v1/events.jsonl et fixtures/dataset/v1/labels.json.
Deterministe (graine fixe). Relancer : python3 fixtures/dataset/gen_dataset.py
"""
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gen_events import call, event, user  # noqa: E402

OUT = Path(__file__).parent / "v1"
DAY = 86400
WEEK = 7 * DAY
RNG = random.Random(20260926)


class Dataset:
    def __init__(self):
        self.events, self.scenarios, self.n = [], [], 0

    def emit(self, **kw):
        self.n += 1
        e = event(self.n, **kw)
        e["event_id"] = f"ds_{self.n:05d}"
        self.events.append(e)
        return e

    def scenario(self, name, app, expected, events, note, traces=None):
        self.scenarios.append({
            "scenario": name, "app_id": app, "expected_rules": expected, "note": note,
            "event_ids": [e["event_id"] for e in events],
            "traces": {k: [e["event_id"] for e in v] for k, v in (traces or {}).items()},
        })


def spread(i, total, jitter=600):
    """Repartit total appels sur la semaine, avec du bruit."""
    return int(i * WEEK / total) + RNG.randint(0, jitter)


def lat(base, spread_pct=0.25):
    return round(base * (1 + RNG.uniform(-spread_pct, spread_pct)), 1)


# ---------- R1 / R2 ----------

SPAM = ["Gagnez un {x} maintenant", "PROMO -{n}% sur {x}", "Vous avez gagne {n} euros", "Offre exclusive {x}"]
FACT = ["Votre facture n°{n} est disponible", "Relance facture impayee {x}", "Avoir n°{n} sur votre compte"]
SUPP = ["Impossible de me connecter depuis {x}", "Bug sur l'export {x}", "Mon mot de passe ne marche plus ({x})"]
NOISE = {"spam": ["spam", "Spam", "SPAM", "spam.", "Spam."],
         "facture": ["facture", "Facture", "facture.", "FACTURE"],
         "support": ["support", "Support", "support.", "Support."]}
WORDS = ["iPhone", "hier", "CSV", "mars", "casino", "PDF", "lundi", "l'app", "voyage", "Excel"]


def mail_triage(ds):
    evts = []
    for i in range(400):
        label = RNG.choices(["spam", "facture", "support"], [5, 3, 2])[0]
        tpl = RNG.choice({"spam": SPAM, "facture": FACT, "support": SUPP}[label])
        mail = tpl.format(x=RNG.choice(WORDS), n=RNG.randint(10, 9999))
        evts.append(ds.emit(app="mail-triage", provider="openai", model="gpt-4o",
                            system="Classe le mail en une seule etiquette : spam, facture ou support.",
                            messages=[user(mail)], content=RNG.choice(NOISE[label]),
                            in_tok=55 + len(mail) // 4, out_tok=RNG.randint(1, 3),
                            offset_s=spread(i, 400), latency_ms=lat(620), max_tokens=5))
    ds.scenario("mail_triage", "mail-triage", ["low_entropy_output", "oversized_model"], evts,
                "Classifieur 3 sorties sur 400 appels, gpt-4o. Sorties bruitees (casse, point) : "
                "sans normalisation on compte 13 sorties au lieu de 3.")


def ticket_summary(ds):
    """Negatif R1 et R2 : petit modele, sorties courtes mais toutes differentes."""
    evts = []
    for i in range(120):
        w1, w2 = RNG.sample(WORDS, 2)
        evts.append(ds.emit(app="ticket-summary", provider="openai", model="gpt-4o-mini",
                            system="Resume le ticket en une phrase.",
                            messages=[user(f"Ticket #{4000 + i} : probleme avec {w1} apres {w2}, ...")],
                            content=f"Le client signale un souci {w1} survenu apres {w2} (ticket {4000 + i}).",
                            in_tok=RNG.randint(120, 400), out_tok=RNG.randint(14, 30),
                            offset_s=spread(i, 120), latency_ms=lat(700), temperature=0.3))
    ds.scenario("ticket_summary", "ticket-summary", [], evts,
                "Negatif R1/R2 : sorties courtes mais uniques, deja sur un petit modele.")


def reviews_opus(ds):
    evts = []
    pos = ["Chambre impeccable", "Super sejour", "Personnel adorable", "Rien a redire", "Vue magnifique"]
    neg = ["Petit dejeuner froid", "Bruit toute la nuit", "Trop cher", "Salle de bain sale", "Accueil glacial"]
    for i in range(80):
        good = RNG.random() < 0.6
        evts.append(ds.emit(app="reviews", provider="anthropic", model="claude-opus-4-1",
                            system="Reponds uniquement positif ou negatif.",
                            messages=[user(RNG.choice(pos if good else neg))],
                            content="positif" if good else "negatif", in_tok=RNG.randint(25, 60),
                            out_tok=3, offset_s=spread(i, 80), latency_ms=lat(1500),
                            finish_raw="end_turn", max_tokens=10))
    ds.scenario("reviews_opus", "reviews", ["oversized_model", "low_entropy_output"], evts,
                "Sentiment binaire sur le modele le plus cher. Modele peut etre absent du catalogue de prix : "
                "le chiffrage doit le dire, pas inventer.")


def eng_copilot(ds):
    """Negatif pour toutes les regles : gros modele justifie, vrai raisonnement, streaming."""
    evts = []
    topics = ["migration Postgres", "fuite memoire Go", "pricing SaaS", "archi evenementielle",
              "diagnostic Kubernetes", "revue de securite OAuth", "plan de tests e2e", "choix de cache"]
    for i in range(40):
        t = RNG.choice(topics)
        out = RNG.randint(350, 1400)
        evts.append(ds.emit(app="eng-copilot", provider="openai", model="gpt-4o",
                            system="Tu es un ingenieur senior.",
                            messages=[user(f"Aide-moi sur : {t}. Contexte #{i} : ...")],
                            content=f"[analyse detaillee {i} sur {t}, {out} tokens]",
                            in_tok=RNG.randint(200, 2500), out_tok=out, offset_s=spread(i, 40),
                            latency_ms=lat(9000 + out * 12), stream=True, ttft=lat(400),
                            temperature=0.7))
    ds.scenario("eng_copilot", "eng-copilot", [], evts,
                "Negatif global : raisonnement reel, sorties longues et variees. Ne doit RIEN declencher.")


# ---------- R3 ----------

def conversations(ds, app, model, expected, grow, note):
    evts, traces = [], {}
    for c in range(10):
        start = spread(c, 10, jitter=3600)
        history, conv, t_off = [], [], start
        for turn in range(8):
            t_off += RNG.randint(40, 120)
            history = history + [user(f"Question {turn + 1} (conv {c})")]
            if grow:
                messages = [user("DOCUMENT COMPLET (40 pages) ...")] + history
                in_tok = 11000 + 1700 * turn + RNG.randint(-50, 50)
            else:
                messages = history[-4:]
                in_tok = 900 + RNG.randint(-80, 80)
            answer = f"Reponse {turn + 1} a la conv {c} : [contenu specifique]"
            conv.append(ds.emit(app=app, provider="gemini", model=model,
                                system="Tu es un assistant.", messages=messages, content=answer,
                                in_tok=in_tok, out_tok=RNG.randint(30, 90),
                                offset_s=t_off,
                                latency_ms=lat(1800 + in_tok * 0.05), finish_raw="STOP",
                                trace=(f"{app}-c{c}", "header", turn), temperature=0.3))
            history = history + [{"role": "assistant", "content": answer}]
        evts += conv
        traces[f"{app}-c{c}"] = conv
    ds.scenario(app, app, expected, evts, note, traces)


# ---------- R4 ----------

FAQ = ["Resume la politique de remboursement ci-dessous : ...",
       "Liste les horaires du support ci-dessous : ...",
       "Explique les frais de livraison ci-dessous : ...",
       "Resume les CGV ci-dessous : ...",
       "Donne les etapes de retour ci-dessous : ..."]


def faq_bot(ds):
    evts = []
    for i in range(60):
        p = FAQ[i % 5]
        evts.append(ds.emit(app="faq-bot", provider="openai", model="gpt-4o-mini",
                            system="Tu es le support client.", messages=[user(p)],
                            content=f"[reponse fixe a : {p[:30]}]", in_tok=1850, out_tok=40,
                            offset_s=spread(i, 60), latency_ms=lat(900), cached=0, temperature=0.0))
    ds.scenario("faq_bot", "faq-bot", ["no_cache"], evts,
                "5 prompts exacts repetes 12 fois chacun, zero token en cache.")


def daily_report(ds):
    evts = []
    for i in range(30):
        stamp = f"2026-09-{20 + i // 5:02d}T{8 + i % 5:02d}:00:00Z"
        evts.append(ds.emit(app="daily-report", provider="openai", model="gpt-4.1-mini",
                            system=f"Genere le rapport. Horodatage : {stamp}",
                            messages=[user("Resume les KPI de la veille : [meme bloc de 3000 tokens]")],
                            content=f"[rapport {i}]", in_tok=3100, out_tok=RNG.randint(150, 250),
                            offset_s=spread(i, 30), latency_ms=lat(2400), cached=0))
    ds.scenario("daily_report_timestamp", "daily-report", ["no_cache"], evts,
                "Piege de normalisation : prompts identiques sauf un horodatage. Positif APRES normalisation.")


def kb_bot_cached(ds):
    evts = []
    for i in range(40):
        evts.append(ds.emit(app="kb-bot", provider="anthropic", model="claude-haiku-4-5",
                            system="[base de connaissance 6000 tokens, cache_control]",
                            messages=[user(f"Question client {i} : ...")],
                            content=f"[reponse {i}]", in_tok=6200, out_tok=RNG.randint(60, 200),
                            cached=6000 if i else 0, offset_s=spread(i, 40), latency_ms=lat(1100),
                            finish_raw="end_turn"))
    ds.scenario("kb_bot_cached", "kb-bot", [], evts,
                "Negatif R4 : prefixe repete mais deja en cache (cached_input_tokens > 0).")


def translate(ds):
    evts = []
    for i in range(60):
        w = RNG.sample(WORDS, 3)
        evts.append(ds.emit(app="translate", provider="gemini", model="gemini-2.5-flash",
                            system="Traduis en anglais.",
                            messages=[user(f"Phrase {i} : {' '.join(w)} ...")],
                            content=f"Sentence {i}: {' '.join(w)} ...", in_tok=RNG.randint(40, 200),
                            out_tok=RNG.randint(30, 180), offset_s=spread(i, 60),
                            latency_ms=lat(800), finish_raw="STOP"))
    ds.scenario("translate", "translate", [], evts,
                "Negatif R4 (meme gabarit, contenus tous differents) et R1 (sorties uniques).")


# ---------- R5 / R6 ----------

SEARCH = {"name": "search_docs", "parameters": {"type": "object", "properties": {"q": {"type": "string"}}}}


def agent_trace(ds, app, model, provider, steps, header, key, start, final=None):
    """steps = liste de (outil, args). final = texte de reponse finale ou None."""
    evts, messages, t_off = [], [user("Demande utilisateur")], start
    tools = [{"name": n} for n in sorted({s[0] for s in steps})] or [SEARCH]
    for i, (name, args) in enumerate(steps):
        tc = call(name, args, f"{key}_{i}")
        t_off += RNG.randint(2, 6)
        evts.append(ds.emit(app=app, provider=provider, model=model, system="Agent. Utilise les outils.",
                            messages=list(messages), content=None, tool_calls=[tc], tools=tools,
                            in_tok=700 + 180 * i, out_tok=RNG.randint(20, 45),
                            offset_s=t_off, latency_ms=lat(1200),
                            finish="tool_calls",
                            finish_raw="tool_use" if provider == "anthropic" else "tool_calls",
                            trace=(key, "header", i) if header else (None, None, None)))
        messages = messages + [{"role": "assistant", "content": None, "tool_calls": [tc]},
                               {"role": "tool", "content": "resultat", "tool_call_id": tc["id"]}]
    if final:
        evts.append(ds.emit(app=app, provider=provider, model=model, system="Agent. Utilise les outils.",
                            messages=list(messages), content=final, tools=tools,
                            in_tok=700 + 180 * len(steps), out_tok=RNG.randint(80, 200),
                            offset_s=t_off + 3, latency_ms=lat(1600),
                            finish_raw="end_turn" if provider == "anthropic" else "stop",
                            trace=(key, "header", len(steps)) if header else (None, None, None)))
    return evts


def sales_loop(ds):
    base = ["tarif entreprise", "tarifs entreprise", "tarif entreprise 2026", "tarif offre entreprise"]
    evts, traces = [], {}
    for t in range(3):
        steps = [("search_docs", {"q": RNG.choice(base)}) for _ in range(25)]
        tr = agent_trace(ds, "sales-agent", "claude-sonnet-4-5", "anthropic", steps,
                         header=(t == 0), key=f"sales-t{t}", start=spread(t, 3, 3600))
        evts += tr
        traces[f"sales-t{t}"] = tr
    ds.scenario("sales_loop", "sales-agent", ["unbounded_loop"], evts,
                "3 traces de 25 appels quasi identiques, jamais de reponse finale. "
                "1 trace avec en-tete, 2 sans (teste l'heuristique D1.4).", traces)


def research_agent(ds):
    pool = ["search_web", "read_page", "extract_table", "compute", "summarize"]
    evts, traces = [], {}
    for t in range(6):
        tools = ["search_web"] + RNG.sample(pool[1:], RNG.randint(2, 4)) + ["read_page"]
        steps = [(n, {"arg": f"{n}-{t}-{i}"}) for i, n in enumerate(tools)]
        tr = agent_trace(ds, "research-agent", "gpt-4.1", "openai", steps, header=True,
                         key=f"research-t{t}", start=spread(t, 6, 3600), final="[synthese finale]")
        evts += tr
        traces[f"research-t{t}"] = tr
    ds.scenario("research_agent", "research-agent", [], evts,
                "Negatif R5 : 4 a 6 appels d'outils qui progressent (arguments tous differents) puis une "
                "reponse finale. Negatif R6 : l'ordre des outils varie d'une trace a l'autre.", traces)


def order_chain(ds):
    evts, traces = [], {}
    for t in range(30):
        order = f"A-{1000 + t}"
        steps = [(n, {"order_id": order}) for n in ("get_order", "check_stock", "send_email")]
        tr = agent_trace(ds, "order-agent", "gpt-4.1", "openai", steps, header=False,
                         key=f"order-t{t}", start=spread(t, 30, 1800), final="Votre commande est en route.")
        evts += tr
        traces[f"order-t{t}"] = tr
    ds.scenario("order_chain", "order-agent", ["agent_where_chain"], evts,
                "30 traces sans en-tete, toujours get_order -> check_stock -> send_email puis reponse.", traces)


def travel_agent(ds):
    pool = ["search_flights", "search_hotels", "check_visa", "get_weather", "book", "ask_user"]
    evts, traces = [], {}
    for t in range(20):
        steps = [(n, {"q": f"{n}-{t}"}) for n in RNG.sample(pool, RNG.randint(2, 5))]
        tr = agent_trace(ds, "travel-agent", "claude-sonnet-4-5", "anthropic", steps, header=True,
                         key=f"travel-t{t}", start=spread(t, 20, 1800), final="[itineraire propose]")
        evts += tr
        traces[f"travel-t{t}"] = tr
    ds.scenario("travel_agent", "travel-agent", [], evts,
                "Negatif R6 : ordre et nombre d'outils varient d'une trace a l'autre, l'agent sert.", traces)


def upstream_errors(ds):
    evts = []
    for i in range(10):
        status, kind = RNG.choice([(429, "rate_limit_exceeded"), (500, "server_error"), (529, "overloaded")])
        evts.append(ds.emit(app=RNG.choice(["mail-triage", "eng-copilot", "sales-agent"]),
                            provider="openai", model="gpt-4o", system=None,
                            messages=[user("...")], content=None, in_tok=None, out_tok=None,
                            offset_s=spread(i, 10), latency_ms=lat(150), finish="error",
                            finish_raw=None, http_status=status,
                            error={"type": kind, "message": f"upstream {status}"}))
    ds.scenario("upstream_errors", "*", [], evts,
                "Erreurs fournisseur : capturees, exclues du cout, jamais comptees comme gaspillage.")


def main():
    ds = Dataset()
    mail_triage(ds)
    ticket_summary(ds)
    reviews_opus(ds)
    eng_copilot(ds)
    conversations(ds, "contract-bot", "gemini-2.5-pro", ["raw_context"], grow=True,
                  note="Contrat renvoye a chaque tour : input lineaire (+1700 tokens/tour), reponses courtes.")
    conversations(ds, "support-chat", "gemini-2.5-flash", [], grow=False,
                  note="Negatif R3 : fenetre glissante de 4 messages, input constant.")
    faq_bot(ds)
    daily_report(ds)
    kb_bot_cached(ds)
    translate(ds)
    sales_loop(ds)
    research_agent(ds)
    order_chain(ds)
    travel_agent(ds)
    upstream_errors(ds)

    ds.events.sort(key=lambda e: e["ts_start"])
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "events.jsonl", "w") as f:
        for e in ds.events:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    (OUT / "labels.json").write_text(json.dumps(ds.scenarios, ensure_ascii=False, indent=2) + "\n")
    print(f"v1 : {len(ds.events)} evenements, {len(ds.scenarios)} scenarios")


if __name__ == "__main__":
    main()
