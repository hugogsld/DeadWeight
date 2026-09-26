"""Recette ``regles`` appliquée à une source n8n (``app_id`` = ``n8n:<workflow>/<noeud>``).

Porté de ``patcher/patch.py::build_patched_workflow`` (le prototype), paramétré au lieu de
lire l'environnement : le nœud LLM classifieur est remplacé par un Switch déterministe
(une branche par règle prouvée) + le modèle d'origine gardé en secours pour les entrées
que les règles ne couvrent pas. Aucun appel LLM ici : les règles arrivent déjà extraites
et prouvées par ``proof.extract`` / ``proof.replay``.
"""
from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path
from typing import Any


def _uid() -> str:
    return str(uuid.uuid4())


def _input_expression(node: dict) -> str:
    """Ce que le nœud classifieur lisait : ``inputText`` (textClassifier) ou ``text`` (chaîne LLM)."""
    params = node.get("parameters", {})
    for key in ("inputText", "text"):
        expr = params.get(key)
        if isinstance(expr, str) and expr:
            return expr
    return "={{ $json.text }}"


def build_patched_workflow(original: dict, node_name: str, rules: dict, fallback_model: str) -> dict:
    """Nouveau workflow (le dict d'origine n'est jamais modifié) : nœud ``node_name`` remplacé.

    ``rules`` : ``{"categories": [{"key": ..., "regex": ...}, ...]}``, déjà prouvées par rejeu.
    """
    wf = copy.deepcopy(original)
    nodes = wf["nodes"]
    conns = wf.get("connections", {})

    node = next((n for n in nodes if n["name"] == node_name), None)
    if node is None:
        raise ValueError(f"nœud '{node_name}' introuvable dans le workflow")
    pos = node.get("position", [0, 0])
    input_expr = _input_expression(node)

    downstream = conns.get(node_name, {}).get("main", [[]])
    downstream = downstream[0] if downstream else []

    switch_name = f"{node_name} (rules)"
    fb_name = f"{node_name} fallback ({fallback_model})"
    model_name = f"OpenAI Chat Model ({fallback_model})"

    cats = rules["categories"]
    switch = {
        "parameters": {
            "rules": {"values": [
                {
                    "conditions": {
                        "options": {"caseSensitive": False, "version": 2},
                        "conditions": [{
                            "leftValue": input_expr,
                            "rightValue": c["regex"],
                            "operator": {"type": "string", "operation": "regex"},
                        }],
                        "combinator": "and",
                    },
                    "outputKey": c["key"],
                }
                for c in cats
            ]},
            "options": {"fallbackOutput": "extra", "renameFallbackOutput": "unmatched"},
        },
        "id": _uid(), "name": switch_name,
        "type": "n8n-nodes-base.switch", "typeVersion": 3.2,
        "position": pos,
    }
    fallback = {
        "parameters": {
            "promptType": "define",
            "text": "=Classe ce texte dans exactement une categorie parmi "
                    + ", ".join(c["key"] for c in cats)
                    + f". Reponds uniquement par le mot.\n\nTexte: {{{{ {input_expr[2:-2].strip()} }}}}",
        },
        "id": _uid(), "name": fb_name,
        "type": "@n8n/n8n-nodes-langchain.chainLlm", "typeVersion": 1.4,
        "position": [pos[0] + 240, pos[1] + 200],
    }
    model = {
        "parameters": {"model": {"__rl": True, "mode": "list", "value": fallback_model}, "options": {}},
        "id": _uid(), "name": model_name,
        "type": "@n8n/n8n-nodes-langchain.lmChatOpenAi", "typeVersion": 1.2,
        "position": [pos[0] + 200, pos[1] + 400],
    }

    orphans = set()
    for src, outs in list(conns.items()):
        non_main = {k: v for k, v in outs.items() if k != "main"}
        if not non_main:
            continue
        fed = {link["node"] for branches in non_main.values() for b in branches for link in b}
        if fed and fed <= {node_name}:
            orphans.add(src)
    for o in orphans:
        conns.pop(o, None)

    dead = orphans | {node_name}
    wf["nodes"] = [n for n in nodes if n["name"] not in dead] + [switch, fallback, model]

    for src, outs in conns.items():
        for branches in outs.values():
            for branch in branches:
                for link in branch:
                    if link.get("node") == node_name:
                        link["node"] = switch_name

    conns.pop(node_name, None)
    conns[switch_name] = {"main": [list(downstream) for _ in cats] + [
        [{"node": fb_name, "type": "main", "index": 0}]
    ]}
    conns[fb_name] = {"main": [list(downstream)]}
    conns[model_name] = {"ai_languageModel": [[
        {"node": fb_name, "type": "ai_languageModel", "index": 0}
    ]]}
    wf["connections"] = conns
    return {
        "name": f"{original.get('name', 'workflow')} - patched by Deadweight",
        "nodes": wf["nodes"],
        "connections": wf["connections"],
        "settings": {"executionOrder": (original.get("settings") or {}).get("executionOrder", "v1")},
    }


def apply_regles_n8n(repo: str | Path, proposal: dict[str, Any]) -> list[str]:
    """Écrit l'original et le patché dans ``<repo>/<n8n_output_dir>/`` (défaut ``n8n-email-triage``).

    ``proposal`` doit porter : ``app_id`` (``n8n:<workflow>/<noeud>``), ``model`` (secours),
    ``n8n_workflow_path`` (le workflow original téléchargé), ``preuve.rules`` (catégories prouvées).
    """
    node_name = proposal["app_id"].split("/", 1)[1]
    rules = {"categories": proposal["preuve"]["rules"]}
    if not rules["categories"]:
        return ["aucune règle prouvée : rien à patcher"]
    original = json.loads(Path(proposal["n8n_workflow_path"]).read_text(encoding="utf-8"))
    patched = build_patched_workflow(original, node_name, rules, proposal["model"])

    out_dir = Path(repo) / proposal.get("n8n_output_dir", "n8n-email-triage")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "workflow.original.json").write_text(
        json.dumps(original, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_dir / "workflow.patched.json").write_text(
        json.dumps(patched, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return [f"nœud '{node_name}' remplacé par un Switch à {len(rules['categories'])} règles "
            f"+ secours {proposal['model']} : relire le mapping des catégories avant d'accepter"]
