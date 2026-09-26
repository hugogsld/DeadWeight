"""R10 — appels en série sans dépendance textuelle visible.

Au moins deux appels dans une trace assign_traces, sans chevauchement et
sans reprise d'aucune réponse antérieure (casse/espaces normalisés). On exige
contenu lisible et absence d'outils/images : leurs dépendances sont opaques.
Une réponse de moins de 20 caractères ne permet pas de conclure à l'indépendance.
Gain théorique >= 1 seconde : évite de proposer une réorganisation négligeable.
Gain = somme des durées horodatées - maximum ; les pauses sont exclues.

Angles morts : dépendances métier externes, paraphrases, quotas et concurrence
réelle inconnus. Ce gain n'est donc ni garanti ni une borne minimale prouvée.
Une trace mixte est ignorée, choix conservateur ; sans en-tête, les appels
indépendants ne peuvent généralement pas être regroupés. Aucun gain financier.
"""
import hashlib
import json
from collections import defaultdict
from datetime import datetime

from gateway.traces import assign_traces

MIN_CALLS = 2  # Deux étapes suffisent à former un travail parallèle.
MIN_RESPONSE_CHARS = 20  # Écarter les réponses trop ambiguës, telles que « OK ».
MIN_GAIN_SECONDS = 1  # Une seconde rend la piste sensible à l'échelle d'un workflow.


def text(value):
    return ' '.join((value or '').casefold().split())


def time(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def traces(events):
    groups = defaultdict(list)
    for e in assign_traces(sorted(events, key=lambda e: (e['ts_start'], e['event_id']))):
        if e['trace']['id'] is not None:
            groups[(e['app_id'], e['trace']['id'])].append(e)
    return [sorted(es, key=lambda e: (e['trace']['step'], e['ts_start'], e['event_id']))
            for _, es in sorted(groups.items())]


def request_text(e):
    return text((e['request']['system'] or '') + ' ' + ' '.join(
        m.get('content') or '' for m in e['request']['messages']))


def plain(e):
    return (e.get('error') is None and not e['request']['tools'] and not e['response']['tool_calls']
            and not any(m.get('n_images', 0) for m in e['request']['messages'])
            and bool(request_text(e)) and bool(text(e['response']['content'])))


def serial_gain(es):
    if any(time(b['ts_start']) < time(a['ts_end']) for a, b in zip(es, es[1:])):
        return None
    durations = [(time(e['ts_end']) - time(e['ts_start'])).total_seconds() for e in es]
    if not durations or min(durations) < 0:
        return None
    return sum(durations) - max(durations)


def finding(code, es, title, evidence):
    ids = sorted(e['event_id'] for e in es)
    digest = hashlib.sha256(json.dumps([code, es[0]['app_id'], ids]).encode()).hexdigest()[:20]
    return dict(finding_id=f'f_{digest}_{code}', rule=code, app_id=es[0]['app_id'], model=es[0]['model'],
                template=None, severity='candidate', title=title, proven=False, event_ids=ids, evidence=evidence)


def detect(events):
    found = []
    for es in traces(events):
        if len(es) < MIN_CALLS or not all(plain(e) for e in es):
            continue
        if any(len(text(e['response']['content'])) < MIN_RESPONSE_CHARS for e in es):
            continue
        if any(text(a['response']['content']) in request_text(b)
               for i, b in enumerate(es) for a in es[:i]):
            continue
        gain = serial_gain(es)
        if gain is None or gain < MIN_GAIN_SECONDS:
            continue
        found.append(finding('parallelizable_steps', es,
                             f'{len(es)} étapes en série pourraient être exécutées en parallèle.',
                             dict(calls=len(es), trace_id=es[0]['trace']['id'],
                                  estimated_latency_saving_seconds=gain,
                                  estimate_method='Somme des durées moins leur maximum, sans les pauses ; indépendance à confirmer.')))
    return found
