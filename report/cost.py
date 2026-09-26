"""Chiffrage D2.5, sans réseau ni dépendance externe.

chiffrer(events, pricing=None) charge fixtures/pricing.json par défaut.
Les tarifs sont en USD / million de tokens, comme collector/pricing.py.
Une entrée peut en plus fournir ``cached_in`` : aucun rabais n'est inféré.
"""
import json
import math
import re
from datetime import datetime
from pathlib import Path
from statistics import median

PRICING_PATH = Path(__file__).resolve().parents[1] / 'fixtures' / 'pricing.json'
MONTH_SECONDS = 30 * 24 * 60 * 60
# suffixes de version datée : claude-sonnet-4-5-20250929, gpt-4o-2024-08-06, gemini-2.0-flash-001
_DATED = re.compile(r"(-\d{8}|-\d{4}-\d{2}-\d{2}|@\d{8}|-0\d\d)$")


def lookup(prices, model):
    """Prix d'un modèle tel que l'appelle le client : nom exact, sans préfixe
    fournisseur, puis sans suffixe de date. None si inconnu."""
    if not model:
        return None
    for name in (model, model.split("/", 1)[-1]):
        if name in prices:
            return prices[name]
        base = _DATED.sub("", name)
        if base != name and base in prices:
            return prices[base]
    return None


def chiffrer(events, pricing=None):
    """Retourne coût mensuel projeté, médiane, p95, comptes et manquants.

    Entrée : événements au schéma v1. ``nb_appels`` et les latences incluent
    les erreurs ; ``nb_erreurs`` les compte séparément. Leur coût est exclu.
    Fenêtre : min(ts_start) à max(ts_end), erreurs incluses, ordre indifférent.
    P95 : rang supérieur (ceil(0.95 * n)), sans interpolation.

    Coût null si un appel réussi n'est pas chiffrable, aucun appel ne réussit,
    ou la durée n'est pas positive. Les autres mesures restent disponibles.
    Le cache absent est optionnel ; explicite mais null, il est inconnu.
    OpenAI/Gemini incluent le cache dans input_tokens ; Anthropic le sépare
    (voir schemas/EVENT.md). ``cached_in`` est requis pour un cache positif.
    """
    events = list(events)
    if pricing is None:
        pricing = json.loads(PRICING_PATH.read_text(encoding='utf-8'))
    # Même construction des alias que collector/pricing.py, sans importer
    # son script (qui déclenche une requête réseau et écrit out/pricing.json).
    prices = dict(pricing)
    for model, price in pricing.items():
        if '/' in model:
            prices.setdefault(model.split('/', 1)[1], price)

    missing = []
    latencies = sorted(e['latency_ms'] for e in events)
    errors = sum(e['error'] is not None for e in events)
    result = {
        'cout_mensuel_usd': None,
        'latence_mediane_ms': median(latencies) if latencies else None,
        'latence_p95_ms': latencies[math.ceil(.95 * len(latencies)) - 1] if latencies else None,
        'nb_appels': len(events),
        'nb_erreurs': errors,
        'manquants': missing,
    }
    if not events:
        missing.append('aucun evenement : cout et latences indisponibles')
        return result

    start = min(datetime.fromisoformat(e['ts_start'].replace('Z', '+00:00')) for e in events)
    end = max(datetime.fromisoformat(e['ts_end'].replace('Z', '+00:00')) for e in events)
    duration = (end - start).total_seconds()
    if duration <= 0:
        missing.append('duree observation non positive : projection mensuelle impossible')
    if errors == len(events):
        missing.append('aucun appel reussi : cout indisponible')

    costs = []
    for e in events:
        if e['error'] is not None:
            continue
        reasons = []
        usage = e['usage']
        for field in ('input_tokens', 'output_tokens', 'cached_input_tokens'):
            if (field != 'cached_input_tokens' or field in usage) and usage.get(field) is None:
                reasons.append(f'usage.{field} inconnu')
        model = e['model']
        price = lookup(prices, model)
        if price is None:
            reasons.append(f'modele absent du catalogue : {model}')
        else:
            fields = ['in', 'out']
            cached = usage.get('cached_input_tokens')
            if cached is not None and cached > 0:
                fields.append('cached_in')
            for field in fields:
                rate = price.get(field)
                if (isinstance(rate, bool) or not isinstance(rate, (int, float))
                        or not math.isfinite(rate) or rate < 0):
                    reasons.append(f'tarif {field} absent ou invalide pour {model}')
        cached = usage.get('cached_input_tokens')
        inputs = usage['input_tokens']
        if (e['provider'] != 'anthropic' and cached is not None
                and inputs is not None and cached > inputs):
            reasons.append('cached_input_tokens depasse input_tokens')
        if reasons:
            missing.extend(f"{e['event_id']}: {reason}" for reason in reasons)
            continue
        input_cost = inputs * price['in']
        if cached is not None and cached > 0:
            if e['provider'] != 'anthropic':
                input_cost -= cached * price['in']
            input_cost += cached * price['cached_in']
        costs.append((input_cost + usage['output_tokens'] * price['out']) / 1_000_000)
    if not missing:
        result['cout_mensuel_usd'] = math.fsum(costs) * MONTH_SECONDS / duration
    return result
