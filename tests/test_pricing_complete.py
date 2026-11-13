"""Le catalogue de prix doit résoudre tous les modèles courants et ceux vus dans les jeux de données."""
import json
from pathlib import Path

import pytest

from collector.pricing import EXTRA_PATH, apply_extra
from report.cost import lookup

ROOT = Path(__file__).resolve().parents[1]
PRICES = json.loads((ROOT / "fixtures/pricing.json").read_text(encoding="utf-8"))

# Gammes courantes au 13/11/2026 (pages de prix officielles, voir fixtures/pricing.extra.json).
CURRENT_IDS = """
claude-fable-5-2 claude-fable-5-1 claude-fable-5 claude-mythos-5-2 claude-mythos-5-1 claude-mythos-5
claude-opus-5-5 claude-opus-5 claude-opus-4-8 claude-opus-4-7 claude-opus-4-6 claude-opus-4-5 claude-opus-4-1
claude-opus-4 claude-sonnet-5-5 claude-sonnet-5 claude-sonnet-4-6 claude-sonnet-4-5 claude-sonnet-4
claude-haiku-5-5 claude-haiku-4-5
gpt-6-astra gpt-6.1-sol gpt-6.1-terra gpt-6-luna gpt-6-sol gpt-5.6-sol gpt-5.6-terra gpt-5.6-luna gpt-5.5
gpt-5.5-pro gpt-5.4 gpt-5.4-pro gpt-5.4-mini gpt-5.4-nano gpt-5.2 gpt-5.2-pro gpt-5.1 gpt-5 gpt-5-mini gpt-5-nano
gpt-5-pro gpt-5.3-codex gpt-5-search-api o3-pro o3 gpt-4.1 gpt-4.1-mini gpt-4o gpt-4o-mini chat-latest
gemini-4-carbon gemini-4-argon gemini-4-hydrogen gemini-3.8-flash gemini-3.6-flash gemini-3.5-flash
gemini-3.5-flash-lite gemini-3.1-flash-lite gemini-3.1-pro-preview gemini-3-flash-preview gemini-2.5-pro
gemini-2.5-flash gemini-2.5-flash-lite
mistral-large-4-0 mistral-small-2603 mistral-medium-3-5 codestral-2508 ministral-14b-2512 ministral-8b-2512
ministral-3b-2512 mistral-large-latest mistral-small-latest mistral-medium-latest codestral-latest
ministral-8b-latest ministral-3b-latest open-mistral-nemo claude-sonnet-latest claude-opus-latest
""".split()

# Écritures différentes d'un même modèle : toutes doivent donner le même prix.
SAME_PRICE = [
    ("claude-sonnet-5-5", "anthropic/claude-sonnet-5.5"),
    ("claude-sonnet-5-5", "claude-sonnet-5.5"),
    ("claude-sonnet-5-5", "claude-sonnet-5-5-20261101"),
    ("claude-sonnet-5-5", "Claude-Sonnet-5-5"),
    ("claude-opus-5-5", "claude-opus-5-5[1m]"),
    ("claude-haiku-5-5", "anthropic/claude-haiku-5.5"),
    ("gpt-4o", "openai/gpt-4o-2024-08-06"),
    ("gpt-4.1", "gpt-4-1"),
    ("gemini-2.5-flash", "models/gemini-2.5-flash"),
    ("gemini-2.5-flash", "google/gemini-2.5-flash-001"),
]


@pytest.mark.parametrize("model", CURRENT_IDS)
def test_modeles_courants_ont_un_prix(model):
    price = lookup(PRICES, model)
    assert price and price["in"] > 0 and price["out"] > 0, f"absent du catalogue : {model}"


@pytest.mark.parametrize("a,b", SAME_PRICE)
def test_variantes_de_nom_meme_prix(a, b):
    assert lookup(PRICES, a) is not None
    assert lookup(PRICES, b) == lookup(PRICES, a)


def test_nom_inconnu_reste_inconnu():
    assert lookup(PRICES, "claude-sonnet-9-9") is None
    assert lookup(PRICES, "") is None and lookup(PRICES, None) is None


def test_jeux_de_donnees_sans_modele_absent():
    """Aucun modèle des fixtures et du jeu de données ne doit sortir « absent du catalogue »."""
    seen = set()
    for path in [*(ROOT / "fixtures").glob("*.jsonl"), *(ROOT / "fixtures/dataset").rglob("*.jsonl")]:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict) and isinstance(event.get("model"), str):
                seen.add(event["model"])
    assert seen, "aucun modèle trouvé : le test ne vérifie rien"
    assert sorted(m for m in seen if lookup(PRICES, m) is None) == []


def test_apply_extra_alias_suit_la_cible_et_modele_explicite_l_emporte():
    catalog = {"cible": {"in": 1.0, "out": 2.0}, "gpt-x": {"in": 9.0, "out": 9.0}}
    extra = {"models": {"gpt-x": {"in": 4.0, "out": 5.0, "source": "openai", "note": "n"}},
             "aliases": {"alias-latest": "cible", "alias-orphelin": "absente"}}
    out = apply_extra(catalog, extra)
    assert out["alias-latest"] == {"in": 1.0, "out": 2.0}
    assert out["gpt-x"] == {"in": 4.0, "out": 5.0}  # source et note ne vont pas dans le catalogue
    assert "alias-orphelin" not in out
    assert catalog["gpt-x"] == {"in": 9.0, "out": 9.0}  # entrée non mutée


def test_extra_bien_forme_et_present_dans_le_catalogue():
    extra = json.loads(EXTRA_PATH.read_text(encoding="utf-8"))
    for name, entry in extra["models"].items():
        assert entry["source"] in extra["_meta"]["sources"], name
        assert PRICES[name]["in"] == entry["in"] and PRICES[name]["out"] == entry["out"], name
    for alias, target in extra["aliases"].items():
        assert PRICES[alias] == PRICES[target], alias
