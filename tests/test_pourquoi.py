"""Zéro constat : le rapport explique pourquoi (volume, invisible, prochaine étape) et montre l'utile."""
import copy
import json
from pathlib import Path

from report.audit import build_report, render_html
from report.pourquoi import diagnostic, lignes, utile

ROOT = Path(__file__).resolve().parent.parent
BASE = json.loads((ROOT / "fixtures/events.jsonl").read_text().splitlines()[0])


def ev(i, app="claude-code:proj", session="s1", system=None, tools=()):
    e = copy.deepcopy(BASE)
    e.update(event_id=f"e{i}", app_id=app, provider="anthropic", model="claude-sonnet-4-5",
             ts_start=f"2026-09-01T00:{i // 60:02d}:{i % 60:02d}Z", ts_end=f"2026-09-01T00:{i // 60:02d}:{i % 60:02d}.5Z")
    e["trace"] = {"id": session, "source": "claude-code", "step": i}
    e["usage"] = {"input_tokens": 10, "output_tokens": 50, "cached_input_tokens": 90}
    e["request"].update(system=system, tools=[{"name": t} for t in tools],
                        messages=[{"role": "user", "content": f"question {i}"}])
    e["response"]["content"] = f"réponse {i}"
    return e


def test_diagnostic_volume_and_invisible():
    d = diagnostic([ev(i, session=f"s{i % 2}") for i in range(5)])
    assert d["nb_appels"] == 5 and d["nb_sessions"] == 2
    assert d["max_par_tache"] == 5 and d["minimum"] == 30
    assert d["systeme_visible"] is False and d["outils_visibles"] is False
    assert d["cache_pct"] == 90


def test_lignes_say_why_and_next_step_for_claude_code():
    text = "\n".join(lignes(diagnostic([ev(i) for i in range(5)])))
    assert "5 appels" in text and "30 appels" in text
    assert "prompt système" in text and "--all-projects" in text
    assert "90 %" in "\n".join(utile(diagnostic([ev(i) for i in range(5)])))  # cache


def test_lignes_gateway_source_points_to_more_traffic():
    e = ev(0, app="mon-app", system="sys")
    text = "\n".join(lignes(diagnostic([e])))
    assert "--all-projects" not in text and "passerelle" in text and "1 appel " in text


def test_html_has_block_only_when_no_finding():
    report = build_report([ev(i) for i in range(5)])
    assert not report["constats"]
    page = render_html(report)
    assert "Pourquoi aucun constat" in page and "Ce que montre déjà cette source" in page


def _demo_page():
    events = [json.loads(line) for line in (ROOT / "fixtures/dataset/v1/events.jsonl").read_text().splitlines()]
    return render_html(build_report(events[:40]))


def test_html_checks_folded_and_not_repeated_missing_note():
    page = render_html(build_report([ev(i, system="s") for i in range(40)]))
    assert "<details><summary>Vérifications effectuées (" in page
    assert page.count("Chiffre manquant") == 0 and page.count("laissez tourner la passerelle") == 1


def test_zero_latency_is_not_measured():
    from report.audit import _ms
    assert _ms(0) == "non mesuré" and _ms(None) == "non mesuré" and _ms(640) == "640 ms"


def test_low_entropy_title_singular():
    from rules.low_entropy import detect
    events = [ev(i, system="s") for i in range(40)]
    for e in events:
        e["response"]["content"] = "spam"
        e["provider"], e["model"] = "openai", "gpt-4o"
    [f] = detect(events)
    assert "1 réponse différente :" in f["title"]
