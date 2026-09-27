"""Recette ``modele_alias`` : ne renommer que les étapes mécaniques visées par leur label."""
from optimize.patch_alias import rewrite_model_alias

FIXTURE = """\
const renderRecording = (v, due) => spawn(RENDER(v, due), { label: 'render:' + v.id, phase: 'Render', model: 'opus', effort: 'low' })
const prepLaunch = () => spawn(PREP(), { label: 'prep:launch', phase: 'Prep', model: 'opus', effort: 'low' })
const design = (v) => spawn(DESIGN(v), { label: 'design:' + v.id, phase: 'Design', model: 'opus', effort: 'medium' })
const gate = (v) => spawn(GATE(v), { label: 'gate:cut ' + v.id, phase: 'Gate', effort: 'low' })
"""

PREFIXES = ["render", "prep:launch", "deliver:local", "deliver:drive:verify", "costs:report"]


def test_rewrites_only_matching_labels():
    new_text, changed = rewrite_model_alias(FIXTURE, PREFIXES, "sonnet")
    assert changed == ["render:", "prep:launch"]
    assert "label: 'render:' + v.id, phase: 'Render', model: 'sonnet'" in new_text
    assert "label: 'prep:launch', phase: 'Prep', model: 'sonnet'" in new_text
    # design: pas dans les préfixes visés -> modèle inchangé
    assert "label: 'design:' + v.id, phase: 'Design', model: 'opus'" in new_text


def test_untouched_calls_are_byte_identical():
    new_text, _ = rewrite_model_alias(FIXTURE, PREFIXES, "sonnet")
    assert "label: 'gate:cut ' + v.id, phase: 'Gate', effort: 'low'" in new_text


def test_adds_model_when_absent():
    text = "spawn(FN(), { label: 'costs:report', phase: 'Deliver', effort: 'low' })"
    new_text, changed = rewrite_model_alias(text, ["costs:report"], "sonnet")
    assert changed == ["costs:report"]
    assert "label: 'costs:report', model: 'sonnet', phase: 'Deliver'" in new_text


def test_prefix_must_match_the_start_of_the_label():
    text = "spawn(FN(), { label: 'prep:review', model: 'opus' })"
    new_text, changed = rewrite_model_alias(text, ["prep:launch"], "sonnet")
    assert changed == [] and new_text == text


def test_no_match_returns_text_unchanged():
    new_text, changed = rewrite_model_alias(FIXTURE, ["nonexistent"], "sonnet")
    assert changed == [] and new_text == FIXTURE
