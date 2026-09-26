"""Regle 2 — oversized_model (D2.2).

Un modele haut de gamme utilise pour une tache qu'un petit modele traiterait aussi bien :
reponses courtes, pas d'outils, entree modeste. On ne peut pas prouver l'iso-qualite sans
faire tourner le petit modele : la regle sort donc un CANDIDAT, marque non prouve.
La preuve releve du rejeu (D3.2).
"""
import copy
import json
from collections import defaultdict
from pathlib import Path
from statistics import median

from report.cost import chiffrer, lookup
from rules.low_entropy import normalize, template_of

PRICING_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "pricing.json"

# Seuil du prototype (detector/scan.py) : au-dela de 1 $/Mtok en entree, modele haut de gamme.
PREMIUM_PRICE_IN = 1.0
# Une reponse mediane de 50 tokens ou moins ne demande pas de redaction elaboree.
MAX_MEDIAN_OUTPUT_TOKENS = 50
# Au-dela de 2 000 tokens d'entree, la tache peut exiger une vraie lecture de contexte.
MAX_MEDIAN_INPUT_TOKENS = 2000
# Meme minimum que la regle 1 : en dessous, la mediane n'est pas representative.
MIN_CALLS = 30

# Repli quand le prix est inconnu : on se fie au nom, et l'evidence le dit.
PREMIUM_MARKERS = ("opus", "sonnet", "-pro", "gpt-4o", "gpt-4.1", "gpt-5", "o1", "o3")
SMALL_MARKERS = ("mini", "nano", "haiku", "flash", "lite", "small")
# Petits modeles proposes par format de requete, du moins cher au plus cher.
SMALL_BY_PROVIDER = {
    "openai": ["gpt-4.1-nano", "gpt-4o-mini", "gpt-4.1-mini"],
    "anthropic": ["claude-haiku-4-5", "claude-3-5-haiku"],
    "gemini": ["gemini-2.5-flash-lite", "gemini-2.5-flash"],
}


def _load_pricing():
    return json.loads(PRICING_PATH.read_text(encoding="utf-8"))


def is_premium(model, pricing):
    price = lookup(pricing, model)
    if price and isinstance(price.get("in"), (int, float)):
        return price["in"] >= PREMIUM_PRICE_IN
    name = model.lower()
    return not any(m in name for m in SMALL_MARKERS) and any(m in name for m in PREMIUM_MARKERS)


def suggest_model(provider, model, pricing):
    """Le moins cher de la meme famille present au catalogue, sinon le premier de la liste."""
    options = [m for m in SMALL_BY_PROVIDER.get(provider, []) if m != model]
    priced = [m for m in options if lookup(pricing, m)]
    if priced:
        return min(priced, key=lambda m: lookup(pricing, m)["in"])
    return options[0] if options else None


def _saving(evts, suggested, pricing):
    current = chiffrer(evts, pricing)
    swapped = []
    for e in evts:
        s = copy.deepcopy(e)
        s["model"] = suggested
        swapped.append(s)
    alternative = chiffrer(swapped, pricing)
    a, b = current["cout_mensuel_usd"], alternative["cout_mensuel_usd"]
    if a is None or b is None:
        reasons = sorted({m.split(": ", 1)[-1] for m in current["manquants"] + alternative["manquants"]})
        return None, reasons
    return a - b, []


def _eligible(evts):
    ok = [e for e in evts if not e.get("error") and e["usage"].get("output_tokens") is not None
          and e["usage"].get("input_tokens") is not None]
    if len(ok) < MIN_CALLS:
        return None
    if any(e["request"].get("tools") or e["response"].get("tool_calls") for e in ok):
        return None
    out_med = median(e["usage"]["output_tokens"] for e in ok)
    in_med = median(e["usage"]["input_tokens"] for e in ok)
    if out_med > MAX_MEDIAN_OUTPUT_TOKENS or in_med > MAX_MEDIAN_INPUT_TOKENS:
        return None
    return ok, out_med, in_med


def detect(events, pricing=None):
    pricing = _load_pricing() if pricing is None else pricing
    groups = defaultdict(list)
    for e in events:
        groups[(e["app_id"], e["provider"], e["model"], template_of(e))].append(e)

    findings = []
    for (app, provider, model, template), evts in sorted(groups.items()):
        if not is_premium(model, pricing):
            continue
        eligible = _eligible(evts)
        if not eligible:
            continue
        ok, out_med, in_med = eligible
        suggested = suggest_model(provider, model, pricing)
        saving, missing = _saving(ok, suggested, pricing) if suggested else (None, ["aucun modele plus petit connu"])
        distinct = len({normalize(e["response"].get("content") or "") for e in ok})
        saving_txt = (f" Économie estimée : {saving:.2f} $ par mois, non démontrée tant qu'elle n'est pas vérifiée par rejeu."
                      if saving is not None else " Économie non chiffrable (prix inconnu) et non démontrée.")
        findings.append({
            "finding_id": f"f_{app}_{template}_oversized",
            "rule": "oversized_model",
            "app_id": app,
            "model": model,
            "template": template,
            "severity": "candidate",
            "title": (f"{len(ok)} appels à {model} pour des réponses d'environ {out_med:.0f} tokens, "
                      f"sans outils : un modèle plus petit ({suggested}) ferait probablement l'affaire."
                      f"{saving_txt}"),
            "proven": False,
            "event_ids": [e["event_id"] for e in ok],
            "evidence": {
                "calls": len(ok),
                "median_output_tokens": out_med,
                "median_input_tokens": in_med,
                "distinct_outputs": distinct,
                "premium_by": "prix" if model in pricing else "nom du modele (prix inconnu)",
                "suggested_model": suggested,
                "est_saving_month_usd": saving,
                "saving_missing": missing,
            },
        })
    return findings
