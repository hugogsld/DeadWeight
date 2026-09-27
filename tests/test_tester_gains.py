"""Gains globaux du testeur (étape 4, sous le tableau) : coût total avant/après sur l'historique
rejoué, coût par exécution, projection. Rien n'est estimé : les chiffres viennent du chiffrage global
(report.cost.chiffrer) et des cout_usd déjà mesurés par proposition."""
import copy
import json
from pathlib import Path

import pytest

from scripts.tester_gains import global_gains

ROOT = Path(__file__).resolve().parents[1]
BASE = json.loads((ROOT / "fixtures/events.jsonl").read_text().splitlines()[0])
PRICES = {"gpt-4o": {"in": 2, "out": 8}}


def event(**changes):
    e = copy.deepcopy(BASE)
    e.update(ts_start="2026-09-01T00:00:00Z", ts_end="2026-09-01T00:00:01Z", latency_ms=100,
              usage={"input_tokens": 1000, "output_tokens": 100, "cached_input_tokens": 0}, error=None)
    e.update(changes)
    return e


def proposal(cout_avant, cout_apres, verdict="pass"):
    return {"verdict": verdict, "mesures": {"precision": {"valeur": 100.0, "statut": "mesuré", "unite": "%"}},
            "cout_usd": {"avant": cout_avant, "apres": cout_apres, "statut": "mesuré"}}


def test_cout_total_avant_apres_et_pourcentage():
    events = [event() for _ in range(10)]  # 10 x (1000 in, 100 out) au tarif PRICES = 0.028 $
    gains = global_gains(events, [proposal(0.02, 0.005)], pricing=PRICES)
    assert gains["cout_avant"] == pytest.approx(0.028)
    assert gains["cout_apres"] == pytest.approx(0.028 - (0.02 - 0.005))
    assert gains["cout_pct"] == pytest.approx(-53.6, abs=0.1)


def test_seules_les_propositions_prouvees_et_mesurees_comptent():
    events = [event() for _ in range(10)]
    items = [proposal(0.01, 0.002, verdict="pass"), proposal(0.005, 0.001, verdict="reject")]
    gains = global_gains(events, items, pricing=PRICES)
    assert gains["modifications_comptees"] == 1
    assert gains["cout_apres"] == pytest.approx(gains["cout_avant"] - (0.01 - 0.002))


def test_cout_par_execution_et_projection_pour_mille():
    events = [event() for _ in range(10)]
    gains = global_gains(events, [proposal(0.02, 0.005)], executions=100, pricing=PRICES)
    assert gains["cout_par_execution_avant"] == pytest.approx(gains["cout_avant"] / 100)
    assert gains["cout_par_execution_apres"] == pytest.approx(gains["cout_apres"] / 100)
    assert gains["projection_1000_usd"] == pytest.approx(gains["cout_par_execution_apres"] * 1000)


def test_sans_executions_le_cout_par_execution_reste_non_mesure():
    events = [event() for _ in range(10)]
    gains = global_gains(events, [proposal(0.02, 0.005)], executions=None, pricing=PRICES)
    assert gains["cout_par_execution_avant"] is None and gains["projection_1000_usd"] is None


def test_sans_evenements_rien_n_est_invente():
    gains = global_gains([], [], pricing=PRICES)
    assert gains["cout_avant"] is None and gains["cout_apres"] is None and gains["cout_pct"] is None
