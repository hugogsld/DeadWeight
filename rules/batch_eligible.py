"""R14 — rafales nocturnes régulières, candidates à une API batch.

Même application, fournisseur, modèle et système (espaces normalisés), sans
streaming. >= 10 appels par rafale : éviter la navigation interactive ordinaire.
Écart maximal 30 s entre appels, durée <= 5 min ; >= 3 rafales (2 intervalles)
espacées de 1 h à 48 h, coefficient de variation <= 10 % : indice de tâche
planifiée, pas une unique pointe de charge. Tous les appels retenus sont entre
22 h et 6 h UTC. Le schéma ne connaît ni fuseau utilisateur ni échéance : UTC
est une hypothèse explicite, jamais une mesure d'absence d'utilisateur.

Gain : 50 % du coût mensuel projeté par chiffrer pour les appels retenus,
uniquement OpenAI/Anthropic/Gemini. Remise de scénario demandée par le levier 13,
pas un prix batch vérifié pour chaque modèle ni une garantie de cumul avec le
cache. Catalogue/usage manquants => gain inconnu, raisons conservées.

Angles morts : équipes internationales, utilisateur nocturne, urgences non
streamées, modèles sans support batch, délai de traitement non acceptable.
Les requêtes batch existantes ne sont pas explicitement marquées par le schéma.
Il faut confirmer ces points avant d'appliquer : proven reste False.
"""
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from statistics import mean, pstdev

from report.cost import chiffrer

MIN_BURST_CALLS = 10
MAX_GAP_SECONDS = 30
MAX_BURST_SECONDS = 300
MIN_BURSTS = 3
MIN_INTERVAL_SECONDS = 3600
MAX_INTERVAL_SECONDS = 48 * 3600
MAX_INTERVAL_CV = .10
NIGHT_START_HOUR = 22
NIGHT_END_HOUR = 6
BATCH_PROVIDERS = {'openai', 'anthropic', 'gemini'}
BATCH_DISCOUNT = .5


def _time(event):
    return datetime.fromisoformat(event['ts_start'].replace('Z', '+00:00')).astimezone(timezone.utc)


def detect(events):
    groups = defaultdict(list)
    for e in events:
        if e.get('error') is not None or e['provider'] not in BATCH_PROVIDERS:
            continue
        if e['request']['params'].get('stream') is not False:
            continue
        system = ' '.join((e['request']['system'] or '').split())
        template = hashlib.sha256(system.encode()).hexdigest()[:20]
        groups[(e['app_id'], e['model'], e['provider'], template)].append(e)
    findings = []
    for (app, model, provider, template), evts in sorted(groups.items()):
        ordered = sorted(evts, key=lambda e: (_time(e), e['event_id']))
        bursts = []
        for e in ordered:
            if not bursts or (_time(e) - _time(bursts[-1][-1])).total_seconds() > MAX_GAP_SECONDS:
                bursts.append([])
            bursts[-1].append(e)
        bursts = [b for b in bursts if len(b) >= MIN_BURST_CALLS
                  and (_time(b[-1]) - _time(b[0])).total_seconds() <= MAX_BURST_SECONDS
                  and all(_time(e).hour >= NIGHT_START_HOUR or _time(e).hour < NIGHT_END_HOUR for e in b)]
        if len(bursts) < MIN_BURSTS:
            continue
        intervals = [(_time(b[0]) - _time(a[0])).total_seconds() for a, b in zip(bursts, bursts[1:])]
        if not all(MIN_INTERVAL_SECONDS <= gap <= MAX_INTERVAL_SECONDS for gap in intervals):
            continue
        cv = pstdev(intervals) / mean(intervals)
        if cv > MAX_INTERVAL_CV:
            continue
        selected = [e for burst in bursts for e in burst]
        cost = chiffrer(selected)
        monthly = cost['cout_mensuel_usd']
        digest = hashlib.sha256(json.dumps([app, model, provider, template]).encode()).hexdigest()[:20]
        findings.append({
            'finding_id': f'f_{digest}_batch_eligible', 'rule': 'batch_eligible', 'app_id': app, 'model': model,
            'template': template, 'severity': 'candidate', 'proven': False,
            'title': (f"{len(selected)} appels reviennent en {len(bursts)} rafales nocturnes régulières : "
                      "un traitement différé à moitié prix est à vérifier."),
            'event_ids': [e['event_id'] for e in selected],
            'evidence': {'calls': len(selected), 'bursts': len(bursts), 'burst_sizes': [len(b) for b in bursts],
                         'interval_seconds': intervals, 'interval_cv': cv, 'timezone_assumption': 'UTC',
                         'provider': provider, 'assumed_discount': BATCH_DISCOUNT,
                         'est_saving_month_usd': monthly * BATCH_DISCOUNT if monthly is not None else None,
                         'saving_missing': cost['manquants'],
                         'eligibility_unverified': 'Absence d’utilisateur, délai et modèle batch à confirmer.'},
        })
    return findings
