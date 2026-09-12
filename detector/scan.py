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
       "@n8n/n8n-nodes-langchain.chainSummarization", "n8n-nodes-base.openAi",
       "@n8n/n8n-nodes-langchain.openAi")

# --- regle oversized_model ---
PREMIUM_PRICE_IN = float(os.environ.get("DW_PREMIUM_PRICE_IN", "1.0"))   # $/Mtok
MAX_OUTPUT_WORDS = int(os.environ.get("DW_MAX_OUTPUT_WORDS", "8"))

PRICING = {}
for _p in ("fixtures/pricing.json", "out/pricing.json"):
    if os.path.exists(_p):
        PRICING = json.load(open(_p))
        break


def get(path):
    return json.load(urllib.request.urlopen(
        urllib.request.Request(f"{U}/api/v1{path}", headers=H)))


def norm(v):
    return " ".join(str(v).lower().split())[:200]


def first_text(j):
    m = j.get("message")
    if isinstance(m, dict) and isinstance(m.get("content"), str):
        return m["content"]
    for k in ("text", "output", "response", "content", "message"):
        if k in j and isinstance(j[k], (str, int, float)):
            return str(j[k])
    for v in j.values():
        if isinstance(v, str):
            return v
    return None


def find_node(wf, name):
    return next((n for n in wf["nodes"] if n["name"] == name), None)


def upstream_language_model(wf, node_name):
    """Trouve le noeud connecte en ai_languageModel a node_name (ex: OpenAI Chat Model)."""
    for src, conns in wf.get("connections", {}).items():
        for ctype, branches in conns.items():
            if ctype != "ai_languageModel":
                continue
            for branch in branches:
                for c in branch:
                    if c.get("node") == node_name:
                        return src
    return None


def model_name(wf, node_name, _seen=None):
    """Cherche le nom du modele: parametre direct du noeud, sinon noeud
    Chat Model connecte en amont via ai_languageModel."""
    _seen = _seen or set()
    if node_name in _seen:
        return None
    _seen.add(node_name)

    node = find_node(wf, node_name)
    if node:
        params = node.get("parameters", {})
        for key in ("model", "modelId"):
            m = params.get(key)
            if isinstance(m, dict):
                v = m.get("value") or m.get("cachedResultName")
                if v:
                    return v
            elif isinstance(m, str) and m:
                return m

    src = upstream_language_model(wf, node_name)
    if src:
        return model_name(wf, src, _seen)
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
        avg_words = sum(len(p["output"].split()) for p in pairs) / n
        out.append({"workflow": wf, "node": node, "pairs": pairs,
                    "dist": dist, "calls": n, "entropy": ent,
                    "model": model_name(wf, node) or "unknown",
                    "avg_output_words": round(avg_words, 1)})
    return out


def cheapest_model(exclude=None):
    candidates = {k: v for k, v in PRICING.items() if k != exclude}
    if not candidates:
        return None, None
    k = min(candidates, key=lambda m: candidates[m].get("in", 9e9))
    return k, candidates[k]


