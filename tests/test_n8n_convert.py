"""B1.2 : exécutions n8n → événements, au format enregistré par n8n (n8n-llm-tracing.ts)."""
import copy
import json
from pathlib import Path

import jsonschema
import pytest

from importers.n8n.__main__ import main
from importers.n8n.convert import convert, model_of, split_prompt
from report.audit import build_report

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "tests/data/n8n/support"
SCHEMA = json.loads((ROOT / "schemas/event.schema.json").read_text())


@pytest.fixture(scope="module")
def wf():
    return json.loads((DATA / "workflow.json").read_text())


@pytest.fixture(scope="module")
def executions():
    return [json.loads(line) for line in (DATA / "executions.jsonl").read_text().splitlines()]


@pytest.fixture(scope="module")
def converted(wf, executions):
    return convert(wf, executions)


def test_chaque_evenement_respecte_le_schema(converted):
    events, _ = converted
    assert len(events) == 11
    for e in events:
        jsonschema.validate(e, SCHEMA)


def test_trace_exacte_par_execution(converted):
    events, _ = converted
    first = [e for e in events if e["trace"]["id"] == "n8n-100"]
    assert [e["trace"]["step"] for e in first] == [0, 1, 2]
    assert {e["trace"]["source"] for e in events} == {"header"}
    assert [e["app_id"] for e in first] == ["n8n:Support tickets/Classifier"] + ["n8n:Support tickets/Support Agent"] * 2


def test_classifieur(converted):
    e = converted[0][0]
    assert (e["provider"], e["upstream"], e["model"]) == ("openai", "api.openai.com", "gpt-4o")
    assert e["request"]["system"].startswith("Classe le ticket")
    assert e["request"]["messages"] == [{"role": "user", "content": "Je veux etre rembourse"}]
    assert e["request"]["params"]["max_tokens"] == 5 and e["request"]["params"]["temperature"] == 0
    assert e["response"]["content"] == "remboursement" and e["response"]["finish_reason"] == "stop"
    assert e["usage"] == {"input_tokens": 48, "output_tokens": 2}
    assert e["latency_ms"] == 420 and e["ts_start"] == "2026-09-21T14:13:20.010Z"


def test_agent_et_outils_reconstitues(converted):
    events = [e for e in converted[0] if e["trace"]["id"] == "n8n-100"]
    ask, answer = events[1], events[2]
    assert ask["provider"] == "anthropic" and ask["model"] == "claude-sonnet-4-5"
    assert [t["name"] for t in ask["request"]["tools"]] == ["Search Orders"]
    assert ask["response"]["tool_calls"] == [{"id": None, "name": "Search Orders", "arguments": '"commande 4471"'}]
    assert ask["response"]["finish_reason"] == "tool_calls" and ask["response"]["finish_reason_raw"] == "tool_use"
    assert [m["role"] for m in answer["request"]["messages"]] == ["user", "assistant", "tool"]
    assert answer["response"]["tool_calls"] == [] and answer["response"]["finish_reason"] == "stop"


def test_appel_en_erreur(converted):
    failed = next(e for e in converted[0] if e["error"])
    assert failed["http_status"] == 529 and failed["error"]["message"] == "overloaded_error"
    assert failed["response"]["finish_reason"] == "error"
    assert failed["usage"] == {"input_tokens": None, "output_tokens": None}


def test_jetons_estimes_et_hote_local(converted):
    llama = next(e for e in converted[0] if e["model"] == "llama3.1")
    assert llama["upstream"] == "localhost:11434" and llama["usage"]["input_tokens"] == 12


def test_taux_de_comprehension(converted):
    s = converted[1].as_dict()
    assert (s["executions"], s["appels_llm_vus"], s["evenements"]) == (5, 12, 11)
    assert (s["jetons_reels"], s["jetons_estimes"], s["erreurs"], s["sans_jetons"]) == (9, 1, 1, 0)
    assert s["ignores"] == {"appel sans entrée ni sortie": 1}
    assert s["taux_compris"] == round(11 / 12, 3)


def test_aucune_cle_ne_passe(converted):
    text = json.dumps(converted[0])
    assert "OPENAI_API_KEY" not in text and "ANTHROPIC_API_KEY" not in text


def test_le_rapport_chiffre_et_detecte(wf, executions):
    """Le circuit complet : historique n8n → règles et chiffrage existants, sans modification."""
    many = []
    for k in range(30):
        for ex in executions[:2]:
            c = copy.deepcopy(ex)
            c["id"] = f"{ex['id']}-{k}"
            for runs in c["data"]["resultData"]["runData"].values():
                for run in runs:
                    run["startTime"] += k * 600_000
            many.append(c)
    report = build_report(convert(wf, many)[0])
    assert report["resume"]["global"]["cout_mensuel_usd"] > 0
    assert "n8n:Support tickets/Classifier" in {c["app_id"] for c in report["constats"]}


@pytest.mark.parametrize("prompt,system,roles", [
    ("System: a\nHuman: b", "a", ["user"]),
    ("Human: b\nAI: c\nTool: d\nHuman: e", None, ["user", "assistant", "tool", "user"]),
    ("texte libre sans rôle", None, ["user"]),
    ("System: ligne 1\nligne 2\nHuman: q", "ligne 1\nligne 2", ["user"]),
])
def test_decoupage_du_prompt(prompt, system, roles):
    s, messages = split_prompt(prompt)
    assert s == system and [m["role"] for m in messages] == roles


def test_modele_depuis_le_noeud_si_absent_des_options():
    assert model_of({"parameters": {"model": {"value": "gpt-4o-mini"}}}, {}) == "gpt-4o-mini"
    assert model_of({"parameters": {"modelName": "models/gemini-2.0-flash"}}, {}) == "gemini-2.0-flash"
    assert model_of({"parameters": {"model": "={{ $json.model }}"}}, {}) is None  # expression : inconnu, pas inventé
    assert model_of({}, {"model": "claude-haiku-4-5"}) == "claude-haiku-4-5"


def test_commande_convert(tmp_path, capsys):
    for name in ("workflow.json", "executions.jsonl"):
        (tmp_path / name).write_text((DATA / name).read_text())
    assert main(["convert", str(tmp_path)]) == 0
    assert "compris : 92%" in capsys.readouterr().out
    assert len((tmp_path / "events.jsonl").read_text().splitlines()) == 11
    assert json.loads((tmp_path / "comprehension.json").read_text())["taux_compris"] == 0.917
    assert main(["convert", str(tmp_path / "vide")]) == 1
