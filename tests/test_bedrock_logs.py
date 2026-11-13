"""Connecteur Bedrock : journaux d'invocation → événements v1.

Fixtures SYNTHÉTIQUES (fixtures/bedrock, écrites d'après la doc AWS, pas capturées chez un client) :
les formes de flux et les champs de cache restent à valider sur un vrai journal.
"""
import gzip
import json
import shutil
import zipfile
from pathlib import Path

import jsonschema
import pytest

from connectors.bedrock_logs import SourceError, lire
from connectors.bedrock_logs.__main__ import main
from report.audit import build_report
from report.cost import bedrock_name, chiffrer, lookup

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "fixtures/bedrock"
SCHEMA = json.loads((ROOT / "schemas/event.schema.json").read_text())
PRICES = json.loads((ROOT / "fixtures/pricing.json").read_text())


@pytest.fixture(scope="module")
def s3():
    return lire(FIX / "s3")


@pytest.fixture(scope="module")
def cw():
    return lire(FIX / "cloudwatch")


def ev(events, request_id):
    return next(e for e in events if e["event_id"] == f"bedrock-{request_id}")


def test_tous_les_evenements_respectent_le_schema(s3, cw):
    for e in s3[0] + cw[0]:
        jsonschema.validate(e, SCHEMA)


def test_ligne_malformee_comptee_et_dite(s3):
    events, report = s3
    assert len(events) == 6
    assert report["ignores"] == {"ligne illisible ou qui n'est pas un enregistrement d'invocation": 1}


def test_converse_multi_tour_avec_outil(s3):
    events, _ = s3
    first, second = ev(events, "req-0001"), ev(events, "req-0002")
    assert first["response"]["tool_calls"] == [
        {"id": "tu_1", "name": "lookup_policy", "arguments": '{"policy_id": "P-8841"}'}]
    assert first["response"]["finish_reason"] == "tool_calls"
    assert first["request"]["system"].startswith("Tu instruis")
    assert first["request"]["tools"][0]["parameters"]["required"] == ["policy_id"]
    assert first["request"]["params"]["max_tokens"] == 512
    assert [m["role"] for m in second["request"]["messages"]] == ["user", "assistant", "tool"]
    assert second["request"]["messages"][2]["tool_call_id"] == "tu_1"
    assert second["response"]["content"] == '{"decision": "accepte"}'
    assert first["upstream"] == "bedrock-runtime.eu-west-1.amazonaws.com"
    assert first["model"] == "eu.anthropic.claude-sonnet-4-5-20250929-v1:0"


def test_etiquettes_requestmetadata_donnent_trace_et_application(s3):
    events, _ = s3
    a, b = ev(events, "req-0001"), ev(events, "req-0002")
    assert a["trace"]["id"] == b["trace"]["id"] == "bedrock:claim-8841"
    assert a["trace"]["source"] == "header"
    assert (a["trace"]["step"], b["trace"]["step"]) == (0, 1)
    assert a["app_id"] == "bedrock:triage"
    assert ev(events, "req-0004")["app_id"] == "bedrock:claims-agent-role"  # repli : nom du rôle IAM


def test_jetons_et_cache(s3):
    events, _ = s3
    assert ev(events, "req-0002")["usage"] == {
        "input_tokens": 80, "output_tokens": 20, "cached_input_tokens": 380, "reasoning_tokens": None,
        "cache_write_input_tokens": 0}
    assert ev(events, "req-0003")["usage"]["cache_write_input_tokens"] == 400
    assert ev(events, "req-0002")["latency_ms"] == 900


def test_invokemodel_anthropic(s3):
    e = ev(s3[0], "req-0004")
    assert e["endpoint"] == "/InvokeModel" and e["request"]["system"] == "Classe la demande."
    assert e["request"]["messages"] == [{"role": "user", "content": "Fuite d'eau"}]
    assert e["response"]["content"] == "dégât des eaux" and e["response"]["finish_reason"] == "stop"
    assert e["model_resolved"] == "anthropic.claude-3-haiku-20240307-v1:0"


def test_gros_corps_s3_suivi_en_local(s3):
    e = ev(s3[0], "req-0005")
    assert e["usage"]["input_tokens"] == 33646
    assert len(e["request"]["messages"][0]["content"]) > 100_000
    assert s3[1]["corps_externes_suivis"] == 1


