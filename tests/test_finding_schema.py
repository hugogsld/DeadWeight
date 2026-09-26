"""Les findings emis par les six regles de rules/ respectent schemas/finding.schema.json.

Meme decouverte que report/audit.py (pkgutil.iter_modules sur rules/) : toute
regle ajoutee dans rules/ avec une fonction detect() est couverte sans
modification de ce test.
"""
import importlib
import json
import pkgutil
from pathlib import Path

import jsonschema
import pytest

import rules

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = json.loads((ROOT / "schemas/finding.schema.json").read_text())
DATASET = ROOT / "fixtures/dataset/v1/events.jsonl"
EVENTS = [json.loads(line) for line in DATASET.read_text().splitlines() if line.strip()]


def _detectors():
    found = []
    for mod in pkgutil.iter_modules(rules.__path__):
        detect = getattr(importlib.import_module(f"rules.{mod.name}"), "detect", None)
        if callable(detect):
            found.append((mod.name, detect))
    return found


def _all_findings():
    findings = []
    for _, detect in _detectors():
        findings.extend(detect(EVENTS))
    return findings


FINDINGS = _all_findings()


def test_dataset_produces_at_least_one_finding_per_rule():
    """Garde-fou : si le dataset ne declenche plus une regle, le test suivant passerait a vide."""
    assert FINDINGS
    assert {f["rule"] for f in FINDINGS} == {
        "low_entropy_output", "oversized_model", "raw_context", "no_cache",
    }


@pytest.mark.parametrize("finding", FINDINGS, ids=lambda f: f["finding_id"])
def test_finding_matches_schema(finding):
    jsonschema.validate(finding, SCHEMA)


def test_schema_rejects_prototype_shape():
    """Le format n8n (workflow_id, node_id, proposed_action) n'est plus le contrat courant."""
    prototype = json.loads((ROOT / "fixtures/finding.json").read_text())
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(prototype, SCHEMA)


def test_prototype_fixture_still_matches_its_own_schema():
    """Le pipeline n8n (detector/patcher/prover/habitat) garde son contrat, inchange."""
    n8n_schema = json.loads((ROOT / "schemas/finding.n8n.schema.json").read_text())
    prototype = json.loads((ROOT / "fixtures/finding.json").read_text())
    jsonschema.validate(prototype, n8n_schema)
