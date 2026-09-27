"""Une proposition « pass » sous 95 % de précision (ex. banc de modèles en texte libre, seuil 50 %,
ou plafond, seuil 90 %) ne doit ni diff ni PR : le seuil d'affichage du testeur (proof.replay.THRESHOLD)
s'applique aussi ici, sinon la micro-PR contredirait le tableau."""
import json

import optimize.__main__ as optimize_main


def _proposal(app_id, precision):
    return {"type": "modele", "finding_id": f"f_{app_id}", "app_id": app_id, "model": "gpt-4o",
            "changement": f"Passer {app_id} à un modèle plus petit.", "verdict": "pass", "raisons": [],
            "mesures": {"precision": {"valeur": precision, "statut": "mesuré", "unite": "%"}}, "cout_usd": None}


def test_precision_sous_le_seuil_n_ouvre_aucune_pr(tmp_path, monkeypatch):
    low, high = _proposal("faible", 60.0), _proposal("forte", 100.0)
    monkeypatch.setattr(optimize_main, "propose", lambda events, **kw: [low, high])
    monkeypatch.setattr(optimize_main, "make_patch", lambda repo, p: (f"diff {p['app_id']}", []))
    monkeypatch.setattr(optimize_main, "open_pr", lambda repo, p, branch: f"https://pr.test/{p['app_id']}")
    repo = tmp_path / "repo"
    repo.mkdir()
    events = tmp_path / "events.jsonl"
    events.write_text("")
    out = tmp_path / "out"
    assert optimize_main.main([str(events), "--out", str(out), "--repo", str(repo), "--open-prs"]) == 0
    diffs = sorted(p.name for p in out.glob("*.diff"))
    assert diffs == ["01-modele-forte.diff"]  # « faible » (60 %) écarté, « forte » (100 %) préparée
    prs = json.loads((out / "prs.json").read_text())
    assert [pr["app_id"] for pr in prs] == ["forte"]


def test_dw_llm_api_key_branche_l_ia_pour_ecrire_les_regles(tmp_path, monkeypatch):
    # sans IA, les règles ne sont que des mots-clés (trop grossières sur des tickets réels)
    seen = {}
    monkeypatch.setattr(optimize_main, "propose", lambda events, **kw: seen.update(kw) or [])
    monkeypatch.setenv("DW_LLM_API_KEY", "cle-de-test")
    monkeypatch.delenv("DW_LLM_BASE_URL", raising=False)
    events = tmp_path / "events.jsonl"
    events.write_text("")
    assert optimize_main.main([str(events), "--out", str(tmp_path / "out")]) == 0
    llm = seen["llm"]
    assert llm.base_url == "https://api.openai.com/v1" and llm.api_key == "cle-de-test" and llm.model


def test_sans_dw_llm_api_key_regles_hors_ligne(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(optimize_main, "propose", lambda events, **kw: seen.update(kw) or [])
    monkeypatch.delenv("DW_LLM_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "autre-projet")  # une clé d'un autre projet ne suffit pas
    events = tmp_path / "events.jsonl"
    events.write_text("")
    assert optimize_main.main([str(events), "--out", str(tmp_path / "out")]) == 0
    assert seen["llm"] is None
