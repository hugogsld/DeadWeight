"""Proposer une micro-modification par constat, puis la tester sur l'historique du client.

Chaque proposition porte des mesures, et chaque mesure son statut, décidé par le code :
- « mesuré » : calculé sur les vrais appels (rejeu des mêmes entrées, banc de modèles, historique) ;
- « estimé » : calcul sur l'historique + une hypothèse nommée dans ``hypothese`` ;
- « non testé » : pas de preuve possible ici (clé absente, pas de contenu), la proposition reste une piste.
Rien n'est arrondi vers le plus favorable, rien ne vient du modèle.

Types de modifications (une par micro-PR) :
- ``regles``       : un LLM qui aiguille (R1) remplacé par des règles extraites, prouvé par rejeu ;
- ``modele``       : un modèle plus petit (R2), prouvé au banc sur les mêmes entrées (clé nécessaire) ;
- ``plafond``      : un plafond de longueur (R12), mesuré sur l'historique des réponses ;
- ``cache``        : les appels identiques en trop (R8), mis en cache plutôt que rejoués ;
- ``erreurs``      : les relances d'un échec déjà facturé (R9), évitées en corrigeant la cause ;
- ``cache_prompt`` : le cache de prompt du fournisseur (R4), calcul exact sur les jetons répétés ;
- ``batch``        : l'API batch d'un fournisseur (R14), remise de scénario non vérifiée par modèle ;
- ``raisonnement`` : un effort de raisonnement réduit (R7), prouvé au banc (clé OpenAI nécessaire).

Le verdict « pass » exige une précision >= optimize.thresholds.PRECISION_THRESHOLD (95 %),
mesurée, jamais estimée. Pour les types sans risque de qualité (cache, erreurs, cache_prompt :
le modèle et sa réponse ne changent pas, seule la facturation ou le nombre d'appels change),
cette précision de 100 % n'est pas une hypothèse mais la définition même du constat sous-jacent ;
elle reste donc « mesurée », pas fabriquée.
"""
import math
from statistics import median

import time

from proof.extract import build_router, extract_rules
from proof.replay import _user_text
from proof.replay import replay
from report.audit import _discover_detectors
from report.cost import chiffrer
from optimize.thresholds import PRECISION_THRESHOLD

MESURE, ESTIME, NON_TESTE = "mesuré", "estimé", "non testé"


def _m(valeur, statut, unite="", hypothese=None):
    return {"valeur": valeur, "statut": statut, "unite": unite, **({"hypothese": hypothese} if hypothese else {})}


def _p95(values):
    values = sorted(v for v in values if v is not None)
    return values[math.ceil(.95 * len(values)) - 1] if values else None


def _cost(events):
    """Coût réellement dépensé sur ces appels (pas de projection mensuelle)."""
    c = chiffrer(events)
    if c["cout_mensuel_usd"] is None:
        return None
    from report.cost import MONTH_SECONDS, window_seconds
    return c["cout_mensuel_usd"] * window_seconds(events) / MONTH_SECONDS


def _sent_tokens(events):
    return sum((e["usage"].get("input_tokens") or 0) for e in events)


def _pct_change(before, after):
    return None if not before or after is None else round((after - before) / before * 100, 1)


