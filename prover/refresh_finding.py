"""Reconstruit fixtures/finding.json depuis les executions reelles.
Provisoire : c'est le job du Collector+Detector de A."""
import json, math, os, urllib.request
from collections import Counter
U = os.environ.get("N8N_URL", "http://localhost:5678").rstrip("/")
H = {"X-N8N-API-KEY": os.environ["N8N_API_KEY"]}
f = json.load(open("fixtures/finding.json"))
wid, node = f["workflow_id"], f["node_name"]
r = urllib.request.Request(f"{U}/api/v1/executions?includeData=true&workflowId={wid}&limit=250", headers=H)
pairs = []
for ex in json.load(urllib.request.urlopen(r))["data"]:
    run = ex.get("data", {}).get("resultData", {}).get("runData", {})
    if node not in run:
        continue
    try:
        j = run[node][0]["data"]["main"][0][0]["json"]
        src = run["Webhook"][0]["data"]["main"][0][0]["json"]
        text = src.get("body", {}).get("text") or src.get("text")
        val = j.get("text") or j.get("output") or next(iter(j.values()))
        if text and val:
            pairs.append({"input": str(text), "output": str(val).strip().lower()})
    except Exception:
        continue
print(f"{len(pairs)} paires extraites")
dist = Counter(p["output"] for p in pairs)
n = sum(dist.values())
ent = -sum((c/n) * math.log2(c/n) for c in dist.values())
seen, samples = Counter(), []
for p in pairs:                       # samples equilibres par categorie
    if seen[p["output"]] < 12:
        samples.append(p); seen[p["output"]] += 1
f["evidence"] = {"calls": n, "distinct_outputs": len(dist),
                 "entropy_bits": round(ent, 2), "max_entropy_bits": round(math.log2(n), 2),
                 "output_distribution": dict(dist), "samples": samples}
f["severity"] = "cut" if len(dist) <= 4 else "trim"
json.dump(f, open("fixtures/finding.json", "w"), indent=2, ensure_ascii=False)
print("distribution:", dict(dist))
print(f"entropie {ent:.2f} bits sur {n} appels, {len(samples)} samples retenus")
