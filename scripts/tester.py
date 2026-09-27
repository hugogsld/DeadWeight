"""Scénario testeur : une commande, un parcours guidé, de la source n8n jusqu'à la PR et au message Slack.

    make tester WF=4553 [SOURCE=…] [REPO=chemin/du/depot] [OUI=1] [--no-anim]
    python -m scripts.tester 4553 [--source …] [--repo …] [--oui] [--no-anim]

Réutilise la chaîne d'``audit_complet`` (détection de la source, audit, ``optimize``, ``optimize.send``).
Aucun chiffre n'est calculé ici : ils viennent tous de ``propositions.json`` ; un chiffre absent est
affiché « — », une estimation porte « ~ » et rien n'est additionné. Sous 95 % de précision (même seuil
que le rejeu, ``proof.replay.THRESHOLD``), une proposition n'apparaît nulle part : ni dans les étapes,
ni dans le tableau, ni dans la PR.

Source par défaut pour ``WF=<id>`` : ``n8n:<id>`` si ``N8N_URL`` est défini, sinon un dossier déjà
téléchargé par ``importers.n8n fetch`` (``private/n8n/<id>``). Sans historique d'exécution, le parcours
s'arrête et le dit : rien n'est simulé.
"""
import argparse
import contextlib
import csv
import io
import json
import os
import sys
from pathlib import Path

from agent.audit import main as audit_main
from optimize.__main__ import main as optimize_main
from optimize.send import send
from proof.replay import THRESHOLD
from scripts import tester_ui as ui
from scripts.audit_complet import detect, notify
from scripts.tester_gains import global_gains
from scripts.tester_seuils import load_workflow, show_pending, show_structure, structure

LIBRARY_CSV = Path(__file__).resolve().parent.parent / "docs" / "bibliotheque-n8n.csv"
LOCAL_DIRS = ("private/n8n",)
NO_HISTORY = ("pas d'exécutions : rien à rejouer, lancez le workflow quelques fois dans n8n puis relancez "
              "cette commande")
# seuil d'affichage : même chiffre que le rejeu des règles (proof.replay.THRESHOLD), pas un deuxième.
PRECISION_FLOOR_PCT = THRESHOLD * 100
STEPS = 4


def ask(question, yes=False, interactive=None, read=input):
    """[O/n] : Entrée ou « o » = oui. ``--oui`` accepte tout ; sans terminal, rien n'est demandé (oui)."""
    interactive = sys.stdin.isatty() if interactive is None else interactive
    if yes or not interactive:
        print(f"{question} [O/n] O")
        return True
    try:
        answer = read(f"{question} [O/n] ").strip().lower()
    except EOFError:
        return False
    return answer in ("", "o", "oui", "y", "yes")


def catalog(wf, path=LIBRARY_CSV):
    """Ligne de docs/bibliotheque-n8n.csv pour cet id (nom, nœuds), ou None."""
    try:
        with open(path, encoding="utf-8") as f:
            for row in csv.reader(f):
                if row and row[0] == str(wf):
                    return {"nom": row[1], "noeuds": int(row[4]) if row[4].isdigit() else None}
    except OSError:
        pass
    return None


def default_source(wf, env=os.environ, dirs=LOCAL_DIRS):
    if env.get("N8N_URL"):
        return f"n8n:{wf}"
    for d in dirs:
        folder = Path(d) / str(wf)
        if (folder / "workflow.json").is_file() and (folder / "executions.jsonl").is_file():
            return str(folder)
    return None


