"""make tester : parcours guidé (O/n), --oui, sans terminal, sans exécutions. Aucun appel réseau, ni gh."""
import json
from pathlib import Path

import pytest

from scripts import tester
from rules import oversized_model
from scripts.tester import NO_HISTORY, ask, default_source, figure, run
from scripts.tester_seuils import pending

ROOT = Path(__file__).resolve().parents[1]
EVENTS = ROOT / "fixtures/dataset/v1/events.jsonl"
PR_URL = "https://github.com/client/app/pull/7"


@pytest.fixture(autouse=True)
def no_keys(monkeypatch):
    for key in ("DW_LLM_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY", "SLACK_WEBHOOK_URL", "N8N_URL"):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def no_gh(monkeypatch):
    """--open-prs simulé : prs.json écrit comme optimize le ferait, sans gh ni git."""
    real, opened = tester._optimize, []

    def fake(events, optim, repo=None, open_prs=False):
        code = real(events, optim)
        if open_prs:
            opened.append(repo)
            (Path(optim) / "prs.json").write_text(json.dumps([{"app_id": "mail-triage", "changement": "x",
                                                              "url": PR_URL}]), encoding="utf-8")
        return code
    monkeypatch.setattr(tester, "_optimize", fake)
    return opened


class Answers:
    def __init__(self, *answers):
        self.answers, self.questions = list(answers), []

    def __call__(self, prompt):
        self.questions.append(prompt)
        return self.answers.pop(0)


def test_ask_oui_et_sans_terminal_acceptent_sans_rien_lire():
    boom = Answers()
    assert ask("Q ?", yes=True, interactive=True, read=boom)
    assert ask("Q ?", interactive=False, read=boom)
    assert boom.questions == []


@pytest.mark.parametrize("answer,expected", [("", True), ("O", True), ("oui", True), ("n", False), ("non", False)])
def test_ask_lit_la_reponse(answer, expected):
    assert ask("Q ?", interactive=True, read=Answers(answer)) is expected


def test_figure_mesure_estime_et_absent():
    assert figure({"valeur": -24.4, "statut": "mesuré", "unite": "%"}) == "-24.4 % (mesuré)"
    assert figure({"valeur": -35.7, "statut": "estimé", "unite": "%", "hypothese": "h"}) == "~-35.7 % (estimé : h)"
    assert figure({"valeur": 100.0, "statut": "mesuré", "unite": "%"}, level=True) == "100 % (mesuré)"
    assert figure({"valeur": None, "statut": "mesuré", "unite": "%"}) == "non mesuré"
    assert figure(None) == "non mesuré"


def test_source_par_defaut(tmp_path):
    assert default_source("4553", {"N8N_URL": "http://localhost:5678"}) == "n8n:4553"
    assert default_source("4553", {}, dirs=(str(tmp_path),)) is None
    folder = tmp_path / "4553"
    folder.mkdir()
    (folder / "workflow.json").write_text("{}")
    (folder / "executions.jsonl").write_text("")
    assert default_source("4553", {}, dirs=(str(tmp_path),)) == str(folder)


SWARM = {"id": 4553, "name": "Essaim", "nodes": [
    {"name": "Modele", "type": "@n8n/n8n-nodes-langchain.lmChatOpenAi", "parameters": {"model": "gpt-4.1-mini"}},
    {"name": "Agent A", "type": "@n8n/n8n-nodes-langchain.agent", "parameters": {}},
    {"name": "Agent B", "type": "@n8n/n8n-nodes-langchain.agent", "parameters": {}},
    {"name": "Webhook", "type": "n8n-nodes-base.webhook", "parameters": {}}],
    "connections": {"Modele": {"ai_languageModel": [[{"node": "Agent A"}, {"node": "Agent B"}]]}}}


