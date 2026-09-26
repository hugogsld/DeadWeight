"""D4.3 — Mode miroir : mesurer en production les règles, sans jamais les appliquer.

Désactivé par défaut. GATEWAY_MIRROR pointe vers un fichier proof-*.json ou un dossier
(sortie de `python3 -m proof.replay`), preuves PASS **et** REJECT : une règle refusée au
rejeu est justement ce qu'on veut continuer d'observer sur le trafic réel.

Pour chaque appel capturé (OpenAI, Anthropic ou Gemini) qui tombe dans le groupe d'une preuve (application ×
modèle × gabarit, comme le court-circuit), on calcule ce que les règles auraient répondu
et on le compare à la vraie réponse du modèle. Contrairement au
court-circuit, rien n'est rendu au client : le format du fournisseur n'importe pas. Le client reçoit toujours la réponse du
modèle : le miroir branche sur la capture, pas sur le relais.

Le journal (GATEWAY_MIRROR_LOG, par défaut out/mirror.jsonl) ne contient ni prompt ni
réponse du client : l'étiquette des règles et l'accord, rien d'autre.

    python -m gateway.mirror stats                # accord par constat
"""
import argparse
import json
import logging
import os
import sys
from collections import defaultdict
from pathlib import Path

from gateway import shortcircuit
from rules.low_entropy import normalize, template_of

log = logging.getLogger("deadweight.mirror")

THRESHOLD = 0.95  # même seuil que le rejeu (proof/replay.py)


def default_log():
    return os.environ.get("GATEWAY_MIRROR_LOG", "out/mirror.jsonl")


class Mirror:
    """Compare chaque réponse capturée à celle des règles ; écrit une ligne par appel couvert."""

    def __init__(self, table, path=None):
        self.table = table
        self.path = Path(path or default_log())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._out = self.path.open("a", encoding="utf-8", buffering=1)

    def observe(self, event):
        # appelé dans la capture : ne doit jamais casser le relais
        try:
            record = self._compare(event)
            if record is not None:
                self._out.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            log.exception("miroir : comparaison en échec")

    def _compare(self, event):
        # tous fournisseurs : on ne répond rien, on compare des événements déjà normalisés
        if event.get("upstream") == "deadweight" or event.get("error") is not None:
            return None
        hit = self.table.get((event["app_id"], event["model"], template_of(event)))
        if hit is None:
            return None
        finding_id, route = hit
        text = shortcircuit.user_text(event["request"])
        rules_out = route(text) if text.strip() else None
        model_out = event["response"].get("content")
        agreed = None if rules_out is None or model_out is None else normalize(rules_out) == normalize(model_out)
        return {"ts": event["ts_start"], "event_id": event["event_id"], "app_id": event["app_id"],
                "finding_id": finding_id, "rules_output": rules_out, "agreed": agreed}

    def close(self):
        self._out.close()


def load(path):
    return shortcircuit.load(path, verdicts=("pass", "reject"))


def stats(records):
    """Par constat : appels vus, couverts par les règles, taux d'accord sur les couverts."""
    by = defaultdict(lambda: {"seen": 0, "covered": 0, "agreed": 0})
    for r in records:
        s = by[(r["app_id"], r["finding_id"])]
        s["seen"] += 1
        if r["agreed"] is not None:
            s["covered"] += 1
            s["agreed"] += r["agreed"]
    rows = []
    for (app_id, finding_id), s in sorted(by.items()):
        rate = s["agreed"] / s["covered"] if s["covered"] else None
        rows.append({"app_id": app_id, "finding_id": finding_id, **s,
                     "coverage": s["covered"] / s["seen"], "agreement": rate,
                     "ready": rate is not None and rate >= THRESHOLD})
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description="Mode miroir : accord des règles sur le trafic réel")
    ap.add_argument("command", choices=["stats"])
    ap.add_argument("--log", default=default_log())
    args = ap.parse_args(argv)
    path = Path(args.log)
    if not path.exists():
        sys.exit(f"{path} introuvable : lancer la passerelle avec GATEWAY_MIRROR=<dossier de preuves>")
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows = stats(records)
    if not rows:
        print("Aucun appel couvert par une preuve pour l'instant.")
    for r in rows:
        agreement = "—" if r["agreement"] is None else f"{r['agreement']:.1%}"
        verdict = "prêt pour le court-circuit" if r["ready"] else "pas encore"
        print(f"{r['app_id']:<16} {r['finding_id']:<28} vus {r['seen']:>6}  couverts {r['coverage']:>6.1%}  "
              f"accord {agreement:>6}  {verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
