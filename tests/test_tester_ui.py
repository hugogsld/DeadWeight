"""Rendu du scénario testeur : cellules du tableau, seuil d'affichage, barre de rejeu animée, menu."""
import io

import pytest

from scripts.tester_ui import (ReplayBar, above_threshold, cell, choose, header, latency_cell, measure,
                                menu_line, precision_candidates, render_table, replay_detail, width)


def m(valeur, statut="mesuré", unite="%"):
    return {"valeur": valeur, "statut": statut, "unite": unite}


def prop(app_id, verdict, precision, **extra_mesures):
    mesures = {"precision": m(precision)}
    mesures.update(extra_mesures)
    return {"app_id": app_id, "verdict": verdict, "mesures": mesures}


def test_cell_mesure_estime_et_absent():
    assert cell(m(-24.4)) == "-24.4 %"
    assert cell(m(-35.7, statut="estimé")) == "~-35.7 %"
    assert cell(m(100.0), level=True) == "100 %"
    assert cell(m(None)) == "—"
    assert cell(None) == "—"


def test_measure_prend_la_premiere_cle_presente():
    p = {"mesures": {"jetons_sortie": m(-10.0)}}
    assert measure(p, ("jetons_envoyes", "jetons_sortie")) == m(-10.0)
    assert measure(p, ("absente",)) is None


def test_latency_cell_bascule_en_ms_a_moins_100_pour_cent():
    p = {"mesures": {"latence_mediane": m(-100.0)}, "latence_ms": {"avant": 812.0, "apres": 0.0}}
    assert latency_cell(p) == "812 ms → 0 ms"


def test_latency_cell_reste_en_pourcentage_hors_moins_100():
    p = {"mesures": {"latence_mediane": m(-24.4)}, "latence_ms": {"avant": 100.0, "apres": 75.0}}
    assert latency_cell(p) == "-24.4 %"


def test_latency_cell_sans_ms_brutes_reste_en_pourcentage():
    p = {"mesures": {"latence_mediane": m(-100.0)}}
    assert latency_cell(p) == "-100 %"


def test_precision_candidates_filtre_et_trie_prouvees_dabord_puis_precision():
    a = prop("a", "reject", 82.5)
    b = prop("b", "pass", 100.0)
    c = prop("c", "reject", 100.0)
    d = prop("d", "reject", None)  # precision non mesurée : jamais montrée
    assert precision_candidates([a, b, c, d]) == [b, c, a]


def test_above_threshold_ecarte_sous_le_seuil():
    items = [prop("mail-triage", "pass", 100.0), prop("reviews", "reject", 100.0), prop("brainstorm-bot", "reject", 82.5)]
    kept = above_threshold(items, 95.0)
    assert [p["app_id"] for p in kept] == ["mail-triage", "reviews"]


def test_replay_detail_avec_et_sans_appels_rejoues():
    assert replay_detail(prop("a", "pass", 100.0, appels_rejoues=m(364, unite=""))) == \
        "réponses identiques · 364 entrées rejouées"
    assert replay_detail(prop("a", "pass", 82.5)) == "réponses inchangées"


def test_render_table_contient_les_colonnes_et_reste_sans_ansi_hors_couleur():
    items = [prop("mail-triage", "pass", 100.0, cout=m(-71.7), latence_mediane=m(-100.0),
                   latence_p95=m(-2.9), jetons_envoyes=m(-73.3))]
    text = render_table(items, on=False)
    assert "Modification" in text and "Précision" in text and "Coût" in text and "mail-triage" in text
    assert "100 %" in text and "\033[" not in text


def test_replay_bar_anime_suit_le_vrai_nombre_d_entrees_puis_le_resultat_final():
    sleeps = []
    out = io.StringIO()
    bar = ReplayBar("1  mail-triage", 100.0, total=364, detail="réponses identiques · 364 entrées rejouées",
                    animate=True, on=False, sleep=lambda s: sleeps.append(s), out=out, min_seconds=1.2, frames=12)
    bar.render()
    text = out.getvalue()
    assert "182/364 entrées rejouées" in text  # mi-parcours réel (364 * 6/12), pas décoratif
    assert len(sleeps) == 12 and all(s == pytest.approx(0.1) for s in sleeps)  # durée minimale honorée
    assert text.rstrip().endswith("réponses identiques · 364 entrées rejouées")
    assert "100 %" in text


def test_replay_bar_hors_tty_affiche_directement_la_ligne_finale():
    out = io.StringIO()
    bar = ReplayBar("1  mail-triage", 100.0, total=364, detail="x", animate=False, on=False, out=out,
                     sleep=lambda s: pytest.fail("ne doit jamais dormir hors TTY"))
    bar.render()
    assert out.getvalue().count("\n") == 1
    assert "364/364" not in out.getvalue()


def test_menu_line_met_la_touche_active_en_evidence():
    line = menu_line([("R", "Review la PR"), ("P", "Push la PR"), ("Q", "Quitter")], active="P", on=False)
    assert "R" in line and "Review la PR" in line and "Push la PR" in line and "Quitter" in line


def test_choose_navigue_aux_fleches_puis_valide_avec_entree():
    keys = iter(["right", "right", "enter"])
    out = io.StringIO()
    options = [("R", "Review la PR"), ("P", "Push la PR"), ("Q", "Quitter")]
    assert choose(options, read_key=lambda: next(keys), out=out, on=False) == "Q"


def test_choose_accepte_un_raccourci_lettre_direct():
    keys = iter(["p"])
    options = [("R", "Review la PR"), ("P", "Push la PR"), ("Q", "Quitter")]
    assert choose(options, read_key=lambda: next(keys), out=io.StringIO(), on=False) == "P"


def test_header_affiche_la_source_quand_elle_est_donnee():
    text = header("4553", source="fixtures/dataset/v1/events.jsonl", on=False)
    assert "test sur fixtures/dataset/v1/events.jsonl" in text and "WF 4553" in text


def test_header_sans_source_reste_le_workflow_n8n():
    text = header("4553", on=False)
    assert "test du workflow n8n 4553" in text


def test_width_ignore_les_codes_ansi():
    assert width("\033[32mx\033[0m") == 1
