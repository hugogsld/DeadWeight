"""R4/levier 04 : jetons d'entrée répétés d'un gabarit déjà identique (après masquage des dates,
heures, UUID et longs nombres par rules.no_cache), au tarif de cache du même modèle. Calcul
exact (jetons enregistrés x écart de tarif du catalogue) sur les appels qui suivent le premier
de chaque gabarit (celui-ci établit le cache, rien à gagner dessus) — jamais une mesure du taux
de succès réel du cache fournisseur, que le rejeu ne peut pas observer. Activer le cache ne
change ni le modèle ni les jetons envoyés, seulement leur tarif : précision 100 % mesurée."""
import json

from optimize.propose import MESURE, _m, _pct_change
from report.cost import PRICING_PATH, lookup
from rules.no_cache import _detect_templates


def cache_prompt_proposal(finding, events):
    by_id = {e["event_id"]: e for e in events}
    templates = [f for f in _detect_templates(events)
                if f["app_id"] == finding["app_id"] and f["model"] == finding["model"]]
    prices = json.loads(PRICING_PATH.read_text(encoding="utf-8"))
    before = after = 0.0
    repeated_tokens = known = 0
    for t in templates:
        ordered = sorted((by_id[i] for i in t["event_ids"] if i in by_id), key=lambda e: e["ts_start"])
        for e in ordered[1:]:
            price = lookup(prices, e["model"])
            tin = e["usage"].get("input_tokens")
            if price is None or tin is None or "cached_in" not in price:
                continue
            known += 1
            repeated_tokens += tin
            before += tin * price["in"] / 1e6
            after += tin * price["cached_in"] / 1e6
    if not known or before <= 0:
        return None
    return {
        "type": "cache_prompt", "finding_id": finding["finding_id"], "app_id": finding["app_id"],
        "model": finding["model"],
        "changement": "Ordonner le prompt (partie fixe d'abord, variable ensuite) et activer le cache "
                      "de prompt du fournisseur.",
        "verdict": "pass", "raisons": [],
        "mesures": {
            "precision": _m(100.0, MESURE, "%",
                            "le cache ne change ni le modèle ni les jetons envoyés, seulement leur tarif"),
            "jetons_repetes": _m(repeated_tokens, MESURE, "jetons"),
            "cout": _m(_pct_change(before, after), MESURE, "%"),
        },
        "cout_usd": {"avant": before, "apres": after, "statut": MESURE},
    }
