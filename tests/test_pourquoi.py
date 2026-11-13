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
