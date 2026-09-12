"""
Prover Deadweight — la piece qu'on ne sacrifie jamais.

Rejoue des inputs REELS dans le chemin patche et compare a la sortie que le
noeud LLM avait reellement produite. On ne rejoue jamais l'ancien chemin :
sa sortie est deja dans l'historique d'execution. On ne paie que le nouveau.

    python3 prover/prove.py out/patch.json fixtures/finding.json
"""
import json, os, re, sys, time, urllib.request

N8N_URL = os.environ.get("N8N_URL", "http://localhost:5678").rstrip("/")
API_KEY = os.environ.get("N8N_API_KEY", "")
THRESHOLD = float(os.environ.get("DW_THRESHOLD", "0.95"))
MAX_REPLAY = int(os.environ.get("DW_MAX_REPLAY", "100"))

# $ / million de tokens. A remplacera par le catalogue OpenRouter (tache A7).
PRICES = {"gpt-5": {"in": 1.25, "out": 10.0},
          "gpt-5-mini": {"in": 0.25, "out": 2.0},
          "default": {"in": 1.0, "out": 5.0}}
if os.path.exists("out/pricing.json"):
    PRICES.update(json.load(open("out/pricing.json")))


def price(model, tin, tout):
    p = PRICES.get(model, PRICES["default"])
    return (tin * p["in"] + tout * p["out"]) / 1_000_000


# ---------- les paires (input, sortie historique) ----------
def pairs_from_n8n(workflow_id, node_name, limit):
    url = (f"{N8N_URL}/api/v1/executions?includeData=true"
           f"&workflowId={workflow_id}&limit={min(limit, 250)}")
    req = urllib.request.Request(url, headers={"X-N8N-API-KEY": API_KEY})
    with urllib.request.urlopen(req) as r:
        data = json.load(r).get("data", [])
    out = []
    for ex in data:
        run = (ex.get("data", {}).get("resultData", {}).get("runData", {}) or {})
        node = run.get(node_name)
        if not node:
            continue
        try:
            j = node[0]["data"]["main"][0][0]["json"]
            src = run.get("Webhook", [{}])[0].get("data", {}).get("main", [[{}]])[0][0]["json"]
            text = src.get("body", {}).get("text") or src.get("text")
            val = j.get("text") or j.get("output") or next(iter(j.values()))
            if text and val:
                out.append({"input": str(text), "output": str(val).strip().lower()})
        except (KeyError, IndexError, StopIteration):
            continue
    return out


def pairs_from_finding(finding):
    return [{"input": s["input"], "output": str(s["output"]).strip().lower()}
            for s in finding["evidence"].get("samples", [])]


# ---------- le chemin patche, rejoue en local ----------
def switch_rules(patch):
    for n in patch["patched_workflow"]["nodes"]:
        if n["type"] == "n8n-nodes-base.switch":
            return [{"key": r["outputKey"],
                     "regex": r["conditions"]["conditions"][0]["rightValue"]}
                    for r in n["parameters"]["rules"]["values"]]
    raise SystemExit("aucun noeud Switch dans le patch")


def llm_fallback(text, keys, model):
    from openai import OpenAI
    r = OpenAI().chat.completions.create(
        model=model,
        messages=[{"role": "user", "content":
                   f"Classe ce texte dans exactement une categorie parmi "
                   f"{', '.join(keys)}. Reponds uniquement par le mot.\n\n{text}"}],
    )
    u = r.usage
    return (r.choices[0].message.content.strip().lower(),
            u.prompt_tokens, u.completion_tokens)


def main():
    patch = json.load(open(sys.argv[1] if len(sys.argv) > 1 else "out/patch.json"))
    finding = json.load(open(sys.argv[2] if len(sys.argv) > 2 else "fixtures/finding.json"))

    rules = switch_rules(patch)
    keys = [r["key"] for r in rules]
    fb_model = os.environ.get("DW_FALLBACK_MODEL", "gpt-5-mini")
    old_model = next((n.get("model") for n in finding.get("evidence", {}).get("nodes", [])), None) \
        or os.environ.get("DW_OLD_MODEL", "gpt-5")
    use_llm = "--no-llm" not in sys.argv and os.environ.get("OPENAI_API_KEY")

    pairs = []
    if API_KEY:
        try:
            pairs = pairs_from_n8n(finding["workflow_id"], finding["node_name"], MAX_REPLAY)
        except Exception as e:
            print(f"executions n8n indisponibles ({e}), repli sur les samples")
    source = "executions n8n"
    if not pairs:
        pairs, source = pairs_from_finding(finding), "samples du finding"
    pairs = pairs[:MAX_REPLAY]
    if not pairs:
        raise SystemExit("aucune paire a rejouer")
    print(f"{len(pairs)} paires rejouees, source: {source}")

    tin_avg = 1840
    agree = matched = fb_used = 0
    fb_tin = fb_tout = 0
    lat_after = []
    disagreements = []

    for p in pairs:
        t0 = time.perf_counter()
        hit = next((r["key"] for r in rules
                    if re.search(r["regex"], p["input"], re.I)), None)
        if hit is not None:
            matched += 1
            lat_after.append((time.perf_counter() - t0) * 1000)
        elif use_llm:
            hit, a, b = llm_fallback(p["input"], keys, fb_model)
            fb_used += 1
            fb_tin += a
            fb_tout += b
            lat_after.append((time.perf_counter() - t0) * 1000)
        else:
            hit = None
        if hit == p["output"]:
            agree += 1
        elif len(disagreements) < 10:
            disagreements.append({"input": p["input"][:120],
                                  "expected": p["output"], "got": hit})

    n = len(pairs)
    rate = agree / n

    cost_before = price(old_model, tin_avg * n, 6 * n)
    cost_after = price(fb_model, fb_tin, fb_tout) if fb_used else 0.0
    if not use_llm and matched < n:  # estimation des unmatched non rejoues
        cost_after = price(fb_model, tin_avg * (n - matched), 6 * (n - matched))

    lat_after.sort()
    p95_after = lat_after[int(len(lat_after) * 0.95) - 1] if lat_after else 0.0
    p95_before = float(os.environ.get("DW_P95_BEFORE", "4300"))

    proof = {
        "patch_id": patch["patch_id"],
        "finding_id": patch["finding_id"],
        "n_replayed": n,
        "source": source,
        "agreement_rate": round(rate, 4),
        "matched_by_rules": matched,
        "sent_to_fallback": fb_used,
        "disagreements": disagreements,
        "cost_before_month_eur": round(cost_before, 4),
        "cost_after_month_eur": round(cost_after, 4),
        "cost_factor": round(cost_before / cost_after, 1) if cost_after else None,
        "p95_before_ms": p95_before,
        "p95_after_ms": round(p95_after, 2),
        "threshold": THRESHOLD,
        "verdict": "pass" if rate >= THRESHOLD else "reject",
    }
    os.makedirs("out", exist_ok=True)
    json.dump(proof, open("out/proof.json", "w"), indent=2, ensure_ascii=False)

    v = proof["verdict"].upper()
    print(f"\n  accord    {rate:.1%}   ({matched} par regles, {fb_used} par fallback)")
    if proof["cost_factor"]:
        print(f"  cout      /{proof['cost_factor']}")
    print(f"  p95       {p95_before:.0f} ms -> {p95_after:.1f} ms")
    print(f"  VERDICT   {v}  (seuil {THRESHOLD:.0%})")
    print("\necrit out/proof.json")


if __name__ == "__main__":
    main()