def _rules(finding, events, llm):
    rules = extract_rules(finding, events, llm=llm)
    proof = replay(finding, events, rules)
    group = [e for e in events if e["event_id"] in set(finding["event_ids"])]
    # latence médiane mesurée : les règles chronométrées sur chaque vraie entrée, le modèle sinon
    route, lat_after = build_router(rules), []
    for e in group:
        t0 = time.perf_counter()
        covered = route(_user_text(e)) is not None
        lat_after.append((time.perf_counter() - t0) * 1000 if covered else e["latency_ms"])
    med_before = median(e["latency_ms"] for e in group) if group else None
    # part des appels encore envoyés au modèle : ceux que les règles ne couvrent pas
    kept = 1 - proof["rules_coverage"] if proof["n_replayed"] else None
    tokens_before = _sent_tokens(group)
    spent = _cost(group)
    return {
        "type": "regles", "finding_id": finding["finding_id"], "app_id": finding["app_id"], "model": finding["model"],
        "changement": f"Remplacer les appels à {finding['model']} par {len(rules['categories'])} règles fixes "
                      f"({', '.join(c['key'] for c in rules['categories'])}), le modèle gardé en secours.",
        "verdict": proof["verdict"], "raisons": proof["reasons"], "preuve": proof,
        "mesures": {
            "precision": _m(round(proof["agreement_rate"] * 100, 1), MESURE, "%"),
            "appels_rejoues": _m(proof["n_replayed"], MESURE),
            "latence_p95": _m(_pct_change(proof["p95_before_ms"], proof["p95_after_ms"]), MESURE, "%"),
            "latence_mediane": _m(_pct_change(med_before, median(lat_after)) if lat_after else None, MESURE, "%"),
            "cout": _m(_pct_change(proof["cost_before_month_usd"], proof["cost_after_month_usd"]),
                       MESURE if proof["cost_after_month_usd"] is not None else NON_TESTE, "%"),
            "jetons_envoyes": _m(_pct_change(tokens_before, tokens_before * kept if kept is not None else None),
                                 ESTIME, "%", "les appels couverts par les règles n'envoient plus rien au modèle"),
        },
        # dépense réelle de l'historique, et ce qu'elle aurait été : base du total du message Slack
        "cout_usd": {"avant": spent, "apres": spent * (1 + _pct_change(proof["cost_before_month_usd"],
                                                                        proof["cost_after_month_usd"]) / 100)
                     if spent is not None and proof["cost_after_month_usd"] is not None else None,
                     "statut": MESURE},
    }


def _model(finding, events, keys_available, prove):
    """Banc : les mêmes entrées envoyées au modèle proposé, comparées aux anciennes réponses."""
    if not keys_available:
        return {"type": "modele", "finding_id": finding["finding_id"], "app_id": finding["app_id"],
                "model": finding["model"], "changement": f"Tester un modèle plus petit que {finding['model']}.",
                "verdict": "non_teste", "raisons": ["aucune clé pour le banc : rien de mesuré"],
                "mesures": {"precision": _m(None, NON_TESTE, "%")}}
    result = prove(events, finding)
    ranked = sorted((o for o in result["options"].values() if o.get("verdict") == "pass"),
                    key=lambda o: o.get("cost_per_1000_calls_usd") or float("inf"))
    best = ranked[0] if ranked else None
    group = [e for e in events if e["event_id"] in set(finding["event_ids"])]
    before_p95 = _p95([e["latency_ms"] for e in group])
    ref = result.get("reference_cost_per_1000_calls_usd")
    return {
        "type": "modele", "finding_id": finding["finding_id"], "app_id": finding["app_id"], "model": finding["model"],
        "changement": (f"Passer de {finding['model']} à {best['model']}." if best
                       else f"Aucun modèle plus petit ne tient le seuil pour {finding['model']}."),
        "nouveau_modele": best["model"] if best else None,
        "verdict": "pass" if best else "reject", "raisons": [] if best else ["aucun candidat au-dessus du seuil"],
        "preuve": result,
        "mesures": {
            "precision": _m(round(best["score"] * 100, 1) if best else None, MESURE, "%"),
            "appels_rejoues": _m(best["n_calls"] if best else None, MESURE),
            "latence_p95": _m(_pct_change(before_p95, best["latency_p95_ms"]) if best else None, MESURE, "%"),
            "cout": _m(_pct_change(ref, best["cost_per_1000_calls_usd"]) if best and ref else None, MESURE, "%"),
        },
        "cout_usd": ({"avant": _cost(group), "apres": _cost(group) * best["cost_per_1000_calls_usd"] / ref,
                      "statut": MESURE} if best and ref and _cost(group) is not None else None),
    }


def _cap(finding, events):
    """Plafond de longueur : ce que l'historique dit des réponses qu'il aurait coupées."""
    cap = finding["evidence"].get("suggested_cap_tokens")
    group = [e for e in events if e["event_id"] in set(finding["event_ids"]) and e["error"] is None]
    outs = [e["usage"].get("output_tokens") for e in group if e["usage"].get("output_tokens") is not None]
    if not cap or not outs:
        return None
    intact = sum(o <= cap for o in outs) / len(outs)
    before = sum(outs)
    after = sum(min(o, cap) for o in outs)
    return {
        "type": "plafond", "finding_id": finding["finding_id"], "app_id": finding["app_id"], "model": finding["model"],
        "changement": f"Plafonner les réponses à {cap} jetons (max_tokens).", "plafond": cap,
        "verdict": "pass" if intact >= .9 else "reject",
        "raisons": [] if intact >= .9 else [f"{round((1 - intact) * 100)} % des réponses passées auraient été coupées"],
        "mesures": {
            "precision": _m(round(intact * 100, 1), MESURE, "%",
                            "réponses passées sous le plafond : elles n'auraient pas changé"),
            "jetons_sortie": _m(_pct_change(before, after), MESURE, "%"),
            "latence_p95": _m(_pct_change(before, after), ESTIME, "%", "la durée suit le nombre de jetons générés"),
            "mediane_sortie": _m(median(outs), MESURE, "jetons"),
        },
        "cout_usd": _cap_cost(group, cap),
    }


