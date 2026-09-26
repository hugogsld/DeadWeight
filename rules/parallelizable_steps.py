"""R10 — appels en série sans dépendance textuelle ni structurelle visible.

Au moins deux appels dans une trace assign_traces, sans chevauchement. On exige
contenu lisible et absence d'outils/images : leurs dépendances sont opaques.
Une réponse de moins de 20 caractères ne permet pas de conclure à l'indépendance.
Gain théorique >= 1 seconde par exécution : évite de proposer une réorganisation
négligeable. Gain d'une exécution = somme des durées horodatées - maximum ; les
pauses sont exclues.

Indépendance, entre un appel et celui qui le précède immédiatement dans la
trace : dépendant si sa requête reprend la réponse d'un appel antérieur
(casse/espaces normalisés), OU si sa conversation grandit par rapport à
l'appel précédent (plus de messages, ou un tour assistant déjà présent dans
sa requête). Un journal d'agent réel (Claude Code) donnait 313 constats sur
une seule application, un par trace, presque tous de faux positifs : les
tours d'un agent dépendent en général de l'historique de conversation, que
la réponse précédente soit reprise mot pour mot ou seulement résumée/outillée
(d'où le deuxième critère, structurel, qui ne dépend pas d'une reprise
textuelle exacte).

Un constat par application (et par modèle) : compte les exécutions et le
gain total, plutôt qu'un constat par trace qui noierait le rapport sous des
répétitions du même phénomène.

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


def dependent(es):
    """Un appel qui reprend la réponse précédente, ou dont la conversation grandit par
    rapport à l'appel précédent (plus de messages, tour assistant déjà présent)."""
    if any(text(a['response']['content']) in request_text(b) for i, b in enumerate(es) for a in es[:i]):
        return True
    for a, b in zip(es, es[1:]):
        bm = b['request']['messages']
        if len(bm) > len(a['request']['messages']) or any(m.get('role') == 'assistant' for m in bm):
            return True
    return False


def finding(code, es, title, evidence):
    ids = sorted(e['event_id'] for e in es)
    digest = hashlib.sha256(json.dumps([code, es[0]['app_id'], ids]).encode()).hexdigest()[:20]
    return dict(finding_id=f'f_{digest}_{code}', rule=code, app_id=es[0]['app_id'], model=es[0]['model'],
                template=None, severity='candidate', title=title, proven=False, event_ids=ids, evidence=evidence)


def _qualifying_traces(events):
    for es in traces(events):
        if len(es) < MIN_CALLS or not all(plain(e) for e in es):
            continue
        if any(len(text(e['response']['content'])) < MIN_RESPONSE_CHARS for e in es):
            continue
        if dependent(es):
            continue
        gain = serial_gain(es)
        if gain is None or gain < MIN_GAIN_SECONDS:
            continue
        yield es, gain


def detect(events):
    """Un constat par (application, modèle), qui regroupe toutes les traces en série indépendantes."""
    groups = defaultdict(list)
    for es, gain in _qualifying_traces(events):
        groups[(es[0]['app_id'], es[0]['model'])].append((es, gain))

    found = []
    for (_, _), items in sorted(groups.items()):
        all_events = [e for es, _ in items for e in es]
        trace_count = len(items)
        calls = sum(len(es) for es, _ in items)
        total_gain = sum(gain for _, gain in items)
        found.append(finding('parallelizable_steps', all_events,
                             f"{trace_count} exécution(s) en série ({calls} appels au total) "
                             f"pourraient être exécutées en parallèle.",
                             dict(traces=trace_count, calls=calls,
                                  estimated_latency_saving_seconds=total_gain,
                                  estimate_method='Somme des gains théoriques par exécution '
                                                  '(durées moins leur maximum, sans les pauses) ; '
                                                  'indépendance à confirmer.')))
    return found
