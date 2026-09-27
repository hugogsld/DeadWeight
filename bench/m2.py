"""M2.2 — Les options de M2 passées au banc : un verdict mesuré au lieu de « qualité non prouvée ».

Le banc ne choisit rien : il prend exactement les options que catalog.recommend.recommend()
rend pour un constat (le moins cher, même éditeur, éditeur européen) et les teste sur le trafic
réel du groupe, avec run_candidate. Une option chiffrée sur la route de son éditeur (Mistral
via Mistral) est testée sur cette route et à son prix, pas chez un hébergeur tiers.

    python -m bench m2 events.jsonl --finding <finding_id> [--dry-run] [--out out/banc/]
"""
from bench.models import Candidate
from bench.pricing import cost_per_1000_calls, load_prices
from bench.report import dry_run_estimate, to_dict
from bench.runner import Throttle, run_candidate
from bench.scoring import detect_task_type, threshold_for
from bench.testset import DEFAULT_MAX_CASES, build_test_cases
from catalog.capabilities import load as load_capabilities
from catalog.recommend import recommend

# Limite de sortie : large pour un modèle à raisonnement (sa réflexion compte dedans), sinon courte.
MAX_TOKENS, MAX_TOKENS_REASONING = 512, 4096
OPENROUTER = {"kind": "openrouter", "base_url_env": "OPENROUTER_BASE_URL",
              "default_base_url": "https://openrouter.ai/api/v1", "api_key_env": "OPENROUTER_API_KEY"}
# Route de l'éditeur OpenAI (fixtures/capabilities.json, hebergeur "OpenAI") : appelée en direct
# (OPENAI_API_KEY), jamais via OpenRouter. Seule route directe câblée ici : une démo avec la seule
# clé OpenAI peut donc mesurer les options "meilleur_compromis" d'un constat sur un modèle OpenAI
# (gpt-4o-mini, gpt-4.1-mini, gpt-4.1-nano... selon ce que recommend() juge moins cher et compatible ;
# ids et tarifs viennent de fixtures/pricing.json, jamais inventés ici). Les autres hébergeurs
# (Mistral, DeepSeek...) restent sur OpenRouter : sans OPENROUTER_API_KEY, ils redeviennent
# proprement "non testé" (bench.runner puis le repli de prove() ci-dessous), jamais un plantage.
OPENAI = {"kind": "openai", "base_url_env": "OPENAI_BASE_URL",
          "default_base_url": "https://api.openai.com/v1", "api_key_env": "OPENAI_API_KEY"}
DIRECT_HOSTS = {"OpenAI": OPENAI}


def candidate_for(key, option):
    """Une option de recommend() en candidat du banc, sur la route qu'elle recommande (directe pour
    l'éditeur OpenAI, OpenRouter sinon — DIRECT_HOSTS)."""
    direct = DIRECT_HOSTS.get(option["hebergeur"])
    base, route = (direct, None) if direct else (OPENROUTER, option["hebergeur"])
    return Candidate(id=f"m2-{key}", model=option["modele"], size_class="small", origin=option["pays"] or "?",
                     note=f"option M2 « {key} »", route=route,
                     max_tokens=MAX_TOKENS_REASONING if option["raisonnement"] else MAX_TOKENS, **base)


def _prices_for(option, prices, capabilities):
    """Prix de la route testée : celle de l'éditeur si l'option y est chiffrée."""
    route = (capabilities.get(option["modele"]) or {}).get("route_editeur")
    if option["hebergeur"] and route and route["hebergeur"] == option["hebergeur"]:
        return {**prices, option["modele"]: {"in": route["in"], "out": route["out"]}}
    return prices


def _plan(events, finding, max_cases, keys=None):
    by_id = {e["event_id"]: e for e in events}
    group = [by_id[i] for i in finding["event_ids"] if i in by_id]
    rec = recommend(group)
    cases = build_test_cases(events, finding["app_id"], finding["model"], finding.get("template"), max_cases)
    options = {k: o for k, o in rec["options"].items() if o and (keys is None or k in keys)}
    return rec, cases, options


def prove(events, finding, max_cases=DEFAULT_MAX_CASES, max_calls=None, min_interval=0.0,
          prices=None, capabilities=None, keys=None, **runner_kwargs):
    """Rend {finding_id, task_type, threshold, n_cases, raison, options: {clé: résultat du banc}}.
    keys : options à tester (défaut : toutes) ; une option non testée reste « non prouvée »."""
    prices = prices if prices is not None else load_prices()
    capabilities = capabilities if capabilities is not None else load_capabilities()
    rec, cases, options = _plan(events, finding, max_cases, keys)
    task_type = detect_task_type(cases) if cases else None
    tin = [c.origin_input_tokens for c in cases if c.origin_input_tokens is not None]
    tout = [c.origin_output_tokens for c in cases if c.origin_output_tokens is not None]
    # coût du modèle actuel sur les mêmes requêtes : la base du facteur mesuré
    reference = (cost_per_1000_calls(finding["model"], sum(tin) / len(tin), sum(tout) / len(tout), prices)
                 if tin and tout else None)
    out = {"finding_id": finding["finding_id"], "app_id": finding["app_id"], "model": finding["model"],
           "task_type": task_type, "threshold": threshold_for(task_type) if task_type else None,
           "n_cases": len(cases), "raison": rec["raison"],
           "reference_cost_per_1000_calls_usd": reference, "options": {}}
    for key, option in options.items():
        result = run_candidate(candidate_for(key, option), cases, task_type,
                               Throttle(max_calls or len(cases), min_interval),
                               _prices_for(option, prices, capabilities), **runner_kwargs)
        entry = {**to_dict(result), "route": option["hebergeur"], "task_type": task_type}
        measured = entry["cost_per_1000_calls_usd"]
        entry["facteur_mesure"] = round(reference / measured, 1) if reference and measured else None
        if entry["n_calls"] and entry["n_errors"] == entry["n_calls"]:
            # accès refusé (crédit, route indisponible…) : rien n'a été mesuré, ce n'est pas un refus de qualité
            entry.update(verdict="not_tested", score=None,
                         reasons=[f"les {entry['n_calls']} appels ont échoué : rien de mesuré"])
        out["options"][key] = entry
    return out


def dry_run(events, finding, max_cases=DEFAULT_MAX_CASES, prices=None, capabilities=None, keys=None):
    """Ce que prove() appellerait, et son coût estimé, sans émettre un seul appel."""
    prices = prices if prices is not None else load_prices()
    capabilities = capabilities if capabilities is not None else load_capabilities()
    rec, cases, options = _plan(events, finding, max_cases, keys)
    return {"n_cases": len(cases), "raison": rec["raison"], "options": {
        key: {**dry_run_estimate(candidate_for(key, o), cases, _prices_for(o, prices, capabilities)),
              "route": o["hebergeur"]}
        for key, o in options.items()}}
