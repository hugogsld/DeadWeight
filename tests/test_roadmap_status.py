"""Tableau d'avancement automatique de ROADMAP.md."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from roadmap_status import BEGIN, END, compute, render, replace_block  # noqa: E402


def issue(n, title, state="open", assignees=(), labels=()):
    return {"number": n, "title": title, "state": state, "assignees": list(assignees), "labels": list(labels)}


def pr(n, title, state="open", merged=False):
    return {"number": n, "title": title, "state": state, "merged": merged}


def status(rows, did):
    return next(r["status"] for r in rows if r["id"] == did)


def test_merged_pr_marks_done_and_unblocks_dependents():
    rows = compute([issue(1, "D0.1 — Schéma", "closed")], [pr(2, "D0.1 — Schéma", "merged", True)])
    assert status(rows, "D0.1") == "Fait"
    assert status(rows, "D0.3") == "Prenable"
    assert status(rows, "D1.1").startswith("Bloqué (attend D0.2")


def test_open_pr_is_in_review_and_open_issue_in_progress():
    rows = compute([issue(3, "D0.2 — Repo", assignees=["hugo"]), issue(4, "D1.1 — Proxy", labels=["agent:codex"])],
                   [pr(5, "D0.2 — Repo")])
    assert status(rows, "D0.2") == "En relecture"
    assert status(rows, "D1.1") == "En cours"
    assert next(r["who"] for r in rows if r["id"] == "D1.1") == "codex"


def test_titles_without_id_are_ignored():
    rows = compute([issue(9, "AGENTS.md — coordination")], [pr(10, "Schéma : champ upstream", "merged", True)])
    assert all(r["status"] != "Fait" for r in rows)


def test_render_counts_base_plan_only():
    rows = compute([], [pr(1, "D3.3 — Court-circuit", "merged", True)])
    assert render(rows, "now").startswith("**0 / 17 livrables")


def test_replace_block_keeps_the_rest():
    text = f"avant\n{BEGIN}\nvieux\n{END}\napres"
    assert replace_block(text, "neuf") == f"avant\n{BEGIN}\nneuf\n{END}\napres"
