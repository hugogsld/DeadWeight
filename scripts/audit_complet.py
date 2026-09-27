"""Audit complet en une commande : source → événements → rapport → micro-PR → message Slack.

    make audit-complet SOURCE=<source> [REPO=chemin/du/depot] [DEMO=1]

Sources reconnues :
    n8n:<id>             historique d'un workflow n8n (N8N_URL, N8N_API_KEY) : check, fetch puis convert
    dossier n8n          dossier déjà écrit par fetch (workflow.json + executions.jsonl)
    gateway | *.db       trafic déjà capturé par la passerelle (défaut : GATEWAY_DB)
    events.jsonl         événements déjà au format DeadWeight
    autre                journaux Claude Code / Codex (fichier .jsonl, dossier ou .zip)

Avec ``--repo``, les micro-PR prouvées sont ouvertes (gh) et deviennent des boutons lien dans Slack.
Le message part par ``SLACK_WEBHOOK_URL`` seulement s'il y a un gain prouvé (``--demo`` montre tout) ;
sans webhook, il reste dans ``slack.md``.
"""
import argparse
import json
import os
import sys
import urllib.error
from pathlib import Path

from agent.audit import main as audit_main
from connectors.agent_logs.__main__ import jsonl_line, lire
from gateway.store import read_events
from gateway.traces import assign_traces
from importers.n8n.__main__ import main as n8n_main, run_convert
from optimize.__main__ import main as optimize_main
from optimize.send import payload, send


def _is_events(path):
    """Un fichier d'événements DeadWeight : la première ligne porte ``event_id`` et ``app_id``."""
    try:
        with path.open(encoding="utf-8") as f:
            first = json.loads(next((line for line in f if line.strip()), "{}"))
    except (OSError, ValueError, UnicodeDecodeError):
        return False
    return isinstance(first, dict) and {"event_id", "app_id"} <= first.keys()


def _write(events, out):
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for ev in events:
            f.write(jsonl_line(ev))
    return out


def _from_n8n(folder):
    return folder / "events.jsonl" if run_convert(folder) == 0 else None


def _fetch_n8n(workflow, out):
    if n8n_main(["check", "--workflow", workflow]) or n8n_main(["fetch", "--workflow", workflow, "--out", str(out)]):
        return None
    return _from_n8n(out / workflow)


def _from_gateway(db, out):
    if not Path(db).is_file():
        print(f"erreur : base de la passerelle absente ({db}) ; lancez make dev et laissez passer du trafic",
              file=sys.stderr)
        return None
    return _write(assign_traces(read_events(db)), out)


def _from_agent_logs(source, out):
    try:
        events, reports = lire([source])
    except FileNotFoundError as e:
        print(f"erreur : {e}", file=sys.stderr)
        return None
    if not reports:
        print(f"erreur : {source} n'est ni un workflow n8n, ni une base de la passerelle, ni des journaux "
              "Claude Code / Codex reconnus", file=sys.stderr)
        return None
    print(", ".join(f"{name} : {r['appels_lus']} appel(s) lus" for name, r in reports.items()))
    return _write(events, out)


def detect(source, out):
    """Source → chemin d'un events.jsonl (ou None, message d'erreur déjà affiché)."""
    if source.startswith("n8n:"):
        return _fetch_n8n(source[4:], out / "n8n")
    if source == "gateway":
        return _from_gateway(os.environ.get("GATEWAY_DB", "out/events.db"), out / "events.jsonl")
    path = Path(source).expanduser()
    if path.suffix == ".db":
        return _from_gateway(path, out / "events.jsonl")
    if path.is_dir() and (path / "workflow.json").is_file() and (path / "executions.jsonl").is_file():
        return _from_n8n(path)
    if path.is_file() and path.suffix == ".jsonl" and _is_events(path):
        return path
    return _from_agent_logs(str(path), out / "events.jsonl")


def notify(folder, demo=False, webhook=None, sender=send):
    """Envoie slack.md (+ boutons PR) si un gain est prouvé ; sinon dit clairement pourquoi rien ne part."""
    folder = Path(folder)
    text = (folder / "slack.md").read_text(encoding="utf-8").strip()
    proposals = json.loads((folder / "propositions.json").read_text(encoding="utf-8"))
    prs_file = folder / "prs.json"
    prs = json.loads(prs_file.read_text(encoding="utf-8")) if prs_file.is_file() else []
    if not demo and not any(p["verdict"] == "pass" for p in proposals):
        print("Slack : aucun gain prouvé, aucun message envoyé (Slack est réservé aux gains prouvés).")
        return "rien"
    if not webhook:
        print(f"Slack : SLACK_WEBHOOK_URL absent, message NON envoyé ; il est dans {folder / 'slack.md'}.")
        return "fichier"
    try:
        sender(webhook, payload(text, prs))
    except (OSError, RuntimeError, urllib.error.URLError) as e:
        print(f"Slack : envoi impossible ({e}) ; le message reste dans {folder / 'slack.md'}.", file=sys.stderr)
        return "erreur"
    print(f"Slack : message envoyé ({len(prs)} bouton(s) PR).")
    return "envoye"


def run(source, out, repo=None, demo=False, webhook=None, sender=send):
    out = Path(out)
    print(f"1/4 Détection : {source}")
    events = detect(source, out)
    if events is None:
        return 1
    print(f"2/4 Audit → {out / 'audit.html'}")
    if audit_main([str(events), "-o", str(out / "audit.html")]):
        return 1
    print("3/4 Optimisation" + (f" et micro-PR sur {repo}" if repo else " (sans REPO : aucune PR ouverte)"))
    argv = [str(events), "--out", str(out / "optim")]
    argv += ["--repo", str(repo), "--open-prs"] if repo else []
    argv += ["--demo"] if demo else []
    if optimize_main(argv):
        return 1
    print("4/4 Slack")
    return 1 if notify(out / "optim", demo, webhook, sender) == "erreur" else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Audit complet : détection, rapport, micro-PR, Slack")
    ap.add_argument("source", help="n8n:<id>, dossier n8n, gateway, base .db, events.jsonl ou journaux d'agent")
    ap.add_argument("--out", default="out/audit-complet")
    ap.add_argument("--repo", help="dépôt où ouvrir les micro-PR prouvées (gh)")
    ap.add_argument("--demo", action="store_true", help="Slack montre aussi les pistes non prouvées")
    args = ap.parse_args(argv)
    return run(args.source, args.out, args.repo, args.demo, os.environ.get("SLACK_WEBHOOK_URL"))


if __name__ == "__main__":
    sys.exit(main())