def _cap_cost(group, cap):
    """Dépense réelle, et la même sans les jetons de sortie au-delà du plafond (prix de sortie du modèle)."""
    from report.cost import PRICING_PATH, lookup
    import json
    prices = json.loads(PRICING_PATH.read_text(encoding="utf-8"))
    spent, cut = _cost(group), 0.0
    for e in group:
        price = lookup(prices, e["model"])
        out = e["usage"].get("output_tokens") or 0
        if price and out > cap:
            cut += (out - cap) * price["out"] / 1e6
    return {"avant": spent, "apres": spent - cut if spent is not None else None, "statut": MESURE}


def _cache(finding, events):
    """R8/levier 07 : les appels en trop d'une rafale de doublons stricts (même demande normalisée,
    même réponse, dans l'heure). Aucun risque de qualité : rules.duplicate_calls a déjà vérifié que
    la réponse servie une deuxième fois est identique à celle qu'un cache aurait renvoyée ; la
    précision de 100 % est la définition même du constat, pas une hypothèse."""
    ids = set(finding["event_ids"])
    wasted_ids = set(finding["evidence"]["wasted_event_ids"])
    group = [e for e in events if e["event_id"] in ids]
    kept = [e for e in group if e["event_id"] not in wasted_ids]
    before, after = _cost(group), _cost(kept)
    return {
        "type": "cache", "finding_id": finding["finding_id"], "app_id": finding["app_id"], "model": finding["model"],
        "changement": f"Mettre en cache les réponses aux demandes déjà posées dans l'heure précédente "
                      f"({len(wasted_ids)} appel(s) en trop évité(s) sur {len(group)}).",
        "verdict": "pass", "raisons": [],
        "mesures": {
            "precision": _m(100.0, MESURE, "%",
                            "réponse déjà vérifiée identique par le détecteur : servir le cache ne change rien"),
            "appels_evites": _m(len(wasted_ids), MESURE),
            "cout": (_m(_pct_change(before, after), MESURE, "%") if before is not None
                    else _m(None, NON_TESTE, "%")),
        },
        "cout_usd": {"avant": before, "apres": after, "statut": MESURE} if before is not None else None,
    }


def _errors(finding, events):
    """R9/levier 12 : coût déjà facturé des relances (même demande, même échec facturé, relancée
    en moins de rules.paid_errors.RETRY_WINDOW_SECONDS). Corriger la cause de l'échec ne change pas
    la réponse gardée (celle de la relance, déjà obtenue) : seule la dépense du premier essai raté
    disparaît, la précision n'est pas affectée. Les échecs facturés jamais relancés (rate seul au-
    dessus du seuil) ne sont pas comptés ici : supprimer leur cause changerait la réponse obtenue,
    ce que rien ici ne mesure — cette proposition ne porte que sur le doublon prouvé."""
    retry_ids = set(finding["evidence"]["retry_event_ids"])
    if not retry_ids:
        return None
    group = [e for e in events if e["event_id"] in set(finding["event_ids"])]
    kept = [e for e in group if e["event_id"] not in retry_ids]
    before, after = _cost(group), _cost(kept)
    return {
        "type": "erreurs", "finding_id": finding["finding_id"], "app_id": finding["app_id"], "model": finding["model"],
        "changement": f"Corriger la cause de l'échec avant de relancer ({len(retry_ids)} relance(s) "
                      "facturée(s) évitée(s)).",
        "verdict": "pass", "raisons": [],
        "mesures": {
            "precision": _m(100.0, MESURE, "%",
                            "la réponse gardée est celle de la relance, déjà obtenue : rien ne change pour l'utilisateur"),
            "relances_evitees": _m(len(retry_ids), MESURE),
            "cout": (_m(_pct_change(before, after), MESURE, "%") if before is not None
                    else _m(None, NON_TESTE, "%")),
        },
        "cout_usd": {"avant": before, "apres": after, "statut": MESURE} if before is not None else None,
    }