def json_lines(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def describe(wf, events_path, source):
    """Nom, nœuds, appels IA, exécutions : lus dans la source, jamais supposés."""
    events = json_lines(events_path)
    folder = Path(events_path).parent
    wf_json = folder / "workflow.json"
    name, nodes = None, None
    if wf_json.is_file():
        wf_data = json.loads(wf_json.read_text(encoding="utf-8"))
        name, nodes = wf_data.get("name"), len(wf_data.get("nodes") or [])
    elif (entry := catalog(wf)) and source.startswith("n8n:"):
        name, nodes = entry["nom"], entry["noeuds"]
    traces = {(e.get("trace") or {}).get("id") for e in events} - {None}
    executions = len(traces) if traces else None
    etapes = len({e.get("app_id") for e in events if e.get("app_id")})
    return {"nom": name, "noeuds": nodes, "appels": len(events), "executions": executions, "etapes": etapes}


def found_line(info):
    """« Workflow trouvé : nom · 1 872 appels IA · 99 exécutions · 40 étapes » ; rien d'inconnu affiché."""
    parts = [info["nom"]] if info.get("nom") else []
    parts += [f"{ui.number(info['noeuds'])} nœuds"] if info.get("noeuds") else []
    parts.append(f"{ui.number(info['appels'])} appels IA")
    parts += [f"{ui.number(info['executions'])} exécutions"] if info.get("executions") else []
    parts += [f"{ui.number(info['etapes'])} étape{'s' if info['etapes'] > 1 else ''}"] if info.get("etapes") else []
    return "Workflow trouvé : " + " · ".join(parts)


def _quiet(fn, argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = fn(argv)
    return code, buf.getvalue()


def _optimize(events, optim, repo=None, open_prs=False):
    argv = [str(events), "--out", str(optim)]
    argv += ["--repo", str(repo)] + (["--open-prs"] if open_prs else []) if repo else []
    return _quiet(optimize_main, argv)[0]


def _money(v):
    return f"{v:.4g} $" if v is not None else "—"


def _pct(v):
    return f"{v:+.1f} %" if v is not None else "—"


def print_gains(events, shown, executions, on):
    """Gains sur l'ensemble du workflow (pas seulement les modifications retenues), sous le tableau."""
    gains = global_gains(events, shown, executions)
    print(f"\n    {ui.paint('Gains sur l’ensemble du workflow (historique rejoué) :', 'gras', on=on)}")
    print(f"      coût total : {_money(gains['cout_avant'])} → {_money(gains['cout_apres'])} "
          f"({_pct(gains['cout_pct'])})")
    if gains["executions"]:
        print(f"      coût par exécution : {_money(gains['cout_par_execution_avant'])} → "
              f"{_money(gains['cout_par_execution_apres'])}  ·  projection pour 1 000 exécutions : "
              f"{_money(gains['projection_1000_usd'])} (sur la base de {gains['executions']} exécutions observées)")
    else:
        print("      coût par exécution : — (nombre d'exécutions non mesuré)")


def print_modifications(shown, on):
    """Étape 2 : la liste des modifications retenues (précision ≥ seuil), ou rien à tester."""
    ui.step(2, STEPS, "Modifications proposées", on)
    if not shown:
        print("    Aucune modification testable sur cet historique.")
        return
    name_w = max(len(p["app_id"]) for p in shown)
    for i, p in enumerate(shown, 1):
        print(f"    {i}  {p['app_id'].ljust(name_w)}  {p['changement']}")


def print_replay_bars(shown, animate, on):
    """Étape 3 : une barre de précision par modification, animée sur le vrai nombre d'entrées rejouées."""
    ui.step(3, STEPS, "Tests : l'historique rejoué, nouveau workflow comparé à l'ancien", on)
    name_w = max((len(p["app_id"]) for p in shown), default=0)
    for i, p in enumerate(shown, 1):
        total = (ui.measure(p, ("appels_rejoues",)) or {}).get("valeur")
        label = f"{i}  {p['app_id'].ljust(name_w)}"
        bar = ui.ReplayBar(label, p["mesures"]["precision"]["valeur"], total, ui.replay_detail(p),
                           animate=animate, on=on)
        bar.render()


def print_results(shown, excluded, events, executions, on):
    """Étape 4 : le tableau des gains par modification, puis les gains globaux du workflow."""
    ui.step(4, STEPS, "Résumé des gains", on)
    if not shown:
        print("    Aucune modification retenue sur cet historique.")
        return
    print(ui.render_table(shown, on))
    print_gains(events, shown, executions, on)
    if excluded:
        s = "s" if excluded > 1 else ""
        print(ui.paint(f"    {excluded} proposition{s} écartée{s} (précision < {PRECISION_FLOOR_PCT:g} %)",
                       "gris", on=on))


def _review(optim, on):
    diffs = sorted(Path(optim).glob("*.diff"))
    if not diffs:
        print("    Aucune micro-PR préparée.")
        return
    for d in diffs:
        print(f"\n    {ui.paint(str(d), 'gras', on=on)}")
        print(d.read_text(encoding="utf-8"))


def _push(events, optim, repo, on):
    if _optimize(events, optim, repo, open_prs=True):
        print("erreur : ouverture de la PR impossible", file=sys.stderr)
        return 1
    for pr in json.loads((optim / "prs.json").read_text(encoding="utf-8")):
        print(f"    {ui.paint('PR ouverte : ' + pr['url'], 'vert', on=on)}")
    return 0


def handle_pr(events, optim, repo, proved, yes, interactive, on, read_key=ui.read_key):
    """Bouton Review / Push / Quitter. ``--oui`` : pousse directement. Hors TTY : aucune action."""
    if not repo:
        print(ui.paint("\n  PR : REPO non fourni, aucune PR ouverte (make tester … REPO=chemin/du/depot).",
                        "gris", on=on))
        return 0
    if not proved:
        return 0
    keys = [("R", "Review la PR"), ("P", "Push la PR"), ("Q", "Quitter")]
    if yes:
        return _push(events, optim, repo, on)
    if not interactive:
        print("\n    " + ui.menu_line(keys, on=on))
        print(f"    {ui.paint('(terminal non interactif : aucun bouton actionné)', 'gris', on=on)}")
        return 0
    while True:
        action = ui.choose(keys, read_key=read_key, out=sys.stdout, on=on)
        if action == "R":
            _review(optim, on)
        elif action == "P":
            return _push(events, optim, repo, on)
        else:
            return 0


def handle_slack(optim, webhook, proved, yes, interactive, read, sender):
    if webhook and proved:
        if ask("Envoyer le message sur Slack ?", yes, interactive, read):
            return 1 if notify(optim, webhook=webhook, sender=sender) == "erreur" else 0
        return 0
    print("\nMessage Slack " + ("(SLACK_WEBHOOK_URL absent, non envoyé)" if not webhook
                                else "(aucun gain prouvé, non envoyé)") + " :\n")
    print((optim / "slack.md").read_text(encoding="utf-8"))
    return 0


def structure_only(wf, folder=None, get=None):
    """Aucune exécution : structure du workflow seule, estimations « ~ », puis comment mesurer."""
    kwargs = {"get": get} if get else {}
    wf_data = load_workflow(wf, folder, **kwargs)
    if wf_data is None:
        print(f"Workflow {wf} : ni historique ni structure lisible. Importez-le dans n8n, exécutez-le, "
              "puis définissez N8N_URL et N8N_API_KEY.")
        return 1
    print(f"Workflow {wf} : {NO_HISTORY}.")
    show_structure(structure(wf_data))
    return 0


def run(wf, source=None, out="out/tester", repo=None, yes=False, interactive=None, read=input,
        webhook=None, sender=send, env=os.environ, get=None, animate=None, read_key=ui.read_key):
    out = Path(out)
    interactive = sys.stdin.isatty() if interactive is None else interactive
    given_source = source
    source = source or default_source(wf, env)
    if source is None:
        print(f"Aucune source d'exécutions pour {wf} (ni N8N_URL, ni dossier private/n8n/{wf}).")
        return structure_only(wf, get=get)
    on = ui.colors_on(env=env)
    animate = on if animate is None else animate
    print(ui.header(wf, given_source, on=on))
    events, log = _quiet(lambda _: detect(source, out), None)
    if events is None:
        print(log, end="")
        return 1
    info = describe(wf, events, source)
    if not info["appels"]:
        return structure_only(wf, Path(events).parent, get)
    ui.step(1, STEPS, "Analyse du workflow", on)
    print(f"  {found_line(info)}")
    if not ask("Commencer l'analyse ?", yes, interactive, read):
        return 0
    if _quiet(audit_main, [str(events), "-o", str(out / "audit.html")])[0]:
        print("erreur : l'audit a échoué", file=sys.stderr)
        return 1
    optim = out / "optim"
    if _optimize(events, optim, repo):
        print("erreur : l'optimisation a échoué", file=sys.stderr)
        return 1
    proposals = json.loads((optim / "propositions.json").read_text(encoding="utf-8"))
    candidates = ui.precision_candidates(proposals)
    shown = ui.above_threshold(candidates, PRECISION_FLOOR_PCT)
    excluded = len(candidates) - len(shown)

    print_modifications(shown, on)
    print_replay_bars(shown, animate, on)

    history = json_lines(events)
    print_results(shown, excluded, history, info["executions"], on)
    show_pending(history, info["executions"])
    print(ui.paint(f"\nPage développeur : {optim / 'propositions.html'}  ·  rapport : {out / 'audit.html'}",
                   "gris", on=on))
    proved = any(p["verdict"] == "pass" for p in shown)
    code = handle_pr(events, optim, repo, proved, yes, interactive, on, read_key)
    if code:
        return code
    return handle_slack(optim, webhook, proved, yes, interactive, read, sender)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Scénario testeur guidé : analyse, gains, PR, Slack")
    ap.add_argument("wf", help="id du workflow n8n (ex. 4553)")
    ap.add_argument("--source", help="remplace la source par défaut (n8n:<id>, dossier n8n, events.jsonl…)")
    ap.add_argument("--repo", help="dépôt où ouvrir la micro-PR prouvée (gh)")
    ap.add_argument("--out", default="out/tester")
    ap.add_argument("-y", "--oui", action="store_true", help="répond oui à tout (tournage)")
    ap.add_argument("--no-anim", action="store_true", help="barres de rejeu affichées directement, sans animation")
    args = ap.parse_args(argv)
    animate = False if args.no_anim else None
    return run(args.wf, args.source, args.out, args.repo, args.oui, webhook=os.environ.get("SLACK_WEBHOOK_URL"),
               animate=animate)


if __name__ == "__main__":
    sys.exit(main())
