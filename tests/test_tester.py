"""make tester : parcours guidé (O/n), --oui, sans terminal, sans exécutions. Aucun appel réseau, ni gh."""
import json
import subprocess
from pathlib import Path

import pytest

from rules import oversized_model
from scripts import tester
from scripts.tester import NO_HISTORY, ask, default_source, min_calls_env, run
from scripts.tester_seuils import pending
from scripts.tester_ui import cell

ROOT = Path(__file__).resolve().parents[1]
EVENTS = ROOT / "fixtures/dataset/v1/events.jsonl"
PR_URL = "https://github.com/client/app/pull/7"


@pytest.fixture(autouse=True)
def no_keys(monkeypatch):
    for key in ("DW_LLM_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY", "SLACK_WEBHOOK_URL", "N8N_URL",
                "DW_MIN_CALLS"):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def no_gh(monkeypatch):
    """--open-prs simulé : prs.json écrit comme optimize le ferait, sans gh ni push réel. ``make_patch``
    a besoin d'un vrai dépôt (``git add``) : le dépôt cible est git-initialisé à la volée si besoin."""
    real, opened = tester._optimize, []

    def fake(events, optim, repo=None, open_prs=False):
        if repo and not (Path(repo) / ".git").is_dir():
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True, capture_output=True)
        code = real(events, optim, repo)
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


def test_cellule_mesure_estime_et_absent():
    assert cell({"valeur": -24.4, "statut": "mesuré", "unite": "%"}) == "-24.4 %"
    assert cell({"valeur": -35.7, "statut": "estimé", "unite": "%", "hypothese": "h"}) == "~-35.7 %"
    assert cell({"valeur": 100.0, "statut": "mesuré", "unite": "%"}, level=True) == "100 %"
    assert cell({"valeur": None, "statut": "mesuré", "unite": "%"}) == "—"
    assert cell(None) == "—"


@pytest.mark.parametrize("env,expected", [({}, 30), ({"DW_MIN_CALLS": "3"}, 3), ({"DW_MIN_CALLS": "x"}, 30)])
def test_min_calls_env_defaut_et_invalide(env, expected):
    assert min_calls_env(env) == expected


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
    assert run("4553", source=str(EVENTS), out=tmp_path, interactive=True, read=answers, color=False) == 0
    assert "Workflow trouvé" in capsys.readouterr().out
    assert not (tmp_path / "optim").exists()


def test_titre_affiche_la_source_donnee_pas_un_faux_workflow_n8n(tmp_path, capsys):
    run("4553", source=str(EVENTS), out=tmp_path, interactive=False, animate=False, color=False)
    out = capsys.readouterr().out
    assert f"test sur {EVENTS}" in out and "WF 4553" in out and "test du workflow n8n 4553" not in out


def test_echantillon_reduit_affiche_un_avertissement(tmp_path, capsys):
    run("4553", source=str(EVENTS), out=tmp_path, interactive=False, animate=False, color=False,
        env={"DW_MIN_CALLS": "3"})
    out = capsys.readouterr().out
    assert "échantillon réduit : seuil abaissé à 3 appels par étape, chiffres indicatifs" in out


def test_sans_dw_min_calls_pas_d_avertissement(tmp_path, capsys):
    run("4553", source=str(EVENTS), out=tmp_path, interactive=False, animate=False, color=False, env={})
    assert "échantillon réduit" not in capsys.readouterr().out


def test_parcours_complet_interactif(tmp_path, capsys, no_gh):
    sender = []
    answers = Answers("")  # Lancer l'analyse ?
    code = run("4553", source=str(EVENTS), out=tmp_path, repo=str(tmp_path), interactive=True, read=answers,
               webhook="https://hooks.slack.test/x", sender=lambda url, data: sender.append(data),
               read_key=keys("R", "P", "S", "Q"), animate=False, color=False)
    out = capsys.readouterr().out
    assert code == 0
    assert answers.questions == ["  Lancer l'analyse ? [O/n] "]
    for title in ("[1/4] Analyse du workflow", "[2/4] Modifications proposées", "[3/4] Tests",
                  "[4/4] Résumé des gains", "Review la PR", "Push la PR", "Envoyer sur Slack"):
        assert title in out
    assert "1872 appels IA" in out
    assert "brainstorm-bot" not in out  # 82.5 % : sous le seuil d'affichage, écarté partout
    assert "364 entrées rejouées" in out and "-73.3 %" in out  # jetons mesurés, plus de « ~ »
    assert "633 ms → 0 ms" in out  # latence médiane à -100 % : ms brutes, pas un pourcentage
    assert "Gains sur l’ensemble du workflow" in out and "coût par exécution" in out
    assert no_gh == [str(tmp_path)] and f"PR ouverte : {PR_URL}" in out
    assert len(sender) == 1 and sender[0]["blocks"][-1]["elements"][0]["url"] == PR_URL


