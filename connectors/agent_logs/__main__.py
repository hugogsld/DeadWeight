"""Journaux de session Claude Code et Codex → événements + rapport de compréhension.

    python -m connectors.agent_logs <source> [<source>...] [-o private/agent-logs/events.jsonl]

Une source est un fichier .jsonl, un dossier (parcouru récursivement) ou une archive .zip.
Le format est reconnu ligne à ligne : on peut mélanger Claude Code et Codex.

    ~/.claude/projects/<projet>/            Claude Code (sous-agents compris)
    ~/.codex/sessions/AAAA/MM/JJ/           Codex

Écrit les événements (lisibles par report.audit ou agent.audit) et, à côté, comprehension.json.
Les clés d'API qui apparaissent dans les journaux sont masquées ([secret]).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import claude_code, codex
from .common import iter_files


def jsonl_line(obj) -> str:
    # U+2028 et U+2029 échappés : un lecteur qui coupe avec splitlines() casserait la ligne
    text = json.dumps(obj, ensure_ascii=False)
    return text.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029") + "\n"


def lire(sources) -> tuple[list[dict], dict]:
    """Contrat d'un connecteur : sources → (événements, rapport de compréhension par outil)."""
    files = [f for src in sources for f in iter_files(src)]
    events, reports = [], {}
    for name, reader in (("claude-code", claude_code), ("codex", codex)):
        found, report = reader.read(files)
        if report.files:
            events.extend(found)
            reports[name] = report.as_dict()
    events.sort(key=lambda e: e["ts_start"])
    return events, reports


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m connectors.agent_logs",
                                description="Journaux Claude Code et Codex → événements.")
    p.add_argument("sources", nargs="+", help="fichier .jsonl, dossier ou archive .zip")
    p.add_argument("-o", "--out", default="private/agent-logs/events.jsonl",
                   help="fichier d'événements (défaut : private/agent-logs/events.jsonl) ; comprehension.json à côté")
    args = p.parse_args(argv)

    try:
        events, reports = lire(args.sources)
    except FileNotFoundError as e:
        print(f"erreur : {e}", file=sys.stderr)
        return 1
    if not reports:
        print("erreur : aucun journal Claude Code ou Codex reconnu dans ces sources", file=sys.stderr)
        return 1

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for ev in events:
            f.write(jsonl_line(ev))
    summary = out.with_name("comprehension.json")
    summary.write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")

    for name, r in reports.items():
        ignored = sum(r["ignores"].values())
        print(f"{name} : {r['fichiers']} fichier(s), {r['sessions']} session(s), {r['appels_lus']} appel(s) lus, "
              f"{ignored} ignoré(s), niveaux {r['niveaux']}")
        for reason, n in r["ignores"].items():
            print(f"    ignoré ×{n} : {reason}")
    print(f"→ {out} ({len(events)} événements), {summary}")
    print(f"rapport : python -m report.audit {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
