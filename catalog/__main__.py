import argparse
import json
import sys
from pathlib import Path

from catalog import coverage, editor_index, info, load_pricing, load_providers, observed_latency


def main(argv=None):
    ap = argparse.ArgumentParser(description="Catalogue des modèles (M1)")
    ap.add_argument("--events", help="événements au schéma v1 (jsonl) : latence observée par modèle")
    args = ap.parse_args(argv)

    pricing, providers = load_pricing(), load_providers()
    cov = coverage(pricing, providers)
    print(f"catalogue : {cov['modeles']} modèles OpenRouter, {len(providers)} éditeurs décrits, "
          f"{cov['part']:.0%} des modèles couverts")
    top = ", ".join(f"{p} ({n})" for p, n in list(cov["editeurs_sans_fiche"].items())[:8])
    if top:
        print(f"  sans fiche : {top}")

    if args.events:
        events = [json.loads(line) for line in Path(args.events).read_text().splitlines() if line.strip()]
        index = editor_index(pricing)
        print(f"\n{'modèle':32} {'appels':>6} {'p50':>8} {'p95':>8}  {'éditeur':12} pays  UE")
        for model, lat in observed_latency(events).items():
            sheet = info(model, pricing, providers, index)
            ue = {True: "oui", False: "non", None: "?"}[sheet["hebergement_ue"]]
            print(f"{model:32} {lat['n']:>6} {lat['p50_ms']:>6.0f}ms {lat['p95_ms']:>6.0f}ms  "
                  f"{sheet['editeur'] or '?':12} {sheet['pays'] or '?':4}  {ue}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
