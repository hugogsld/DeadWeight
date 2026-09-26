"""D0.3 — jeu de donnees realiste, versionne (v1).

Sept jours de trafic simulé, scénarios historiques puis extensions additives. Chaque regle a au moins un cas
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
    ds.scenario("mail_triage", "mail-triage", ["low_entropy_output", "oversized_model", "duplicate_calls"], evts,
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


# ---------- R7 ----------

def reasoning_trivia(ds):
    """R7 positif : gpt-5 (raisonnement) qui reflechit longuement pour une addition en une phrase."""
    evts = []
    for i in range(40):
        a, b = RNG.randint(2, 50), RNG.randint(2, 50)
        reasoning_tok = RNG.randint(1800, 3000)
        visible_tok = RNG.randint(6, 10)
        evts.append(ds.emit(app="trivia-bot", provider="openai", model="gpt-5",
                            system="Reponds a la question de calcul avec la reponse finale uniquement.",
                            messages=[user(f"Combien font {a} + {b} ?")],
                            content=f"La reponse est {a + b}.", in_tok=40 + i,
                            out_tok=reasoning_tok + visible_tok, offset_s=spread(i, 40),
                            latency_ms=lat(2200), reasoning_tok=reasoning_tok))
    ds.scenario("reasoning_trivia", "trivia-bot", ["excess_reasoning"], evts,
                "gpt-5 : 1800-3000 tokens de raisonnement factures pour une addition en une phrase.")


def reasoning_used_well(ds):
    """Negatif R7 : gpt-5 avec un partage de raisonnement modeste et des reponses longues et variees."""
    evts = []
    for i in range(35):
        reasoning_tok = RNG.randint(150, 300)
        visible_tok = RNG.randint(500, 900)
        evts.append(ds.emit(app="analysis-bot", provider="openai", model="gpt-5",
                            system="Analyse en detail la question posee.",
                            messages=[user(f"Analyse le cas {i} : ...")],
                            content=f"[analyse detaillee {i}, plusieurs paragraphes...]",
                            in_tok=300 + i, out_tok=reasoning_tok + visible_tok,
                            offset_s=spread(i, 35, jitter=1800), latency_ms=lat(3000),
                            reasoning_tok=reasoning_tok))
    ds.scenario("reasoning_used_well", "analysis-bot", [], evts,
                "Negatif R7 : le raisonnement reste minoritaire et les reponses visibles restent longues.")


# ---------- R8 ----------

def status_poll(ds):
    """R8 positif : meme requete de statut posee 6 fois, reponse identique, fenetre courte."""
    prompt = "Quel est le statut de la commande A-1000 ?"
    answer = "Commande A-1000 : en cours de preparation."
    evts = [ds.emit(app="status-poll", provider="openai", model="gpt-4.1-mini",
                    system="Reponds au statut de la commande.", messages=[user(prompt)],
                    content=answer, in_tok=180, out_tok=14, offset_s=11000 + i * 1200,
                    latency_ms=lat(500), cached=0)
            for i in range(6)]
    ds.scenario("status_poll", "status-poll", ["duplicate_calls"], evts,
                "6 appels identiques (requete et reponse) sur ~100 minutes (chaque paire a moins "
                "d'une heure d'ecart), en dessous du seuil de taille de no_cache (R4) : 5 des 6 "
                "appels sont evitables.")


def status_poll_varies(ds):
    """Negatif R8 : meme requete mais reponse differente a chaque fois (statut qui evolue reellement)."""
    prompt = "Quel est le statut de la commande A-2000 ?"
    statuses = ["en cours de preparation", "expediee", "en transit", "livree", "annulee", "remboursee"]
    evts = [ds.emit(app="status-poll-live", provider="openai", model="gpt-4.1-mini",
                    system="Reponds au statut de la commande.", messages=[user(prompt)],
                    content=f"Commande A-2000 : {s}.", in_tok=180, out_tok=14,
                    offset_s=12000 + i * 300, latency_ms=lat(500))
            for i, s in enumerate(statuses)]
    ds.scenario("status_poll_varies", "status-poll-live", [], evts,
                "Negatif R8 : meme demande mais reponse differente a chaque fois (etat reel qui change).")


# ---------- R9 ----------

def checkout_retries(ds):
    """R9 positif : reponses tronquees (facturees) puis relancees en moins de 30 s avec succes."""
    evts = []
    for i in range(15):
        prompt = f"Resume la commande #{5000 + i} en detail."
        base = 13000 + i * 400
        evts.append(ds.emit(app="checkout-bot", provider="openai", model="gpt-4o",
                            system="Resume la commande pour le client.", messages=[user(prompt)],
                            content=f"Commande #{5000 + i} : le client a command",
                            in_tok=300 + i, out_tok=60, offset_s=base, latency_ms=lat(900),
                            finish="length", finish_raw="length", max_tokens=60))
        evts.append(ds.emit(app="checkout-bot", provider="openai", model="gpt-4o",
                            system="Resume la commande pour le client.", messages=[user(prompt)],
                            content=f"Commande #{5000 + i} : le client a commande 2 articles, "
                                    "livraison prevue sous 3 jours.",
                            in_tok=300 + i, out_tok=180, offset_s=base + 8, latency_ms=lat(1100),
                            finish="stop", finish_raw="stop"))
    ds.scenario("checkout_retries", "checkout-bot", ["paid_errors"], evts,
                "15 reponses tronquees (finish_reason=length), facturees, relancees en moins de 30 s.")


def notify_retries_unbilled(ds):
    """Negatif R9 : echecs upstream non factures (tokens absents), relances rapides mais rien double-paye."""
    evts = []
    for i in range(15):
        prompt = f"Notifie le client #{7000 + i}."
        base = 25000 + i * 300
        evts.append(ds.emit(app="notify-bot", provider="openai", model="gpt-4o", system=None,
                            messages=[user(prompt)], content=None, in_tok=None, out_tok=None,
                            offset_s=base, latency_ms=lat(150), finish="error", finish_raw=None,
                            http_status=503, error={"type": "server_error", "message": "upstream 503"}))
        evts.append(ds.emit(app="notify-bot", provider="openai", model="gpt-4o",
                            system="Notifie le client.", messages=[user(prompt)],
                            content=f"Client #{7000 + i} notifie avec succes.",
                            in_tok=120 + i, out_tok=20, offset_s=base + 5, latency_ms=lat(500),
                            finish="stop", finish_raw="stop"))
    ds.scenario("notify_retries_unbilled", "notify-bot", [], evts,
                "Negatif R9 : les echecs upstream ne sont jamais factures, malgre des relances rapides.")


# ---------- R12 ----------

def brainstorm_bot(ds):
    """R12 positif : sorties tres longues, jamais plafonnees, une reponse sur six tres au-dessus des autres."""
    evts = []
    for i in range(40):
        out = RNG.randint(2000, 3200) if i % 6 == 0 else RNG.randint(450, 750)
        evts.append(ds.emit(app="brainstorm-bot", provider="openai", model="gpt-4o",
                            system="Genere des idees de campagnes marketing, sans limite de longueur.",
                            messages=[user(f"Idees de campagne pour le produit {i} : ...")],
                            content=f"[liste d'idees {i}, {out} tokens]", in_tok=200 + i, out_tok=out,
                            offset_s=spread(i, 40, jitter=1800), latency_ms=lat(4000 + out * 3),
                            max_tokens=None))
    ds.scenario("brainstorm_bot", "brainstorm-bot", ["verbose_output"], evts,
                "40 appels gpt-4o sans max_tokens : mediane ~600 tokens, une reponse sur six depasse 2000.")


def capped_writer(ds):
    """Negatif R12 : sorties longues mais deja plafonnees (max_tokens systematique, peu de variance)."""
    evts = []
    for i in range(35):
        out = RNG.randint(480, 520)
        evts.append(ds.emit(app="capped-writer", provider="openai", model="gpt-4o-mini",
                            system="Redige un article de blog, longueur cadree.",
                            messages=[user(f"Article sur le sujet {i} : ...")],
                            content=f"[article {i}, {out} tokens]", in_tok=150 + i, out_tok=out,
                            offset_s=spread(i, 35, jitter=1800), latency_ms=lat(2500), max_tokens=520))
    ds.scenario("capped_writer", "capped-writer", [], evts,
                "Negatif R12 : max_tokens fixe et sorties homogenes, rien a plafonner davantage.")


def tool_catalogue_scenarios(ds):
    for useful in (False, True):
        app = 'focused-tools' if useful else 'wide-tools'
        tools = [{'name': f'outil{k}', 'description': 'Description détaillée. ' * 80,
                  'parameters': {'type': 'object'}} for k in range(10)]
        evts, history = [], []
        for i in range(4):
            names = range(8) if useful else [0]
            history = history + [user(f"Traite la page {i}")]
            evts.append(ds.emit(app=app, provider='openai', model='gpt-4o-mini', system='Choisis un outil.',
                                messages=history, content=None, tools=tools,
                                tool_calls=[call(f'outil{k}', {'page': i}, f'{app}-{i}-{k}') for k in names],
                                in_tok=6000, out_tok=50, offset_s=10000 + i * 10,
                                latency_ms=500, finish='tool_calls', trace=(app, 'header', i)))
            calls = evts[-1]['response']['tool_calls']
            history = history + [{'role': 'assistant', 'content': None, 'tool_calls': calls}]
            history = history + [{'role': 'tool', 'content': f'Résultat page {i}', 'tool_call_id': c['id']}
                                 for c in calls]
        ds.scenario(app, app, [] if useful else ['tool_bloat'], evts,
                    'Catalogue volumineux répété ; 8 outils utilisés sur 10.' if useful else
                    'Catalogue volumineux répété ; 9 outils jamais appelés sur 10.', {app: evts})


def batch_scenarios(ds):
    for night in (True, False):
        app = 'night-batch' if night else 'day-burst'
        evts = []
        for day in range(3):
            for i in range(10):
                evts.append(ds.emit(app=app, provider='openai', model='gpt-4o-mini', system='Résume ce produit.',
                                    messages=[user(f'Produit {day}-{i}')], content=f'Détail produit {day}-{i}',
                                    in_tok=200, out_tok=30, offset_s=day * DAY + (17 if night else 5) * 3600 + i * 2,
                                    latency_ms=500))
        ds.scenario(app, app, ['batch_eligible'] if night else [], evts,
                    'Trois rafales identiques à 02h UTC.' if night else
                    'Même régularité à 14h UTC : urgence inconnue, pas de conseil batch.')


def image_scenarios(ds):
    for short in (True, False):
        app = 'image-titles' if short else 'image-analysis'
        evts = []
        for i in range(6):
            evts.append(ds.emit(app=app, provider='gemini', model='gemini-2.5-flash', system='Analyse cette image.',
                                messages=[{'role': 'user', 'content': f'Image dossier {i}', 'n_images': 1}],
                                content=f'Titre {i}' if short else f'Analyse détaillée du dossier {i}',
                                in_tok=4096, out_tok=10 if short else 800,
                                offset_s=20000 + i * 600, latency_ms=800))
        ds.scenario(app, app, ['image_heavy'] if short else [], evts,
                    'Entrée de 4096 tokens par image, réponse courte.' if short else
                    'Même entrée, longue analyse différente : pas de conseil de réduction.')


def judge_scenarios(ds):
    for reviewing in (True, False):
        app = 'systematic-review' if reviewing else 'useful-followup'
        evts, traces = [], {}
        for i in range(6):
            tid = f'{app}-{i}'
            response = f'Document {i} : ' + 'Une réponse argumentée adaptée à la situation. ' * 4
            question = user(f'Rédige le document {i}')
            system = 'Rédige puis vérifie les réponses.' if reviewing else 'Assistant documentaire.'
            first = ds.emit(app=app, provider='openai', model='gpt-4o-mini', system=system,
                            messages=[question], content=response, in_tok=200, out_tok=100,
                            offset_s=30000 + i * 1800, latency_ms=700, trace=(tid, 'header', 0))
            second = ds.emit(app=app, provider='openai', model='gpt-4o-mini', system=system,
                             messages=[question, {'role': 'assistant', 'content': response},
                                       user('Vérifie : oui ou non ?' if reviewing else 'Développe le dernier argument.')],
                             content='OK' if reviewing else f'Explication complémentaire propre au document {i}',
                             in_tok=400, out_tok=2 if reviewing else 200,
                             offset_s=30002 + i * 1800, latency_ms=500, trace=(tid, 'header', 1))
            evts += [first, second]
            traces[tid] = [first, second]
        ds.scenario(app, app, ['llm_judge'] if reviewing else [], evts,
                    'Six générations suivies de verdicts courts.' if reviewing else
                    'Six approfondissements utiles, ni verdict ni intention de relecture.', traces)


def parallel_scenarios(ds):
    for independent in (True, False):
        app = 'serial-independent' if independent else 'serial-dependent'
        evts = []
        for i in range(4):
            messages = [user(f'Analyse le dossier distinct {i}')]
            if not independent and evts:
                messages += [{'role': 'assistant', 'content': evts[-1]['response']['content']}]
            evts.append(ds.emit(app=app, provider='openai', model='gpt-4o-mini',
                                system='Analyse documentaire.', messages=messages,
                                content=f'Conclusion argumentée et particulière pour le dossier {i}.',
                                in_tok=200, out_tok=40, offset_s=800000 + i * 3,
                                latency_ms=2000, trace=(app, 'header', i)))
        ds.scenario(app, app, ['parallelizable_steps'] if independent else [], evts,
                    'Étapes indépendantes, gain théorique de 6 secondes.' if independent else
                    'Chaque étape dépend de la conclusion précédente.', {app: evts})
        ds.scenarios[-1]['requires_header'] = True


def item_scenarios(ds):
    for short in (True, False):
        app = 'item-loop' if short else 'item-long-analysis'
        es = []
        for i in range(10):
            es.append(ds.emit(app=app, provider='openai', model='gpt-4o-mini',
                              system='Instructions communes pour analyser chaque élément. ' * 6,
                              messages=[user(f'Produit particulier numéro {i}')],
                              content=f'Analyse propre au produit {i}', in_tok=200,
                              out_tok=30 if short else 500, offset_s=810000 + i * 3, latency_ms=2000))
        ds.scenario(app, app, ['per_item_calls'] if short else [], es,
                    'Dix éléments courts, système répété.' if short else 'Analyses longues : regroupement non présumé.')


def merge_scenarios(ds):
    for transform in (True, False):
        app = 'rewrite-chain' if transform else 'research-followup'
        es, traces = [], {}
        for i in range(4):
            tid = f'{app}-{i}'
            response = f'Dossier {i} : ' + 'Le rapport expose les conclusions particulières de cette étude. ' * 3
            question = user(f'Rédige une étude sur le dossier {i}')
            a = ds.emit(app=app, provider='openai', model='gpt-4o-mini', system='Assistant de rédaction.',
                        messages=[question], content=response, in_tok=200, out_tok=80,
                        offset_s=820000 + i * 60, latency_ms=1200, trace=(tid, 'header', 0))
            b = ds.emit(app=app, provider='openai', model='gpt-4o-mini', system='Assistant de rédaction.',
                        messages=[question, {'role': 'assistant', 'content': response},
                                  user('Traduis cette réponse en anglais.' if transform else 'Cherche des éléments nouveaux sur les ventes.')],
                        content=f'Result of the detailed study for file {i}.', in_tok=300, out_tok=60,
                        offset_s=820002 + i * 60, latency_ms=1000, trace=(tid, 'header', 1))
            es += [a, b]
            traces[tid] = [a, b]
        ds.scenario(app, app, ['mergeable_steps'] if transform else [], es,
                    'Transformation seule de la réponse.' if transform else 'Nouvelle recherche, fusion non présumée.', traces)


def harness_scenarios(ds):
    for heavy in (True, False):
        app = 'heavy-harness' if heavy else 'lean-harness'
        es = []
        for i in range(24):
            es.append(ds.emit(app=app, provider='openai', model='gpt-4o-mini',
                              system='Instructions générales de traitement. ' * (150 if heavy else 5),
                              messages=[user(f'Dossier {i} avec des observations particulières.')],
                              content=f'Analyse détaillée adaptée au dossier {i}', in_tok=1700 if heavy else 200,
                              out_tok=100, cached=1000 if heavy else 0,
                              offset_s=830000 + i * 60, latency_ms=1500))
        ds.scenario(app, app, ['harness_overhead'] if heavy else [], es,
                    'Part fixe dominante, cache déjà partiellement actif.' if heavy else 'Instructions courtes, pas de surcharge dominante.')

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
    reasoning_trivia(ds)
    reasoning_used_well(ds)
    status_poll(ds)
    status_poll_varies(ds)
    checkout_retries(ds)
    notify_retries_unbilled(ds)
    brainstorm_bot(ds)
    capped_writer(ds)

    tool_catalogue_scenarios(ds)
    batch_scenarios(ds)
    image_scenarios(ds)
    judge_scenarios(ds)
    parallel_scenarios(ds)
    item_scenarios(ds)
    merge_scenarios(ds)
    harness_scenarios(ds)

    ds.events.sort(key=lambda e: e["ts_start"])
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "events.jsonl", "w") as f:
        for e in ds.events:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    (OUT / "labels.json").write_text(json.dumps(ds.scenarios, ensure_ascii=False, indent=2) + "\n")
    print(f"v1 : {len(ds.events)} evenements, {len(ds.scenarios)} scenarios")


if __name__ == "__main__":
    main()
