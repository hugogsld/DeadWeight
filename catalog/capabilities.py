"""M2 — capacités des modèles depuis OpenRouter (API publique, sans clé).

    python -m catalog.capabilities      # réécrit fixtures/capabilities.json

Par nom complet OpenRouter : contexte, outils, sortie JSON, entrée image. Un modèle
absent de la table n'est jamais recommandé : on ne peut pas vérifier qu'il convient.
"""
import json
import sys
from pathlib import Path

from collector.pricing import fetch

CAPABILITIES_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "capabilities.json"


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
            "json": bool({"response_format", "structured_outputs"} & params),
            "images": "image" in ((m.get("architecture") or {}).get("input_modalities") or []),
        }
    return out


def load(path=CAPABILITIES_PATH):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main():
    try:
        models = fetch()
    except OSError as exc:
        print(f"OpenRouter injoignable ({exc}) : capacités inchangées.", file=sys.stderr)
        return 1
    table = build(models)
    CAPABILITIES_PATH.write_text(json.dumps(table, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{len(table)} modèles, {sum(c['outils'] for c in table.values())} avec outils -> {CAPABILITIES_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
