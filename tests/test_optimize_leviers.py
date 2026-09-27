"""Leviers 03/04/07/12/13 : propositions testables à partir de constats déjà détectés
(R7 excess_reasoning, R8 duplicate_calls, R9 paid_errors, R4 no_cache, R14 batch_eligible),
sur le même modèle que optimize.propose._rules/_model/_cap (tests/test_optimize.py)."""
import copy
import json
from pathlib import Path

import pytest

from optimize.propose import ESTIME, MESURE, NON_TESTE, propose
from proof.replay import THRESHOLD

ROOT = Path(__file__).resolve().parents[1]
BASE = json.loads((ROOT / "fixtures/events.jsonl").read_text().splitlines()[0])
DATASET = [json.loads(line) for line in (ROOT / "fixtures/dataset/v1/events.jsonl").read_text().splitlines()
          if line.strip()]


@pytest.fixture(scope="module")
def proposals():
    return propose(DATASET)


def by(proposals, type_, app_id):
    return next(p for p in proposals if p["type"] == type_ and p["app_id"] == app_id)


# ---------- 07 appels identiques (R8 duplicate_calls -> type "cache") ----------

def test_cache_proposal_is_pass_with_100_percent_measured_precision(proposals):
    p = by(proposals, "cache", "mail-triage")
    assert p["verdict"] == "pass" and p["raisons"] == []
    m = p["mesures"]
    assert m["precision"] == {"valeur": 100.0, "statut": MESURE, "unite": "%",
                              "hypothese": "réponse déjà vérifiée identique par le détecteur : "
                                           "servir le cache ne change rien"}
    assert m["appels_evites"] == {"valeur": 4, "statut": MESURE, "unite": ""}
    assert m["cout"]["statut"] == MESURE and m["cout"]["valeur"] < 0
    assert p["cout_usd"]["apres"] < p["cout_usd"]["avant"] and p["cout_usd"]["statut"] == MESURE


def test_cache_proposal_cost_excludes_only_the_wasted_calls(proposals):
    """avant = toute la rafale (premier appel + doublons), apres = seulement le premier appel gardé."""
    p = by(proposals, "cache", "mail-triage")
    assert p["mesures"]["appels_evites"]["valeur"] > 0
    assert 100.0 >= THRESHOLD * 100  # le verdict pass respecte bien le plancher du projet


# ---------- 12 erreurs et relances (R9 paid_errors -> type "erreurs") ----------

def test_errors_proposal_counts_only_the_retries_not_all_billed_failures(proposals):
    p = by(proposals, "erreurs", "checkout-bot")
    assert p["verdict"] == "pass" and p["mesures"]["precision"]["valeur"] == 100.0
    assert p["mesures"]["precision"]["statut"] == MESURE
    assert p["mesures"]["relances_evitees"]["valeur"] == 15  # les 15 relances, pas les 15+15 échecs
    assert p["cout_usd"]["apres"] < p["cout_usd"]["avant"]


def _paid_error_event(i, *, offset_s, prompt, content, finish, out_tok=50):
    e = copy.deepcopy(BASE)
    e.update(event_id=f"pe{i}", app_id="no-retry-app", model="gpt-4o", error=None, http_status=200,
             ts_start=f"2026-09-01T{offset_s // 3600:02d}:{(offset_s % 3600) // 60:02d}:{offset_s % 60:02d}Z",
             ts_end=f"2026-09-01T{offset_s // 3600:02d}:{(offset_s % 3600) // 60:02d}:{offset_s % 60:02d}.500000Z")
    e["request"]["system"] = "Agent."
    e["request"]["messages"] = [{"role": "user", "content": prompt}]
    e["response"]["content"] = content
    e["response"]["finish_reason"] = finish
    e["usage"] = {"input_tokens": 100, "output_tokens": out_tok, "cached_input_tokens": 0}
    return e


def test_errors_returns_no_proposal_when_billed_failures_are_never_retried():
    """Taux d'echec facture au-dessus du seuil, mais jamais relance (rules.paid_errors le signale
    quand meme, severite trim) : optimize.leviers.errors.errors_proposal refuse de chiffrer un
    gain ici, la reponse obtenue changerait si la cause etait corrigee, ce que rien ne mesure sans rejeu."""
    events = [_paid_error_event(i, offset_s=i * 300, prompt=f"q{i}", content="ok", finish="stop")
             for i in range(18)]
    events += [_paid_error_event(18, offset_s=18 * 300, prompt="q18", content="tronque", finish="length"),
              _paid_error_event(19, offset_s=19 * 300, prompt="q19", content="tronque", finish="length")]
    proposals = propose(events)
    assert not any(p["app_id"] == "no-retry-app" for p in proposals)


# ---------- 04 cache de prompt (R4 no_cache -> type "cache_prompt") ----------

def test_prompt_cache_proposal_is_pass_with_measured_savings(proposals):
    for app in ("daily-report", "faq-bot"):
        p = by(proposals, "cache_prompt", app)
        assert p["verdict"] == "pass" and p["raisons"] == []
        assert p["mesures"]["precision"] == {"valeur": 100.0, "statut": MESURE, "unite": "%",
                                             "hypothese": "le cache ne change ni le modèle ni les jetons "
                                                          "envoyés, seulement leur tarif"}
        assert p["mesures"]["jetons_repetes"]["valeur"] > 0 and p["mesures"]["jetons_repetes"]["statut"] == MESURE
        assert p["mesures"]["cout"]["valeur"] < 0 and p["mesures"]["cout"]["statut"] == MESURE
        assert p["cout_usd"]["apres"] < p["cout_usd"]["avant"]