def make_low_entropy_finding(best):
    seen, samples = Counter(), []
    for p in best["pairs"]:
        if seen[p["output"]] < 12:
            samples.append(p)
            seen[p["output"]] += 1
    return {
        "finding_id": "f_" + str(best["workflow"]["id"])[:8] + "_ent",
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


def make_oversized_model_finding(best):
    price = PRICING.get(best["model"], {})
    cheap_name, cheap_price = cheapest_model(exclude=best["model"])
    ratio = None
    if price.get("in") and cheap_price and cheap_price.get("in"):
        ratio = round(price["in"] / cheap_price["in"], 1)
    return {
        "finding_id": "f_" + str(best["workflow"]["id"])[:8] + "_ovs",
        "workflow_id": best["workflow"]["id"],
        "workflow_name": best["workflow"]["name"],
        "node_id": next(n["id"] for n in best["workflow"]["nodes"]
                        if n["name"] == best["node"]),
        "node_name": best["node"],
        "rule": "oversized_model",
        "severity": "trim",
        "title": f"Modele premium ({best['model']}) pour une sortie contrainte",
        "evidence": {
            "calls": best["calls"], "model": best["model"],
            "avg_output_words": best["avg_output_words"],
            "price_in_per_mtok": price.get("in"), "price_out_per_mtok": price.get("out"),
            "suggested_model": cheap_name,
            "suggested_price_in_per_mtok": cheap_price.get("in") if cheap_price else None,
            "cost_ratio": ratio,
        },
        "proposed_action": f"Remplacer {best['model']} par {cheap_name or 'un modele moins cher'} "
                           f"pour ce noeud, la sortie ne justifie pas un modele premium",
    }


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

    # --- oversized_model : regle independante, basee sur modele + longueur de sortie ---
    oversized = []
    if PRICING:
        for r in results:
            price = PRICING.get(r["model"], {})
            if (price.get("in", 0) >= PREMIUM_PRICE_IN
                    and r["avg_output_words"] <= MAX_OUTPUT_WORDS):
                oversized.append(r)
        if oversized:
            print(f"\n{'WORKFLOW':30} {'NODE':22} {'MODEL':16} {'AVG WORDS':>10}  VERDICT")
            print("-" * 92)
            for r in sorted(oversized, key=lambda r: -PRICING.get(r["model"], {}).get("in", 0)):
                print(f"{r['workflow']['name'][:30]:30} {r['node'][:22]:22} "
                      f"{r['model'][:16]:16} {r['avg_output_words']:>10}  TRIM  oversized model")
    else:
        print("\nfixtures/pricing.json introuvable, regle oversized_model desactivee")

    if not flagged and not oversized:
        print(f"\naucun noeud signale (il faut >= {MIN_CALLS} executions par noeud)")
        return

    # honore le contrat Collector -> profile.json (un profil par workflow scanne)
    profiles = {}
    for r in results:
        prof = profiles.setdefault(r["workflow"]["id"], {
            "workflow_id": r["workflow"]["id"], "name": r["workflow"]["name"],
            "executions_sampled": r["calls"], "nodes": []})
        prof["nodes"].append({
            "id": next(n["id"] for n in r["workflow"]["nodes"] if n["name"] == r["node"]),
            "name": r["node"],
            "type": next(n["type"] for n in r["workflow"]["nodes"] if n["name"] == r["node"]),
            "calls": r["calls"], "distinct_outputs": len(r["dist"]),
            "entropy_bits": round(r["entropy"], 2),
            "model": r["model"], "avg_output_words": r["avg_output_words"],
            "output_samples": list(r["dist"])[:8]})
    os.makedirs("out", exist_ok=True)
    json.dump(list(profiles.values()), open("out/profile.json", "w"),
              indent=2, ensure_ascii=False)
    print(f"\nprofile.json ecrit ({len(profiles)} workflow(s))")

    findings = []
    if flagged:
        best_entropy = min(flagged, key=lambda r: r["entropy"])
        findings.append(make_low_entropy_finding(best_entropy))
    if oversized:
        best_oversized = min(oversized, key=lambda r: r["avg_output_words"])
        findings.append(make_oversized_model_finding(best_oversized))

    os.makedirs("fixtures", exist_ok=True)
    json.dump(findings, open("out/findings.json", "w"), indent=2, ensure_ascii=False)
    print(f"\n{len(findings)} finding(s) ecrit(s) dans out/findings.json")

    # compat : fixtures/finding.json garde un objet unique (le premier trouve),
    # pour ne rien casser dans prover/prove.py qui lit ce fichier tel quel.
    if findings:
        json.dump(findings[0], open("fixtures/finding.json", "w"), indent=2, ensure_ascii=False)
        print(f"fixtures/finding.json (compat) ecrit: {findings[0]['rule']} "
              f"/ {findings[0]['workflow_name']} / {findings[0]['node_name']}")
        print("-> python3 patcher/patch.py fixtures/finding.json")


if __name__ == "__main__":
    main()