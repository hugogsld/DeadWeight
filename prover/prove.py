"""
Prover Deadweight.

Rejoue des inputs REELS dans le chemin patche et compare a la sortie que le
noeud LLM avait reellement produite. On ne rejoue jamais l'ancien chemin :
sa sortie et sa latence sont deja dans l'historique d'execution.

    python3 prover/prove.py out/patch.json fixtures/finding.json
"""
import json, os, re, sys, time, urllib.request

N8N_URL = os.environ.get("N8N_URL", "http://localhost:5678").rstrip("/")
API_KEY = os.environ.get("N8N_API_KEY", "")
THRESHOLD = float(os.environ.get("DW_THRESHOLD", "0.95"))
MAX_REPLAY = int(os.environ.get("DW_MAX_REPLAY", "100"))

PRICES = {"gpt-5": {"in": 1.25, "out": 10.0},
          "gpt-4o-mini": {"in": 0.15, "out": 0.60},
          "gpt-5-mini": {"in": 0.25, "out": 2.0},
          "default": {"in": 1.0, "out": 5.0}}
if os.path.exists("out/pricing.json"):
    PRICES.update(json.load(open("out/pricing.json")))


def price(model, tin, tout):
    p = PRICES.get(model, PRICES["default"])
    return (tin * p["in"] + tout * p["out"]) / 1_000_000


def pct(values, q=0.95):
    if not values:
        return None
    s = sorted(values)
    i = min(len(s) - 1, max(0, int(round(q * len(s))) - 1))
    return s[i]


def first_text(j):
    m = j.get("message")
    if isinstance(m, dict) and isinstance(m.get("content"), str):
        return m["content"]
    for k in ("text", "output", "response", "content"):
        if isinstance(j.get(k), (str, int, float)):
            return str(j[k])
    for v in j.values():
        if isinstance(v, str):
            return v
    return None


def from_n8n(workflow_id, node_name, limit):
    """Paires (input, sortie) ET latences reelles du noeud, depuis l'historique."""
    wf = json.load(urllib.request.urlopen(urllib.request.Request(
        f"{N8N_URL}/api/v1/workflows/{workflow_id}",
        headers={"X-N8N-API-KEY": API_KEY})))
    # le noeud d'entree : trigger ou webhook, quel que soit son nom
    trigger = next((n["name"] for n in wf["nodes"]
                    if n["type"].endswith(".webhook")
                    or n["type"].lower().endswith("trigger")), None)

    url = (f"{N8N_URL}/api/v1/executions?includeData=true"
           f"&workflowId={workflow_id}&limit={min(limit, 250)}")
    data = json.load(urllib.request.urlopen(urllib.request.Request(
        url, headers={"X-N8N-API-KEY": API_KEY}))).get("data", [])

    pairs, lat = [], []
    for ex in data:
        run = (ex.get("data", {}).get("resultData", {}).get("runData", {}) or {})
        node = run.get(node_name)
        if not node:
            continue
        ms = node[0].get("executionTime")
        if isinstance(ms, (int, float)):
            lat.append(float(ms))
        try:
            val = first_text(node[0]["data"]["main"][0][0]["json"])
            src = run.get(trigger, [{}])[0]["data"]["main"][0][0]["json"]
            txt = (src.get("body") or {}).get("text") or src.get("text") or first_text(src)
            if val and txt:
                pairs.append({"input": str(txt), "output": str(val).strip().lower()})
        except (KeyError, IndexError, TypeError):
            continue
    return pairs, lat


def switch_rules(patch):
    for n in patch["patched_workflow"]["nodes"]:
        if n["type"] == "n8n-nodes-base.switch":
            return [{"key": r["outputKey"],
                     "regex": r["conditions"]["conditions"][0]["rightValue"]}
                    for r in n["parameters"]["rules"]["values"]]
    raise SystemExit("aucun noeud Switch dans le patch")


def llm_fallback(text, keys, model):
    from openai import OpenAI
    r = OpenAI().chat.completions.create(model=model, messages=[{"role": "user",
        "content": f"Classe ce texte dans exactement une categorie parmi "
                   f"{', '.join(keys)}. Reponds uniquement par le mot.\n\n{text}"}])
    u = r.usage
    return (r.choices[0].message.content.strip().lower(),
            u.prompt_tokens, u.completion_tokens)