def test_oui_accepte_tout(tmp_path, capsys, no_gh):
    sent = []
    assert run("4553", source=str(EVENTS), out=tmp_path, repo=str(tmp_path), yes=True, interactive=True,
               read=Answers(), webhook="https://hooks.slack.test/x", sender=lambda u, d: sent.append(d),
               animate=False, color=False) == 0
    assert no_gh and sent


def test_oui_sans_repo_le_dit_plutot_que_de_rester_muet(tmp_path, capsys):
    """Régression : ``OUI=1`` sans ``REPO`` doit quand même expliquer pourquoi rien n'est poussé."""
    assert run("4553", source=str(EVENTS), out=tmp_path, yes=True, interactive=True, read=Answers(),
               animate=False, color=False) == 0
    assert "REPO non fourni" in capsys.readouterr().out


def test_oui_sans_webhook_affiche_quand_meme_le_message_prepare(tmp_path, capsys):
    """Régression : sans ``SLACK_WEBHOOK_URL``, le message Slack préparé reste visible (README)."""
    assert run("4553", source=str(EVENTS), out=tmp_path, yes=True, interactive=True, read=Answers(),
               animate=False, color=False) == 0
    out = capsys.readouterr().out
    assert "SLACK_WEBHOOK_URL absent, non envoyé" in out and "*Deadweight :" in out


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
    import optimize.__main__ as optimize_cli
    monkeypatch.setattr(optimize_cli, "open_pr", lambda repo, p, branch: PR_URL)
    code = run("4553", source=str(EVENTS), out=tmp_path, repo=str(_repo(tmp_path)), interactive=True,
               read=Answers(""), read_key=keys("R", "Q"), animate=False, color=False)
    out = capsys.readouterr().out
    assert code == 0
    assert "+GATEWAY_SHORTCIRCUIT=deadweight/preuves" in out  # le vrai diff relu, pas un texte statique


def test_sans_repo_les_boutons_restent_disponibles_mais_s_adaptent(tmp_path, capsys):
    """Sans REPO : Review pointe vers la page développeur (rien à relire, aucun dépôt cible), et Push
    donne la commande exacte à relancer plutôt que de rester muet ou de pousser quelque part."""
    assert run("4553", source=str(EVENTS), out=tmp_path, interactive=True, read=Answers(""),
               read_key=keys("R", "P", "Q"), animate=False, color=False) == 0
    out = capsys.readouterr().out
    assert "Review la PR" in out and "Push la PR" in out  # les deux boutons apparaissent, même sans REPO
    assert f"Page développeur (diff des propositions) : {tmp_path / 'optim' / 'propositions.html'}" in out
    assert f"make tester WF=4553 SOURCE={EVENTS} REPO=chemin/du/depot" in out
    assert "Envoyer sur Slack" not in out  # pas de webhook : pas de bouton Slack


def test_menu_absent_hors_tty_et_sans_oui(tmp_path, capsys, no_gh):
    assert run("4553", source=str(EVENTS), out=tmp_path, repo=str(tmp_path), interactive=False, yes=False,
               animate=False, color=False, webhook=None) == 0
    out = capsys.readouterr().out
    assert "Review la PR" in out and "Push la PR" in out and "Quitter" in out
    assert "(terminal non interactif : aucun bouton actionné)" in out
    assert no_gh == []


def test_sans_terminal_aucun_bouton_actionne(tmp_path, capsys):
    assert run("4553", source=str(EVENTS), out=tmp_path, interactive=False, animate=False, color=False) == 0
    out = capsys.readouterr().out
    assert "Lancer l'analyse ? [O/n] O" in out and "aucun bouton actionné" in out
    assert "\x1b[" not in out and str(tmp_path / "optim" / "propositions.html") in out
