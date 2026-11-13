"""R12 : sorties bien plus longues que necessaire, sans plafond reel."""
import copy
import json
from pathlib import Path

from rules.verbose_output import detect

ROOT = Path(__file__).resolve().parents[1]
BASE = json.loads((ROOT / "fixtures/events.jsonl").read_text().splitlines()[0])
DATASET = [json.loads(line) for line in (ROOT / "fixtures/dataset/v1/events.jsonl").read_text().splitlines()]
LABELS = json.loads((ROOT / "fixtures/dataset/v1/labels.json").read_text())
PRICES = {"gpt-4o": {"in": 2.5, "out": 10.0}}
KEYS = {"finding_id", "rule", "app_id", "model", "template", "severity",
        "title", "proven", "event_ids", "evidence"}


def ev(i, *, out_tok=500, max_tokens=None, finish="stop", error=None, app="a",
       model="gpt-4o", system="Redige librement."):
    e = copy.deepcopy(BASE)
    e.update(event_id=f"e{i}", app_id=app, model=model, error=error,
             ts_start=f"2026-09-01T00:{i // 60:02d}:{i % 60:02d}Z",
             ts_end=f"2026-09-01T00:{i // 60:02d}:{i % 60:02d}.900000Z")
    e["request"]["system"] = system
    e["request"]["messages"] = [{"role": "user", "content": f"tache {i}"}]
    e["request"]["params"]["max_tokens"] = max_tokens
    e["response"]["content"] = f"[sortie {i}, {out_tok} tokens]"
    e["response"]["finish_reason"] = finish
    e["usage"] = {"input_tokens": 200, "output_tokens": out_tok, "cached_input_tokens": 0}
    return e


def _verbose_group(n=32):
    """Mediane basse, une minorite tres au-dessus : p90/mediane > 2, jamais plafonne."""
    return [ev(i, out_tok=3000 if i % 8 == 0 else 500) for i in range(n)]


def test_verbose_uncapped_group_is_flagged_as_trim():
    events = _verbose_group()
    [f] = detect(events, PRICES)
    assert set(f) == KEYS
    assert f["rule"] == "verbose_output" and f["proven"] is False and f["severity"] == "trim"
    assert f["evidence"]["calls"] == 32
    assert f["evidence"]["uncapped_share"] == 1.0
    assert f["evidence"]["p90_output_tokens"] / f["evidence"]["median_output_tokens"] >= 2.0
    assert f["evidence"]["est_saving_month_usd"] > 0
    assert "non démontré" in f["title"]


def test_below_min_calls_is_ignored():
    assert detect(_verbose_group(29), PRICES) == []


def test_short_median_output_is_ignored():
    assert detect([ev(i, out_tok=150) for i in range(32)], PRICES) == []


def test_already_capped_group_is_ignored():
    events = [ev(i, out_tok=500, max_tokens=520) for i in range(32)]
    assert detect(events, PRICES) == []


def test_low_dispersion_is_ignored():
    """Sorties longues mais homogenes : p90 proche de la mediane, rien a plafonner."""
    events = [ev(i, out_tok=520 if i % 2 else 500) for i in range(32)]
    assert detect(events, PRICES) == []


def test_errors_and_unknown_output_are_excluded():
    events = [ev(i, error={"type": "x", "message": "y"}) for i in range(32)]
    assert detect(events, PRICES) == []
    events = [ev(i, out_tok=None) for i in range(32)]
    assert detect(events, PRICES) == []


def test_unknown_price_gives_null_saving_with_reason():
    [f] = detect(_verbose_group(), {})
    assert f["evidence"]["est_saving_month_usd"] is None
    assert f["evidence"]["saving_missing"]


def test_dataset_v1_positives_and_negatives():
    flagged = {f["app_id"] for f in detect(DATASET)}
    assert "brainstorm-bot" in flagged
    assert "capped-writer" not in flagged
    expected = {label["app_id"] for label in LABELS if "verbose_output" in label["expected_rules"]}
    assert expected == {"brainstorm-bot"}


def test_agent_de_code_dont_la_sortie_est_faite_d_appels_d_outils_n_est_pas_signale():
    # forme mesurée sur des journaux Claude Code réels : 64 constats, tous portés à 68-100 % par des
    # tours qui rendent des arguments d'outil (écriture de fichier, commande). Plafonner la sortie
    # couperait l'action, pas un bavardage. Texte inventé, forme reprise (volumes en jetons).
    events = []
    for i in range(60):
        e = ev(i, out_tok=3000 if i % 8 == 0 else 500)
        if i % 10 != 9:  # 90 % des tours demandent un outil
            e["response"]["content"] = None
            e["response"]["tool_calls"] = [{"id": f"t{i}", "name": "Write", "arguments": "{}"}]
        events.append(e)
    assert detect(events, PRICES) == []


def test_les_tours_texte_d_un_agent_restent_evalues_a_part():
    events = _verbose_group(40)
    for i in range(40, 70):  # des tours d'outils en plus ne masquent ni ne créent le constat
        e = ev(i, out_tok=900)
        e["response"]["content"] = None
        e["response"]["tool_calls"] = [{"id": f"t{i}", "name": "Bash", "arguments": "{}"}]
        events.append(e)
    [f] = detect(events, PRICES)
    assert f["evidence"]["calls"] == 40
