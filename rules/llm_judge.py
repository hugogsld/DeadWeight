"""R16 — une deuxième lecture par LLM à presque chaque génération.

assign_traces regroupe d'abord les appels (en-tête ou historique reconstruit).
Une paire adjacente doit être séquentielle : la seconde démarre après la fin
de la première. La réponse précédente (>= 80 caractères, éviter les 'OK'
accidentels) est contenue dans la requête suivante, avec une intention de
relecture/vérification. La sortie du second est un verdict court reconnu
(oui/non, OK, note...), <= 16 tokens, sans appel d'outil.

>= 5 paires sur >= 5 traces et >= 80 % des paires comparables : une vérification
ponctuelle est légitime, on signale seulement une étape quasi systématique.
Comparables = même application, modèle du second appel et système, prédécesseur
textuel substantiel, ni erreur ni chevauchement temporel.

Gain : scénario EXPLICITE de conservation de 10 % des relectures ; 90 % du
coût chiffré des juges, pas de celui des générateurs. Rien ne garantit que cet
échantillonnage préserve la qualité. Prix/usage inconnus => gain None.

Angles morts : jugements paraphrasés ou structurés complexes, traces interrompues
par changement de système sans en-tête, contrôle réglementaire indispensable,
validation critique légitime. Une note brève n'implique pas une tâche facile.
D'où proven=False ; tester l'échantillonnage ou une règle avant tout retrait.
"""
import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime

from gateway.traces import assign_traces
from report.cost import chiffrer

MIN_PAIRS = 5
MIN_TRACES = 5
MIN_JUDGE_SHARE = .8
MIN_PREVIOUS_CHARS = 80
MAX_VERDICT_TOKENS = 16
ASSUMED_SAMPLE_SHARE = .1
_INTENT = re.compile(r'\b(?:vérifi\w*|verifi\w*|relis\w*|relect\w*|juge\w*|évalu\w*|evalu\w*|review\w*|judge\w*|score|note|valid\w*)\b', re.I)
_VERDICT = re.compile(r'(?:ok|oui|non|yes|no|valid[eé]?|invalide|approved|rejected|pass|fail|'
                      r'\d{1,3}(?:[.,]\d+)?(?:\s*/\s*(?:10|100))?)[.!]?', re.I)


def _text(value):
    return ' '.join((value or '').casefold().split())


def _time(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def detect(events):
    traces = defaultdict(list)
    for e in assign_traces(sorted(events, key=lambda e: (e['ts_start'], e['event_id']))):
        if e['trace']['id'] is not None:
            traces[(e['app_id'], e['trace']['id'])].append(e)
    groups = defaultdict(list)
    for (_, trace_id), evts in sorted(traces.items()):
        evts.sort(key=lambda e: (e['trace']['step'], e['ts_start'], e['event_id']))
        for first, second in zip(evts, evts[1:]):
            if first.get('error') is not None or second.get('error') is not None:
                continue
            previous = _text(first['response']['content'])
            if len(previous) < MIN_PREVIOUS_CHARS or _time(second['ts_start']) < _time(first['ts_end']):
                continue
            system = _text(second['request']['system'])
            template = hashlib.sha256(system.encode()).hexdigest()[:20]
            content = _text(' '.join(m.get('content') or '' for m in second['request']['messages']))
            # L'intention doit être dans les instructions, pas uniquement dans le texte à juger.
            instructions = system + ' ' + ' '.join(m.get('content') or '' for m in second['request']['messages']
                                                   if m['role'] == 'user')
            tokens = second['usage']['output_tokens']
            verdict = (second['response']['content'] or '').strip()
            judge = (previous in content and bool(_INTENT.search(instructions))
                     and tokens is not None and tokens <= MAX_VERDICT_TOKENS
                     and bool(_VERDICT.fullmatch(verdict)) and not second['response']['tool_calls'])
            groups[(second['app_id'], second['model'], template)].append((first, second, trace_id, judge))
    findings = []
    for (app, model, template), pairs in sorted(groups.items()):
        matches = [p for p in pairs if p[3]]
        n_traces = len({p[2] for p in matches})
        if len(matches) < MIN_PAIRS or n_traces < MIN_TRACES or len(matches) / len(pairs) < MIN_JUDGE_SHARE:
            continue
        judges = sorted({p[1]['event_id']: p[1] for p in matches}.values(), key=lambda e: (e['ts_start'], e['event_id']))
        cost = chiffrer(judges)
        monthly = cost['cout_mensuel_usd']
        digest = hashlib.sha256(json.dumps([app, model, template]).encode()).hexdigest()[:20]
        findings.append({
            'finding_id': f'f_{digest}_llm_judge', 'rule': 'llm_judge', 'app_id': app, 'model': model,
            'template': template, 'severity': 'candidate', 'proven': False,
            'title': (f"Dans {n_traces} conversations, un second appel relit la réponse pour rendre "
                      "un simple verdict : une vérification par échantillon est à tester."),
            'event_ids': [e['event_id'] for e in judges],
            'evidence': {'pairs': len(matches), 'comparable_pairs': len(pairs), 'traces': n_traces,
                         'judge_share': len(matches) / len(pairs),
                         'per_pair': [{'generation_event_id': a['event_id'], 'judge_event_id': b['event_id'],
                                       'trace_id': trace, 'trace_source': b['trace']['source']}
                                      for a, b, trace, _ in matches],
                         'assumed_review_sample_share': ASSUMED_SAMPLE_SHARE,
                         'est_saving_month_usd': monthly * (1 - ASSUMED_SAMPLE_SHARE) if monthly is not None else None,
                         'saving_missing': cost['manquants']},
        })
    return findings
