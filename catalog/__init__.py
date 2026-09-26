"""M1 — Catalogue des modèles : prix (OpenRouter), origine et hébergement, latence observée.

    python -m catalog                                   # couverture du catalogue
    python -m catalog --events fixtures/dataset/v1/events.jsonl   # + latence par modèle

Tables versionnées : fixtures/pricing.json (make prices) et fixtures/providers.json (M1.1).
Rien n'est deviné : un champ inconnu vaut null, et la source de chaque fiche est citée.
"""
import json
import math
from pathlib import Path
from statistics import median

from collector.pricing import aliases
from report.cost import _DATED, PRICING_PATH, lookup

PROVIDERS_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "providers.json"
FIELDS = ("nom", "pays", "hebergement_ue", "souverain", "option_ue", "source", "date")


def load_pricing(path=PRICING_PATH):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_providers(path=PROVIDERS_PATH):
    return json.loads(Path(path).read_text(encoding="utf-8"))["editeurs"]


def _prefix(full_name):
    return full_name.split("/", 1)[0].lstrip("~")


def editor_index(pricing):
    """{nom sous lequel un client appelle le modèle: préfixe OpenRouter}. Le premier nom complet gagne."""
    index = {}
    for full in sorted(k for k in pricing if "/" in k and not k.startswith("~")):
        for name in aliases(full):
            index.setdefault(name, _prefix(full))
    return index


def editor_of(model, index):
    """Préfixe OpenRouter de l'éditeur, ou None si le modèle est inconnu du catalogue."""
    if not model:
        return None
    if "/" in model:
        return _prefix(model)
    return index.get(model) or index.get(_DATED.sub("", model))


def info(model, pricing, providers, index=None):
    """Fiche d'un modèle : prix USD/Mtok (None si hors catalogue) et fiche de son éditeur."""
    editor = editor_of(model, index if index is not None else editor_index(pricing))
    sheet = providers.get(editor) or {}
    return {"modele": model, "editeur": editor, "prix": lookup(pricing, model),
            **{f: sheet.get(f) for f in FIELDS}}


def observed_latency(events):
    """M1.3 — latence mesurée chez le client, par modèle, appels réussis seulement.

    Même p95 que report.cost : rang supérieur, sans interpolation.
    """
    by_model = {}
    for e in events:
        if e.get("error") is None and isinstance(e.get("latency_ms"), (int, float)):
            by_model.setdefault(e["model"], []).append(e["latency_ms"])
    out = {}
    for model, values in sorted(by_model.items()):
        values.sort()
        out[model] = {"n": len(values), "p50_ms": median(values),
                      "p95_ms": values[math.ceil(.95 * len(values)) - 1]}
    return out


def coverage(pricing, providers):
    """Part des modèles du catalogue de prix dont l'éditeur a une fiche ; éditeurs sans fiche."""
    fulls = [k for k in pricing if "/" in k and not k.startswith("~")]
    missing = {}
    for k in fulls:
        if _prefix(k) not in providers:
            missing[_prefix(k)] = missing.get(_prefix(k), 0) + 1
    covered = len(fulls) - sum(missing.values())
    return {"modeles": len(fulls), "couverts": covered,
            "part": covered / len(fulls) if fulls else 0.0,
            "editeurs_sans_fiche": dict(sorted(missing.items(), key=lambda kv: -kv[1]))}
