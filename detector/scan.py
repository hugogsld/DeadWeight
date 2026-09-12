"""
Deadweight scanner.

Parcourt une instance n8n, trouve les noeuds LLM, mesure l'entropie de leurs
sorties sur l'historique d'execution reel, et ecrit un finding pour le pire.

    python3 detector/scan.py            # toute l'instance
    python3 detector/scan.py <wf_id>    # un seul workflow

Aucun appel LLM : c'est de la statistique.
"""
import json, math, os, sys, urllib.request
from collections import Counter

U = os.environ.get("N8N_URL", "http://localhost:5678").rstrip("/")
H = {"X-N8N-API-KEY": os.environ["N8N_API_KEY"]}
MIN_CALLS = int(os.environ.get("DW_MIN_CALLS", "30"))
MAX_DISTINCT = int(os.environ.get("DW_MAX_DISTINCT", "8"))
LLM = ("@n8n/n8n-nodes-langchain.chainLlm", "@n8n/n8n-nodes-langchain.agent",
       "@n8n/n8n-nodes-langchain.chainSummarization", "n8n-nodes-base.openAi")


def get(path):
    return json.load(urllib.request.urlopen(
        urllib.request.Request(f"{U}/api/v1{path}", headers=H)))


def norm(v):
    return " ".join(str(v).lower().split())[:200]


def first_text(j):
    for k in ("text", "output", "response", "content", "message"):
        if k in j and isinstance(j[k], (str, int, float)):
            return str(j[k])
    for v in j.values():
        if isinstance(v, str):
            return v
    return None


def scan_workflow(wf):
    llm_nodes = [n["name"] for n in wf["nodes"] if n["type"] in LLM]
    if not llm_nodes:
        return []
    try:
        exs = get(f"/executions?includeData=true&workflowId={wf['id']}&limit=250")["data"]
    except Exception:
        return []

    trigger = next((n["name"] for n in wf["nodes"]
                    if n["type"].endswith(".webhook")
                    or n["type"].lower().endswith("trigger")), None)
    out = []
    for node in llm_nodes:
        pairs = []
        for ex in exs:
            run = ex.get("data", {}).get("resultData", {}).get("runData", {})
            if node not in run:
                continue
            try:
                j = run[node][0]["data"]["main"][0][0]["json"]
                val = first_text(j)
                src = run.get(trigger, [{}])[0].get("data", {}).get("main", [[{}]])[0][0]["json"]
                txt = (src.get("body") or {}).get("text") or src.get("text") or first_text(src)
                if val and txt:
                    pairs.append({"input": str(txt), "output": norm(val)})
            except Exception:
                continue
        if len(pairs) < MIN_CALLS:
            continue
        dist = Counter(p["output"] for p in pairs)
        n = sum(dist.values())
        ent = -sum((c / n) * math.log2(c / n) for c in dist.values())
        out.append({"workflow": wf, "node": node, "pairs": pairs,
                    "dist": dist, "calls": n, "entropy": ent})
    return out


def main():
    wfs = ([get(f"/workflows/{sys.argv[1]}")] if len(sys.argv) > 1
           else get("/workflows?limit=100")["data"])
    print(f"{len(wfs)} workflow(s) a scanner\n")

    results = []
    for wf in wfs:
        results += scan_workflow(wf)

    print(f"{'WORKFLOW':30} {'NODE':22} {'CALLS':>6} {'OUT':>4} {'ENTROPY':>12}  VERDICT")
    print("-" * 92)
    flagged = []
    for r in sorted(results, key=lambda r: r["entropy"]):
        d = len(r["dist"])
        hit = d <= MAX_DISTINCT
        v = ("CUT   replaceable by rules" if d <= 4 else
             "TRIM  oversized model") if hit else "keep"
        ent = f"{r['entropy']:.2f}/{math.log2(r['calls']):.2f}"
        print(f"{r['workflow']['name'][:30]:30} {r['node'][:22]:22} "
              f"{r['calls']:>6} {d:>4} {ent:>12}  {v}")
        if hit:
            flagged.append(r)

    if not flagged:
        print(f"\naucun noeud signale (il faut >= {MIN_CALLS} executions par noeud)")
        return

    best = min(flagged, key=lambda r: r["entropy"])
    seen, samples = Counter(), []
    for p in best["pairs"]:
        if seen[p["output"]] < 12:
            samples.append(p)
            seen[p["output"]] += 1

    finding = {
        "finding_id": "f_" + str(best["workflow"]["id"])[:8],
        "workflow_id": best["workflow"]["id"],
        "workflow_name": best["workflow"]["name"],
        "node_id": next(n["id"] for n in best["workflow"]["nodes"]
                        if n["name"] == best["node"]),
        "node_name": best["node"],
        "rule": "low_entropy_output",
        "severity": "cut" if len(best["dist"]) <= 4 else "trim",
        "title": "Ce noeud LLM est un aiguillage deguise en agent",
        "evidence": {
            "calls": best["calls"], "distinct_outputs": len(best["dist"]),
            "entropy_bits": round(best["entropy"], 2),
            "max_entropy_bits": round(math.log2(best["calls"]), 2),
            "output_distribution": dict(best["dist"]), "samples": samples,
        },
        "proposed_action": "Remplacer par un Switch deterministe, avec un petit "
                           "modele en fallback pour les cas non couverts",
    }
    json.dump(finding, open("fixtures/finding.json", "w"), indent=2, ensure_ascii=False)
    print(f"\nfinding ecrit: {best['workflow']['name']} / {best['node']}")
    print("-> python3 patcher/patch.py fixtures/finding.json")


if __name__ == "__main__":
    main()