def test_sans_source_analyse_de_structure_seule(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)  # pas de private/n8n-library local
    urls = []
    get = lambda url: urls.append(url) or {"workflow": {**SWARM, "workflow": SWARM}}  # noqa: E731
    assert run("4553", out=tmp_path / "o", env={}, get=get) == 0
    out = capsys.readouterr().out
    assert urls == ["https://api.n8n.io/api/templates/workflows/4553"]
    assert NO_HISTORY in out and "4 nœuds, 1 nœud(s) modèle, gpt-4.1-mini, 2 agent(s)" in out
    assert "~2 appels IA par exécution" in out and "non mesuré" in out
    assert f"modèle trop gros : {oversized_model.MIN_CALLS} appels nécessaires par étape, 0 présents" in out
    assert "N8N_URL" in out and not (tmp_path / "o" / "optim").exists()


def test_sans_structure_ni_historique(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert run("4553", out=tmp_path, env={}, get=lambda url: None) == 1


def test_peu_d_appels_liste_les_verifications_en_attente():
    events = [{"app_id": "n8n:wf/Agent A", "model": "gpt-4.1-mini", "trace": {"id": f"x{i % 2}"}}
              for i in range(18)]
    rows = {r["verification"]: r for r in pending(events, executions=2)}
    assert rows["modèle trop gros"] == {"verification": "modèle trop gros", "seuil": oversized_model.MIN_CALLS,
                                        "presents": 18, "executions_estimees": 4}
    assert pending(events * 2) == []  # 36 appels : tous les seuils atteints


def test_sans_executions_rien_n_est_simule(tmp_path, capsys):
    folder = tmp_path / "4553"  # workflow importé dans n8n mais jamais exécuté
    folder.mkdir()
    (folder / "workflow.json").write_text(json.dumps(SWARM))
    (folder / "executions.jsonl").write_text("")
    assert run("4553", source=str(folder), out=tmp_path / "o", yes=True, get=lambda url: pytest.fail(url)) == 0
    out = capsys.readouterr().out
    assert NO_HISTORY in out and "Analyse de structure seule : Essaim" in out
    assert not (tmp_path / "o" / "optim").exists()


def test_refus_au_depart_n_analyse_rien(tmp_path, capsys):
    answers = Answers("n")
    assert run("4553", source=str(EVENTS), out=tmp_path, interactive=True, read=answers) == 0
    assert "Workflow trouvé" in capsys.readouterr().out
    assert not (tmp_path / "optim").exists()


def test_parcours_complet_interactif(tmp_path, capsys, no_gh):
    sender = []
    answers = Answers("", "o", "O")
    code = run("4553", source=str(EVENTS), out=tmp_path, repo=str(tmp_path), interactive=True, read=answers,
               webhook="https://hooks.slack.test/x", sender=lambda url, data: sender.append(data))
    out = capsys.readouterr().out
    assert code == 0
    assert [q.split(" [")[0] for q in answers.questions] == [
        "Commencer l'analyse ?", "Ouvrir la PR GitHub ?", "Envoyer le message sur Slack ?"]
    proposals = json.loads((tmp_path / "optim" / "propositions.json").read_text())
    assert f"Workflow analysé : {len(proposals)} modifications trouvées" in out
    assert "1872 appels IA" in out and "Vérifications en attente de données (pas un échec" not in out and "(mesuré)" in out and "~" in out and "non mesuré" in out
    assert no_gh == [str(tmp_path)] and f"PR ouverte : {PR_URL}" in out
    assert len(sender) == 1 and sender[0]["blocks"][-1]["elements"][0]["url"] == PR_URL


def test_oui_accepte_tout(tmp_path, capsys, no_gh):
    sent = []
    assert run("4553", source=str(EVENTS), out=tmp_path, repo=str(tmp_path), yes=True, interactive=True,
               read=Answers(), webhook="https://hooks.slack.test/x", sender=lambda u, d: sent.append(d)) == 0
    assert no_gh and sent


def test_sans_terminal_ni_repo_ni_webhook_affiche_le_message(tmp_path, capsys):
    assert run("4553", source=str(EVENTS), out=tmp_path, interactive=False) == 0
    out = capsys.readouterr().out
    assert "Commencer l'analyse ? [O/n] O" in out
    assert "REPO non fourni" in out and "SLACK_WEBHOOK_URL absent" in out
    assert "*Deadweight :" in out and str(tmp_path / "optim" / "propositions.html") in out
