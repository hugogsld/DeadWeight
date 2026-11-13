"""Rapport lisible à tout volume : un problème = une carte, au plus trois actions, vue par workflow."""
from report.audit import render_html
from report.audit_vue import console, vue
from report.regroupe import nom_workflow, parents

ACTION_A = "`/compact` avant de continuer une longue session. Effet : moins de jetons relus."
ACTION_B = "`/mcp` pour désactiver les serveurs inutilisés. Effet : moins d'outils listés."


def _chiffres(cout, appels=100):
    return {"cout_mensuel_usd": cout, "latence_mediane_ms": 4000, "latence_p95_ms": 20000, "nb_appels": appels,
            "nb_erreurs": 0, "manquants": []}


def _constat(i, app, regle, titre, action, cout, evidence):
    return {"finding_id": f"f{i}", "app_id": f"claude-code:{app}", "model": "m", "titre": titre, "phrase": "p",
            "regle": regle, "evidence": evidence, "action": action, "prouve": False, "gravite": "trim",
            "chiffres": _chiffres(cout), "raisons_manquantes": [], "alternatives": None}


def _report(n=12):
    apps = [f"flux{i}" for i in range(n)] + ["flux0-worktree", "flux1/sous-agent"]
    constats = []
    for i in range(n):
        constats.append(_constat(i, f"flux{i}", "context_reread", "Chaque appel relit la conversation", ACTION_A,
                                 100 - i, {"median_context_tokens": 150000 + i, "est_saving_month_usd": 5}))
        constats.append(_constat(100 + i, f"flux{i}", "tool_bloat", "Des outils renvoyés inutilement", ACTION_B,
                                 10 - i * 0.5, {"unused_tool_share": 0.8}))
    apps_rows = [{"app_id": f"claude-code:{a}", "chiffres": _chiffres(120)} for a in apps]
    return {
        "verifications": ["Chaque appel relit la conversation", "Des outils renvoyés inutilement",
                          "Un agent qui tourne en rond"],
        "raisons_globales": [], "constats": constats, "rien_a_signaler": [], "souverainete": [], "billing": None,
        "pourquoi_rien": None, "gains_par_tache": [], "gains_equivalent_api": False, "applications": apps_rows,
        "diagnostic": {"systeme_visible": False, "outils_visibles": True, "part_contexte_pct": 79},
        "resume": {"nb_appels": 1000, "nb_applications": len(apps), "debut": "2026-11-01T00:00:00Z",
                   "fin": "2026-11-13T00:00:00Z", "global": _chiffres(2000, 1000)}}


def test_sous_agents_et_worktrees_rangés_sous_leur_parent():
    m = parents(["claude-code:flux", "claude-code:flux/sous-agent", "claude-code:flux-fusion", "claude-code:autre"])
    assert set(m.values()) == {"flux", "autre"}
    assert nom_workflow("codex:x/sous-agent") == "x"


def test_une_carte_par_probleme_et_le_que_faire_une_seule_fois():
    page = render_html(_report())
    assert page.count("Que faire :") == 2
    assert page.count("avant de continuer une longue session") == 2  # action du haut + « Que faire » de la carte
    assert page.count("<h3>Chaque appel relit la conversation</h3>") == 1
    assert page.count('<div class="card">') == 2


def test_tableau_top_5_et_reste_replie():
    page = render_html(_report(12))
    assert "7 autres workflows" in page
    assert "Par workflow" in page and "2 autres workflows" in page  # 12 workflows : 10 montrés, 2 repliés


def test_au_plus_trois_actions_classees_par_cout():
    r = _report()
    for i, (regle, titre) in enumerate([("no_cache", "Pas de cache"), ("unbounded_loop", "Boucle"),
                                        ("verbose_output", "Réponses longues")]):
        r["constats"].append(_constat(900 + i, "flux0", regle, titre, f"Action {regle}.", 1 + i, {}))
    acts = vue(r)["actions"]
    assert len(acts) == 3
    assert acts[0]["action"].startswith("`/compact`") and "Effet" not in acts[0]["action"]
    assert acts[0]["part"] > acts[1]["part"] > acts[2]["part"]
    assert render_html(r).count('<ol class="todo-top">') == 1
    assert "statistique" in render_html(r)


def test_metrique_propre_a_la_regle_et_verifications_sans_resultat():
    page = render_html(_report())
    assert "jetons relus / appel" in page and "outils inutilisés" in page
    assert "Vérifications sans résultat sur cette source" in page and "Un agent qui tourne en rond" in page
    assert "prompt système" in page


def test_console_une_ligne_par_action():
    lines = console(_report())
    assert lines[0].startswith("24 constats : 2 types de problème sur 12 workflows")
    assert len(lines) == 3


def test_slack_une_ligne_par_probleme_avec_les_workflows():
    from optimize.slack import message
    rows = [{"regle": f"r{i}", "titre": f"Problème {i}", "nb": 40, "pourquoi": "p", "pour_tester": "t",
             "workflows": ["a", "b", "c"], "nb_workflows": 40, "part": 0.3 - i * 0.05} for i in range(5)]
    text = message([], sans_piste=rows, kind="logs")
    assert text.count("Où : 40 workflows, 30 % du coût (a, b, c et 37 autres)") == 1
    assert text.count("Problème 0") == 1 and "Problème 3" in text and "2 autres problèmes" in text
    assert text.count("   - Problème") == 3  # trois détaillés, les autres tiennent en une ligne


def test_ce_quil_faut_faire_sans_projection_mensuelle_sous_une_journee():
    from report.audit_vue import actions_html
    act = {"action": "x", "workflows": ["w"], "nb_workflows": 1, "economie": 89513.0, "part": 1.0,
           "statut": "statistique"}
    assert "par mois" not in actions_html([act], projection=False)
    assert "par mois" in actions_html([act], projection=True)
