import argparse
import json
import os
import sys
from pathlib import Path

from bench import DEFAULT_SAMPLE, OpenAICompatibleBench, run
from catalog import load_pricing
from catalog.capabilities import load as load_capabilities
from proof.replay import DEFAULT_MAX_CALLS, DEFAULT_MIN_INTERVAL_S, HARD_MAX_CALLS, Throttle
from report.audit import _discover_detectors
from report.cost import lookup


def main(argv=None):
    ap = argparse.ArgumentParser(description="Banc de modèles (M2.2) : rejoue de vraies requêtes sur un candidat")
    ap.add_argument("events", help="événements au schéma v1 (jsonl)")
    ap.add_argument("--finding", required=True, help="finding_id du constat à tester")
    ap.add_argument("--model", required=True, help="modèle candidat, nom complet OpenRouter")
    ap.add_argument("--route", help="hébergeur imposé (ex. Mistral, OpenAI) : teste exactement cette route")
    ap.add_argument("--sample", type=int, default=DEFAULT_SAMPLE)
    ap.add_argument("--max-calls", type=int, default=DEFAULT_MAX_CALLS, help=f"plafonné à {HARD_MAX_CALLS}")
    ap.add_argument("--min-interval", type=float, default=DEFAULT_MIN_INTERVAL_S)
    ap.add_argument("--out", default="out")
    args = ap.parse_args(argv)

    base, key = os.environ.get("DW_LLM_BASE_URL"), os.environ.get("DW_LLM_API_KEY")
    if not base or not key:
        print("Le banc appelle le modèle candidat : DW_LLM_BASE_URL et DW_LLM_API_KEY requis "
              "(ex. https://openrouter.ai/api/v1).", file=sys.stderr)
        return 2
    events = [json.loads(line) for line in Path(args.events).read_text().splitlines() if line.strip()]
    finding = next((f for _, detect in _discover_detectors() for f in detect(events)
                    if f["finding_id"] == args.finding), None)
    if finding is None:
        print(f"constat inconnu : {args.finding}", file=sys.stderr)
        return 2
    pricing = load_pricing()
    route = (load_capabilities().get(args.model) or {}).get("route_editeur")
    if args.route and route and route["hebergeur"] == args.route:
        price = {"in": route["in"], "out": route["out"]}
    else:
        price = lookup(pricing, args.model)
    if price is None:
        print(f"prix inconnu pour {args.model}", file=sys.stderr)
        return 2
    by_id = {e["event_id"]: e for e in events}
    result = run([by_id[i] for i in finding["event_ids"] if i in by_id], args.model,
                 OpenAICompatibleBench(base, key, args.route), price, pricing,
                 Throttle(args.max_calls, args.min_interval), args.sample)
    result["finding_id"] = args.finding
    os.makedirs(args.out, exist_ok=True)
    path = Path(args.out) / f"bench-{args.finding}-{args.model.replace('/', '_')}.json"
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    accord = "—" if result["accord"] is None else f"{result['accord']:.1%}"
    print(f"{args.model}{' via ' + args.route if args.route else ''} : {result['n']} requêtes réelles, accord {accord}, "
          f"verdict {result['verdict'].upper()}")
    if result.get("facteur_mesure"):
        print(f"  coût mesuré : {result['cout_mensuel_mesure_usd']:.4g} $/mois (÷{result['facteur_mesure']})")
    if result.get("jetons_reflexion_moyens"):
        print(f"  réflexion : {result['jetons_reflexion_moyens']} jetons par appel en moyenne, comptés dans le coût")
    for reason in result["raisons"]:
        print(f"  - {reason}")
    print(f"  -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
