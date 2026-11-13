"""Rapport cohérent : une note de chiffre manquant, un seul montant de valeur consommée, conseils selon la source."""
import copy
import json
import re
from pathlib import Path

from report.audit import _card, build_report, render_html
from report.cost import more_data_hint, source_kind
from report.pourquoi import diagnostic, lignes

ROOT = Path(__file__).resolve().parent.parent
BASE = json.loads((ROOT / "fixtures/events.jsonl").read_text().splitlines()[0])


def ev(i, app="claude-code:proj", model="claude-sonnet-4-5"):
    e = copy.deepcopy(BASE)
    e.update(event_id=f"e{i}", app_id=app, provider="anthropic", model=model, error=None,
             ts_start=f"2026-09-01T00:{i // 60:02d}:{i % 60:02d}Z", ts_end=f"2026-09-01T00:{i // 60:02d}:{i % 60:02d}.5Z")
    e["usage"] = {"input_tokens": 1000, "output_tokens": 50, "cached_input_tokens": 0}
    return e


def _constat(app, reasons):
    n = {"cout_mensuel_usd": None, "cout_observe_usd": 1.0, "latence_mediane_ms": 100, "latence_p95_ms": 200,
         "nb_appels": 3, "passages": 2, "cout_par_passage_usd": 0.5}
    return {"titre": "t", "app_id": app, "model": "m", "phrase": "p", "action": "a", "prouve": False,
            "chiffres": n, "raisons_manquantes": reasons, "alternatives": None}


def test_note_de_duree_courte_jamais_repetee_sous_un_constat():
    short = "moins d'une journée de trafic observée (12.0 min, 1 passage), projection sur un mois non fiable, x"
    page = _card(_constat("a", [short, "modele absent du catalogue : zzz"]), global_reasons=["autre texte"])
    assert "moins d'une journée" not in page
    assert "modele absent du catalogue : zzz" in page  # une raison propre au constat reste dite


def test_une_seule_valeur_consommee_en_tete_et_dans_facturation():
    events = [ev(i) for i in range(5)] + [ev(5 + i, model="modele-inconnu-x") for i in range(5)]
    report = build_report(events, billing={"claude-code": {"mode": "abonnement", "source": "t"}})
    page = render_html(report)
    header = re.search(r'<b>([^<]+)</b><span>valeur consommée', page).group(1)
    billing = re.search(r"équivalent API</b>[^:]*: ([^<]*?) \(partiel[^<]* sur la période observée", page).group(1)
    assert header == billing != "non disponible"
    assert "non disponible sur la période observée" not in page


def test_source_kind_et_conseil_par_source():
    assert source_kind([ev(0)]) == "logs" and source_kind([ev(0, app="codex:p")]) == "logs"
    assert source_kind([ev(0, app="n8n:wf/node")]) == "n8n"
    assert source_kind([ev(0, app="mon-app")]) == "passerelle"
    assert "plus de sessions" in more_data_hint([ev(0)]) and "passerelle" not in more_data_hint([ev(0)])
    assert "exécutions" in more_data_hint([ev(0, app="n8n:w/x")])
    assert "passerelle" in more_data_hint([ev(0, app="mon-app")])


def test_rapport_logs_ne_parle_pas_de_passerelle():
    events = [ev(i) for i in range(5)]
    for e in events:
        e["model"] = "modele-inconnu-x"
    report = build_report(events)
    page = render_html(report) + "\n".join(lignes(diagnostic(events)))
    assert "laissez tourner la passerelle" not in page
    n8n = [ev(i, app="n8n:wf/x") for i in range(5)]
    assert "exécutions" in "\n".join(lignes(diagnostic(n8n))) and "passerelle" not in "\n".join(lignes(diagnostic(n8n)))


# ---------- items 5 et 6 : constats sans piste rejouable, conseils selon la source ----------

def test_slack_distingue_constats_sans_piste_et_aucun_constat():
    from optimize.slack import message
    rows = [{"regle": "context_reread", "titre": "Chaque appel relit la conversation", "nb": 2,
             "pourquoi": "p", "pour_tester": "t"}]
    text = message([], sans_piste=rows, kind="logs")
    assert "2 constat(s) statistique(s), mais aucune piste testable par rejeu" in text
    assert "Pour le tester : t" in text and "/compact" in text
    assert "Pourquoi aucun constat" not in text
    assert "Aucun constat sur ces données" in message([], sans_piste=[])


def test_sans_piste_liste_les_constats_sans_proposition():
    from optimize.propose import sans_piste
    events = [json.loads(line) for line in (ROOT / "fixtures/dataset/v1/events.jsonl").read_text().splitlines()]
    rows = sans_piste(events, [])
    assert rows and all(r["pourquoi"] and r["pour_tester"] and r["nb"] > 0 for r in rows)


def test_conseils_claude_code_pas_de_cache_control_ni_sdk():
    from optimize.slack import message
    from report.conseils import CLAUDE_CODE, conseil_proposition
    assert all("cache_control" not in t and "max_tokens" not in t for t in CLAUDE_CODE.values())
    prop = {"type": "cache_prompt", "model": "claude-sonnet-4-5", "verdict": "pass", "app_id": "a", "changement": "c",
            "finding_id": "f", "mesures": {}, "raisons": []}
    assert "cache_control" not in conseil_proposition(prop, "logs")
    assert conseil_proposition(prop, "passerelle") is None
    assert "cache_control" in message([prop], kind="passerelle")
    assert "cache_control" not in message([prop], kind="logs")