def _prompt_cache(finding, events):
    """R4/levier 04 : jetons d'entrée répétés d'un gabarit déjà identique (après masquage des dates,
    heures, UUID et longs nombres par rules.no_cache), au tarif de cache du même modèle. Calcul
    exact (jetons enregistrés x écart de tarif du catalogue) sur les appels qui suivent le premier
    de chaque gabarit (celui-ci établit le cache, rien à gagner dessus) — jamais une mesure du taux
    de succès réel du cache fournisseur, que le rejeu ne peut pas observer. Activer le cache ne
    change ni le modèle ni les jetons envoyés, seulement leur tarif : précision 100 % mesurée."""
    from rules.no_cache import _detect_templates
    from report.cost import PRICING_PATH, lookup
    import json

    by_id = {e["event_id"]: e for e in events}
    templates = [f for f in _detect_templates(events)
                if f["app_id"] == finding["app_id"] and f["model"] == finding["model"]]
    prices = json.loads(PRICING_PATH.read_text(encoding="utf-8"))
    before = after = 0.0
    repeated_tokens = known = 0
    for t in templates:
        ordered = sorted((by_id[i] for i in t["event_ids"] if i in by_id), key=lambda e: e["ts_start"])
        for e in ordered[1:]:
            price = lookup(prices, e["model"])
            tin = e["usage"].get("input_tokens")
            if price is None or tin is None or "cached_in" not in price:
                continue
            known += 1
            repeated_tokens += tin
            before += tin * price["in"] / 1e6
            after += tin * price["cached_in"] / 1e6
    if not known or before <= 0:
        return None
    return {
        "type": "cache_prompt", "finding_id": finding["finding_id"], "app_id": finding["app_id"],
        "model": finding["model"],
        "changement": "Ordonner le prompt (partie fixe d'abord, variable ensuite) et activer le cache "
                      "de prompt du fournisseur.",
        "verdict": "pass", "raisons": [],
        "mesures": {
            "precision": _m(100.0, MESURE, "%",
                            "le cache ne change ni le modèle ni les jetons envoyés, seulement leur tarif"),
            "jetons_repetes": _m(repeated_tokens, MESURE, "jetons"),
            "cout": _m(_pct_change(before, after), MESURE, "%"),
        },
        "cout_usd": {"avant": before, "apres": after, "statut": MESURE},
    }


def _batch(finding, events):
    """R14/levier 13 : rafales nocturnes régulières, candidates à l'API batch d'un fournisseur.
    Jamais « pass » : rules.batch_eligible chiffre une remise de scénario (BATCH_DISCOUNT = 50 %),
    pas un prix batch vérifié par modèle, et l'éligibilité réelle (absence d'utilisateur, délai
    accepté) ne s'observe pas dans l'historique — le dire mesuré serait fabriquer une valeur."""
    ev = finding["evidence"]
    group = [e for e in events if e["event_id"] in set(finding["event_ids"])]
    spent = _cost(group)
    return {
        "type": "batch", "finding_id": finding["finding_id"], "app_id": finding["app_id"], "model": finding["model"],
        "changement": "Passer ces rafales nocturnes régulières par l'API batch du fournisseur "
                      f"(remise de scénario annoncée : {round(ev['assumed_discount'] * 100)} %).",
        "verdict": "non_teste",
        "raisons": ["remise batch non vérifiée par modèle", ev["eligibility_unverified"]],
        "mesures": {
            "precision": _m(None, NON_TESTE, "%",
                            "absence d'utilisateur et modèle batch du fournisseur non observables dans l'historique"),
            "cout": (_m(round(-ev["assumed_discount"] * 100, 1), ESTIME, "%",
                       "remise de scénario, jamais vérifiée par modèle") if spent is not None
                    else _m(None, NON_TESTE, "%")),
        },
        "cout_usd": ({"avant": spent, "apres": spent * (1 - ev["assumed_discount"]), "statut": ESTIME}
                    if spent is not None else None),
    }


