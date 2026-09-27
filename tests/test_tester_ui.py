"""Rendu du scénario testeur : cellules du tableau, seuil d'affichage à 95 %, barre de rejeu animée,
menu de boutons. Le module ``scripts.tester_ui`` expose ``tests``/``analysis``/etc, jamais importés par
leur nom ici (« tests » serait collecté par pytest comme un test) : on passe par ``tester_ui.xxx``."""
import io

import pytest

from scripts import tester_ui
from scripts.tester_ui import (Style, cell, choose, colors_on, excluded_summary, exclusion_reason,
                                gains_block, header, latency_cell, measure, menu_line, replayed_cell,
                                shown, width)


def m(valeur, statut="mesuré", unite="%"):
    return {"valeur": valeur, "statut": statut, "unite": unite}


def prop(app_id, verdict, precision, **extra_mesures):
    mesures = {"precision": m(precision)}
    mesures.update(extra_mesures)
    return {"app_id": app_id, "verdict": verdict, "mesures": mesures}


def test_style_colore_seulement_si_active():
    assert Style(False)("x", "green") == "x"
    assert Style(True)("x", "green") == "\x1b[32mx\x1b[0m"
    assert Style(True)("x") == "x"  # sans style demandé, rien à peindre


def test_couleurs_seulement_sur_terminal_et_sans_no_color():
    class Tty(io.StringIO):
        def isatty(self):
            return True
    assert colors_on(Tty(), env={}) and not colors_on(Tty(), env={"NO_COLOR": "1"})
    assert not colors_on(io.StringIO(), env={})


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
    p = {"mesures": {"latence_mediane": m(-100.0)}, "latence_ms": {"avant": 633.0, "apres": 0.0}}
    assert latency_cell(p) == "633 ms → 0 ms"


def test_latency_cell_reste_en_pourcentage_hors_moins_100():
    p = {"mesures": {"latence_mediane": m(-24.4)}, "latence_ms": {"avant": 100.0, "apres": 75.0}}
    assert latency_cell(p) == "-24.4 %"


def test_latency_cell_sans_ms_brutes_reste_en_pourcentage():
    assert latency_cell({"mesures": {"latence_mediane": m(-100.0)}}) == "-100 %"


def test_replayed_cell_avec_et_sans_appels_rejoues():
    assert replayed_cell(prop("a", "pass", 100.0, appels_rejoues=m(4, unite=""))) == "4 entrées rejouées"
    assert replayed_cell(prop("a", "pass", 100.0)) == "—"


def test_shown_ne_garde_que_les_propositions_prouvees_au_moins_95_pour_cent():
    a = prop("a", "reject", 82.5)     # sous le seuil : écarté
    b = prop("b", "pass", 100.0)
    c = prop("c", "reject", 100.0)    # au-dessus, mais refusée (échantillon insuffisant) : écarté aussi
    d = prop("d", "pass", None)       # precision non mesurée : jamais montrée
    e = prop("e", "pass", 99.0)
    assert shown([a, b, c, d, e]) == [b, e]  # prouvées seulement, la précision la plus haute d'abord


def test_exclusion_reason_distingue_precision_et_echantillon():
    assert exclusion_reason(prop("a", "reject", 82.5)) == "précision < 95 %"
    assert exclusion_reason(prop("c", "reject", 100.0)) == "échantillon insuffisant"
    assert exclusion_reason(prop("d", "pass", None)) == "échantillon insuffisant"


def test_excluded_summary_groupe_par_raison():
    items = [prop("mail-triage", "pass", 100.0), prop("reviews", "reject", 100.0),
             prop("brainstorm-bot", "reject", 82.5)]
    assert excluded_summary(items) == "2 propositions écartées (1 échantillon insuffisant, 1 précision < 95 %)"
    assert excluded_summary([prop("mail-triage", "pass", 100.0)]) is None


def test_gains_block_affiche_cout_total_et_par_execution(capsys):
    gains = {"cout_avant": 9.161, "cout_apres": 9.111, "cout_pct": -0.5, "executions": 99,
             "cout_par_execution_avant": 0.0925, "cout_par_execution_apres": 0.0920,
             "projection_1000_usd": 92.03}
    gains_block(gains, Style(False))
    out = capsys.readouterr().out
    assert "coût total" in out and "9.161 $" in out and "9.111 $" in out
    assert "coût par exécution" in out and "projection pour 1 000 exécutions" in out and "92.03 $" in out


def test_gains_block_sans_executions_le_dit(capsys):
    gains = {"cout_avant": 1.0, "cout_apres": 0.5, "cout_pct": -50.0, "executions": None,
             "cout_par_execution_avant": None, "cout_par_execution_apres": None, "projection_1000_usd": None}
    gains_block(gains, Style(False))
    assert "non mesuré" in capsys.readouterr().out


def test_menu_line_met_la_touche_active_en_evidence():
    line = menu_line([("R", "Review la PR"), ("P", "Push la PR"), ("Q", "Quitter")], Style(False), active="P")
    assert "R" in line and "Review la PR" in line and "Push la PR" in line and "Quitter" in line


def test_choose_navigue_aux_fleches_puis_valide_avec_entree():
    keys = iter(["right", "right", "enter"])
    out = io.StringIO()
    options = [("R", "Review la PR"), ("P", "Push la PR"), ("Q", "Quitter")]
    assert choose(options, Style(False), read_key=lambda: next(keys), out=out) == "Q"


