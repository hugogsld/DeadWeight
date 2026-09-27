"""Proposer une micro-modification par constat, puis la tester sur l'historique du client.

Chaque proposition porte des mesures, et chaque mesure son statut, décidé par le code :
- « mesuré » : calculé sur les vrais appels (rejeu des mêmes entrées, banc de modèles, historique) ;
- « estimé » : calcul sur l'historique + une hypothèse nommée dans ``hypothese`` ;
- « non testé » : pas de preuve possible ici (clé absente, pas de contenu), la proposition reste une piste.
Rien n'est arrondi vers le plus favorable, rien ne vient du modèle.

Types de modifications (une par micro-PR) :
- ``regles``   : un LLM qui aiguille (R1) remplacé par des règles extraites, prouvé par rejeu ;
- ``modele``   : un modèle plus petit (R2), prouvé au banc sur les mêmes entrées (clé nécessaire) ;
- ``plafond``  : un plafond de longueur (R12), mesuré sur l'historique des réponses.
"""
import math
from statistics import median

import time

from proof.extract import build_router, extract_rules
from proof.replay import _user_text
from proof.replay import replay
from report.audit import _discover_detectors
from report.cost import chiffrer

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
    # latence médiane et jetons envoyés mesurés ensemble, entrée par entrée : une règle répond sans
    # rien envoyer au modèle (0 jeton, latence chronométrée) ; un appel resté sur le secours garde ses
    # jetons et sa latence enregistrés. Rien n'est extrapolé depuis un taux de couverture global.
    route, lat_after, tokens_after = build_router(rules), [], 0
    for e in group:
        t0 = time.perf_counter()
        covered = route(_user_text(e)) is not None
        lat_after.append((time.perf_counter() - t0) * 1000 if covered else e["latency_ms"])
        tokens_after += 0 if covered else (e["usage"].get("input_tokens") or 0)
    med_before = median(e["latency_ms"] for e in group) if group else None
    med_after = median(lat_after) if lat_after else None
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
            "latence_mediane": _m(_pct_change(med_before, med_after), MESURE, "%"),
            "cout": _m(_pct_change(proof["cost_before_month_usd"], proof["cost_after_month_usd"]),
                       MESURE if proof["cost_after_month_usd"] is not None else NON_TESTE, "%"),
            "jetons_envoyes": _m(_pct_change(tokens_before, tokens_after), MESURE, "%"),
        },
        # valeurs brutes (ms) pour l'affichage quand le pourcentage seul ressemble à un bug (ex. -100 %) :
        # cf. scripts.tester_ui.latency_cell.
        "latence_ms": {"avant": med_before, "apres": med_after, "statut": MESURE},
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


def propose(events, llm=None, keys_available=False, prove=None):
    """Toutes les propositions testables, dans l'ordre des constats. ``prove`` : bench.m2.prove (injectable)."""
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
    return out
