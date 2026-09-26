"""Catalogue de prix réel depuis OpenRouter (API publique, sans clé).

    python -m collector.pricing                       # réécrit fixtures/pricing.json
    python -m collector.pricing --out out/pricing.json

USD par million de jetons : ``in``, ``out``, et ``cached_in`` (lecture du cache) quand
OpenRouter le publie. Chaque modèle est aussi rangé sous les noms qu'emploient les API
des fournisseurs : sans préfixe (``gpt-4o``), et pour Anthropic avec des tirets
(``claude-sonnet-4-5`` pour ``claude-sonnet-4.5``). Les suffixes de date
(``claude-sonnet-4-5-20250929``) sont retirés à la recherche, dans report.cost.lookup.
"""
import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

URL = "https://openrouter.ai/api/v1/models"
DEFAULT_OUT = Path(__file__).resolve().parents[1] / "fixtures" / "pricing.json"
_VERSION_DOT = re.compile(r"(\d)\.(\d)")


def _per_million(value):
    try:
        v = float(value) * 1e6
    except (TypeError, ValueError):
        return None
    return round(v, 4) if v >= 0 else None


def aliases(model_id):
    """Noms sous lesquels les clients appellent ce modèle."""
    names = [model_id]
    if "/" in model_id:
        provider, short = model_id.split("/", 1)
        names.append(short)
        if provider == "anthropic":
            names.append(_VERSION_DOT.sub(r"\1-\2", short))  # claude-sonnet-4.5 -> claude-sonnet-4-5
    return names


def build(models):
    """Liste de modèles OpenRouter -> {nom: {in, out[, cached_in]}}. Le nom complet prime."""
    out, short = {}, {}
    for m in models:
        p = m.get("pricing") or {}
        pin, pout = _per_million(p.get("prompt")), _per_million(p.get("completion"))
        if pin is None or pout is None or (pin <= 0 and pout <= 0):
            continue
        entry = {"in": pin, "out": pout}
        cached = _per_million(p.get("input_cache_read"))
        if cached is not None and cached > 0:
            entry["cached_in"] = cached
        full, *others = aliases(m["id"])
        out[full] = entry
        for name in others:
            short.setdefault(name, entry)
    for name, entry in short.items():
        out.setdefault(name, entry)
    return out


def fetch():
    req = urllib.request.Request(URL, headers={"User-Agent": "deadweight/0.2"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)["data"]


def main(argv=None):
    ap = argparse.ArgumentParser(description="Catalogue de prix OpenRouter")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args(argv)
    try:
        models = fetch()
    except OSError as exc:
        print(f"OpenRouter injoignable ({exc}) : catalogue inchangé.", file=sys.stderr)
        return 1
    catalog = build(models)
    # un modèle retiré d'OpenRouter peut encore être appelé par un client : on garde son dernier prix
    out = Path(args.out)
    kept = 0
    if out.exists():
        for name, entry in json.loads(out.read_text(encoding="utf-8")).items():
            if name not in catalog:
                catalog[name] = entry
                kept += 1
    out.parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(catalog, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    cached = sum("cached_in" in e for e in catalog.values())
    print(f"{len(models)} modèles OpenRouter, {len(catalog)} noms ({cached} avec prix du cache, "
          f"{kept} anciens conservés) -> {args.out}")
    for k in ("gpt-4o", "claude-sonnet-4-5", "gemini-2.5-flash", "mistral-small-3.2-24b-instruct"):
        e = catalog.get(k)
        print(f"  {k:32}", f"in {e['in']:>8.3f}  out {e['out']:>8.3f}  cache {e.get('cached_in', '—')}" if e else "absent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
