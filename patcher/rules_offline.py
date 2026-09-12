import re
from collections import Counter
STOP = set("""le la les un une des du de et ou a au aux en dans pour par sur avec sans mon ma mes
ton ta tes son sa ses ce cet cette ces je tu il elle nous vous ils elles est sont ete etre ai as
ont avoir pas ne plus que qui quoi dont si comme the an of to in on for with my your it is are""".split())

def _tok(t):
    return [x for x in re.findall(r"[a-zA-ZàâäéèêëîïôöùûüçA-Za-z]{4,}", t.lower()) if x not in STOP]

def extract_rules(finding, per_cat=4):
    ev = finding["evidence"]
    samples, dist = ev.get("samples", []), ev.get("output_distribution", {})
    by = {}
    for s in samples:
        by.setdefault(s["output"], []).extend(_tok(s["input"]))
    counts = {c: Counter(t) for c, t in by.items()}
    total = Counter()
    for c in counts.values():
        total.update(c)
    cats = []
    for cat in (sorted(dist, key=dist.get, reverse=True) if dist else list(counts)):
        c = counts.get(cat)
        if not c:
            continue
        sc = sorted(c, key=lambda t: c[t] / (1 + total[t] - c[t]), reverse=True)
        kept = [re.escape(t[:-1] if t.endswith("s") else t) for t in sc[:per_cat]]
        if kept:
            cats.append({"key": cat, "regex": "|".join(dict.fromkeys(kept))})
    ok = sum(1 for s in samples if next(
        (c["key"] for c in cats if re.search(c["regex"], s["input"], re.I)), None) == s["output"])
    return {"categories": cats,
            "coverage_estimate": round(ok / len(samples), 3) if samples else 0.0,
            "reasoning": f"tokens discriminants sur {len(samples)} exemples, sans LLM"}
