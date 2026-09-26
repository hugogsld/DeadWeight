"""B1.4 : masquage des données personnelles et effacement du brut."""
import json
from pathlib import Path

import jsonschema
import pytest

from importers.n8n.__main__ import main
from importers.n8n.privacy import Masker, purge

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "tests/data/n8n/support"
SCHEMA = json.loads((ROOT / "schemas/event.schema.json").read_text())


@pytest.mark.parametrize("raw,masked", [
    ("écrire à jean.dupont+sav@exemple.fr svp", "écrire à [email-1] svp"),
    ("appelez le 06 12 34 56 78", "appelez le [telephone-1]"),
    ("ou le +33 6 12 34 56 78.", "ou le [telephone-1]."),
    ("fixe : 01.23.45.67.89", "fixe : [telephone-1]"),
    ("IBAN FR76 3000 6000 0112 3456 7890 189", "IBAN [iban-1]"),
    ("carte 4111 1111 1111 1111", "carte [carte-1]"),
])
def test_masque(raw, masked):
    assert Masker().text(raw) == masked


@pytest.mark.parametrize("keep", [
    "commande 4471",
    "le 2026-09-21 à 14:13",
    "montant 1234.56 €",
    "ticket 123456789",           # identifiant qui ne commence ni par 0 ni par +
    "carte 1234 5678 9012 3456",  # 16 chiffres mais pas un numéro de carte valide
])
def test_ne_masque_pas(keep):
    assert Masker().text(keep) == keep


def test_etiquettes_stables():
    m = Masker()
    out = m.text("a@b.fr, 06 12 34 56 78, A@B.FR, 0612345678, c@d.fr")
    assert out == "[email-1], [telephone-1], [email-1], [telephone-1], [email-2]"
    assert m.summary() == {"email": 2, "telephone": 1}


def test_evenement_masque_partout():
    ev = {"request": {"system": "support@acme.fr", "messages": [
              {"role": "assistant", "content": None,
               "tool_calls": [{"name": "t", "arguments": '{"to": "x@y.fr"}'}]},
              {"role": "user", "content": "rappel 0612345678"}]},
          "response": {"content": "écrit à x@y.fr", "tool_calls": [{"name": "t", "arguments": '"0612345678"'}]},
          "error": {"type": "e", "message": "refusé pour x@y.fr"}}
    Masker().event(ev)
    text = json.dumps(ev)
    assert "@" not in text and "0612345678" not in text
    assert ev["response"]["content"] == "écrit à [email-2]"


def test_commande_anonymize_puis_purge(tmp_path, capsys):
    folder = tmp_path / "wf"
    folder.mkdir()
    wf = (DATA / "workflow.json").read_text()
    ex = (DATA / "executions.jsonl").read_text().replace("Ou est mon colis ?", "Ou est mon colis ? marie@exemple.fr")
    (folder / "workflow.json").write_text(wf)
    (folder / "executions.jsonl").write_text(ex)

    assert main(["convert", str(folder), "--anonymize"]) == 0
    assert "anonymisé : 1 email" in capsys.readouterr().out
    lines = (folder / "events.jsonl").read_text().splitlines()
    assert "marie@exemple.fr" not in "".join(lines) and "[email-1]" in "".join(lines)
    for line in lines:
        jsonschema.validate(json.loads(line), SCHEMA)

    assert main(["purge", str(folder)]) == 0
    assert not folder.exists()


def test_purge_refuse_un_autre_dossier(tmp_path):
    (tmp_path / "important.txt").write_text("x")
    with pytest.raises(ValueError):
        purge(tmp_path)
    assert (tmp_path / "important.txt").exists()
    assert main(["purge", str(tmp_path)]) == 1
