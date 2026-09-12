"""Catalogue de prix reel depuis OpenRouter -> out/pricing.json
Le Prover le charge automatiquement s'il existe."""
import json, os, urllib.request

req = urllib.request.Request("https://openrouter.ai/api/v1/models",
                             headers={"User-Agent": "deadweight/0.1"})
models = json.load(urllib.request.urlopen(req))["data"]

out = {}
for m in models:
    p = m.get("pricing") or {}
    try:
        pin, pout = float(p.get("prompt") or 0) * 1e6, float(p.get("completion") or 0) * 1e6
    except (TypeError, ValueError):
        continue
    if pin <= 0 and pout <= 0:
        continue
    entry = {"in": round(pin, 4), "out": round(pout, 4)}
    out[m["id"]] = entry
    if "/" in m["id"]:
        out.setdefault(m["id"].split("/", 1)[1], entry)

os.makedirs("out", exist_ok=True)
json.dump(out, open("out/pricing.json", "w"), indent=1, sort_keys=True)
print(f"{len(models)} modeles lus, {len(out)} entrees -> out/pricing.json")
for k in ("gpt-5", "gpt-5-mini", "gpt-4o-mini"):
    e = out.get(k)
    print(f"  {k:14}", f"in {e['in']:>8.3f} $/Mtok   out {e['out']:>8.3f}" if e else "absent")
