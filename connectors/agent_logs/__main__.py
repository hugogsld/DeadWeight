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

from . import billing, claude_code, codex
from .common import iter_files


def jsonl_line(obj) -> str:
    # U+2028 et U+2029 échappés : un lecteur qui coupe avec splitlines() casserait la ligne
    text = json.dumps(obj, ensure_ascii=False)
    return text.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029") + "\n"


def projets(source) -> list[tuple[str, int]]:
    """Si ``source`` est un dossier qui range plusieurs projets (comme ~/.claude/projects) : [(projet, sessions)].
    Sinon liste vide. Un projet = un sous-dossier qui contient directement des .jsonl."""
    root = Path(source)
    if not root.is_dir():
        return []
    found = [(d.name, len(list(d.glob("*.jsonl")))) for d in sorted(root.iterdir()) if d.is_dir()]
    found = [(name, n) for name, n in found if n]
    return found if len(found) >= 2 else []


def lire(sources, project: str | None = None) -> tuple[list[dict], dict]:
    """Contrat d'un connecteur : sources → (événements, rapport de compréhension par outil).
    ``project`` : ne garde que les fichiers dont le chemin contient ce texte."""
    files = [f for src in sources for f in iter_files(src) if project is None or project in f[0]]
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
    p.add_argument("--billing", choices=[billing.ABONNEMENT, billing.API],
                   help="force le mode de facturation (abonnement ou api) pour tous les outils reconnus, "
                        "au lieu de le détecter dans la configuration locale")
    p.add_argument("--project", help="ne lit que les projets dont le nom de dossier contient ce texte "
                                     "(exigé pour un dossier qui range plusieurs projets, comme ~/.claude/projects)")
    p.add_argument("--all-projects", action="store_true",
                   help="lit tous les projets d'un dossier qui en range plusieurs (en connaissance de cause)")
    args = p.parse_args(argv)

    if not args.project and not args.all_projects:
        for src in args.sources:
            if found := projets(src):
                print(f"erreur : {src} range {len(found)} projets ; les lire tous mélangerait des projets sans rapport.",
                      file=sys.stderr)
                for name, n in found:
                    print(f"    {name} ({n} session(s))", file=sys.stderr)
                print("Choisissez : --project <texte du nom> (un seul projet), ou --all-projects pour tout lire.",
                      file=sys.stderr)
                return 2
    try:
        events, reports = lire(args.sources, args.project)
    except FileNotFoundError as e:
        print(f"erreur : {e}", file=sys.stderr)
        return 1
    if not reports:
        print("erreur : aucun journal Claude Code ou Codex reconnu dans ces sources"
              + (f" pour le projet « {args.project} »" if args.project else ""), file=sys.stderr)
        return 1

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for ev in events:
            f.write(jsonl_line(ev))
    for name, r in reports.items():
        r["billing"] = billing.resolve(name, args.billing)
    summary = out.with_name("comprehension.json")
    summary.write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")

    for name, r in reports.items():
        ignored = sum(r["ignores"].values())
        print(f"{name} : {r['fichiers']} fichier(s), {r['sessions']} session(s), {r['appels_lus']} appel(s) lus, "
              f"{ignored} ignoré(s), niveaux {r['niveaux']}")
        for reason, n in r["ignores"].items():
            print(f"    ignoré ×{n} : {reason}")
        print(f"    facturation : {r['billing']['mode']}"
              + (f" ({r['billing']['source']})" if r["billing"]["source"] else " (non détectée)"))
    print(f"→ {out} ({len(events)} événements), {summary}")
    print(f"rapport : python -m report.audit {out} --comprehension {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
