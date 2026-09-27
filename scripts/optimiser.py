"""Tout ce qui vient après la capture, en une commande : bilan, optimisations testées, micro-PR.

    make optimiser REPO=chemin/du/depot            # bilan + propositions + diffs et textes de PR
    make optimiser REPO=chemin/du/depot PR=oui     # ... et ouvre réellement les PR (gh)

1. bilan HTML (comme ``make audit``, agent auditeur compris si une clé est configurée) ;
2. propositions : une modification par constat, testée en rejouant l'historique (``optimize``) ;
3. avec un dépôt : un diff et un texte de PR par modification prouvée ; avec ``--pr``, les PR sont ouvertes.

L'export des appels est temporaire et supprimé à la fin, comme pour ``make audit``. Le banc de modèles
(appels payants à d'autres modèles) n'est lancé qu'avec ``--banc``.
"""
import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from scripts.audit import NEXT_STEPS, audit

KEYS = ("DW_LLM_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY", "MISTRAL_API_KEY")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Bilan, optimisations testées et micro-PR, en une commande")
    ap.add_argument("--db", default=os.environ.get("GATEWAY_DB", "out/events.db"))
    ap.add_argument("--out", default="out/optimiser", help="dossier des résultats")
    ap.add_argument("--repo", help="dépôt du client où préparer les micro-PR")
    ap.add_argument("--pr", action="store_true", help="ouvre réellement les PR (gh) ; seulement sur un dépôt qu'on contrôle")
    ap.add_argument("--banc", action="store_true", help="teste aussi des modèles moins chers (appels payants)")
    args = ap.parse_args(argv)
    db, out = Path(args.db), Path(args.out)
    if not db.is_file():
        print(f"Base absente : {db}. {NEXT_STEPS}", file=sys.stderr)
        return 1
    if args.pr and not args.repo:
        print("--pr demande un dépôt : ajoutez REPO=chemin/du/depot.", file=sys.stderr)
        return 1
    if args.repo and not (Path(args.repo) / ".git").exists():
        print(f"{args.repo} n'est pas un dépôt git : les micro-PR s'appliquent à un dépôt.", file=sys.stderr)
        return 1

    print("1/3  bilan", flush=True)
    if audit(db, out / "audit.html"):
        return 1

    print("\n2/3  propositions testées sur l'historique" + (" et micro-PR" if args.repo else ""), flush=True)
    env = dict(os.environ)
    if not args.banc:  # sans --banc : aucune clé transmise, donc aucun appel payant au banc de modèles
        for key in KEYS:
            env.pop(key, None)
    with tempfile.TemporaryDirectory(prefix="deadweight-optimiser-") as tmp:
        events = Path(tmp) / "events.jsonl"
        with events.open("w", encoding="utf-8") as stream:
            if subprocess.run([sys.executable, "-m", "gateway.store", "export", "--db", str(db)],
                              stdout=stream).returncode:
                print(f"Impossible de lire la base {db}.", file=sys.stderr)
                return 1
        cmd = [sys.executable, "-m", "optimize", str(events), "--out", str(out / "propositions")]
        if args.repo:
            cmd += ["--repo", args.repo] + (["--open-prs"] if args.pr else [])
        if subprocess.run(cmd, env=env).returncode:
            return 1

    print(f"\n3/3  résultats dans {out}/")
    print(f"     bilan              {out / 'audit.html'}")
    print(f"     page développeur   {out / 'propositions' / 'propositions.html'}")
    print(f"     message Slack      {out / 'propositions' / 'slack.md'}")
    if args.repo and not args.pr:
        print(f"     diffs et PR        {out / 'propositions'}/*.diff, *.pr.md "
              "(relancez avec PR=oui pour les ouvrir)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