def test_gros_corps_absent_contenu_manquant_jetons_comptes(s3):
    events, report = s3
    e = ev(events, "req-0006")
    assert e["usage"]["input_tokens"] == 40100 and e["usage"]["output_tokens"] == 7
    assert e["request"]["messages"] == [] and e["response"]["content"] is None
    assert report["corps_externes_absents"] == 1
    assert any("100 Ko" in n and "manquant" in n for n in report["limites"])


def test_converse_stream_reconstitue(cw):
    e = ev(cw[0], "req-1001")
    assert e["request"]["params"]["stream"] is True
    assert e["response"]["content"] == "Je vérifie le contrat."
    assert e["response"]["tool_calls"] == [{"id": "tu_9", "name": "lookup_policy", "arguments": '{"policy_id": "P-9"}'}]
    assert e["response"]["finish_reason"] == "tool_calls"
    assert e["usage"]["cached_input_tokens"] == 150


def test_invoke_stream_anthropic_en_chunks_base64(cw):
    e = ev(cw[0], "req-1002")
    assert e["response"]["content"] == "Accepté." and e["response"]["finish_reason"] == "stop"
    assert e["usage"]["output_tokens"] == 6


def test_cloudwatch_trois_formes_identiques(cw, tmp_path):
    """Export en lignes horodatées, sortie de filter-log-events et envoi par abonnement : mêmes enregistrements."""
    events, _ = cw
    again, _ = lire(FIX / "cloudwatch/filter-log-events.json")
    assert again[0]["event_id"] == "bedrock-req-1001" and again[0]["usage"] == ev(events, "req-1001")["usage"]
    record = json.loads((FIX / "cloudwatch/export.log").read_text().splitlines()[0].split(" ", 1)[1])
    sub = tmp_path / "sub.json"
    sub.write_text(json.dumps({"messageType": "DATA_MESSAGE", "logEvents": [{"id": "1", "message": json.dumps(record)}]}))
    assert lire(sub)[0][0]["event_id"] == "bedrock-req-1001"


def test_zip_et_gz_isole(tmp_path):
    z = tmp_path / "export.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for p in (FIX / "s3").rglob("*.gz"):
            zf.write(p, p.relative_to(FIX))
    events, report = lire(z)
    assert len(events) == 6 and report["corps_externes_suivis"] == 1
    gz = next((FIX / "s3").rglob("2026*.json.gz"))
    assert len(lire(gz)[0]) == 6  # sans le corps externe : suivi impossible, dit
    assert lire(gz)[1]["corps_externes_absents"] == 2


def test_erreurs_explicites(tmp_path):
    with pytest.raises(SourceError, match="introuvable"):
        lire(tmp_path / "nope")
    bad = tmp_path / "x.json.gz"
    bad.write_bytes(b"\x1f\x8bpas du gzip")
    with pytest.raises(SourceError, match="gzip corrompu"):
        lire(bad)
    zz = tmp_path / "x.zip"
    zz.write_bytes(b"pas un zip")
    with pytest.raises(SourceError, match="zip"):
        lire(zz)


def test_cli_zero_appel_est_une_erreur(tmp_path, capsys):
    (tmp_path / "vide.json").write_text('{"hello": 1}')
    assert main([str(tmp_path), "-o", str(tmp_path / "o.jsonl")]) == 2
    err = capsys.readouterr().err
    assert "aucun appel Bedrock lu" in err and "ModelInvocationLog" in err
    assert not (tmp_path / "o.jsonl").exists()
    assert main([str(tmp_path / "absent")]) == 1


def test_cli_ecrit_evenements_et_comprehension(tmp_path, capsys):
    out = tmp_path / "o" / "events.jsonl"
    assert main([str(FIX / "s3"), "-o", str(out)]) == 0
    lines = out.read_text().splitlines()
    assert len(lines) == 6 and json.loads(lines[0])["schema_version"] == "1"
    assert json.loads((out.parent / "comprehension.json").read_text())["bedrock"]["appels_lus"] == 6
    assert "limite" in capsys.readouterr().out


