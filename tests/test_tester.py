"""make tester : parcours guidé (O/n), --oui, sans terminal, sans exécutions. Aucun appel réseau, ni gh."""
import io
import json
import subprocess
from pathlib import Path

import pytest

import optimize.__main__ as optimize_cli
from scripts import tester
from rules import oversized_model
from scripts.tester import NO_HISTORY, ask, default_source, run
from scripts.tester_seuils import pending
from scripts.tester import found_line
from scripts.tester_ui import colors_on, paint

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


def keys(*sequence):
    it = iter(sequence)
    return lambda: next(it)


def test_ask_oui_et_sans_terminal_acceptent_sans_rien_lire():
    boom = Answers()
    assert ask("Q ?", yes=True, interactive=True, read=boom)
    assert ask("Q ?", interactive=False, read=boom)
    assert boom.questions == []


@pytest.mark.parametrize("answer,expected", [("", True), ("O", True), ("oui", True), ("n", False), ("non", False)])
def test_ask_lit_la_reponse(answer, expected):
    assert ask("Q ?", interactive=True, read=Answers(answer)) is expected


def test_couleurs_seulement_sur_terminal_et_sans_no_color(monkeypatch):
    class Tty(io.StringIO):
        def isatty(self):
            return True
    assert colors_on(Tty(), env={}) and not colors_on(Tty(), env={"NO_COLOR": "1"})
    assert not colors_on(io.StringIO(), env={})
    assert paint("x", "vert", on=False) == "x" and paint("x", "vert", on=True) == "\033[32mx\033[0m"


def test_premiere_ligne_sans_inconnu():
    assert found_line({"nom": None, "noeuds": None, "appels": 1872, "executions": 99, "etapes": 40}) == \
        "Workflow trouvé : 1 872 appels IA · 99 exécutions · 40 étapes"
    assert found_line({"nom": "Essaim", "noeuds": 39, "appels": 18, "executions": None, "etapes": 19}) == \
        "Workflow trouvé : Essaim · 39 nœuds · 18 appels IA · 19 étapes"


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


def test_titre_affiche_la_source_donnee_pas_un_faux_workflow_n8n(tmp_path, capsys):
    run("4553", source=str(EVENTS), out=tmp_path, interactive=False)
    out = capsys.readouterr().out
    assert f"test sur {EVENTS}" in out and "WF 4553" in out and "test du workflow n8n 4553" not in out


