"""R19 — context_reread : chaque appel relit (presque) toute la conversation.

Niveau 1 STRICT : seuls les champs d'usage (jetons entrée/cache/sortie), le
modèle, le fournisseur, ``app_id`` et l'identifiant de trace/session (donné
par le client, jamais déduit du contenu) sont lus. Aucun message, aucune
réponse, aucun outil déclaré n'est inspecté : cette règle doit rester
utilisable avec un simple export d'usage plus un identifiant de session,
sans capture de contenu (docs/analyser-un-workflow.md, niveau 1).

Cas réels qui ont motivé la règle : un agent de code où chaque appel relit
environ 290 000 jetons de conversation (72 % du coût), 59 000 jetons dès le
premier appel de la session ; un autre où le cache (écriture + lecture)
représente 66 % du coût, avec environ 185 000 jetons relus par appel sur
~43 appels. Aucune règle existante ne les repère (voir plus bas).

Par (application, modèle), on regroupe les appels en sessions via
``trace.id`` déjà posé par le client ou le connecteur (en-tête, ou
identifiant de session du journal Claude Code/Codex) — jamais reconstruit à
partir du contenu (``gateway.traces.assign_traces`` ne serait pas niveau 1).
Une session sans identifiant de trace est invisible pour cette règle : angle
mort assumé, signalé dans les manquants plutôt que corrigé par une
heuristique de contenu.

Contexte d'un appel = jetons d'entrée réellement transmis au modèle ce
tour-ci. Chez OpenAI et Gemini, le cache est un sous-ensemble de
``input_tokens`` (déjà compté) ; chez Anthropic, ``cached_input_tokens`` est
disjoint et s'ajoute (même convention que ``rules/harness_overhead.py``).

Seuils, avec le raisonnement :

- MIN_SESSION_LEN_FOR_COUNT = 2 : un appel isolé n'a encore rien relu.
- MIN_SESSIONS = 2 : une session unique, aussi longue soit-elle, peut être un
  incident isolé. Au moins deux sessions montrent un mode de fonctionnement
  durable de l'application, pas un pic ponctuel.
- MIN_CALLS_PER_SESSION = 8 : une conversation courte (quelques échanges) est
  un usage normal de chat ; les cas réels tournent autour de 40 à 45 appels
  par session. Huit appels est un plancher bas qui laisse passer les usages
  courts, et exige une répétition réelle avant de conclure à une surcharge.
- MIN_MEDIAN_CONTEXT_TOKENS = 8192 : sous ce volume, même relu intégralement
  à chaque tour, le contexte ne domine pas la facture face à des sorties
  ordinaires. Les cas réels sont à 59 000 (premier appel) et 185 000 à
  290 000 (régime établi) : 8192 est délibérément bas pour rester un plancher,
  pas un seuil calé sur les deux cas connus.
- STAY_OR_GROW_RATIO = 0.8 : le contexte médian du dernier appel de chaque
  session doit rester au moins à 80 % du contexte médian du premier appel.
  En dessous, une compaction ou un résumé réduit déjà le contexte : ce n'est
  plus le problème que cette règle vise, la baisse serait alors un faux
  positif qu'on préfère écarter.
- MIN_CONTEXT_COST_SHARE = 0.5 : le contexte (entrée + cache) doit représenter
  la majorité du coût, pas seulement du volume de jetons — le cache est
  souvent facturé moins cher que l'entrée neuve ou la sortie. Les deux cas
  réels mesurent 72 % et 66 % ; 50 % est délibérément sous les deux pour ne
  pas caler le seuil sur les cas qui ont motivé la règle.

Coût du contexte : chiffrer(session) une fois tel quel, une fois avec les
jetons de sortie mis à zéro (même procédé que ``rules/harness_overhead.py``
pour isoler une part du coût) ; la part = coût sans sortie / coût total. Si
un prix manque, la part reste inconnue et la règle ne se déclenche pas : on
ne prétend pas qu'un coût domine sans pouvoir le chiffrer.

Économie : estimation, jamais une garantie. On calcule la fraction du
contexte médian qui dépasse le contexte du premier appel de la session
(``1 - premier / médian``, bornée à 0) et on l'applique au coût du contexte :
c'est le volume qui disparaîtrait si chaque session restait à la taille de
son premier appel (fenêtre glissante ou compaction agressive), pas une
promesse de résultat.

Pourquoi ça ne double-compte pas R3 (raw_context) : R3 mesure la pente de
``usage.input_tokens`` seul sur UNE trace, avec sortie plafonnée à 256 jetons
et à 10 % de l'entrée — pensé pour un chat classique à réponses courtes. Chez
Anthropic, la croissance du contexte relu passe surtout par
``cached_input_tokens`` (disjoint de ``input_tokens``) : R3 ne la voit pas.
R19 agrège aussi plusieurs sessions par application (R3 note une trace à la
fois) et n'impose aucune limite sur la longueur des réponses : un agent de
code répond longuement, R3 l'exclurait, R19 continue de mesurer le contexte.

Pourquoi ça ne double-compte pas R18 (harness_overhead) : R18 lit le texte du
système et des outils déclarés (niveau 2, un contenu réel) pour estimer une
surcharge FIXE sur des tâches à un seul message utilisateur et une sortie
courte (<=128 jetons) répétées à l'identique (classification, extraction...).
R19 ne lit aucun contenu, cible des sessions d'AU MOINS 8 tours (R18 exige
exactement 1 message utilisateur par appel) et mesure un contexte qui
CROÎT ou reste large au fil des tours, pas une part fixe et stable. Les deux
conditions de forme (1 tour vs 8+ tours) sont structurellement disjointes.

Angles morts : une session sans identifiant de trace transmis par le client
est invisible (aucune reconstruction par contenu, volontairement, pour rester
niveau 1) ; chez OpenAI/Gemini la part de coût mesurée est celle du contexte
total, pas isolément celle du cache (le fournisseur ne sépare pas les deux) ;
une session qui compacte fortement en cours de route mais reste malgré tout
volumineuse en moyenne peut échapper au filtre STAY_OR_GROW_RATIO ; le calcul
ne regarde que le premier et le dernier appel de chaque session, pas la forme
entière de la courbe.
"""
import hashlib
import json
from collections import defaultdict
from statistics import median

