"""R3 : contexte croissant et réponses courtes, par conversation identifiée.

La croissance est un signal à examiner, pas une preuve que le contexte est
inutile : l'estimation compare l'entrée cumulée à un contexte de taille fixe.
"""
import hashlib
import json
from collections import defaultdict
from statistics import mean

# Quatre tours évitent de conclure à une tendance sur deux points seulement.
MIN_TURNS = 4
# Un ajout inférieur à 256 tokens/tour peut être une fluctuation ordinaire.
MIN_SLOPE_TOKENS_PER_TURN = 256
# 90 % de variance expliquée tolèrent du bruit, mais pas des sauts irréguliers.
MIN_R_SQUARED = 0.90
# Chaque réponse doit rester courte, et pas seulement la réponse moyenne.
MAX_OUTPUT_TOKENS = 256
# Au plus 10 % de sortie par entrée évitent les conversations très productives.
MAX_OUTPUT_INPUT_RATIO = 0.10


def detect(events):
    """Un finding par (app, modèle), qui regroupe les traces signalées."""
    return _merge(_detect_traces(events))


def _merge(per_trace):
    """Le rapport doit montrer un constat par application, pas une carte par conversation."""
    groups = defaultdict(list)
    for f in per_trace:
        groups[(f['app_id'], f['model'])].append(f)
    merged = []
    for (app, model), fs in sorted(groups.items()):
        slope = mean(f['evidence']['slope_tokens_per_turn'] for f in fs)
        turns = mean(f['evidence']['turns'] for f in fs)
        digest = hashlib.sha256(json.dumps([app, model]).encode()).hexdigest()[:20]
        merged.append({
            'finding_id': f'f_{digest}_raw_context', 'rule': 'raw_context', 'app_id': app,
            'model': model, 'template': None, 'severity': 'trim',
            'title': (f"Dans {len(fs)} conversation(s) d'environ {turns:.0f} tours, le texte envoyé "
                      f"augmente d'environ {slope:.0f} tokens par tour alors que les réponses restent courtes."),
            'proven': False,
            'event_ids': [i for f in fs for i in f['event_ids']],
            'evidence': {'traces': len(fs), 'mean_slope_tokens_per_turn': slope,
                         'per_trace': [f['evidence'] for f in fs]},
        })
    return merged


def _detect_traces(events):
    """Retourne un finding par (app, modèle, trace), ordonné par trace.step.

    Les traces incomplètes (étapes/tokens inconnus ou étapes dupliquées) sont
    ignorées : ni les tours ni l'usage ne sont inventés. Les erreurs sont exclues.
    """
    groups = defaultdict(list)
    for e in events:
        if e.get('error') is not None or e['trace']['id'] is None:
            continue
        groups[(e['app_id'], e['model'], e['trace']['id'])].append(e)
    findings = []
    for (app, model, trace), evts in sorted(groups.items()):
        if len(evts) < MIN_TURNS:
            continue
        if any(e['trace'].get('step') is None or
               e['usage'].get('input_tokens') is None or
               e['usage'].get('output_tokens') is None for e in evts):
            continue
        evts = sorted(evts, key=lambda e: e['trace']['step'])
        steps = [e['trace']['step'] for e in evts]
        if len(set(steps)) != len(steps):
            continue
        inputs = [e['usage']['input_tokens'] for e in evts]
        outputs = [e['usage']['output_tokens'] for e in evts]
        if any(i <= 0 or o > MAX_OUTPUT_TOKENS or o / i > MAX_OUTPUT_INPUT_RATIO
               for i, o in zip(inputs, outputs)):
            continue
        xbar, ybar = mean(steps), mean(inputs)
        sxx = sum((x - xbar) ** 2 for x in steps)
        syy = sum((y - ybar) ** 2 for y in inputs)
        if syy == 0:
            continue
        sxy = sum((x - xbar) * (y - ybar) for x, y in zip(steps, inputs))
        slope = sxy / sxx
        r_squared = sxy ** 2 / (sxx * syy)
        if slope < MIN_SLOPE_TOKENS_PER_TURN or r_squared < MIN_R_SQUARED:
            continue
        identity = json.dumps([app, model, trace], ensure_ascii=False)
        digest = hashlib.sha256(identity.encode()).hexdigest()[:20]
        estimated_share = sum(max(0, i - inputs[0]) for i in inputs) / sum(inputs)
        findings.append({
            'finding_id': f'f_{digest}_raw_context',
            'rule': 'raw_context',
            'app_id': app,
            'model': model,
            'template': None,
            'severity': 'trim',
            'title': (f"Sur {len(evts)} tours, le texte envoyé augmente d'environ "
                      f"{slope:.0f} tokens par tour alors que les réponses restent courtes."),
            'proven': False,
            'event_ids': [e['event_id'] for e in evts],
            'evidence': {
                'trace_id': trace,
                'slope_tokens_per_turn': slope,
                'r_squared': r_squared,
                'turns': len(evts),
                'first_input_tokens': inputs[0],
                'last_input_tokens': inputs[-1],
                'estimated_unused_input_share': estimated_share,
                'estimate_method': ("Somme des entrées au-delà de la taille du premier tour / "
                                    "total des entrées ; estimation du contexte potentiellement "
                                    "évitable, sans preuve de son inutilité."),
            },
        })
    return findings
