"""Import de l'historique n8n (B1).

    export N8N_API_KEY=...            # jamais en argument : il finirait dans l'historique du shell
    python -m importers.n8n check --url https://n8n.exemple.com
    python -m importers.n8n fetch --url https://n8n.exemple.com --workflow <id> [--limit 500] [--since 2026-09-01]
    python -m importers.n8n convert private/n8n/<id> [--anonymize]   # → events.jsonl, lisible par report.audit
    python -m importers.n8n purge private/n8n/<id>        # efface l'historique brut après analyse
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .api import N8nClient, N8nError
from .check import check, render
from .convert import convert
from .fetch import fetch
from .privacy import Masker, purge


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

    v = sub.add_parser("convert", help="exécutions téléchargées → événements (events.jsonl)")
    v.add_argument("dir", help="dossier écrit par fetch (workflow.json + executions.jsonl)")
    v.add_argument("--anonymize", action="store_true", help="masquer emails, téléphones, IBAN, cartes")

    d = sub.add_parser("purge", help="effacer un dossier téléchargé (historique brut et événements)")
    d.add_argument("dir")

    for s in (c, f):
        s.add_argument("--url", default=os.environ.get("N8N_URL"), help="adresse de l'instance (défaut : N8N_URL)")

    args = p.parse_args(argv)
    if args.cmd == "convert":
        return run_convert(Path(args.dir), args.anonymize)
    if args.cmd == "purge":
        try:
            removed = purge(Path(args.dir))
        except (ValueError, FileNotFoundError) as e:
            print(f"erreur : {e}", file=sys.stderr)
            return 1
        print(f"effacé : {args.dir} ({', '.join(removed)})")
        return 0
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


def run_convert(folder: Path, anonymize: bool = False) -> int:
    wf_path, ex_path = folder / "workflow.json", folder / "executions.jsonl"
    if not wf_path.exists() or not ex_path.exists():
        print(f"erreur : {folder} doit contenir workflow.json et executions.jsonl (écrits par fetch)", file=sys.stderr)
        return 1
    wf = json.loads(wf_path.read_text(encoding="utf-8"))
    with ex_path.open(encoding="utf-8") as lines:
        events, stats = convert(wf, (json.loads(line) for line in lines if line.strip()))
    masker = Masker() if anonymize else None
    if masker:
        events = [masker.event(ev) for ev in events]
    out = folder / "events.jsonl"
    with out.open("w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
    summary = stats.as_dict()
    (folder / "comprehension.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    rate = summary["taux_compris"]
    print(f"{summary['executions']} exécution(s), {summary['appels_llm_vus']} appel(s) LLM, {len(events)} événement(s) → {out}")
    print(f"compris : {'—' if rate is None else f'{rate:.0%}'} (jetons réels {summary['jetons_reels']}, "
          f"estimés {summary['jetons_estimes']}, sans jetons {summary['sans_jetons']}, modèle inconnu {summary['modele_inconnu']})")
    if masker:
        masked = ", ".join(f"{n} {k}" for k, n in sorted(masker.summary().items())) or "rien trouvé"
        print(f"anonymisé : {masked} (valeurs distinctes)")
    print(f"rapport : python -m report.audit {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