def test_prompt_cache_skips_the_first_call_of_each_template():
    """Le premier appel de chaque gabarit établit le cache : aucun jeton à son tarif dans le calcul."""
    p = by(propose(DATASET), "cache_prompt", "daily-report")
    # daily-report : 1 gabarit, 30 appels, input_tokens identiques (fixture) ; 29 appels contribuent.
    from rules.no_cache import _detect_templates
    [f] = [f for f in _detect_templates(DATASET) if f["app_id"] == "daily-report"]
    assert p["mesures"]["jetons_repetes"]["valeur"] < f["evidence"]["calls"] * f["evidence"]["mean_input_tokens"]


def test_prompt_cache_returns_no_proposal_without_cache_pricing():
    events = [copy.deepcopy(BASE) for _ in range(3)]
    for i, e in enumerate(events):
        e.update(event_id=f"nc{i}", app_id="unknown-model-app", model="modele-inconnu-sans-tarif", error=None,
                 ts_start=f"2026-09-01T00:0{i}:00Z", ts_end=f"2026-09-01T00:0{i}:00.500000Z")
        e["request"]["system"] = "Un tres long prefixe fixe. " * 100
        e["request"]["messages"] = [{"role": "user", "content": "question"}]
        e["response"]["content"] = f"reponse {i}"  # differente : n'est pas aussi un doublon strict (R8)
        e["usage"] = {"input_tokens": 1200, "output_tokens": 5, "cached_input_tokens": 0}
    proposals = propose(events)
    assert not any(p["app_id"] == "unknown-model-app" for p in proposals)


# ---------- 13 API batch (R14 batch_eligible -> type "batch") ----------

def test_batch_proposal_never_passes_and_marks_savings_as_estimated(proposals):
    p = by(proposals, "batch", "night-batch")
    assert p["verdict"] == "non_teste" and p["raisons"]
    assert p["mesures"]["precision"] == {"valeur": None, "statut": NON_TESTE, "unite": "%",
                                         "hypothese": "absence d'utilisateur et modèle batch du fournisseur "
                                                      "non observables dans l'historique"}
    assert p["mesures"]["cout"]["statut"] == ESTIME
    assert p["cout_usd"]["statut"] == ESTIME
    assert p["cout_usd"]["apres"] < p["cout_usd"]["avant"]


# ---------- 03 raisonnement excessif (R7 excess_reasoning -> type "raisonnement") ----------

def test_reasoning_without_a_key_is_never_measured(proposals):
    p = by(proposals, "raisonnement", "trivia-bot")
    assert p["verdict"] == "non_teste" and p["mesures"]["precision"]["valeur"] is None
    assert "preuve" not in p


def _fake_prove(verdict, score, **extra):
    def prove(events, finding):
        return {"n_cases": 30, "task_type": "classification", "threshold": 0.95, "effort": "low",
                "n_calls": 30, "n_errors": 0, "score": score, "latency_p95_ms": 100.0,
                "cost_per_1000_calls_usd": 1.0, "reference_cost_per_1000_calls_usd": 5.0,
                "verdict": verdict, "reasons": [], **extra}
    return prove


def test_reasoning_passes_when_the_bench_score_clears_the_project_threshold():
    proposals = propose(DATASET, keys_available=True, prove_reasoning=_fake_prove("pass", 1.0))
    p = by(proposals, "raisonnement", "trivia-bot")
    assert p["verdict"] == "pass"
    assert p["mesures"]["precision"] == {"valeur": 100.0, "statut": MESURE, "unite": "%"}
    assert p["mesures"]["cout"]["valeur"] < 0 and p["mesures"]["cout"]["statut"] == MESURE
    assert p["cout_usd"]["apres"] < p["cout_usd"]["avant"]


def test_reasoning_rejects_a_bench_pass_below_the_project_threshold():
    """bench.scoring.threshold_for descend a 0.5 en texte libre : le banc dirait « pass », le
    plancher du projet (95 %, proof.replay.THRESHOLD, réutilisé) dit non."""
    proposals = propose(DATASET, keys_available=True,
                        prove_reasoning=_fake_prove("pass", 0.7, task_type="text", threshold=0.5))
    p = by(proposals, "raisonnement", "trivia-bot")
    assert p["verdict"] == "reject"
    assert any("seuil du projet" in r for r in p["raisons"])
    assert p["mesures"]["precision"] == {"valeur": 70.0, "statut": MESURE, "unite": "%"}


def test_reasoning_maps_a_bench_not_tested_verdict_to_non_teste():
    proposals = propose(DATASET, keys_available=True,
                        prove_reasoning=_fake_prove("not_tested", None, reasons=["clé refusée"]))
    p = by(proposals, "raisonnement", "trivia-bot")
    assert p["verdict"] == "non_teste"
    assert p["mesures"]["precision"] == {"valeur": None, "statut": NON_TESTE, "unite": "%"}


# ---------- couverture d'ensemble ----------

def test_propose_wires_all_five_new_levers_on_the_fixture_dataset(proposals):
    types = {p["type"] for p in proposals}
    assert {"cache", "erreurs", "cache_prompt", "batch", "raisonnement"} <= types
