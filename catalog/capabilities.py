"""M2 — capacités des modèles depuis OpenRouter (API publique, sans clé).

    python -m catalog.capabilities      # réécrit fixtures/capabilities.json

Par nom complet OpenRouter : contexte, outils, sortie JSON, entrée image, raisonnement.
Ces valeurs sont l'union de tous les hébergeurs du modèle, et son prix affiché est celui du
moins cher d'entre eux, souvent un hébergeur tiers. Pour les éditeurs qui servent leurs
modèles eux-mêmes (route_openrouter dans fixtures/providers.json), on garde aussi la route
de l'éditeur : son prix et ses capacités à elle, les seuls qui valent pour une option
« même éditeur » ou « souveraine ». Un modèle absent de la table n'est jamais recommandé.
"""
import json
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from catalog import load_providers
from collector.pricing import _per_million, fetch

CAPABILITIES_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "capabilities.json"
ENDPOINTS_URL = "https://openrouter.ai/api/v1/models/{}/endpoints"
REASONING = {"reasoning", "include_reasoning"}
JSON_PARAMS = {"response_format", "structured_outputs"}


def build(models):
    out = {}
    for m in models:
        params = set(m.get("supported_parameters") or [])
        context = m.get("context_length") or (m.get("top_provider") or {}).get("context_length")
        if not isinstance(context, int) or context <= 0:
            continue
        out[m["id"]] = {
            "contexte": context,
            "outils": "tools" in params,
            "json": bool(JSON_PARAMS & params),
            "images": "image" in ((m.get("architecture") or {}).get("input_modalities") or []),
            "raisonnement": bool(REASONING & params),
            "route_editeur": None,
        }
    return out


def editor_route(endpoints, names, images):
    """Route de l'éditeur parmi les hébergeurs. Plusieurs offres : la plus chère (prudent)."""
    routes = []
    for e in endpoints:
        if e.get("provider_name") not in names:
            continue
        p = e.get("pricing") or {}
        pin, pout = _per_million(p.get("prompt")), _per_million(p.get("completion"))
        context = e.get("context_length")
        if pin is None or pout is None or not isinstance(context, int) or context <= 0:
            continue
        params = set(e.get("supported_parameters") or [])
        routes.append({"in": pin, "out": pout, "contexte": context, "outils": "tools" in params,
                       "json": bool(JSON_PARAMS & params), "images": images,
                       "hebergeur": e["provider_name"]})
    return max(routes, key=lambda r: (r["in"], r["out"])) if routes else None


def _endpoints(model_id):
    req = urllib.request.Request(ENDPOINTS_URL.format(model_id), headers={"User-Agent": "deadweight/0.2"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)["data"]["endpoints"]


def load(path=CAPABILITIES_PATH):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main():
    try:
        models = fetch()
    except OSError as exc:
        print(f"OpenRouter injoignable ({exc}) : capacités inchangées.", file=sys.stderr)
        return 1
    table = build(models)
    routes = {k: v["route_openrouter"] for k, v in load_providers().items() if v.get("route_openrouter")}
    todo = [m for m in table if m.split("/", 1)[0] in routes]

    def one(model_id):
        try:
            return model_id, _endpoints(model_id)
        except (OSError, KeyError, ValueError):
            return model_id, None

    failed = 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        for model_id, endpoints in pool.map(one, todo):
            if endpoints is None:
                failed += 1
                continue
            table[model_id]["route_editeur"] = editor_route(
                endpoints, routes[model_id.split("/", 1)[0]], table[model_id]["images"])
    CAPABILITIES_PATH.write_text(json.dumps(table, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    with_route = sum(1 for v in table.values() if v["route_editeur"])
    print(f"{len(table)} modèles, {with_route} avec la route de leur éditeur"
          f"{f', {failed} route(s) illisible(s)' if failed else ''} -> {CAPABILITIES_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