def test_choose_accepte_un_raccourci_lettre_direct():
    keys = iter(["p"])
    options = [("R", "Review la PR"), ("P", "Push la PR"), ("Q", "Quitter")]
    assert choose(options, Style(False), read_key=lambda: next(keys), out=io.StringIO()) == "P"


def test_header_affiche_la_source_quand_elle_est_donnee(capsys):
    header("4553", Style(False), source="fixtures/dataset/v1/events.jsonl")
    out = capsys.readouterr().out
    assert "test sur fixtures/dataset/v1/events.jsonl" in out and "WF 4553" in out


def test_header_sans_source_reste_le_workflow_n8n(capsys):
    header("4553", Style(False))
    assert "test du workflow n8n 4553" in capsys.readouterr().out


def test_width_ignore_les_codes_ansi():
    assert width("\x1b[32mx\x1b[0m") == 1


def test_tests_anime_suit_le_vrai_nombre_d_entrees_puis_le_resultat_final():
    sleeps = []
    out = io.StringIO()
    items = [prop("mail-triage", "pass", 100.0, appels_rejoues=m(364, unite=""))]
    tester_ui.tests(items, Style(False), animate=True, sleep=lambda s: sleeps.append(s), out=out,
                    min_seconds=1.2, frames=12)
    text = out.getvalue()
    assert "182/364 entrées rejouées" in text  # mi-parcours réel (364 * 6/12), pas décoratif
    assert len(sleeps) == 12 and all(x == pytest.approx(0.1) for x in sleeps)  # durée minimale honorée
    assert text.rstrip().endswith("réponses identiques · 364 entrées rejouées")
    assert "100 %" in text


def test_tests_sans_animation_affiche_directement_la_ligne_finale():
    out = io.StringIO()
    items = [prop("mail-triage", "pass", 100.0, appels_rejoues=m(364, unite=""))]
    tester_ui.tests(items, Style(False), animate=False, out=out,
                     sleep=lambda s: pytest.fail("ne doit jamais dormir sans animation"))
    text = out.getvalue()
    assert text.count("\n") == 3  # ligne vide + ligne d'étape + ligne finale
    assert "364/364" not in text and "réponses identiques · 364 entrées rejouées" in text


def test_tests_anime_ne_depasse_jamais_la_largeur_du_terminal():
    # terminal étroit (vu chez un testeur) : une image plus large que l'écran passe à la ligne et le
    # \r ne revient qu'au début de la dernière ligne, les images s'empilent au lieu de se remplacer
    out = io.StringIO()
    items = [prop("n8n-4553", "pass", 100.0, appels_rejoues=m(77, unite=""))]
    tester_ui.tests(items, Style(False), animate=True, sleep=lambda s: None, out=out, frames=4, columns=50)
    frames = [f for f in out.getvalue().split("\r\x1b[2K") if "/77" in f]
    assert frames and all(width(f) < 50 for f in frames)  # « n/77 » tient, pas « entrées rejouées »


def test_analyse_accorde_le_singulier(capsys):
    tester_ui.analysis({"nom": "wf5.db", "noeuds": None, "appels": 279, "executions": 1,
                        "etapes": ["a"], "modeles": ["gpt-4.1-mini"]}, Style(False))
    text = capsys.readouterr().out
    assert "1 exécution" in text and "1 exécutions" not in text
    assert "1 étape IA" in text and "1 modèle (gpt-4.1-mini)" in text


def test_gains_globaux_non_chiffrables_expliques_au_lieu_de_tirets(capsys):
    gains_block({"cout_avant": None, "cout_apres": None, "cout_pct": None, "executions": 1,
                 "cout_par_execution_avant": None, "cout_par_execution_apres": None,
                 "projection_1000_usd": None, "modifications_comptees": 1}, Style(False))
    text = capsys.readouterr().out
    assert "— → —" not in text and "non chiffrable" in text


def _rej(app_id, precision, raison, verdict="reject", **mes):
    return {**prop(app_id, verdict, precision, **mes), "changement": f"Changer {app_id}.", "raisons": [raison]}


def test_exclusion_reason_dit_la_vraie_raison():
    assert exclusion_reason(_rej("a", 100.0, "le jeu de test ne contient qu'une seule réponse (false) : …")) \
        == "règle qui répond toujours pareil"
    assert exclusion_reason(_rej("b", 90.0, "la réponse « true » n'est jamais retrouvée par les règles (3 cas)")) \
        == "règle qui répond toujours pareil"
    assert exclusion_reason(_rej("c", None, "aucune clé pour le banc : rien de mesuré", "non_teste")) \
        == "non testé sans clé API"
    assert exclusion_reason(_rej("d", 100.0, "12 entrée(s) remplacée(s) sur 20 rejouée(s), il en faut au moins 30")) \
        == "échantillon insuffisant"


def test_sans_modification_prouvee_les_pistes_testees_restent_visibles(capsys):
    rejetee = _rej("n8n-4553", 100.0, "le jeu de test ne contient qu'une seule réponse (false) : …",
                   appels_rejoues=m(77, unite=""))
    tester_ui.modifications([], Style(False), others=[rejetee])
    tester_ui.tests([], Style(False), animate=False, others=[rejetee])
    text = capsys.readouterr().out
    assert "Changer n8n-4553." in text and "écartée" in text
    assert "règle qui répond toujours pareil" in text and "77 entrées rejouées" in text
