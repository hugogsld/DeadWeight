"""Journaux d'invocation Amazon Bedrock → événements + rapport de compréhension.

    python -m connectors.bedrock_logs <fichier|dossier|zip> [-o private/bedrock/events.jsonl]

Lecture seule : le client active « Model invocation logging » (S3 ou CloudWatch Logs) et nous remet l'export.
Sort avec un code non nul, et un message clair, si aucun appel n'a pu être lu.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from connectors.agent_logs.__main__ import jsonl_line

from . import SourceError, lire


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m connectors.bedrock_logs",
                                description="Journaux d'invocation Bedrock → événements Deadweight.")
    p.add_argument("source", help="fichier (.json, .jsonl, .gz), dossier (parcouru récursivement) ou archive .zip")
    p.add_argument("-o", "--out", default="private/bedrock/events.jsonl",
                   help="fichier d'événements (défaut : private/bedrock/events.jsonl) ; comprehension.json à côté")
    args = p.parse_args(argv)

    try:
        events, report = lire(args.source)
    except SourceError as exc:
        print(f"erreur : {exc}", file=sys.stderr)
        return 1
    if not events:
        print(f"erreur : aucun appel Bedrock lu dans {args.source} "
              f"({report['fichiers']} fichier(s), {report.get('enregistrements_lus', 0)} enregistrement(s) reconnus).",
              file=sys.stderr)
        for reason, n in report["ignores"].items():
            print(f"    ignoré ×{n} : {reason}", file=sys.stderr)
        print("Attendu : des enregistrements ModelInvocationLog (opérations Converse, ConverseStream, "
              "InvokeModel, InvokeModelWithResponseStream) en .json, .jsonl ou .gz.", file=sys.stderr)
        return 2

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(jsonl_line(e) for e in events), encoding="utf-8")
    summary = out.with_name("comprehension.json")
    summary.write_text(json.dumps({"bedrock": report}, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"bedrock : {report['fichiers']} fichier(s), {report['appels_lus']} appel(s) lus, "
          f"{sum(report['ignores'].values())} ignoré(s), niveaux {report['niveaux']}")
    for reason, n in report["ignores"].items():
        print(f"    ignoré ×{n} : {reason}")
    for note in report["limites"]:
        print(f"    limite : {note}")
    print(f"→ {out} ({len(events)} événements), {summary}")
    print(f"rapport : python -m report.audit {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
