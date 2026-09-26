"""M2.2 — Les options de M2 passées au banc : un verdict mesuré au lieu de « qualité non prouvée ».

Le banc ne choisit rien : il prend exactement les options que catalog.recommend.recommend()
rend pour un constat (le moins cher, même éditeur, éditeur européen) et les teste sur le trafic
réel du groupe, avec run_candidate. Une option chiffrée sur la route de son éditeur (Mistral
via Mistral) est testée sur cette route et à son prix, pas chez un hébergeur tiers.

    python -m bench m2 events.jsonl --finding <finding_id> [--dry-run] [--out out/banc/]
"""
from bench.models import Candidate
from bench.pricing import load_prices
from bench.report import dry_run_estimate, to_dict
from bench.runner import Throttle, run_candidate
from bench.scoring import detect_task_type, threshold_for
from bench.testset import DEFAULT_MAX_CASES, build_test_cases
from catalog.capabilities import load as load_capabilities
from catalog.recommend import recommend

OPENROUTER = {"kind": "openrouter", "base_url_env": "OPENROUTER_BASE_URL",
              "default_base_url": "https://openrouter.ai/api/v1", "api_key_env": "OPENROUTER_API_KEY"}


def candidate_for(key, option):
    """Une option de recommend() en candidat du banc, sur la route qu'elle recommande."""
    return Candidate(id=f"m2-{key}", model=option["modele"], size_class="small", origin=option["pays"] or "?",
                     note=f"option M2 « {key} »", route=option["hebergeur"], **OPENROUTER)


def _prices_for(option, prices, capabilities):
    """Prix de la route testée : celle de l'éditeur si l'option y est chiffrée."""
    route = (capabilities.get(option["modele"]) or {}).get("route_editeur")
    if option["hebergeur"] and route and route["hebergeur"] == option["hebergeur"]:
        return {**prices, option["modele"]: {"in": route["in"], "out": route["out"]}}
    return prices


def _plan(events, finding, max_cases):
    by_id = {e["event_id"]: e for e in events}
    group = [by_id[i] for i in finding["event_ids"] if i in by_id]
    rec = recommend(group)
    cases = build_test_cases(events, finding["app_id"], finding["model"], finding.get("template"), max_cases)
    options = {k: o for k, o in rec["options"].items() if o}
    return rec, cases, options


def prove(events, finding, max_cases=DEFAULT_MAX_CASES, max_calls=None, min_interval=0.0,
          prices=None, capabilities=None, **runner_kwargs):
    """Rend {finding_id, task_type, threshold, n_cases, raison, options: {clé: résultat du banc}}."""
    prices = prices if prices is not None else load_prices()
    capabilities = capabilities if capabilities is not None else load_capabilities()
    rec, cases, options = _plan(events, finding, max_cases)
    task_type = detect_task_type(cases) if cases else None
    out = {"finding_id": finding["finding_id"], "app_id": finding["app_id"], "model": finding["model"],
           "task_type": task_type, "threshold": threshold_for(task_type) if task_type else None,
           "n_cases": len(cases), "raison": rec["raison"], "options": {}}
    for key, option in options.items():
        result = run_candidate(candidate_for(key, option), cases, task_type,
                               Throttle(max_calls or len(cases), min_interval),
                               _prices_for(option, prices, capabilities), **runner_kwargs)
        out["options"][key] = {**to_dict(result), "route": option["hebergeur"], "task_type": task_type}
    return out


def dry_run(events, finding, max_cases=DEFAULT_MAX_CASES, prices=None, capabilities=None):
    """Ce que prove() appellerait, et son coût estimé, sans émettre un seul appel."""
    prices = prices if prices is not None else load_prices()
    capabilities = capabilities if capabilities is not None else load_capabilities()
    rec, cases, options = _plan(events, finding, max_cases)
    return {"n_cases": len(cases), "raison": rec["raison"], "options": {
        key: {**dry_run_estimate(candidate_for(key, o), cases, _prices_for(o, prices, capabilities)),
              "route": o["hebergeur"]}
        for key, o in options.items()}}
