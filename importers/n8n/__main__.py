"""Import de l'historique n8n (B1).

    export N8N_API_KEY=...            # jamais en argument : il finirait dans l'historique du shell
    python -m importers.n8n check --url https://n8n.exemple.com
    python -m importers.n8n fetch --url https://n8n.exemple.com --workflow <id> [--limit 500] [--since 2026-09-01]
"""
from __future__ import annotations

import argparse
import os
import sys

from .api import N8nClient, N8nError
from .check import check, render
from .fetch import fetch


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m importers.n8n", description="Import de l'historique n8n.")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("check", help="l'instance garde-t-elle un historique exploitable ?")
    c.add_argument("--workflow", help="un seul workflow (id)")

    f = sub.add_parser("fetch", help="télécharger l'historique d'un workflow")
    f.add_argument("--workflow", required=True, help="id du workflow")
    f.add_argument("--limit", type=int, help="les N exécutions les plus récentes")
    f.add_argument("--since", help="à partir de cette date (AAAA-MM-JJ)")
    f.add_argument("--out", default="private/n8n", help="dossier de sortie (défaut : private/n8n)")

    for s in (c, f):
        s.add_argument("--url", default=os.environ.get("N8N_URL"), help="adresse de l'instance (défaut : N8N_URL)")

    args = p.parse_args(argv)
    try:
        client = N8nClient(args.url, os.environ.get("N8N_API_KEY", ""))
        if args.cmd == "check":
            print(render(check(client, args.workflow)))
        else:
            fetch(client, args.workflow, args.out, args.limit, args.since)
    except N8nError as e:
        print(f"erreur : {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
