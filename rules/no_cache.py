"""R4 : prompts répétés après masquage des métadonnées volatiles.

Une répétition est un candidat à examiner : la normalisation peut masquer une
valeur métier et ne démontre pas que deux appels peuvent partager une réponse.
"""
import hashlib
import json
import re
from collections import defaultdict

# Trois appels donnent deux répétitions, plutôt qu'un simple doublon isolé.
MIN_CALLS = 3
# Cibler les contextes volumineux, pas les petits doublons de classification.
MIN_MEAN_INPUT_TOKENS = 1024
# Seule une majorité stricte d'appels en cache exclut le groupe.
CACHE_MAJORITY = 0.5
# Six chiffres distinguent les identifiants longs des petits nombres métier.
LONG_NUMBER_DIGITS = 6

_ISO = re.compile(r'\b\d{4}-\d{2}-\d{2}(?:[Tt ]\d{2}:\d{2}'
                  r'(?::\d{2}(?:[.,]\d+)?)?(?:[Zz]|[+-]\d{2}:?\d{2})?)?\b')
_TIME = re.compile(r'\b\d{2}:\d{2}(?::\d{2}(?:[.,]\d+)?)?\b')
_UUID = re.compile(r'\b[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\b', re.I)
_LONG_NUMBER = re.compile(r'\b\d{' + str(LONG_NUMBER_DIGITS) + r',}\b')


def _normalize(value):
    # Garder rôles, frontières des messages, appels d'outils et texte complet.
    if isinstance(value, str):
        for pattern, token in ((_UUID, '<UUID>'), (_ISO, '<DATE>'),
                               (_TIME, '<TIME>'), (_LONG_NUMBER, '<NUMBER>')):
            value = pattern.sub(token, value)
        return ' '.join(value.split())
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize(item) for key, item in value.items()}
    return value


def detect(events):
    """Groupe par app, modèle et empreinte de system + messages normalisés.

    Cache absent/null : compté comme inconnu, jamais comme zéro mesuré.
    Les findings restent candidats, y compris lorsque le cache est inconnu.
    """
    groups = defaultdict(list)
    for e in events:
        if e.get('error') is not None:
            continue
        prompt = _normalize({'system': e['request']['system'],
                             'messages': e['request']['messages']})
        serialized = json.dumps(prompt, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
        template = hashlib.sha256(serialized.encode()).hexdigest()
        groups[(e['app_id'], e['model'], template)].append(e)
    findings = []
    for (app, model, template), evts in sorted(groups.items()):
        if len(evts) < MIN_CALLS:
            continue
        inputs = [e['usage'].get('input_tokens') for e in evts]
        if any(value is None for value in inputs):
            continue
        if sum(inputs) / len(inputs) < MIN_MEAN_INPUT_TOKENS:
            continue
        cache = [e['usage'].get('cached_input_tokens') for e in evts]
        cached_calls = sum(value is not None and value > 0 for value in cache)
        if cached_calls / len(evts) > CACHE_MAJORITY:
            continue
        identity = json.dumps([app, model, template], ensure_ascii=False)
        digest = hashlib.sha256(identity.encode()).hexdigest()[:20]
        findings.append({
            'finding_id': f'f_{digest}_no_cache',
            'rule': 'no_cache',
            'app_id': app,
            'model': model,
            'template': template,
            'severity': 'candidate',
            'title': (f"La même demande revient {len(evts)} fois après retrait des dates et "
                      "identifiants : la possibilité de réutiliser une réponse est à vérifier."),
            'proven': False,
            'event_ids': sorted(e['event_id'] for e in evts),
            'evidence': {
                'calls': len(evts),
                'mean_input_tokens': sum(inputs) / len(inputs),
                'repetitions': len(evts) - 1,
                'cached_calls': cached_calls,
                'unknown_cache_calls': sum(value is None for value in cache),
            },
        })
    return findings
