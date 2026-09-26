"""R17 — seconde étape qui transforme uniquement la réponse précédente.

Deux appels adjacents d'une trace assign_traces, sans erreur/outils/images,
séquentiels, même modèle (préfixe fournisseur et date de version ignorés).
Réponse précédente >= 80 caractères : éviter une coïncidence sur un mot.
La dernière consigne est une transformation explicite, <= 200 caractères hors
réponse citée ; historique antérieur identique ou réponse seule. Les verdicts
courts reconnus par R16 sont exclus, même sans intention de relecture.
Gain hypothétique : totalité du coût et de la durée du second appel seulement.
Ce plafond suppose une fusion sans surcoût de la première génération.
Angles morts : modèles proches non reconnus hors versions datées ; instructions
composées, nouvelles contraintes et nécessité métier d'une étape intermédiaire.
Absence de donnée nouvelle ne prouve pas que la qualité survit à la fusion.
"""
import re
from collections import defaultdict

from report.cost import chiffrer
from rules.llm_judge import _VERDICT
from rules.parallelizable_steps import finding, plain, request_text, text, time, traces

MIN_PREVIOUS_CHARS = 80  # Un passage substantiel rend la reprise identifiable.
MAX_INSTRUCTION_CHARS = 200  # Une courte transformation, pas un nouveau dossier.
_TRANSFORM = re.compile(r'^(?:reformule\w*|tradui\w*|extra[ci]\w*|réécri\w*|reecri\w*|translate|rewrite|rephrase|extract)\b', re.I)


def _model(name):
    return re.sub(r'-(?:\d{8}|\d{4}-\d{2}-\d{2})$', '', name.split('/')[-1])


def detect(events):
    groups = defaultdict(list)
    for es in traces(events):
        for a, b in zip(es, es[1:]):
            if not plain(a) or not plain(b) or _model(a['model']) != _model(b['model']):
                continue
            previous = text(a['response']['content'])
            if (len(previous) < MIN_PREVIOUS_CHARS or previous not in request_text(b)
                    or time(b['ts_start']) < time(a['ts_end'])):
                continue
            ms = b['request']['messages']
            if not ms or ms[-1]['role'] != 'user':
                continue
            instruction = text(ms[-1].get('content')).replace(previous, '').strip(' :\n"')
            if not _TRANSFORM.search(instruction) or len(instruction) > MAX_INSTRUCTION_CHARS:
                continue
            if _VERDICT.fullmatch((b['response']['content'] or '').strip()):
                continue
            prior = ms[:-1]
            if prior and prior[-1]['role'] == 'assistant' and text(prior[-1].get('content')) == previous:
                prior = prior[:-1]
            if prior and prior != a['request']['messages']:
                continue
            # Un changement de système apporte potentiellement une autre tâche.
            if text(a['request']['system']) != text(b['request']['system']):
                continue
            groups[(b['app_id'], b['model'])].append((a, b))
    found = []
    for _, pairs in sorted(groups.items()):
        seconds = list({b['event_id']: b for _, b in pairs}.values())
        cost = chiffrer(seconds)
        found.append(finding('mergeable_steps', seconds,
                             f'{len(seconds)} appels retravaillent une réponse qui pourrait être produite directement.',
                             dict(pairs=len(pairs),
                                  per_pair=[dict(first_event_id=a['event_id'], second_event_id=b['event_id']) for a, b in pairs],
                                  estimated_latency_saving_seconds=sum((time(b['ts_end']) - time(b['ts_start'])).total_seconds() for b in seconds),
                                  est_saving_month_usd=cost['cout_mensuel_usd'], saving_missing=cost['manquants'],
                                  estimate_method='Coût et durée du second appel ; plafond hypothétique sans surcoût de fusion.')))
    return found