from report.cost import chiffrer

MIN_SESSION_LEN_FOR_COUNT = 2
MIN_SESSIONS = 2
MIN_CALLS_PER_SESSION = 8
MIN_MEDIAN_CONTEXT_TOKENS = 8192
STAY_OR_GROW_RATIO = 0.8
MIN_CONTEXT_COST_SHARE = 0.5


def _context_tokens(e):
    """Jetons d'entrée réellement envoyés ce tour-ci (entrée + cache si disjoint)."""
    usage = e['usage']
    input_tokens = usage.get('input_tokens')
    if input_tokens is None:
        return None
    if e['provider'] == 'anthropic':
        cached = usage.get('cached_input_tokens')
        if cached is None:
            return None
        return input_tokens + cached
    return input_tokens


def _sessions(events):
    """(app, modele, trace.id) -> [(evenement, contexte)] trie par heure. Sans en-tete : invisible."""
    groups = defaultdict(list)
    for e in events:
        if e.get('error') is not None or e['trace']['id'] is None:
            continue
        ctx = _context_tokens(e)
        if ctx is None:
            continue
        groups[(e['app_id'], e['model'], e['trace']['id'])].append((e, ctx))
    for key in groups:
        groups[key].sort(key=lambda pair: (pair[0]['ts_start'], pair[0]['event_id']))
    return groups


def _context_cost_share(session_events):
    """Part du coût du contexte (entree + cache) sur le cout total, sorties mises a zero."""
    total = chiffrer(session_events)
    context_only = [{**e, 'usage': {**e['usage'], 'output_tokens': 0}} for e in session_events]
    context = chiffrer(context_only)
    if total['cout_mensuel_usd'] is None or context['cout_mensuel_usd'] is None or total['cout_mensuel_usd'] <= 0:
        return None, None
    return context['cout_mensuel_usd'] / total['cout_mensuel_usd'], context['cout_mensuel_usd']


def finding(app, model, ids, title, evidence):
    digest = hashlib.sha256(json.dumps(['context_reread', app, model, sorted(ids)]).encode()).hexdigest()[:20]
    return dict(finding_id=f'f_{digest}_context_reread', rule='context_reread', app_id=app, model=model,
                template=None, severity='trim', title=title, proven=False, event_ids=sorted(ids), evidence=evidence)


def detect(events):
    """Un constat par (application, modele) : sessions longues au contexte dominant et durable."""
    sessions = _sessions(events)
    by_app = defaultdict(dict)
    for (app, model, trace_id), pairs in sessions.items():
        if len(pairs) >= MIN_SESSION_LEN_FOR_COUNT:
            by_app[(app, model)][trace_id] = pairs

    found = []
    for (app, model), sess in sorted(by_app.items()):
        if len(sess) < MIN_SESSIONS:
            continue
        lengths = [len(v) for v in sess.values()]
        if median(lengths) < MIN_CALLS_PER_SESSION:
            continue

        all_ctx = [ctx for v in sess.values() for _, ctx in v]
        median_ctx = median(all_ctx)
        if median_ctx < MIN_MEDIAN_CONTEXT_TOKENS:
            continue

        firsts = [v[0][1] for v in sess.values()]
        lasts = [v[-1][1] for v in sess.values()]
        median_first, median_last = median(firsts), median(lasts)
        if median_last < STAY_OR_GROW_RATIO * median_first:
            continue

        session_events = [e for v in sess.values() for e, _ in v]
        share, context_cost = _context_cost_share(session_events)
        if share is None or share < MIN_CONTEXT_COST_SHARE:
            continue

        reduction_share = max(0.0, 1 - median_first / median_ctx) if median_ctx else 0.0
        estimated_saving = context_cost * reduction_share

        titre = (f"Chaque appel relit {median_ctx:,.0f} jetons de conversation : "
                 f"{share * 100:.0f} % du coût.").replace(',', ' ')
        found.append(finding(app, model, [e['event_id'] for e in session_events], titre,
            dict(sessions=len(sess), calls=len(session_events),
                 median_context_tokens=median_ctx, median_startup_context_tokens=median_first,
                 median_last_context_tokens=median_last, median_calls_per_session=median(lengths),
                 context_cost_share=share, context_cost_month_usd=context_cost,
                 est_saving_month_usd=estimated_saving,
                 estimate_method="Coût du contexte (entrée + cache, sortie mise à zéro) multiplié par la part "
                                 "du contexte médian qui dépasse le contexte du premier appel de session ; "
                                 "estimation d'une fenêtre glissante ou d'une compaction, pas une garantie.")))
    return found
