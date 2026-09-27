"""Démo scénarisée (vidéo) : même rendu que le testeur, aucune donnée lue, aucun réseau."""
from scripts import demo_scenario


def test_demo_scenario_affiche_le_parcours_complet(capsys):
    assert demo_scenario.run(animate=False, interactive=False) == 0
    text = capsys.readouterr().out
    for bloc in ("Workflow trouvé", "[1/4]", "[2/4]", "[3/4]", "[4/4]", "Idea is good enough?",
                 "coût par exécution", "économie", "Review la PR", "Push la PR", "Quitter"):
        assert bloc in text


def test_demo_scenario_boutons_review_push_puis_quitter(capsys):
    keys = iter(["r", "right", "enter", "q"])  # R, puis flèche vers Push + Entrée, puis Q
    assert demo_scenario.run(animate=False, interactive=True, read_key=lambda: next(keys),
                             sleep=lambda s: None) == 0
    text = capsys.readouterr().out
    assert "gpt-4.1-nano" in text  # le diff de la PR
    assert "PR prête à relire" in text
