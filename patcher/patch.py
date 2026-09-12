"""
Patcher Deadweight.

Le LLM ne genere PAS le JSON n8n : il extrait seulement les regles de
classification depuis les exemples reels. Python fait le montage du
workflow, de facon deterministe.

C'est exactement la these du produit appliquee a nous-memes : le LLM
la ou il apporte quelque chose, du code la ou le code suffit.

    export N8N_URL=http://localhost:5678
    export N8N_API_KEY=...
    export OPENAI_API_KEY=...
    python3 patcher/patch.py fixtures/finding.json
"""
import copy, json, os, sys, urllib.request, uuid

N8N_URL = os.environ.get("N8N_URL", "http://localhost:5678").rstrip("/")
API_KEY = os.environ.get("N8N_API_KEY", "")
INPUT_EXPR = os.environ.get("DW_INPUT_EXPR", "={{ $json.body.text }}")
FALLBACK_MODEL = os.environ.get("DW_FALLBACK_MODEL", "gpt-5-mini")


# ---------- n8n ----------
def n8n_get_workflow(workflow_id: str) -> dict:
    req = urllib.request.Request(
        f"{N8N_URL}/api/v1/workflows/{workflow_id}",
        headers={"X-N8N-API-KEY": API_KEY},
    )
    with urllib.request.urlopen(req) as r:
        return json.load(r)


# ---------- LLM : extraction des regles, rien d'autre ----------
RULES_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["categories", "coverage_estimate", "reasoning"],
    "properties": {
        "categories": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["key", "regex"],
                "properties": {
                    "key": {"type": "string"},
                    "regex": {"type": "string"},
                },
            },
        },
        "coverage_estimate": {"type": "number"},
        "reasoning": {"type": "string"},
    },
}

SYSTEM = """Tu analyses un noeud LLM d'un workflow n8n qui fait en realite de la
classification : sur N executions il n'a produit qu'une poignee de sorties distinctes.

Ta seule tache : produire, pour chaque sortie observee, une expression reguliere
qui reconnait les inputs de cette categorie.

Contraintes :
- Les regex sont derivees UNIQUEMENT des exemples fournis, jamais inventees.
- Alternatives simples separees par | , insensibles a la casse, sans ancrage.
- Une categorie par sortie observee, dans l'ordre decroissant de frequence.
- coverage_estimate est la fraction des exemples que tes regex classent correctement.
  Sois honnete : un Prover verifiera sur 100 executions reelles."""


def llm_extract_rules(finding: dict) -> dict:
    from openai import OpenAI

    ev = finding["evidence"]
    payload = {
        "observed_outputs": ev.get("output_distribution", {}),
        "samples": ev.get("samples", []),
        "node_name": finding.get("node_name"),
    }
    client = OpenAI()
    resp = client.chat.completions.create(
        model=os.environ.get("DW_PATCHER_MODEL", "gpt-5"),
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "rules", "strict": True, "schema": RULES_SCHEMA},
        },
    )
    return json.loads(resp.choices[0].message.content)


# ---------- montage deterministe ----------
def _uid() -> str:
    return str(uuid.uuid4())


def build_patched_workflow(original: dict, finding: dict, rules: dict) -> dict:
    wf = copy.deepcopy(original)
    target = finding.get("node_name")
    nodes = wf["nodes"]
    conns = wf.get("connections", {})

    node = next((n for n in nodes if n["name"] == target), None)
    if node is None:
        raise SystemExit(f"noeud '{target}' introuvable dans le workflow")
    pos = node.get("position", [0, 0])

    # ce que le noeud cible alimentait
    downstream = conns.get(target, {}).get("main", [[]])
    downstream = downstream[0] if downstream else []

    switch_name = f"{target} (rules)"
    fb_name = f"{target} fallback ({FALLBACK_MODEL})"
    model_name = f"OpenAI Chat Model ({FALLBACK_MODEL})"

    cats = rules["categories"]
    switch = {
        "parameters": {
            "rules": {"values": [
                {
                    "conditions": {
                        "options": {"caseSensitive": False, "version": 2},
                        "conditions": [{
                            "leftValue": INPUT_EXPR,
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
                    + ". Reponds uniquement par le mot.\n\nTexte: {{ $json.body.text }}",
        },
        "id": _uid(), "name": fb_name,
        "type": "@n8n/n8n-nodes-langchain.chainLlm", "typeVersion": 1.4,
        "position": [pos[0] + 240, pos[1] + 200],
    }

    model = {
        "parameters": {"model": FALLBACK_MODEL, "options": {}},
        "id": _uid(), "name": model_name,
        "type": "@n8n/n8n-nodes-langchain.lmChatOpenAi", "typeVersion": 1.2,
        "position": [pos[0] + 200, pos[1] + 400],
    }

    orphans = set()
    for src, outs in list(conns.items()):
        non_main = {k: v for k, v in outs.items() if k != "main"}
        if not non_main:
            continue
        fed = {l["node"] for branches in non_main.values() for b in branches for l in b}
        if fed and fed <= {target}:
            orphans.add(src)
    for o in orphans:
        conns.pop(o, None)

    dead = orphans | {target}
    wf["nodes"] = [n for n in nodes if n["name"] not in dead] + [switch, fallback, model]

    # amont : tout ce qui pointait vers la cible pointe vers le Switch
    for src, outs in conns.items():
        for out_type, branches in outs.items():
            for branch in branches:
                for link in branch:
                    if link.get("node") == target:
                        link["node"] = switch_name

    conns.pop(target, None)
    # une sortie de Switch par categorie + la sortie unmatched vers le fallback
    conns[switch_name] = {"main": [list(downstream) for _ in cats] + [
        [{"node": fb_name, "type": "main", "index": 0}]
    ]}
    conns[fb_name] = {"main": [list(downstream)]}
    conns[model_name] = {"ai_languageModel": [[
        {"node": fb_name, "type": "ai_languageModel", "index": 0}
    ]]}

    wf["connections"] = conns
    return {
        "name": f"{original['name']} - patched by Deadweight",
        "nodes": wf["nodes"],
        "connections": wf["connections"],
        "settings": {"executionOrder": (original.get("settings") or {}).get("executionOrder", "v1")},
    }


def main():
    finding = json.load(open(sys.argv[1] if len(sys.argv) > 1 else "fixtures/finding.json"))
    original = n8n_get_workflow(finding["workflow_id"])
    rules = llm_extract_rules(finding)
    print(f"regles extraites: {[c['key'] for c in rules['categories']]}  "
          f"couverture estimee {rules['coverage_estimate']:.0%}")

    patched = build_patched_workflow(original, finding, rules)
    patch = {
        "patch_id": "p_" + _uid()[:8],
        "finding_id": finding["finding_id"],
        "workflow_id": finding["workflow_id"],
        "strategy": "rule_switch",
        "diff_summary": f"Noeud '{finding['node_name']}' remplace par un Switch a "
                        f"{len(rules['categories'])} regles + fallback {FALLBACK_MODEL}",
        "coverage_estimate": rules["coverage_estimate"],
        "patched_workflow": patched,
    }
    os.makedirs("out", exist_ok=True)
    with open("out/patch.json", "w") as f:
        json.dump(patch, f, indent=2, ensure_ascii=False)
    print("ecrit out/patch.json  ->  python3 patcher/validate_reimport.py out/patch.json")


if __name__ == "__main__":
    main()
