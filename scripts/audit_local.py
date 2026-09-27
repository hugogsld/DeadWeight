"""Audit 100 % local (Ollama) avec relevé réseau : prouve qu'aucune donnée ne sort de la machine.

    python -m scripts.audit_local [events.jsonl] [--out out/audit-local.html]

Lance l'agent auditeur en mode local et, pendant tout le run, relève avec lsof chaque
connexion réseau de l'audit et du serveur Ollama. Écrit le relevé à côté du rapport et
échoue si une seule connexion vise un hôte non local.
"""
import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

from agent.local import is_local_host

DEFAULT_EVENTS = "fixtures/dataset/v1/events.jsonl"
POLL_SECONDS = 0.5
_REMOTE = re.compile(r"->(\[[^\]]+\]|[^:\s]+):(\d+)")


def remote_endpoints(lsof_output):
    """Adresses distantes « hôte:port » des connexions listées par lsof -nP -i."""
    return {f"{host.strip('[]')}:{port}" for host, port in _REMOTE.findall(lsof_output)}


def _pids(name):
    out = subprocess.run(["pgrep", "-f", name], capture_output=True, text=True).stdout
    return [p for p in out.split() if p.isdigit()]


def _snapshot(pids):
    out = subprocess.run(["lsof", "-a", "-nP", "-i", "-p", ",".join(pids)], capture_output=True, text=True)
    return out.stdout


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("events", nargs="?", default=DEFAULT_EVENTS)
    ap.add_argument("--out", default="out/audit-local.html")
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    ollama = _pids("ollama")
    if not ollama:
        print("Ollama ne tourne pas : lancez `ollama serve` puis `ollama pull qwen2.5:3b`.", file=sys.stderr)
        return 1
    audit = subprocess.Popen([sys.executable, "-m", "agent.audit", "--local", args.events, "-o", str(out),
                              "--journal", str(out.with_suffix(".json"))])
    seen, polls, start = set(), 0, time.time()
    while audit.poll() is None:
        seen |= remote_endpoints(_snapshot([str(audit.pid)] + _pids("ollama")))
        polls += 1
        time.sleep(POLL_SECONDS)
    outside = sorted(e for e in seen if not is_local_host(e.rsplit(":", 1)[0]))
    record = {"duree_s": round(time.time() - start), "releves_lsof": polls, "processus": "audit + ollama",
              "connexions_distantes": sorted(seen), "hors_machine": outside, "code_retour_audit": audit.returncode}
    out.with_name(out.stem + "-reseau.json").write_text(json.dumps(record, ensure_ascii=False, indent=1),
                                                         encoding="utf-8")
    print(f"Relevé réseau : {polls} relevés lsof en {record['duree_s']} s, connexions vues : "
          f"{', '.join(sorted(seen)) or 'aucune'} ; hors de la machine : {', '.join(outside) or 'aucune'}.")
    return 1 if outside or audit.returncode else 0


if __name__ == "__main__":
    sys.exit(main())
