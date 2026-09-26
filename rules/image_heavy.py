"""R15 — images coûteuses en entrée pour des réponses courtes ou répétitives.

Hypothèse commune à OpenAI, Anthropic et Gemini (pas une formule fournisseur) :
usage.input_tokens / somme(n_images) est une BORNE SUPÉRIEURE des tokens par
image, puisqu'elle inclut le texte. Aucune source tarifaire vision n'est invoquée :
ni dimensions, ni détail/résolution, ni ventilation texte/vision ne sont capturés.
Chez Anthropic l'entrée peut exclure le cache lu : des tokens manquants ne sont
pas reconstitués ; ce signal peut donc manquer des images déjà mises en cache.

>= 5 appels comparables limitent les accidents. >= 80 % doivent dépasser
2 048 tokens d'entrée par image : seuil exploratoire élevé, non limite officielle.
Le texte et les outils sont estimés à caractères / 4 ; s'ils représentent > 25 %
de l'entrée, on s'abstient (long document mêlé à une petite image).
Les sorties sont soit toutes <= 64 tokens, soit <= 3 textes distincts sur au
moins 5 appels : lecture de titres/étiquettes probable, non prouvée.

Angles morts : tokenisation différente, OCR critique, image intrinsèquement
complexe malgré réponse brève, instructions exigeant fidélité. Pas de gain en
USD inventé : une baisse de résolution doit être testée puis mesurée. Le coût
courant utilise chiffrer ; le gain reste None avec sa raison.
"""
import hashlib
import json
from collections import defaultdict
from statistics import median

from report.cost import chiffrer

MIN_CALLS = 5
MIN_HIGH_SHARE = .8
MIN_INPUT_PER_IMAGE = 2048
MAX_ESTIMATED_TEXT_SHARE = .25
CHARS_PER_TEXT_TOKEN = 4
MAX_SHORT_OUTPUT_TOKENS = 64
MAX_DISTINCT_OUTPUTS = 3


def detect(events):
    groups = defaultdict(list)
    for e in events:
        if e.get('error') is not None:
            continue
        images = sum(m.get('n_images', 0) for m in e['request']['messages'])
        if not images:
            continue
        system = ' '.join((e['request']['system'] or '').split())
        template = hashlib.sha256(system.encode()).hexdigest()[:20]
        groups[(e['app_id'], e['model'], e['provider'], template)].append((e, images))
    findings = []
    for (app, model, provider, template), rows in sorted(groups.items()):
        selected, ratios = [], []
        for e, images in sorted(rows, key=lambda row: (row[0]['ts_start'], row[0]['event_id'])):
            inputs, outputs = e['usage']['input_tokens'], e['usage']['output_tokens']
            if inputs is None or outputs is None or inputs <= 0 or e['response']['content'] is None:
                continue
            text = (e['request']['system'] or '') + '\n'.join(m.get('content') or '' for m in e['request']['messages'])
            if e['request']['tools']:
                text += json.dumps(e['request']['tools'], ensure_ascii=False)
            if len(text) / CHARS_PER_TEXT_TOKEN / inputs > MAX_ESTIMATED_TEXT_SHARE:
                continue
            if inputs / images >= MIN_INPUT_PER_IMAGE:
                selected.append(e)
                ratios.append(inputs / images)
        if len(selected) < MIN_CALLS or len(selected) / len(rows) < MIN_HIGH_SHARE:
            continue
        distinct = len({' '.join(e['response']['content'].casefold().split()) for e in selected})
        short = all(e['usage']['output_tokens'] <= MAX_SHORT_OUTPUT_TOKENS for e in selected)
        if not short and distinct > MAX_DISTINCT_OUTPUTS:
            continue
        current = chiffrer(selected)
        digest = hashlib.sha256(json.dumps([app, model, provider, template]).encode()).hexdigest()[:20]
        findings.append({
            'finding_id': f'f_{digest}_image_heavy', 'rule': 'image_heavy', 'app_id': app, 'model': model,
            'template': template, 'severity': 'candidate', 'proven': False,
            'title': (f"{len(selected)} appels avec images consomment beaucoup d'entrée pour des réponses "
                      "courtes ou répétitives : tester des images moins détaillées."),
            'event_ids': [e['event_id'] for e in selected],
            'evidence': {'calls': len(selected), 'image_calls_observed': len(rows),
                         'median_input_tokens_per_image_upper_bound': median(ratios),
                         'median_output_tokens': median(e['usage']['output_tokens'] for e in selected),
                         'distinct_outputs': distinct, 'provider': provider,
                         'image_token_estimation': 'Hypothèse : entrée totale / images, texte inclus ; pas de résolution mesurée.',
                         'cout_mensuel_usd': current['cout_mensuel_usd'], 'cost_missing': current['manquants'],
                         'est_saving_month_usd': None,
                         'saving_missing': ['Résolution et tokens visuels inconnus ; gain à mesurer par rejeu.']},
        })
    return findings
