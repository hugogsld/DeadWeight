"""R11 — traitement unitaire répétitif, regroupement à essayer.

Même application/modèle/instructions exactes, >= 8 appels : écarter une poignée
normale d'interactions. Une trace explicite ou une rafale (écart <= 10 s entre
fins/débuts) suffit. Un seul message utilisateur, sans outils/images/historique,
<= 512 caractères, sortie <= 64 jetons, >= 80 % d'entrées distinctes.
Instructions >= 64 jetons estimés : gain de répétition suffisamment substantiel.
Estimation hypothétique : ceil(caractères système / 4), répétés N-1 fois.
Coût via chiffrer avant/après, mêmes dates, sorties inchangées, entrée plafonnée.
Cache positif/inconnu : attribution impossible, gain financier inconnu.
Latence : somme des durées - maximum uniquement en série ; hypothèse de lot
parallèle, pas prédiction de la durée d'un unique appel groupé.
Angles morts : contraintes de confidentialité, délai, limite de contexte et
qualité d'un lot inconnus. Similarité du système ne prouve pas un même métier.
"""
import math
from collections import defaultdict

from gateway.traces import assign_traces
from report.cost import chiffrer
from rules.parallelizable_steps import finding, plain, serial_gain, text, time

MIN_CALLS = 8  # Assez de répétitions pour amortir un regroupement.
MAX_GAP_SECONDS = 10  # Rafale serrée, pas des utilisateurs séparés dans la journée.
MAX_INPUT_CHARS = 512  # Un élément court peut raisonnablement rejoindre un lot.
MAX_OUTPUT_TOKENS = 64  # Éviter les générations longues difficiles à regrouper.
MIN_DISTINCT_SHARE = .8  # Les doublons exacts relèvent plutôt du cache de réponse.
MIN_SYSTEM_TOKENS = 64  # La répétition doit représenter un volume utile à retirer.


def detect(events):
    groups = defaultdict(list)
    for e in assign_traces(sorted(events, key=lambda e: (e['ts_start'], e['event_id']))):
        ms = e['request']['messages']
        out = e['usage']['output_tokens']
        if (not plain(e) or len(ms) != 1 or ms[0]['role'] != 'user'
                or not text(ms[0].get('content')) or len(ms[0]['content']) > MAX_INPUT_CHARS
                or out is None or out > MAX_OUTPUT_TOKENS):
            continue
        system = e['request']['system'] or ''
        if math.ceil(len(system) / 4) < MIN_SYSTEM_TOKENS:
            continue
        groups[(e['app_id'], e['model'], e['provider'], system, e['trace']['id'])].append(e)
    batches = []
    for key, es in sorted(groups.items(), key=lambda pair: str(pair[0])):
        if key[-1] is not None:
            batches.append(es)
            continue
        current = []
        for e in es:
            if current and (time(e['ts_start']) - time(current[-1]['ts_end'])).total_seconds() > MAX_GAP_SECONDS:
                batches.append(current)
                current = []
            current.append(e)
        batches.append(current)
    found = []
    for es in batches:
        if len(es) < MIN_CALLS:
            continue
        share = len({text(e['request']['messages'][0]['content']) for e in es}) / len(es)
        if share < MIN_DISTINCT_SHARE:
            continue
        fixed = math.ceil(len(es[0]['request']['system']) / 4)
        before = chiffrer(es)
        missing = list(before['manquants'])
        saving = None
        if any(e['usage'].get('cached_input_tokens') != 0 for e in es):
            missing.append('Attribution du cache aux instructions inconnue.')
        if not missing:
            reduced = [es[0]] + [{**e, 'usage': {**e['usage'], 'input_tokens': max(0, e['usage']['input_tokens'] - fixed)}}
                                 for e in es[1:]]
            after = chiffrer(reduced)
            missing.extend(after['manquants'])
            if after['cout_mensuel_usd'] is not None:
                saving = before['cout_mensuel_usd'] - after['cout_mensuel_usd']
        found.append(finding('per_item_calls', es,
                             f'{len(es)} éléments courts sont traités séparément avec les mêmes instructions.',
                             dict(calls=len(es), distinct_input_share=share,
                                  estimated_repeated_system_tokens=fixed * (len(es) - 1),
                                  estimate_method='Caractères système / 4 arrondis au supérieur, multipliés par N−1 ; hypothèse de lot.',
                                  estimated_latency_saving_seconds=serial_gain(es),
                                  est_saving_month_usd=saving, saving_missing=missing)))
    return found
