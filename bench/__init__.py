"""M2.2 — Banc de modèles : la preuve avant la recommandation.

Rejoue un échantillon des VRAIES requêtes d'un constat (prompt système + messages) sur un
modèle candidat, et compare ses réponses à celles que le modèle d'origine avait données.
Mesure au passage ce que M2 ne peut qu'estimer : les jetons réellement facturés, réflexion
comprise, et la latence.

    python -m bench events.jsonl --finding <finding_id> --model mistralai/mistral-small-3.2-24b-instruct --route Mistral

- Même normalisation que R1, même seuil que D3.2 (95 %). Réponses libres (plus de
  MAX_DISTINCT sorties différentes) : une comparaison exacte n'a pas de sens, verdict
  « non_mesurable » plutôt qu'un faux taux.
- Échantillon réparti sur toutes les sorties observées, pas seulement la plus fréquente.
- Appels limités comme le rejeu D3.2 : plafond dur (proof.replay.HARD_MAX_CALLS) et
  intervalle minimal. La clé (DW_LLM_API_KEY) n'est jamais écrite ni recopiée.
- Coût mensuel mesuré = coût mensuel actuel × (coût mesuré du candidat / coût d'origine),
  sur les mêmes requêtes : report.cost projette, le banc donne le rapport.
"""
import json
import math
import time
import urllib.request
from collections import defaultdict
from statistics import median

from proof.replay import THRESHOLD, Throttle
from report.cost import chiffrer, lookup
from rules.low_entropy import normalize

MAX_DISTINCT = 8        # comme R1 : au-delà, les sorties sont du texte libre
MIN_SAMPLE = 20         # en dessous, un taux d'accord ne veut rien dire
DEFAULT_SAMPLE = 50
MAX_DISAGREEMENTS = 5


class OpenAICompatibleBench:
    """Client /chat/completions. ``route`` : nom d'hébergeur OpenRouter à imposer (sans repli)."""

    def __init__(self, base_url, api_key, route=None):
        self.base_url, self.api_key, self.route = base_url.rstrip("/"), api_key, route

    def complete(self, model, messages):
        body = {"model": model, "messages": messages, "temperature": 0, "usage": {"include": True}}
        if self.route:
            body["provider"] = {"order": [self.route], "allow_fallbacks": False}
        request = urllib.request.Request(
            self.base_url + "/chat/completions", method="POST",
            data=json.dumps(body, ensure_ascii=False).encode(),
            headers={"Authorization": "Bearer " + self.api_key, "Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=120) as response:
            payload = json.load(response)
        usage = payload.get("usage") or {}
        details = usage.get("completion_tokens_details") or {}
        return {"content": payload["choices"][0]["message"].get("content") or "",
                "input_tokens": usage.get("prompt_tokens"), "output_tokens": usage.get("completion_tokens"),
                "reasoning_tokens": details.get("reasoning_tokens")}


def messages_of(event):
    """La requête telle que le client l'a envoyée : prompt système + messages (texte)."""
    req = event["request"]
    out = [{"role": "system", "content": req["system"]}] if req.get("system") else []
    return out + [{"role": m["role"], "content": m.get("content") or ""} for m in req.get("messages", [])
                  if m.get("role") in ("user", "assistant")]


def sample(events, size):
    """Échantillon réparti sur les sorties observées (tour à tour), ordre stable."""
    by_output = defaultdict(list)
    for e in events:
        if e.get("error") is None and e["response"].get("content") is not None:
            by_output[normalize(e["response"]["content"])].append(e)
    queues, picked = [list(v) for _, v in sorted(by_output.items(), key=lambda kv: -len(kv[1]))], []
    while len(picked) < size and any(queues):
        for q in queues:
            if q and len(picked) < size:
                picked.append(q.pop(0))
    return picked


def _p95(values):
    s = sorted(values)
    return s[math.ceil(.95 * len(s)) - 1] if s else None


def run(events, model, client, price, pricing, throttle=None, size=DEFAULT_SAMPLE, threshold=THRESHOLD):
    """Banc d'un modèle candidat sur un groupe d'appels. ``price`` : {in, out} en USD/Mtok de la route testée."""
    throttle = throttle or Throttle()
    distinct = {normalize(e["response"]["content"]) for e in events
                if e.get("error") is None and e["response"].get("content") is not None}
    result = {"modele": model, "route": getattr(client, "route", None), "n": 0, "accord": None,
              "verdict": "non_mesurable", "raisons": [], "desaccords": [], "erreurs": 0, "plafonnes": 0}
    if len(distinct) > MAX_DISTINCT:
        result["raisons"].append(f"{len(distinct)} réponses différentes : texte libre, une comparaison exacte "
                                 "ne mesure pas la qualité")
        return result

    agree, lat, cost_new, cost_old, reasoning, done = 0, [], 0.0, 0.0, [], []
    for e in sample(events, size):
        if not throttle.acquire():
            result["plafonnes"] += 1
            continue
        t0 = time.perf_counter()
        try:
            out = client.complete(model, messages_of(e))
        except Exception:  # ne jamais recopier le message : il peut contenir la clé
            result["erreurs"] += 1
            continue
        lat.append((time.perf_counter() - t0) * 1000)
        done.append(e)
        got, expected = normalize(out["content"]), normalize(e["response"]["content"])
        if got == expected:
            agree += 1
        elif len(result["desaccords"]) < MAX_DISAGREEMENTS:
            result["desaccords"].append({"event_id": e["event_id"], "attendu": expected, "obtenu": got[:80]})
        if out["reasoning_tokens"] is not None:
            reasoning.append(out["reasoning_tokens"])
        old_price = lookup(pricing, e["model"])
        if None in (out["input_tokens"], out["output_tokens"]) or old_price is None \
                or e["usage"].get("input_tokens") is None or e["usage"].get("output_tokens") is None:
            cost_new = None  # un appel non chiffrable : pas de coût mesuré du tout
        if cost_new is not None:
            cost_new += (out["input_tokens"] * price["in"] + out["output_tokens"] * price["out"]) / 1e6
            cost_old += (e["usage"]["input_tokens"] * old_price["in"] + e["usage"]["output_tokens"] * old_price["out"]) / 1e6

    n = len(done)
    result.update(n=n, latence_p50_ms=round(median(lat), 1) if lat else None,
                  latence_p95_ms=round(_p95(lat), 1) if lat else None,
                  jetons_reflexion_moyens=round(sum(reasoning) / len(reasoning), 1) if reasoning else None)
    if n < MIN_SAMPLE:
        result["raisons"].append(f"{n} réponse(s) obtenue(s), il en faut au moins {MIN_SAMPLE} pour conclure")
        return result
    result["accord"] = round(agree / n, 4)
    before = chiffrer(events, pricing)["cout_mensuel_usd"]
    if cost_new is not None and cost_old > 0 and before is not None:
        result["cout_mensuel_mesure_usd"] = before * cost_new / cost_old
        result["facteur_mesure"] = round(cost_old / cost_new, 1) if cost_new > 0 else None
    else:
        result["cout_mensuel_mesure_usd"] = result["facteur_mesure"] = None
        result["raisons"].append("coût non mesurable (jetons ou prix manquants)")
    if result["accord"] < threshold:
        result["raisons"].append(f"accord {result['accord']:.1%} sous le seuil de {threshold:.0%}")
    result["verdict"] = "reject" if result["accord"] < threshold else "pass"
    return result