def test_enregistrements_refuses_a_la_frontiere(tmp_path):
    base = json.loads(gzip.open(next((FIX / "s3").rglob("2026*.json.gz")), "rt").readline())
    cases = [({**base, "operation": "Rerank"}, "opération"), ({**base, "modelId": ""}, "modelId"),
             ({**base, "timestamp": "hier"}, "horodatage"), ({**base, "modelId": "amazon.titan-embed-text-v2:0"}, "embedding"),
             ({**base, "input": {"inputBodyJson": {}}, "output": {}}, "compteur")]
    (tmp_path / "r.jsonl").write_text("\n".join(json.dumps(c) for c, _ in cases))
    events, report = lire(tmp_path)
    assert events == []
    reasons = " | ".join(report["ignores"])
    for _, word in cases:
        assert word in reasons


def test_cle_dans_un_message_est_masquee(tmp_path):
    base = json.loads(gzip.open(next((FIX / "s3").rglob("2026*.json.gz")), "rt").readline())
    base["input"]["inputBodyJson"]["messages"][0]["content"][0]["text"] = "token sk-ant-" + "a" * 30
    (tmp_path / "r.json").write_text(json.dumps(base))
    assert "sk-ant" not in json.dumps(lire(tmp_path)[0])


# --- chiffrage ---

@pytest.mark.parametrize("model,base", [
    ("eu.anthropic.claude-sonnet-4-5-20250929-v1:0", "claude-sonnet-4-5-20250929"),
    ("global.anthropic.claude-haiku-4-5-20251001-v1:0", "claude-haiku-4-5-20251001"),
    ("us.anthropic.claude-opus-4-1-20250805-v1:0", "claude-opus-4-1-20250805"),
    ("anthropic.claude-3-haiku-20240307-v1:0", "claude-3-haiku-20240307"),
    ("arn:aws:bedrock:eu-west-1:123456789012:inference-profile/eu.anthropic.claude-sonnet-4-v2:0", "claude-sonnet-4"),
    ("claude-sonnet-4-5", "claude-sonnet-4-5"),
])
def test_identifiants_bedrock_normalises(model, base):
    assert bedrock_name(model) == base


def test_lookup_retrouve_les_modeles_bedrock():
    for model in ("eu.anthropic.claude-sonnet-4-5-20250929-v1:0", "global.anthropic.claude-haiku-4-5-20251001-v1:0",
                  "anthropic.claude-3-haiku-20240307-v1:0"):
        assert lookup(PRICES, model) is not None
    assert lookup(PRICES, "arn:aws:bedrock:eu-west-1:1:application-inference-profile/abc123") is None


def test_cout_non_null_et_ecriture_cache_facturee(s3):
    events = [e for e in s3[0] if e["event_id"] in ("bedrock-req-0001", "bedrock-req-0002")]
    wide = [dict(e, ts_end="2026-11-14T00:00:00Z") for e in events]
    result = chiffrer(wide)
    assert result["manquants"] == [] and result["cout_mensuel_usd"] > 0
    with_write = ev(s3[0], "req-0003")
    priced = chiffrer([dict(with_write, ts_end="2026-11-14T00:00:00Z")])
    no_write = json.loads(json.dumps(with_write))
    no_write["usage"]["cache_write_input_tokens"] = 0
    base = chiffrer([dict(no_write, ts_end="2026-11-14T00:00:00Z")])
    # 400 jetons x 3,75 $/M (1,25 x 3 $) = 0,0015 $ de plus
    ratio = priced["cout_mensuel_usd"] / base["cout_mensuel_usd"]
    assert ratio > 1


def test_ecriture_cache_sans_tarif_donne_cout_inconnu(s3):
    e = json.loads(json.dumps(ev(s3[0], "req-0003")))
    e["upstream"] = "api.anthropic.com"  # hors Bedrock : pas de surcouche, pas de tarif d'écriture
    e["ts_end"] = "2026-11-14T00:00:00Z"
    result = chiffrer([e])
    assert result["cout_mensuel_usd"] is None
    assert any("cache_write_in" in m for m in result["manquants"])


def test_le_rapport_d_audit_accepte_les_evenements(s3):
    assert build_report(s3[0])


def test_surcouche_tarifs_porte_source_date_et_estimation():
    meta = json.loads((ROOT / "fixtures/pricing.bedrock.json").read_text())["_meta"]
    assert meta["source"].startswith("https://aws.amazon.com/bedrock/pricing")
    assert meta["date"] and meta["estimated"] is True and meta["verified"] is False


def test_dossier_copie_ailleurs_suit_toujours_les_corps(tmp_path):
    shutil.copytree(FIX / "s3", tmp_path / "copie")
    assert lire(tmp_path / "copie")[1]["corps_externes_suivis"] == 1
