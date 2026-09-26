"""D4.1 : rapport d'audit d'une page, lisible par un directeur technique."""
import json
import subprocess
import sys
from pathlib import Path

from report.audit import build_report, render_html

ROOT = Path(__file__).resolve().parent.parent
DATASET = ROOT / "fixtures/dataset/v1/events.jsonl"
EVENTS = [json.loads(line) for line in DATASET.read_text().splitlines()]
RULE_CODES = ["low_entropy_output", "oversized_model", "raw_context", "no_cache",
              "unbounded_loop", "agent_where_chain",
              "excess_reasoning", "duplicate_calls", "paid_errors", "verbose_output",
              "tool_bloat", "batch_eligible", "image_heavy", "llm_judge", "parallelizable_steps"]


def test_findings_sorted_by_monthly_cost_desc_unknown_last():
    costs = [f["chiffres"]["cout_mensuel_usd"] for f in build_report(EVENTS)["constats"]]
    known = [c for c in costs if c is not None]
    assert known == sorted(known, reverse=True)
    assert costs[:len(known)] == known


def test_each_finding_has_four_figures_and_a_sentence():
    for f in build_report(EVENTS)["constats"]:
        assert {"cout_mensuel_usd", "latence_mediane_ms", "latence_p95_ms", "nb_appels"} <= set(f["chiffres"])
        assert f["titre"] and f["phrase"] and f["action"]


def test_clean_apps_are_listed():
    clean = {a["app_id"] for a in build_report(EVENTS)["rien_a_signaler"]}
    assert {"eng-copilot", "ticket-summary", "translate"} <= clean
    assert "mail-triage" not in clean


def test_header_summarises_the_traffic():
    head = build_report(EVENTS)["resume"]
    assert head["nb_appels"] == len(EVENTS)
    assert head["nb_applications"] == len({e["app_id"] for e in EVENTS})
    assert head["debut"] < head["fin"]


def test_html_has_no_internal_jargon():
    html = render_html(build_report(EVENTS))
    for code in RULE_CODES:
        assert code not in html
    assert "Rien à signaler" in html


def test_missing_figures_are_explained_not_hidden():
    report = build_report(EVENTS)
    html = render_html(report)
    for f in report["constats"]:
        if f["chiffres"]["cout_mensuel_usd"] is None:
            assert f["raisons_manquantes"]
            if f["chiffres"].get("cout_observe_usd") is not None:
                assert "Coût observé" in html
                assert "projection sur un mois non fiable" in html
            else:
                assert "non disponible" in html


def test_html_escapes_client_content():
    evil = [dict(e, app_id="<script>x</script>") for e in EVENTS[:5]]
    assert "<script>x" not in render_html(build_report(evil))


def test_empty_traffic_does_not_crash():
    report = build_report([])
    assert report["constats"] == [] and "Aucun appel" in render_html(report)


def test_cli_writes_the_page(tmp_path):
    out = tmp_path / "audit.html"
    subprocess.run([sys.executable, "-m", "report.audit", str(DATASET), "-o", str(out)],
                   cwd=ROOT, check=True, capture_output=True)
    assert out.read_text().startswith("<!doctype html>")


def test_report_lists_the_checks_that_ran():
    report = build_report(EVENTS)
    assert "Une IA qui répond toujours la même chose" in report["verifications"]
    assert "Vérifications effectuées" in render_html(report)


def test_custom_detectors_and_global_missing_reason():
    fake = [("no_cache", lambda evts: [])]
    report = build_report(EVENTS, detectors=fake)
    assert report["constats"] == [] and report["verifications"] == ["Les mêmes demandes payées plusieurs fois"]
    if report["resume"]["global"]["cout_mensuel_usd"] is None:
        assert "Coût total non disponible" in render_html(report)


def test_short_traffic_shows_observed_cost_not_a_monthly_projection():
    """36 appels en quelques secondes ne se projettent pas sur un mois (315 220 $ en démo)."""
    from report.cost import chiffrer
    base = next(e for e in EVENTS if chiffrer([e])["cout_mensuel_usd"])  # un appel chiffrable
    burst = [{**base, "event_id": f"burst_{i}", "ts_start": f"2026-09-26T12:00:{i:02d}Z",
              "ts_end": f"2026-09-26T12:00:{i:02d}.500Z"} for i in range(36)]
    report = build_report(burst, detectors=[])
    g = report["resume"]["global"]
    assert g["cout_mensuel_usd"] is None and g["cout_observe_usd"] > 0
    assert any("moins d'une heure" in r for r in report["raisons_globales"])
    page = render_html(report)
    assert "coût observé total" in page and "315" not in page


def test_unpriced_calls_give_a_partial_cost_not_nothing():
    from report.cost import chiffrer
    priced = [e for e in EVENTS if e["error"] is None and chiffrer([e])["cout_mensuel_usd"]][:10]
    events = [{**e, "ts_start": f"2026-09-26T{8 + i:02d}:00:00Z", "ts_end": f"2026-09-26T{8 + i:02d}:00:01Z"}
              for i, e in enumerate(priced)]
    events[0] = {**events[0], "model": "modele-maison-inconnu"}
    g = build_report(events, detectors=[])["resume"]["global"]
    assert g["cout_mensuel_usd"] > 0 and g["part_chiffree"] == 0.9
    page = render_html(build_report(events, detectors=[]))
    assert "partiel, 90 % des appels" in page and "modele-maison-inconnu" in page