def main():
    patch = json.load(open(sys.argv[1] if len(sys.argv) > 1 else "out/patch.json"))
    finding = json.load(open(sys.argv[2] if len(sys.argv) > 2 else "fixtures/finding.json"))
    rules = switch_rules(patch)
    keys = [r["key"] for r in rules]
    fb_model = os.environ.get("DW_FALLBACK_MODEL", "gpt-5-mini")
    old_model = os.environ.get("DW_OLD_MODEL", "gpt-5")
    use_llm = "--no-llm" not in sys.argv and bool(os.environ.get("OPENAI_API_KEY"))

    pairs, lat_before = [], []
    source = "executions n8n"
    if API_KEY:
        try:
            pairs, lat_before = from_n8n(finding["workflow_id"],
                                         finding["node_name"], MAX_REPLAY)
        except Exception as e:
            print(f"historique n8n illisible ({e})")
    if not pairs:
        pairs = [{"input": s["input"], "output": str(s["output"]).strip().lower()}
                 for s in finding["evidence"].get("samples", [])]
        source = "samples extraits par le scanner"
    pairs = pairs[:MAX_REPLAY]
    if not pairs:
        raise SystemExit("aucune paire a rejouer")
    print(f"{len(pairs)} paires rejouees, source: {source}")
    if lat_before:
        print(f"latence du noeud d'origine mesuree sur {len(lat_before)} executions")

    tin_avg = int(finding.get("evidence", {}).get("prompt_tokens_avg") or 1200)
    agree = matched = fb_used = fb_tin = fb_tout = 0
    lat_rules, lat_fb, disagreements = [], [], []

    for p in pairs:
        t0 = time.perf_counter()
        hit = next((r["key"] for r in rules
                    if re.search(r["regex"], p["input"], re.I)), None)
        if hit is not None:
            matched += 1
            lat_rules.append((time.perf_counter() - t0) * 1000)
        elif use_llm:
            hit, a, b = llm_fallback(p["input"], keys, fb_model)
            fb_used += 1
            fb_tin += a
            fb_tout += b
            lat_fb.append((time.perf_counter() - t0) * 1000)
        if hit == p["output"]:
            agree += 1
        elif len(disagreements) < 10:
            disagreements.append({"input": p["input"][:120],
                                  "expected": p["output"], "got": hit})

    n = len(pairs)
    rate = agree / n
    cost_before = price(old_model, tin_avg * n, 8 * n)
    cost_after = (price(fb_model, fb_tin, fb_tout) if fb_used
                  else price(fb_model, tin_avg * (n - matched), 8 * (n - matched)))

    proof = {
        "patch_id": patch["patch_id"], "finding_id": patch["finding_id"],
        "workflow_name": finding.get("workflow_name"),
        "node_name": finding.get("node_name"),
        "n_replayed": n, "source": source,
        "agreement_rate": round(rate, 4),
        "matched_by_rules": matched, "sent_to_fallback": fb_used,
        "rules_coverage": round(matched / n, 4),
        "disagreements": disagreements,
        "cost_before_month_eur": round(cost_before, 4),
        "cost_after_month_eur": round(cost_after, 4),
        "cost_factor": round(cost_before / cost_after, 1) if cost_after else None,
        "latency_measured": bool(lat_before),
        "p95_before_ms": round(pct(lat_before), 1) if lat_before else None,
        "median_before_ms": round(pct(lat_before, .5), 1) if lat_before else None,
        "p95_rules_path_ms": round(pct(lat_rules), 2) if lat_rules else None,
        "threshold": THRESHOLD,
        "verdict": "pass" if rate >= THRESHOLD else "reject",
    }
    os.makedirs("out", exist_ok=True)
    json.dump(proof, open("out/proof.json", "w"), indent=2, ensure_ascii=False)

    print(f"\n  accord    {rate:.1%}   ({matched} par regles, {fb_used} par fallback)")
    print(f"  couvert   {matched/n:.0%} des inputs traites sans aucun modele")
    if proof["cost_factor"]:
        print(f"  cout      /{proof['cost_factor']}")
    if lat_before:
        print(f"  latence   noeud d'origine p95 {proof['p95_before_ms']:.0f} ms "
              f"(mediane {proof['median_before_ms']:.0f} ms), mesuree")
        print(f"            chemin par regles p95 {proof['p95_rules_path_ms']} ms")
    else:
        print("  latence   non mesuree (pas d'executions lisibles)")
    print(f"  VERDICT   {proof['verdict'].upper()}  (seuil {THRESHOLD:.0%})\n")


if __name__ == "__main__":
    main()
