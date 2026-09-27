"""Proposer, tester et chiffrer des micro-modifications, puis préparer les PR et le message Slack.

    python -m optimize events.jsonl --out private/optim [--repo chemin/du/depot] [--open-prs]

Sans ``--repo`` : propositions mesurées + message Slack. Avec ``--repo`` : un diff et un texte de PR par
proposition validée. ``--open-prs`` ouvre réellement les PR (gh) : à ne faire que sur un dépôt qu'on
contrôle. Le banc de modèles n'est lancé que si une clé est présente (``DW_LLM_API_KEY``).
``--comprehension`` / ``--billing`` : sur abonnement, le message parle de valeur équivalente API, pas d'économie.
"""
import argparse
import json
import os
import sys
from pathlib import Path

from optimize.devpage import render
from optimize.patch import make_patch, open_pr, pr_text
from optimize.propose import _cost, propose
from optimize.slack import message
from report.billing import ABONNEMENT, API, load_billing, subscription_only


def main(argv=None):
    ap = argparse.ArgumentParser(description="Micro-modifications mesurées et message Slack")
    ap.add_argument("events")
    ap.add_argument("--out", default="private/optim")
    ap.add_argument("--repo", help="dépôt du client sur lequel préparer les micro-PR")
    ap.add_argument("--open-prs", action="store_true", help="ouvre réellement les PR (gh)")
    ap.add_argument("--demo", action="store_true", help="Slack montre aussi les pistes refusées ou non testées")
    ap.add_argument("--comprehension", help="comprehension.json de python -m connectors.agent_logs (facturation)")
    ap.add_argument("--billing", choices=[ABONNEMENT, API], help="force le mode de facturation, remplace la détection")
    args = ap.parse_args(argv)
    events = [json.loads(line) for line in Path(args.events).read_text(encoding="utf-8").splitlines() if line.strip()]
    keys = bool(os.environ.get("DW_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENROUTER_API_KEY"))
    proposals = propose(events, keys_available=keys)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    links, diffs = {}, {}
    for i, p in enumerate(proposals):
        if args.repo and p["verdict"] == "pass" and p["type"] in ("regles", "modele", "plafond"):
            diff, notes = make_patch(args.repo, p)
            diffs[i] = diff
            title, body = pr_text(p, notes)
            (out / f"{i:02d}-{p['type']}-{p['app_id']}.diff").write_text(diff, encoding="utf-8")
            (out / f"{i:02d}-{p['type']}-{p['app_id']}.pr.md").write_text(f"# {title}\n\n{body}\n", encoding="utf-8")
            if args.open_prs:
                links[p["finding_id"] + p["type"]] = open_pr(args.repo, p, f"deadweight/{p['type']}-{i:02d}")
    slim = [{k: v for k, v in p.items() if k != "preuve"} for p in proposals]
    (out / "propositions.json").write_text(json.dumps(slim, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "propositions.html").write_text(render(proposals, diffs), encoding="utf-8")
    equivalent_api = subscription_only(events, load_billing(args.comprehension, args.billing))
    text = message(proposals, links, total_spent=_cost(events), show_all=args.demo, equivalent_api=equivalent_api)
    (out / "slack.md").write_text(text + "\n", encoding="utf-8")
    # les boutons « Voir la PR » du message Slack (optimize.send) : un lien, jamais une fusion
    prs = [{"app_id": p["app_id"], "changement": p["changement"], "url": links[p["finding_id"] + p["type"]]}
           for p in proposals if p["verdict"] == "pass" and links.get(p["finding_id"] + p["type"])]
    (out / "prs.json").write_text(json.dumps(prs, ensure_ascii=False, indent=1), encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
