"""R18 — instructions et outils fixes dominants pour une tâche répétitive.

>= 20 appels avec mêmes système/outils, un seul message utilisateur court et
variable (>= 80 % distincts), réponses <= 128 jetons sans appel d'outil/image.
Fixe >= 1 024 jetons estimés et >= 70 % de l'entrée : réserver le signal à une
surcharge dominante et répétée, pas aux instructions ordinaires. Estimation
hypothétique ceil((caractères système + JSON compact outils) / 4), plafonnée
à l'entrée réelle. Anthropic : entrée totale = input + cached ; autres : input.

Cache : attribution inconnue. Bornes de jetons fixes cachés :
[max(0, cache - (entrée - fixe)), min(cache, fixe)]. Coûts via chiffrer sur
ces deux scénarios, sorties nulles en coût (0 retirées explicitement), mêmes
horaires. Aucun prix absent remplacé par zéro. Les économies déjà procurées
par le cache sont comparées au coût de cette part fixe sans cache.
Le coût fixe n'est PAS une économie réalisable intégralement : les instructions
utiles restent nécessaires. Les événements signalés par R13 sont exclus.
Angles morts : tâches sémantiquement différentes sous un même système, estimation
caractères/4 selon langue, instructions indispensables, framework non identifiable.
"""
import json
import math
import os
from collections import defaultdict

from gateway.traces import assign_traces
from report.cost import chiffrer
from rules.parallelizable_steps import finding, text
from rules.tool_bloat import detect as tool_bloat

# Exiger une répétition durable, pas une courte session. DW_MIN_CALLS : seuil unique, abaissable pour
# une démo sur peu d'exécutions (défaut inchangé : 20).
MIN_CALLS = int(os.environ.get("DW_MIN_CALLS", "20"))
MIN_FIXED_TOKENS = 1024  # Surcharge substantielle, au-delà d'un système ordinaire.
MIN_FIXED_SHARE = .7  # La partie fixe doit nettement dominer les données.
MAX_OUTPUT_TOKENS = 128  # Restreindre aux tâches à résultat court.
MAX_USER_CHARS = 2048  # Écarter les longues analyses documentaires.
MIN_DISTINCT_SHARE = .8  # Les répétitions exactes relèvent du cache de réponse.


def _fixed(e):
    tools = e['request']['tools']
    declaration = json.dumps(tools, sort_keys=True, ensure_ascii=False, separators=(',', ':')) if tools else ''
    return math.ceil((len(e['request']['system'] or '') + len(declaration)) / 4)


def _bounds(es):
    variants = [[], [], []]  # cache fixe minimal, maximal, aucun cache
    totals = [0, 0]
    for e in es:
        usage = e['usage']
        cached = usage.get('cached_input_tokens')
        if cached is None:
            return None, ['Cache inconnu : répartition et coût fixe indisponibles.']
        total = usage['input_tokens'] + (cached if e['provider'] == 'anthropic' else 0)
        fixed = min(_fixed(e), total)
        low, high = max(0, cached - (total - fixed)), min(cached, fixed)
        totals[0] += low
        totals[1] += high
        for variant, cache in zip(variants, (low, high, 0)):
            variant.append({**e, 'usage': {**usage, 'input_tokens': fixed - cache if e['provider'] == 'anthropic' else fixed,
                                         'cached_input_tokens': cache, 'output_tokens': 0}})
    costs = [chiffrer(es) for es in variants]
    missing = sorted({reason for c in costs for reason in c['manquants']})
    if missing:
        return dict(estimated_cached_fixed_tokens_min=totals[0], estimated_cached_fixed_tokens_max=totals[1]), missing
    amounts = [c['cout_mensuel_usd'] for c in costs]
    return dict(estimated_cached_fixed_tokens_min=totals[0], estimated_cached_fixed_tokens_max=totals[1],
                fixed_cost_month_usd_min=min(amounts[:2]), fixed_cost_month_usd_max=max(amounts[:2]),
                cache_saving_month_usd_min=amounts[2] - max(amounts[:2]),
                cache_saving_month_usd_max=amounts[2] - min(amounts[:2])), []


def detect(events):
    events = list(events)
    excluded = {i for f in tool_bloat(events) for i in f['event_ids']}
    groups = defaultdict(list)
    for e in assign_traces(sorted(events, key=lambda e: (e['ts_start'], e['event_id']))):
        ms, usage = e['request']['messages'], e['usage']
        if (e['event_id'] in excluded or e.get('error') is not None or e['response']['tool_calls']
                or len(ms) != 1 or ms[0]['role'] != 'user' or not text(ms[0].get('content'))
                or len(ms[0]['content']) > MAX_USER_CHARS or ms[0].get('n_images', 0)
                or usage['input_tokens'] is None or usage['output_tokens'] is None
                or usage['output_tokens'] > MAX_OUTPUT_TOKENS):
            continue
        cached = usage.get('cached_input_tokens')
        if e['provider'] == 'anthropic' and cached is None:
            continue  # Le dénominateur total n'est pas connu.
        total = usage['input_tokens'] + (cached if e['provider'] == 'anthropic' else 0)
        fixed = min(_fixed(e), total)
        if fixed < MIN_FIXED_TOKENS or total <= 0 or fixed / total < MIN_FIXED_SHARE:
            continue
        key = (e['app_id'], e['model'], e['provider'], e['request']['system'],
               json.dumps(e['request']['tools'], sort_keys=True, ensure_ascii=False))
        groups[key].append(e)
    found = []
    for _, es in sorted(groups.items(), key=lambda pair: str(pair[0])):
        if len(es) < MIN_CALLS or len({text(e['request']['messages'][0]['content']) for e in es}) / len(es) < MIN_DISTINCT_SHARE:
            continue
        fixed_total = sum(min(_fixed(e), e['usage']['input_tokens'] +
                              ((e['usage'].get('cached_input_tokens') or 0) if e['provider'] == 'anthropic' else 0)) for e in es)
        input_total = sum(e['usage']['input_tokens'] +
                          ((e['usage'].get('cached_input_tokens') or 0) if e['provider'] == 'anthropic' else 0) for e in es)
        bounds, missing = _bounds(es)
        # Contrôler aussi l'usage original : un cache incohérent ne peut pas être « réparé » par les bornes.
        missing = sorted(set(missing + chiffrer(es)['manquants']))
        evidence = dict(calls=len(es), estimated_fixed_tokens=fixed_total, fixed_input_share=fixed_total / input_total,
                        fixed_cost_month_usd_min=None, fixed_cost_month_usd_max=None,
                        cache_saving_month_usd_min=None, cache_saving_month_usd_max=None,
                        estimated_cached_fixed_tokens_min=None, estimated_cached_fixed_tokens_max=None,
                        est_saving_month_usd=None, saving_missing=missing,
                        estimate_method='Caractères système et JSON outils / 4 ; attribution du cache bornée, coût fixe non intégralement évitable.')
        if bounds:
            evidence.update({k: v for k, v in bounds.items() if not missing or 'tokens' in k})
        evidence['saving_missing'].append('Part fixe utile inconnue : économie réalisable non chiffrée.')
        found.append(finding('harness_overhead', es,
                             f'{len(es)} tâches répétitives consacrent au moins 70 % de leur entrée aux instructions fixes.', evidence))
    return found
