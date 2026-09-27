"""Démo scénarisée pour la vidéo : le parcours de ``make tester`` rejoué à partir d'un fichier de
scénario (``demo/scenario-<wf>.json``), avec le même rendu (barres animées, tableau, boutons).

Aucune donnée lue, aucun appel réseau, aucun push : les chiffres sont ceux du fichier de scénario,
illustratifs. Pour une vraie analyse, c'est ``make tester``.

    make demo-video              (scénario 4553 par défaut)
    python -m scripts.demo_scenario demo/scenario-4553.json [--no-anim]
"""
import argparse
import json
import sys
import time
from pathlib import Path

from scripts import tester_ui as ui

DEFAULT_SCENARIO = Path(__file__).resolve().parent.parent / "demo" / "scenario-4553.json"
LEGEND = "Précision = réponses identiques à l'ancien workflow sur l'historique rejoué · — non applicable"
PAUSE_S = 0.6  # respiration entre deux étapes, pour la caméra


def _m(value, unit="%"):
    return {"valeur": value, "statut": "mesuré", "unite": unit} if value is not None else None


def proposal(mod):
    """Une modification du scénario au format des propositions du testeur (mêmes cellules)."""
    latence = mod.get("latence")
    if latence is None and mod.get("latence_ms"):
        avant, apres = mod["latence_ms"]
        latence = round((apres - avant) / avant * 100, 1)
    mesures = {"precision": _m(mod["precision"]), "appels_rejoues": _m(mod["rejouees"], ""),
               "cout": _m(mod["cout"]), "latence_mediane": _m(latence),
               "latence_p95": _m(mod.get("p95")), "jetons_envoyes": _m(mod.get("jetons") or None)}
    return {"app_id": mod["app_id"], "changement": mod["changement"], "verdict": "pass", "raisons": [],
            "mesures": {k: v for k, v in mesures.items() if v}}


def gains(scenario):
    avant, apres = scenario["gains"]["cout_par_execution"]
    n = scenario["gains"]["executions"]
    return {"cout_avant": avant * n, "cout_apres": apres * n,
            "cout_pct": round((apres - avant) / avant * 100, 1), "executions": n,
            "cout_par_execution_avant": avant, "cout_par_execution_apres": apres,
            "projection_1000_usd": apres * 1000, "modifications_comptees": len(scenario["modifications"])}


def review(scenario, root, s):
    diff = root / scenario["diff"]
    print(f"\n    {s('deadweight : optimisations prouvées du workflow ' + scenario['wf'], 'bold')}\n")
    ui.diff_lines(diff.read_text(encoding="utf-8"), s)


def push(scenario, s, sleep=time.sleep):
    branch = f"deadweight/optim-{scenario['wf']}"
    for line in (f"branche {branch} créée", "3 modifications appliquées au workflow",
                 f"PR prête à relire sur {branch}"):
        sleep(0.4)
        print(f"    {s('✓', 'green')} {line}")


def run(path=DEFAULT_SCENARIO, animate=True, interactive=None, read_key=ui.read_key, sleep=time.sleep):
    path = Path(path)
    scenario = json.loads(path.read_text(encoding="utf-8"))
    root = path.resolve().parent.parent
    s = ui.Style(ui.colors_on())
    interactive = sys.stdin.isatty() and sys.stdout.isatty() if interactive is None else interactive
    pause = (lambda: sleep(PAUSE_S)) if animate else (lambda: None)
    info = scenario["workflow"]
    ui.header(scenario["wf"], s)
    print(f"\n  Workflow trouvé : {info['nom']} ({info['appels']} appels IA)")
    pause()
    ui.analysis(info, s)
    pause()
    items = [proposal(m) for m in scenario["modifications"]]
    ui.modifications(items, s)
    pause()
    ui.tests(items, s, animate=animate, sleep=sleep)
    pause()
    ui.LEGEND = LEGEND
    g = gains(scenario)
    ui.summary(items, s, g)
    saved = (g["cout_par_execution_avant"] - g["cout_par_execution_apres"]) * 1000
    line = f"économie : {saved:.2f} $ pour 1 000 exécutions ({g['cout_pct']:+.1f} %)"
    print(f"      {s(line, 'green', 'bold')}")
    keys = [("R", "Review la PR"), ("P", "Push la PR"), ("Q", "Quitter")]
    if not interactive:
        ui.menu(keys, s)
        return 0
    while True:
        choice = ui.choose(keys, s, read_key=read_key)
        if choice == "R":
            review(scenario, root, s)
        elif choice == "P":
            push(scenario, s, sleep)
        else:
            return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Démo scénarisée du testeur (vidéo)")
    ap.add_argument("scenario", nargs="?", default=str(DEFAULT_SCENARIO))
    ap.add_argument("--no-anim", action="store_true")
    args = ap.parse_args(argv)
    return run(args.scenario, animate=not args.no_anim)


if __name__ == "__main__":
    sys.exit(main())
