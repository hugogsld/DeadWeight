"""R13 — définitions volumineuses et répétées, outils rarement appelés.

Par application/modèle/trace, un même catalogue doit être envoyé >= 3 fois :
un appel isolé ne démontre pas une répétition. >= 5 outils, >= 1 024 jetons
estimés par déclaration complète, >= 80 % de noms jamais appelés dans la
trace : éviter les petits catalogues et les agents qui exploitent leurs outils.

Estimation (hypothèse, pas tokenisation fournisseur) : longueur en caractères
du JSON compact UTF-8 non échappé / 4, arrondie au supérieur. On additionne
chaque envoi, pas seulement la définition unique. Les définitions jamais
utilisées servent au contrefactuel d'entrée réduite, plafonné à l'usage observé.
Le gain mensuel utilise chiffrer avant/après, mêmes dates et sorties ; il reste
inconnu si le cache est positif/inconnu (impossible d'en attribuer les jetons).

Angles morts : une trace partielle peut omettre un outil utilisé plus tard,
un outil non appelé peut être utile à la décision ; JSON et tokens réels ne
coïncident pas, notamment selon langue/fournisseur. Gain estimé, jamais prouvé.
"""
import hashlib
import json
import math
from collections import defaultdict

from gateway.traces import assign_traces
from report.cost import chiffrer

MIN_CALLS = 3
MIN_TOOLS = 5
MIN_DECLARATION_TOKENS = 1024
MIN_UNUSED_SHARE = .8
CHARS_PER_TOKEN = 4


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def _tokens(tools):
    return math.ceil(len(_json(tools)) / CHARS_PER_TOKEN) if tools else 0


def detect(events):
    traces = defaultdict(list)
    for e in assign_traces(sorted(events, key=lambda e: (e['ts_start'], e['event_id']))):
        if e.get('error') is None and e['trace']['id'] is not None:
            traces[(e['app_id'], e['trace']['id'])].append(e)
    groups = defaultdict(list)
    for (app, trace_id), evts in sorted(traces.items()):
        used = {c['name'] for e in evts for c in e['response']['tool_calls']}
        catalogues = defaultdict(list)
        for e in evts:
            tools = e['request']['tools']
            if len({t['name'] for t in tools}) >= MIN_TOOLS and _tokens(tools) >= MIN_DECLARATION_TOKENS:
                catalogues[(e['model'], _json(sorted(tools, key=lambda t: t['name'])))].append(e)
        for (model, _), repeated in sorted(catalogues.items()):
            tools = repeated[0]['request']['tools']
            unused = {t['name'] for t in tools} - used
            share = len(unused) / len({t['name'] for t in tools})
            if len(repeated) < MIN_CALLS or share < MIN_UNUSED_SHARE:
                continue
            removed = _tokens([t for t in tools if t['name'] in unused])
            groups[(app, model)].append((repeated, removed, {
                'trace_id': trace_id, 'calls': len(repeated), 'tools': len(tools),
                'unused_tools': sorted(unused), 'unused_tool_share': share,
                'estimated_tokens_per_call': _tokens(tools),
            }))
    findings = []
    for (app, model), parts in sorted(groups.items()):
        evts = [e for repeated, _, _ in parts for e in repeated]
        original = chiffrer(evts)
        missing = list(original['manquants'])
        saving = None
        if any(e['usage'].get('cached_input_tokens') != 0 for e in evts):
            missing.append('cache positif ou inconnu : coût des définitions non isolable')
        if not missing:
            reduced = [{**e, 'usage': {**e['usage'], 'input_tokens': max(0, e['usage']['input_tokens'] - removed)}}
                       for repeated, removed, _ in parts for e in repeated]
            after = chiffrer(reduced)
            missing.extend(after['manquants'])
            if after['cout_mensuel_usd'] is not None:
                saving = original['cout_mensuel_usd'] - after['cout_mensuel_usd']
        details = [detail for _, _, detail in parts]
        digest = hashlib.sha256(_json([app, model]).encode()).hexdigest()[:20]
        findings.append({
            'finding_id': f'f_{digest}_tool_bloat', 'rule': 'tool_bloat', 'app_id': app, 'model': model,
            'template': None, 'severity': 'candidate', 'proven': False,
            'title': (f"{len(evts)} appels renvoient de longues descriptions d'outils dont au moins "
                      "80 % ne sont jamais utilisés dans la conversation."),
            'event_ids': sorted(e['event_id'] for e in evts),
            'evidence': {'calls': len(evts), 'per_trace': details,
                         'unused_tool_share': min(d['unused_tool_share'] for d in details),
                         'estimated_declaration_tokens': sum(d['estimated_tokens_per_call'] * d['calls'] for d in details),
                         'token_estimation': 'Hypothèse : caractères JSON compact / 4, arrondi supérieur.',
                         'est_saving_month_usd': saving, 'saving_missing': missing},
        })
    return findings
