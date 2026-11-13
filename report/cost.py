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
# Surcouche Amazon Bedrock : tarifs estimés (source, date et réserves dans son bloc _meta).
BEDROCK_PRICING_PATH = Path(__file__).resolve().parents[1] / 'fixtures' / 'pricing.bedrock.json'
MONTH_SECONDS = 30 * 24 * 60 * 60
# En dessous d'une journée observée, une projection sur un mois n'est pas fiable : un workflow par lots
# (un récap par jour) passé deux fois en une heure serait projeté 38 fois trop haut (retour du 26/09).
MIN_WINDOW_SECONDS = 24 * 60 * 60
# Deux appels séparés par plus de 30 minutes de silence appartiennent à deux passages différents.
RUN_GAP_SECONDS = 30 * 60
# suffixes de version datée : claude-sonnet-4-5-20250929, gpt-4o-2024-08-06, gemini-2.0-flash-001
_DATED = re.compile(r"(-\d{8}|-\d{4}-\d{2}-\d{2}|@\d{8}|-0\d\d)$")


# identifiants Bedrock : ARN, préfixe de profil d'inférence (eu., us., global...), préfixe éditeur, suffixe -v1:0
_BEDROCK_ARN = re.compile(r"^arn:aws[a-z-]*:bedrock:[^:]*:[^:]*:(?:inference-profile|foundation-model)/")
_BEDROCK_PROFILE = re.compile(r"^(?:eu|us|us-gov|apac|jp|au|ca|global)\.")
_BEDROCK_PUBLISHER = re.compile(r"^(?:anthropic|amazon|meta|mistral)\.")
_BEDROCK_VERSION = re.compile(r"-v\d+(?::\d+)?$")


def bedrock_name(model):
    """Nom nu d'un identifiant Bedrock (claude-sonnet-4-5-20250929), identique si ce n'en est pas un."""
    name = _BEDROCK_ARN.sub("", model)
    name = _BEDROCK_PROFILE.sub("", name)
    name = _BEDROCK_PUBLISHER.sub("", name)
    return _BEDROCK_VERSION.sub("", name)


_DOTTED = re.compile(r"(?<![\d.])(\d)-(\d)(?!\d)")  # 5-5 -> 5.5 (un seul chiffre de chaque côté)
_DASHED = re.compile(r"(\d)\.(\d)")
_SUFFIX_NOISE = re.compile(r"(\[[^\]]*\]|:thinking|:free|:online|:extended|:nitro|-thinking)$")
_PREVIEW = re.compile(r"-(?:preview|exp|experimental)(?:-[\w.]+)*$")


def _variants(name):
    """Écritures voisines d'un même nom : tirets/points des versions, suffixes de date, -latest, aperçus."""
    seen = []
    pending = [name]
    while pending:
        cur = pending.pop(0)
        if cur in seen or not cur:
            continue
        seen.append(cur)
        pending.extend([
            _DATED.sub("", cur), _SUFFIX_NOISE.sub("", cur), _PREVIEW.sub("", cur),
            _DOTTED.sub(r"\1.\2", cur), _DASHED.sub(r"\1-\2", cur),
            re.sub(r"-latest$", "", cur),
        ])
    return seen


def lookup(prices, model):
    """Prix d'un modèle tel que l'appelle le client : nom exact, sans préfixe fournisseur (openai/, models/,
    anthropic/) ni identifiant Bedrock, puis variantes d'écriture (claude-sonnet-5-5 ou claude-sonnet-5.5,
    suffixe de date, -latest, [1m], aperçu). La casse est ignorée. None si inconnu."""
    if not model or not isinstance(model, str):
        return None
    raw = model.strip()
    for name in (raw, raw.split("/", 1)[-1], raw.rsplit("/", 1)[-1], bedrock_name(raw)):
        for candidate in (name, name.lower()):
            for variant in _variants(candidate):
                if variant in prices:
                    return prices[variant]
    return None


def scoped_price(price, model):
    """Tarif Bedrock applicable : le sous-bloc « global » pour un profil global., sinon le tarif régional (racine)."""
    name = _BEDROCK_ARN.sub("", model or "")
    if price and name.startswith("global.") and isinstance(price.get("global"), dict):
        return {**price, **price["global"]}
    return price


def _bedrock_prices():
    """Tarifs Bedrock estimés (surcouche), ou {} si le fichier est absent."""
    try:
        return json.loads(BEDROCK_PRICING_PATH.read_text(encoding='utf-8')).get('models', {})
    except (OSError, ValueError):
        return {}


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

    bedrock = _bedrock_prices()
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
        on_bedrock = 'bedrock' in (e.get('upstream') or '')
        price = (scoped_price(lookup(bedrock, model), model) if on_bedrock else None) or lookup(prices, model)
        written = usage.get('cache_write_input_tokens') or 0
        written_1h = min(usage.get('cache_write_1h_input_tokens') or 0, written)
        if price is None:
            reasons.append(f'modele absent du catalogue : {model}')
        else:
            fields = ['in', 'out']
            cached = usage.get('cached_input_tokens')
            if cached is not None and cached > 0:
                fields.append('cached_in')
            if written - written_1h > 0:
                fields.append('cache_write_in')
            if written_1h > 0:
                fields.append('cache_write_1h_in')
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
        if written - written_1h > 0:
            input_cost += (written - written_1h) * price['cache_write_in']
        if written_1h > 0:
            input_cost += written_1h * price['cache_write_1h_in']
        costs.append((input_cost + usage['output_tokens'] * price['out']) / 1_000_000)
    if not missing:
        result['cout_mensuel_usd'] = math.fsum(costs) * MONTH_SECONDS / duration
    return result


def runs(events):
    """Passages : rafales d'appels séparées par au moins RUN_GAP_SECONDS de silence."""
    starts = sorted(datetime.fromisoformat(e["ts_start"].replace("Z", "+00:00")) for e in events)
    return sum(1 for a, b in zip(starts, starts[1:]) if (b - a).total_seconds() >= RUN_GAP_SECONDS) + bool(starts)


def window_seconds(events):
    """Durée observée, du premier début au dernier fin d'appel."""
    if not events:
        return 0
    start = min(datetime.fromisoformat(e["ts_start"].replace("Z", "+00:00")) for e in events)
    end = max(datetime.fromisoformat(e["ts_end"].replace("Z", "+00:00")) for e in events)
    return (end - start).total_seconds()


def montant_economie(monthly, events):
    """Un gain en dollars, dit honnêtement : ``X $ par mois`` si la période observée couvre au moins une
    journée, sinon le gain sur la période observée, sans projection (``0.0032 $ sur 36 s observées``)."""
    if window_seconds(events) >= MIN_WINDOW_SECONDS:
        return f"{monthly:.2f} $ par mois"
    seconds = window_seconds(events)
    observed = monthly * seconds / MONTH_SECONDS
    span = ("moins d'1 s" if seconds < 1 else f"{seconds:.0f} s" if seconds < 120
            else f"{seconds / 60:.0f} min" if seconds < 3600 else f"{seconds / 3600:.1f} h")
    return f"{observed:.2g} $ sur la période observée ({span}, trop court pour une projection mensuelle)"
