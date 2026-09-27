"""D2.6 (Problème 1) : abonnement vs API, jamais deviné.

- connectors.agent_logs.billing : détection sur la configuration réelle de l'outil (fichiers de
  test, jamais les vrais fichiers de l'utilisateur), et override explicite ``--billing``.
- report.billing : pics d'appels mesurés (5 heures, semaine) et étiquette « valeur consommée en
  équivalent API » quand la facturation est un abonnement.
- report.audit : rendu, sans jamais changer le comportement par défaut (billing=None)."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from connectors.agent_logs import billing
from optimize.propose import propose
from optimize.slack import message
from report.audit import build_report, render_html
from report.billing import billing_section, load_billing, peak_window, subscription_only

ROOT = Path(__file__).resolve().parent.parent
EVENTS = [json.loads(line) for line in (ROOT / "fixtures/dataset/v1/events.jsonl").read_text().splitlines()
          if line.strip()]
TRIAGE = [e for e in EVENTS if e["app_id"] == "mail-triage"]
SUB = {"claude-code": {"mode": "abonnement", "source": "test"}}


@pytest.fixture(scope="module")
def proposals():
    return propose(EVENTS)


# ---------- détection (connectors.agent_logs.billing) ----------

def test_claude_code_abonnement_detecte_via_oauth_billing_type(tmp_path):
    cfg = tmp_path / ".claude.json"
    cfg.write_text(json.dumps({"oauthAccount": {"billingType": "stripe_subscription"}}), encoding="utf-8")
    result = billing.detect_claude_code(config_path=cfg, env={})
    assert result == {"mode": billing.ABONNEMENT, "source": f"{cfg}:oauthAccount.billingType"}


def test_claude_code_api_detecte_via_variable_environnement(tmp_path):
    cfg = tmp_path / ".claude.json"
    cfg.write_text(json.dumps({}), encoding="utf-8")
    result = billing.detect_claude_code(config_path=cfg, env={"ANTHROPIC_API_KEY": "sk-ant-xxx"})
    assert result == {"mode": billing.API, "source": "env:ANTHROPIC_API_KEY"}
    # jamais la valeur de la clé dans le résultat
    assert "sk-ant-xxx" not in json.dumps(result)


def test_claude_code_oauth_sans_billing_type_reconnu_reste_inconnu(tmp_path):
    cfg = tmp_path / ".claude.json"
    cfg.write_text(json.dumps({"oauthAccount": {"billingType": "autre_chose"}}), encoding="utf-8")
    assert billing.detect_claude_code(config_path=cfg, env={})["mode"] == billing.INCONNU


def test_claude_code_config_absente_est_inconnue(tmp_path):
    assert billing.detect_claude_code(config_path=tmp_path / "absent.json", env={}) == \
        {"mode": billing.INCONNU, "source": None}


def test_codex_abonnement_detecte_via_auth_mode_chatgpt(tmp_path):
    auth = tmp_path / "auth.json"
    auth.write_text(json.dumps({"auth_mode": "chatgpt", "OPENAI_API_KEY": None}), encoding="utf-8")
    result = billing.detect_codex(auth_path=auth)
    assert result == {"mode": billing.ABONNEMENT, "source": f"{auth}:auth_mode"}


def test_codex_api_detecte_via_cle_openai(tmp_path):
    auth = tmp_path / "auth.json"
    auth.write_text(json.dumps({"auth_mode": None, "OPENAI_API_KEY": "sk-xxx"}), encoding="utf-8")
    result = billing.detect_codex(auth_path=auth)
    assert result == {"mode": billing.API, "source": f"{auth}:OPENAI_API_KEY"}
    assert "sk-xxx" not in json.dumps(result)


def test_codex_config_absente_est_inconnue(tmp_path):
    assert billing.detect_codex(auth_path=tmp_path / "absent.json") == {"mode": billing.INCONNU, "source": None}


def test_override_cli_prioritaire_sur_la_detection():
    assert billing.resolve("claude-code", override="api") == {"mode": "api", "source": "--billing (forcé)"}
    assert billing.resolve("codex", override="abonnement") == {"mode": "abonnement", "source": "--billing (forcé)"}


def test_outil_inconnu_sans_override_est_inconnu():
    assert billing.resolve("autre-outil") == {"mode": billing.INCONNU, "source": None}


# ---------- rapport (report.billing) ----------

def test_peak_window_compte_le_pic_mesure_sans_inventer_de_pourcentage():
    events = [{"ts_start": t} for t in ("2026-09-26T10:00:00Z", "2026-09-26T10:30:00Z",
                                        "2026-09-26T10:45:00Z", "2026-09-27T09:00:00Z")]
    pic = peak_window(events, 5 * 3600)
    assert pic["nb_appels"] == 3  # les trois premiers, groupés en 45 min ; le dernier est isolé (+23h)
    assert pic["debut"].startswith("2026-09-26T10:00") and pic["fin"].startswith("2026-09-26T10:45")


def test_billing_section_ajoute_pics_et_valeur_equivalente_pour_un_abonnement():
    events = [{**e, "app_id": "claude-code:demo"} for e in EVENTS if e["app_id"] == "mail-triage"]
    section = billing_section(events, {"claude-code": {"mode": "abonnement", "source": "test"}})
    assert section["tout_abonnement"] is True
    outil = section["outils"][0]
    assert outil["mode"] == "abonnement" and outil["pic_5h"]["nb_appels"] > 0
    assert outil["valeur_equivalente_usd"] is not None
    assert "quota exact" in outil["limite_note"]


def test_billing_section_none_sans_evenement_d_agent_de_code():
    assert billing_section(EVENTS, {"claude-code": {"mode": "abonnement", "source": "t"}}) is None


def test_billing_section_pas_tout_abonnement_si_un_outil_est_en_api():
    events = ([{**e, "app_id": "claude-code:demo"} for e in EVENTS[:2]]
              + [{**e, "app_id": "codex:demo"} for e in EVENTS[:2]])
    section = billing_section(events, {"claude-code": {"mode": "abonnement", "source": "t"},
                                       "codex": {"mode": "api", "source": "t"}})
    assert section["tout_abonnement"] is False


# ---------- rapport HTML (report.audit) ----------

def test_build_report_sans_billing_est_inchange():
    report = build_report(EVENTS)
    assert report["billing"] is None
    assert "valeur consommée" not in render_html(report).lower()


def test_rapport_affiche_valeur_equivalente_api_quand_abonnement():
    events = [{**e, "app_id": "claude-code:demo"} for e in EVENTS if e["app_id"] == "mail-triage"]
    report = build_report(events, billing={"claude-code": {"mode": "abonnement", "source": "test"}})
    html_out = render_html(report).lower()
    assert "valeur consommée (équiv. api)" in html_out
    assert "facturation" in html_out and "pic mesuré" in html_out


def test_rapport_avec_api_garde_le_libelle_cout():
    events = [{**e, "app_id": "claude-code:demo"} for e in EVENTS if e["app_id"] == "mail-triage"]
    report = build_report(events, billing={"claude-code": {"mode": "api", "source": "test"}})
    html_out = render_html(report)
    assert "valeur consommée" not in html_out.lower()
    assert "Facturation" in html_out and "API" in html_out


# ---------- gains par tâche prouvés (report.audit, D2.6 Problème 2) ----------

def test_gains_par_tache_absent_sans_propositions():
    assert build_report(EVENTS)["gains_par_tache"] == []


def test_gains_par_tache_reprend_les_chiffres_de_optimize_propose_sans_les_recalculer(proposals):
    report = build_report(EVENTS, propositions=proposals)
    # "mail-triage" a aussi une proposition "cache" (R8, optimize.propose) désormais : on cible
    # explicitement celle de "regles" (R1), la seule dont les figures attendues sont ci-dessous.
    triage = next(r for r in report["gains_par_tache"]
                 if r["app_id"] == "mail-triage" and "Remplacer les appels" in r["changement"])
    labels = [f["label"] for f in triage["figures"]]
    assert labels == ["contexte envoyé", "coût", "latence médiane", "précision"]
    assert triage["part_pct"] is not None
    html_out = render_html(report)
    assert "Gains par tâche, prouvés" in html_out and "Pour cette tâche : contexte envoyé" in html_out
    assert "% de la dépense totale" in html_out


def test_gains_par_tache_ignore_les_propositions_non_prouvees(proposals):
    assert any(p["verdict"] != "pass" for p in proposals)  # les échanges de modèle ne sont pas prouvés ici
    report = build_report(EVENTS, propositions=proposals)
    assert len(report["gains_par_tache"]) == sum(p["verdict"] == "pass" for p in proposals)


# ---------- câblage CLI (report.audit --comprehension / --billing / --propositions) ----------

def test_cli_comprehension_billing_et_propositions(tmp_path, proposals):
    comprehension = {"claude-code": {"billing": {"mode": "abonnement", "source": "test"}}}
    (tmp_path / "comprehension.json").write_text(json.dumps(comprehension), encoding="utf-8")
    slim = [{k: v for k, v in p.items() if k != "preuve"} for p in proposals]
    (tmp_path / "propositions.json").write_text(json.dumps(slim), encoding="utf-8")
    events_path = tmp_path / "events.jsonl"
    events_path.write_text("\n".join(json.dumps({**e, "app_id": "claude-code:" + e["app_id"]}) for e in EVENTS),
                           encoding="utf-8")
    out = tmp_path / "audit.html"
    subprocess.run([sys.executable, "-m", "report.audit", str(events_path), "-o", str(out),
                   "--comprehension", str(tmp_path / "comprehension.json"),
                   "--propositions", str(tmp_path / "propositions.json")],
                  cwd=ROOT, check=True, capture_output=True)
    html_out = out.read_text().lower()
    assert "valeur consommée (équiv. api)" in html_out
    assert "gains par tâche, prouvés" in html_out


def test_cli_billing_override_sans_comprehension(tmp_path):
    events_path = tmp_path / "events.jsonl"
    events_path.write_text("\n".join(json.dumps({**e, "app_id": "codex:" + e["app_id"]}) for e in TRIAGE),
                           encoding="utf-8")
    out = tmp_path / "audit.html"
    subprocess.run([sys.executable, "-m", "report.audit", str(events_path), "-o", str(out), "--billing", "abonnement"],
                  cwd=ROOT, check=True, capture_output=True)
    assert "valeur consommée (équiv. api)" in out.read_text().lower()


# ---------- abonnement : gains en équivalent API, jamais une économie facturée ----------

def test_load_billing_override_prioritaire_sur_comprehension(tmp_path):
    path = tmp_path / "comprehension.json"
    path.write_text(json.dumps({"claude-code": {"billing": {"mode": "api", "source": "x"}}, "codex": {}}))
    assert load_billing(str(path)) == {"claude-code": {"mode": "api", "source": "x"}}
    assert load_billing(str(path), "abonnement") == {"claude-code": {"mode": "abonnement", "source": "--billing (forcé)"}}
    assert set(load_billing(None, "api")) == {"claude-code", "codex"}
    assert load_billing() is None


def test_subscription_only_exige_que_tous_les_outils_soient_sur_abonnement():
    events = [{**e, "app_id": "claude-code:" + e["app_id"]} for e in TRIAGE]
    assert subscription_only(events, SUB) is True
    assert subscription_only(events, {"claude-code": {"mode": "api", "source": "t"}}) is False
    assert subscription_only(events, None) is False
    assert subscription_only(TRIAGE, SUB) is False  # aucun agent de code : pas de requalification


def test_rapport_abonnement_parle_de_valeur_equivalente_pas_de_depense(proposals):
    events = [{**e, "app_id": "claude-code:" + e["app_id"]} for e in EVENTS]
    props = [{**p, "app_id": "claude-code:" + p["app_id"]} for p in proposals]
    report = build_report(events, billing=SUB, propositions=props)
    assert report["gains_equivalent_api"] is True and report["gains_par_tache"]
    html_out = render_html(report)
    assert "de la valeur consommée (équiv. API)" in html_out and "la facture reste le prix du forfait" in html_out
    assert "de la dépense totale" not in html_out


def test_slack_abonnement_presente_les_gains_par_tache_sans_economie_facturee(proposals):
    triage = next(p for p in proposals if p["type"] == "regles" and p["app_id"] == "mail-triage")
    text = message(proposals, total_spent=triage["cout_usd"]["avant"], equivalent_api=True)
    assert "Valeur consommée (équiv. API) :" in text and "• Coût :" not in text
    assert "pas une économie en argent" in text and "Pour cette tâche : contexte envoyé" in text
    assert "de la dépense totale" not in text


def test_slack_paiement_a_l_usage_garde_l_economie_reelle(proposals):
    text = message(proposals, total_spent=1.0)
    assert "• Coût :" in text and "de la dépense totale" in text and "forfait" not in text


def test_cli_optimize_billing_abonnement(tmp_path):
    from optimize.__main__ import main
    events_path = tmp_path / "events.jsonl"
    events_path.write_text("\n".join(json.dumps({**e, "app_id": "claude-code:" + e["app_id"]}) for e in TRIAGE))
    assert main([str(events_path), "--out", str(tmp_path / "o"), "--billing", "abonnement"]) == 0
    assert "pas une économie en argent" in (tmp_path / "o" / "slack.md").read_text()
