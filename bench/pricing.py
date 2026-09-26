"""Cout par 1000 appels, a partir du meme catalogue que report/cost.py.

La construction des alias sans prefixe fournisseur duplique proof.replay._prices
(nom prive d'un autre module) plutot que d'en dependre : le banc reste appelable
sans connaitre les details internes de proof.replay.
"""
import json
from pathlib import Path

from report.cost import PRICING_PATH, lookup


def load_prices():
    pricing = json.loads(Path(PRICING_PATH).read_text(encoding='utf-8'))
    prices = dict(pricing)
    for model, price in pricing.items():
        if '/' in model:
            prices.setdefault(model.split('/', 1)[1], price)
    return prices


def cost_per_1000_calls(model, avg_input_tokens, avg_output_tokens, prices=None):
    """USD pour 1000 appels aux moyennes de jetons donnees ; None si prix ou jetons inconnus."""
    prices = load_prices() if prices is None else prices
    price = lookup(prices, model)
    if price is None or avg_input_tokens is None or avg_output_tokens is None:
        return None
    per_call = (avg_input_tokens * price['in'] + avg_output_tokens * price['out']) / 1_000_000
    return round(per_call * 1000, 4)
