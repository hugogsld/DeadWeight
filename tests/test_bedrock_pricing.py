"""Tarifs Bedrock (lus dans le catalogue public AWS Price List) et formes de journal tolérées."""
import json
from pathlib import Path

import pytest

from connectors.bedrock_logs import lire
from report.cost import bedrock_name, chiffrer, lookup, scoped_price

ROOT = Path(__file__).resolve().parents[1]
BEDROCK = json.loads((ROOT / "fixtures/pricing.bedrock.json").read_text())["models"]


def test_prix_lus_dans_le_catalogue_aws():
    sonnet = BEDROCK["claude-sonnet-5-5"]
    assert (sonnet["in"], sonnet["out"], sonnet["cached_in"]) == (2.2, 11.0, 0.11)
    assert (sonnet["global"]["in"], sonnet["global"]["out"]) == (2.0, 10.0)
    assert "claude-3-5-sonnet-v2" not in BEDROCK and "claude-instant" not in BEDROCK


def test_batch_est_la_moitie_du_tarif_standard_quand_il_existe():
    batch = {m: p for m, p in BEDROCK.items() if "batch_in" in p}
    assert batch, "aucun tarif batch lu"
    for model, price in batch.items():
        assert price["batch_in"] == pytest.approx(price["in"] / 2), model
        assert price["batch_out"] == pytest.approx(price["out"] / 2), model


def test_profil_global_jamais_plus_cher_et_10_pour_cent_de_moins_sur_les_recents():
    pairs = [(p, p["global"]) for p in BEDROCK.values() if "global" in p]
    ratios = {round(r["in"] / g["in"], 2) for r, g in pairs}
    assert ratios == {1.0, 1.1}  # Sonnet 4 et plus anciens : même prix ; modèles récents : +10 % en régional
    assert all(r["out"] >= g["out"] for r, g in pairs)


def test_aucun_tarif_flex_ni_priority_pour_claude():
    assert not any(k.startswith(("flex", "priority")) for p in BEDROCK.values() for k in p)


@pytest.mark.parametrize("model,name", [("eu.amazon.nova-pro-v1:0", "nova-pro"),
                                        ("meta.llama3-3-70b-instruct-v1:0", "llama3-3-70b-instruct")])
def test_editeurs_non_anthropic_normalises(model, name):
    assert bedrock_name(model) == name


def test_profil_global_prend_le_tarif_global():
    price = lookup(BEDROCK, "global.anthropic.claude-sonnet-4-5-20250929-v1:0")
    assert scoped_price(price, "global.anthropic.claude-sonnet-4-5-20250929-v1:0")["in"] == 3.0
    assert scoped_price(price, "eu.anthropic.claude-sonnet-4-5-20250929-v1:0")["in"] == 3.3
    assert scoped_price(price, "anthropic.claude-sonnet-4-5-20250929-v1:0")["in"] == 3.3


def _record(model, usage=None, input_extra=None, body_usage=None):
    inp = {"inputContentType": "application/json", "inputBodyJson": {"messages": [{"role": "user", "content": [{"text": "x"}]}]},
           **(input_extra or {})}
    out = {"outputContentType": "application/json", "outputTokenCount": 10,
           "outputBodyJson": {"output": {"message": {"role": "assistant", "content": [{"text": "y"}]}},
                              "stopReason": "end_turn", "usage": body_usage or {}, "metrics": {"latencyMs": 100}}}
    return {"schemaType": "ModelInvocationLog", "schemaVersion": "1.0", "timestamp": "2026-11-12T09:00:00Z",
            "accountId": "123456789012", "region": "eu-west-1", "requestId": "r1", "operation": "Converse",
            "modelId": model, "identity": {"arn": "arn:aws:sts::123456789012:assumed-role/r/s"}, "input": inp, "output": out}


def _read(tmp_path, record):
    (tmp_path / "r.json").write_text(json.dumps(record))
    events, report = lire(tmp_path)
    return events[0], report


def test_forme_a_compteurs_dans_input(tmp_path):
    rec = _record("eu.anthropic.claude-sonnet-4-5-20250929-v1:0",
                  input_extra={"inputTokenCount": 50, "cacheReadInputTokenCount": 300, "cacheWriteInputTokenCount": 20})
    e, _ = _read(tmp_path, rec)
    assert e["usage"]["input_tokens"] == 50 and e["usage"]["cached_input_tokens"] == 300
    assert e["usage"]["cache_write_input_tokens"] == 20


def test_forme_b_compteurs_seulement_dans_le_corps(tmp_path):
    rec = _record("eu.anthropic.claude-sonnet-4-5-20250929-v1:0", input_extra={},
                  body_usage={"inputTokens": 50, "outputTokens": 10, "totalTokens": 380,
                              "cacheReadInputTokens": 300, "cacheWriteInputTokens": 20})
    e, _ = _read(tmp_path, rec)
    assert e["usage"]["input_tokens"] == 50 and e["usage"]["cached_input_tokens"] == 300
    assert e["usage"]["cache_write_input_tokens"] == 20


def test_ecritures_1h_depuis_cachedetails(tmp_path):
    rec = _record("global.anthropic.claude-sonnet-5-5", input_extra={"inputTokenCount": 5, "cacheReadInputTokenCount": 0, "cacheWriteInputTokenCount": 1000},
                  body_usage={"cacheDetails": [{"ttl": "1h", "inputTokens": 600}, {"ttl": "5m", "inputTokens": 400}]})
    e, _ = _read(tmp_path, rec)
    assert e["usage"]["cache_write_1h_input_tokens"] == 600
    wide = dict(e, ts_end="2026-11-14T00:00:00Z")
    base = dict(wide, usage={**e["usage"], "cache_write_1h_input_tokens": 0})
    # 600 jetons passent de 2,5 à 4,0 $/M (profil global)
    gap = chiffrer([wide])["cout_mensuel_usd"] - chiffrer([base])["cout_mensuel_usd"]
    assert gap > 0


def test_compteurs_divergents_signales(tmp_path):
    rec = _record("anthropic.claude-3-haiku-20240307-v1:0", input_extra={"inputTokenCount": 380},
                  body_usage={"inputTokens": 80, "outputTokens": 10})
    _, report = _read(tmp_path, rec)
    assert report["compteurs_jetons_divergents"] == 1
    assert any("diffère" in n for n in report["limites"])


def test_cout_profil_global_inferieur_au_regional(tmp_path):
    def cost(model):
        rec = _record(model, input_extra={"inputTokenCount": 1000, "cacheReadInputTokenCount": 0})
        e, _ = _read(tmp_path, rec)
        e = dict(e, ts_end="2026-11-14T00:00:00Z")
        return chiffrer([e])["cout_mensuel_usd"]
    assert cost("global.anthropic.claude-sonnet-4-5-20250929-v1:0") < cost("eu.anthropic.claude-sonnet-4-5-20250929-v1:0")
