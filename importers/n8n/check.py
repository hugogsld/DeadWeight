"""Étape 1 : l'instance garde-t-elle un historique exploitable ?

Répond avant tout import : quels workflows appellent un LLM, leur réglage
d'enregistrement, combien d'exécutions sont disponibles et sur quelle période.
"""
from __future__ import annotations

from collections import Counter

from .api import N8nClient
from .nodes import llm_nodes

# au-delà, on arrête de compter : le chiffre sert à décider, pas à facturer
COUNT_CAP = 5000


def inspect_workflow(client: N8nClient, wf: dict) -> dict:
    settings = wf.get("settings") or {}
    statuses: Counter = Counter()
    oldest = newest = None
    for i, ex in enumerate(client.executions(workflow_id=wf["id"])):
        if i >= COUNT_CAP:
            statuses["plus"] += 1
            break
        statuses[ex.get("status") or "inconnu"] += 1
        started = ex.get("startedAt")
        if started:
            oldest = started if oldest is None or started < oldest else oldest
            newest = started if newest is None or started > newest else newest
    return {
        "id": wf["id"],
        "name": wf.get("name"),
        "active": wf.get("active"),
        "llm_nodes": [n["name"] for n in llm_nodes(wf)],
        "save_success": settings.get("saveDataSuccessExecution", "défaut instance"),
        "save_error": settings.get("saveDataErrorExecution", "défaut instance"),
        "executions": dict(statuses),
        "oldest": oldest,
        "newest": newest,
    }


def verdict(r: dict) -> str:
    ex = r["executions"]
    total = sum(v for k, v in ex.items() if k != "plus")
    if not r["llm_nodes"]:
        return "pas d'appel LLM, rien à importer"
    if r["save_success"] == "none":
        return "PROBLÈME : les exécutions réussies ne sont pas enregistrées (réglage du workflow)"
    if total == 0:
        return "PROBLÈME : aucune exécution enregistrée (jamais lancé, réglage ou purge)"
    if not ex.get("success"):
        return "ATTENTION : seulement des échecs, les réussites ne sont sans doute pas gardées"
    return "OK, historique exploitable"


def check(client: N8nClient, workflow_id: str | None = None) -> list[dict]:
    wfs = [client.workflow(workflow_id)] if workflow_id else list(client.workflows())
    return [inspect_workflow(client, wf) for wf in wfs]


def render(results: list[dict]) -> str:
    lines = [f"{len(results)} workflow(s) sur l'instance", ""]
    for r in sorted(results, key=lambda r: (not r["llm_nodes"], r["name"] or "")):
        ex = r["executions"]
        total = sum(v for k, v in ex.items() if k != "plus")
        count = f"{total}+" if "plus" in ex else str(total)
        detail = ", ".join(f"{k} {v}" for k, v in sorted(ex.items()) if k != "plus")
        lines.append(f"• {r['name']}  (id {r['id']}, {'actif' if r['active'] else 'inactif'})")
        lines.append(f"    nœuds LLM      : {', '.join(r['llm_nodes']) or 'aucun'}")
        lines.append(f"    enregistrement : réussites={r['save_success']}, échecs={r['save_error']}")
        lines.append(f"    exécutions     : {count}" + (f" ({detail})" if detail else ""))
        if r["oldest"]:
            lines.append(f"    période        : {r['oldest'][:10]} → {r['newest'][:10]}")
        lines.append(f"    verdict        : {verdict(r)}")
        lines.append("")
    return "\n".join(lines)