def test_titre_sans_source_donnee_reste_le_workflow_n8n(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("N8N_URL", "http://localhost:5678")
    run("4553", out=tmp_path, env={"N8N_URL": "http://localhost:5678"}, interactive=False,
        get=lambda url: pytest.fail(url))
    out = capsys.readouterr().out
    assert "test du workflow n8n 4553" in out


def test_seuil_95_ecarte_une_proposition_du_tableau_et_de_la_pr(tmp_path, capsys):
    """brainstorm-bot (plafond, 82.5 % de précision) n'apparaît nulle part ; reviews (100 %, mais
    refusée faute de volume) reste montrée, comme mail-triage."""
    assert run("4553", source=str(EVENTS), out=tmp_path, interactive=False, animate=False) == 0
    out = capsys.readouterr().out
    assert "brainstorm-bot" not in out
    assert "mail-triage" in out and "reviews" in out
    assert "1 proposition écartée (précision < 95 %)" in out


def test_etape_3_montre_la_barre_de_chaque_modification_retenue(tmp_path, capsys):
    assert run("4553", source=str(EVENTS), out=tmp_path, interactive=False, animate=False) == 0
    out = capsys.readouterr().out
    assert "[3/4] Tests : l'historique rejoué, nouveau workflow comparé à l'ancien" in out
    assert "364 entrées rejouées" in out and "56 entrées rejouées" in out
    assert "\033[" not in out  # pas de couleur ni d'ANSI hors terminal


def test_etape_4_montre_le_tableau_et_les_gains_globaux(tmp_path, capsys):
    assert run("4553", source=str(EVENTS), out=tmp_path, interactive=False, animate=False) == 0
    out = capsys.readouterr().out
    assert "[4/4] Résumé des gains" in out
    assert "Modification" in out and "Précision" in out and "Latence méd." in out
    assert "633 ms → 0 ms" in out  # -100 % : ms bruts, pas un pourcentage qui ressemble à un bug
    assert "Gains sur l’ensemble du workflow" in out
    assert "coût total :" in out and "coût par exécution :" in out and "projection pour 1 000 exécutions" in out
    # jetons envoyés mesurés, plus estimés : aucune valeur de la table ne porte de « ~ »
    table = out.split("Résumé des gains")[1].split("mesuré = rejeu")[0]
    assert "~" not in table


def test_parcours_complet_interactif(tmp_path, capsys, no_gh):
    sender = []
    answers = Answers("", "o")  # Commencer l'analyse ? ; Envoyer le message sur Slack ?
    code = run("4553", source=str(EVENTS), out=tmp_path, repo=str(tmp_path), interactive=True, read=answers,
               webhook="https://hooks.slack.test/x", sender=lambda url, data: sender.append(data),
               read_key=keys("P"), animate=False)
    out = capsys.readouterr().out
    assert code == 0
    assert [q.split(" [")[0] for q in answers.questions] == ["Commencer l'analyse ?", "Envoyer le message sur Slack ?"]
    assert "[4/4] Résumé des gains" in out
    assert "brainstorm-bot" not in out  # sous le seuil d'affichage
    assert no_gh == [str(tmp_path)] and f"PR ouverte : {PR_URL}" in out
    assert len(sender) == 1 and sender[0]["blocks"][-1]["elements"][0]["url"] == PR_URL


def test_menu_review_puis_push(tmp_path, capsys, no_gh):
    """``no_gh`` ne crée pas de vrai diff (pas de dépôt git réel) : Review le dit, puis Push aboutit."""
    code = run("4553", source=str(EVENTS), out=tmp_path, repo=str(tmp_path), interactive=True, read=Answers(""),
               read_key=keys("R", "P"), animate=False)
    out = capsys.readouterr().out
    assert code == 0
    assert "Aucune micro-PR préparée." in out
    assert no_gh == [str(tmp_path)] and f"PR ouverte : {PR_URL}" in out


def _repo(tmp_path):
    repo = tmp_path / "client"
    repo.mkdir()
    (repo / "app.py").write_text(
        'client = OpenAI(default_headers={"x-deadweight-app": "mail-triage"})\n'
        'r = client.chat.completions.create(model="gpt-4o", messages=m)\n')
    for cmd in (["git", "init", "-q"], ["git", "add", "-A"], ["git", "-c", "user.email=t@t", "-c", "user.name=t",
                                                               "commit", "-qm", "init"]):
        subprocess.run(cmd, cwd=repo, check=True)
    return repo


def test_menu_review_montre_le_vrai_diff_prepare(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(optimize_cli, "open_pr", lambda repo, p, branch: PR_URL)
    code = run("4553", source=str(EVENTS), out=tmp_path, repo=str(_repo(tmp_path)), interactive=True,
               read=Answers(""), read_key=keys("R", "Q"), animate=False)
    out = capsys.readouterr().out
    assert code == 0
    assert ".diff" in out and "gpt-4o" in out  # le vrai contenu du diff préparé pour mail-triage


def test_menu_quitter_ne_pousse_rien(tmp_path, capsys, no_gh):
    code = run("4553", source=str(EVENTS), out=tmp_path, repo=str(tmp_path), interactive=True, read=Answers(""),
               read_key=keys("Q"), animate=False)
    assert code == 0 and no_gh == []


def test_menu_absent_hors_tty_et_sans_oui(tmp_path, capsys, no_gh):
    assert run("4553", source=str(EVENTS), out=tmp_path, repo=str(tmp_path), interactive=False, yes=False,
               animate=False, webhook=None) == 0
    out = capsys.readouterr().out
    assert "Review la PR" in out and "Push la PR" in out and "Quitter" in out
    assert "(terminal non interactif : aucun bouton actionné)" in out
    assert no_gh == []


def test_oui_accepte_tout(tmp_path, capsys, no_gh):
    sent = []
    assert run("4553", source=str(EVENTS), out=tmp_path, repo=str(tmp_path), yes=True, interactive=True,
               read=Answers(), webhook="https://hooks.slack.test/x", sender=lambda u, d: sent.append(d),
               animate=False) == 0
    assert no_gh and sent


def test_sans_terminal_ni_repo_ni_webhook_affiche_le_message(tmp_path, capsys):
    assert run("4553", source=str(EVENTS), out=tmp_path, interactive=False, animate=False) == 0
    out = capsys.readouterr().out
    assert "Commencer l'analyse ? [O/n] O" in out
    assert "REPO non fourni" in out and "SLACK_WEBHOOK_URL absent" in out
    assert "*Deadweight :" in out and str(tmp_path / "optim" / "propositions.html") in out
