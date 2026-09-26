"""B1.1 : récupérer l'historique d'un workflow dans un dossier local.

    <out>/<workflow_id>/workflow.json      le workflow (nœuds, connexions)
    <out>/<workflow_id>/executions.jsonl   une exécution complète par ligne

On liste d'abord les exécutions sans leurs données (léger), puis on télécharge
une à une celles qui manquent. Relancer la commande reprend là où elle s'était
arrêtée : les exécutions déjà présentes ne sont pas retéléchargées.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .api import N8nClient


def load_done(path: Path) -> set[str]:
    """Identifiants déjà écrits. Une dernière ligne tronquée (coupure) est retirée."""
    if not path.exists():
        return set()
    done, keep = set(), 0
    with path.open("rb") as f:
        for raw in f:
            try:
                done.add(str(json.loads(raw)["id"]))
            except (ValueError, KeyError, TypeError):
                break
            keep += len(raw)
    if keep < path.stat().st_size:
        with path.open("r+b") as f:
            f.truncate(keep)
        if keep and not path.read_bytes().endswith(b"\n"):
            with path.open("ab") as f:
                f.write(b"\n")
    return done


def select(listing, limit: int | None, since: str | None) -> list[dict]:
    """Les plus récentes d'abord ; s'arrête à la limite ou avant la date."""
    out = []
    for ex in listing:
        if since and (ex.get("startedAt") or "") < since:
            break
        out.append(ex)
        if limit and len(out) >= limit:
            break
    return out


def fetch(client: N8nClient, workflow_id: str, out_dir: str | os.PathLike = "private/n8n",
          limit: int | None = None, since: str | None = None, log=print) -> dict:
    target = Path(out_dir) / str(workflow_id)
    target.mkdir(parents=True, exist_ok=True)

    wf = client.workflow(workflow_id)
    (target / "workflow.json").write_text(json.dumps(wf, ensure_ascii=False, indent=2), encoding="utf-8")

    path = target / "executions.jsonl"
    done = load_done(path)
    wanted = select(client.executions(workflow_id=workflow_id), limit, since)
    missing = [ex for ex in wanted if str(ex["id"]) not in done]
    log(f"{len(wanted)} exécution(s) retenue(s), {len(wanted) - len(missing)} déjà là, {len(missing)} à télécharger")

    fetched = 0
    with path.open("a", encoding="utf-8") as f:
        for ex in missing:
            full = client.execution(ex["id"])
            f.write(json.dumps(full, ensure_ascii=False) + "\n")
            f.flush()
            fetched += 1
            if fetched % 50 == 0:
                log(f"  {fetched}/{len(missing)}")

    total = len(done) + fetched
    log(f"terminé : {total} exécution(s) dans {path}")
    return {"dir": str(target), "selected": len(wanted), "fetched": fetched, "total": total}