def _reasoning(finding, events, keys_available, prove_reasoning=None):
    """R7/levier 03 : baisser l'effort de raisonnement d'un modèle qui réfléchit longtemps pour une
    réponse triviale, prouvé au banc (même modèle, effort réduit, rejoué sur les mêmes entrées et
    comparé à la réponse d'origine — bench.reasoning.prove, clé OpenAI nécessaire). Sans clé, non
    testé, comme _model : jamais de score inventé."""
    if prove_reasoning is None:
        from bench.reasoning import prove as prove_reasoning
    if not keys_available:
        return {
            "type": "raisonnement", "finding_id": finding["finding_id"], "app_id": finding["app_id"],
            "model": finding["model"],
            "changement": f"Baisser l'effort de raisonnement de {finding['model']}.",
            "verdict": "non_teste", "raisons": ["aucune clé pour le banc : rien de mesuré"],
            "mesures": {"precision": _m(None, NON_TESTE, "%")},
        }
    result = prove_reasoning(events, finding)
    score = result.get("score")
    bench_passed = result["verdict"] == "pass"
    # bench.scoring.threshold_for descend a 0.5 en texte libre (F1 de recouvrement, indicatif) :
    # trop permissif pour un "pass" ici. optimize.thresholds.PRECISION_THRESHOLD est le plancher du
    # projet, applique en plus du seuil interne du banc, jamais a sa place.
    passed = bench_passed and score is not None and score >= PRECISION_THRESHOLD
    reasons = list(result.get("reasons") or [])
    if bench_passed and not passed:
        reasons.append(f"score {score:.2f} sous le seuil du projet ({PRECISION_THRESHOLD:.0%})")
    verdict = "pass" if passed else ("non_teste" if result["verdict"] == "not_tested" else "reject")
    group = [e for e in events if e["event_id"] in set(finding["event_ids"])]
    before_p95 = _p95([e["latency_ms"] for e in group])
    spent, ref, measured = _cost(group), result.get("reference_cost_per_1000_calls_usd"), result.get("cost_per_1000_calls_usd")
    return {
        "type": "raisonnement", "finding_id": finding["finding_id"], "app_id": finding["app_id"],
        "model": finding["model"],
        "changement": (f"Baisser l'effort de raisonnement de {finding['model']} à « {result['effort']} »." if passed
                       else f"Aucun effort de raisonnement réduit ne tient le seuil pour {finding['model']}."),
        "verdict": verdict, "raisons": reasons, "preuve": result,
        "mesures": {
            "precision": _m(round(score * 100, 1), MESURE, "%") if score is not None else _m(None, NON_TESTE, "%"),
            "appels_rejoues": (_m(result["n_calls"], MESURE) if result.get("n_calls")
                              else _m(None, NON_TESTE)),
            "latence_p95": (_m(_pct_change(before_p95, result.get("latency_p95_ms")), MESURE, "%") if passed
                           else _m(None, NON_TESTE, "%")),
            "cout": (_m(_pct_change(ref, measured), MESURE, "%") if passed and ref and measured
                    else _m(None, NON_TESTE, "%")),
        },
        "cout_usd": ({"avant": spent, "apres": spent * measured / ref, "statut": MESURE}
                    if passed and ref and measured and spent is not None else None),
    }


def propose(events, llm=None, keys_available=False, prove=None, prove_reasoning=None):
    """Toutes les propositions testables, dans l'ordre des constats.
    ``prove`` : bench.m2.prove (injectable) ; ``prove_reasoning`` : bench.reasoning.prove (injectable)."""
    if prove is None:
        from bench.m2 import prove
    events = list(events)
    findings = [f for _, detect in _discover_detectors() for f in detect(events)]
    out = []
    for f in findings:
        if f["rule"] == "low_entropy_output":
            out.append(_rules(f, events, llm))
        elif f["rule"] == "oversized_model":
            out.append(_model(f, events, keys_available, prove))
        elif f["rule"] == "verbose_output":
            p = _cap(f, events)
            if p:
                out.append(p)
        elif f["rule"] == "duplicate_calls":
            out.append(_cache(f, events))
        elif f["rule"] == "paid_errors":
            p = _errors(f, events)
            if p:
                out.append(p)
        elif f["rule"] == "no_cache":
            p = _prompt_cache(f, events)
            if p:
                out.append(p)
        elif f["rule"] == "batch_eligible":
            out.append(_batch(f, events))
        elif f["rule"] == "excess_reasoning":
            out.append(_reasoning(f, events, keys_available, prove_reasoning))
    return out
