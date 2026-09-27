"""Scénario testeur : une commande, un parcours guidé, de la source n8n jusqu'à la PR et au message Slack.

    make tester WF=4553 [SOURCE=…] [REPO=chemin/du/depot] [OUI=1] [MIN_APPELS=…]
    python -m scripts.tester 4553 [--source …] [--repo …] [--oui]

Réutilise la chaîne d'``audit_complet`` (détection de la source, audit, ``optimize``, ``optimize.send``).
Aucun chiffre n'est calculé ici : ils viennent tous de ``propositions.json`` ; un chiffre absent est
affiché « — », une estimation porte « ~ » et rien n'est additionné. Sous 95 % de précision (même seuil
que le rejeu, ``proof.replay.THRESHOLD``), une proposition n'apparaît nulle part : ni dans les étapes,
ni dans le tableau, ni dans la PR.

Source par défaut pour ``WF=<id>`` : ``n8n:<id>`` si ``N8N_URL`` est défini, sinon un dossier déjà
téléchargé par ``importers.n8n fetch`` (``private/n8n/<id>``). Sans historique d'exécution, le parcours
s'arrête et le dit : rien n'est simulé.

``MIN_APPELS`` (``DW_MIN_CALLS``) abaisse le seuil minimum d'appels IA par étape (30 par défaut, cf.
``rules.oversized_model.MIN_CALLS``) pour une démo sur un workflow qui n'a que quelques exécutions ;
un avertissement le rappelle en tête de parcours, les chiffres restent indicatifs.
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
from scripts import tester_ui as ui
from scripts.audit_complet import detect, notify
from scripts.tester_gains import global_gains
from scripts.tester_seuils import load_workflow, show_pending, show_structure, structure

LIBRARY_CSV = Path(__file__).resolve().parent.parent / "docs" / "bibliotheque-n8n.csv"
LOCAL_DIRS = ("private/n8n",)
NO_HISTORY = ("pas d'exécutions : rien à rejouer, lancez le workflow quelques fois dans n8n puis relancez "
              "cette commande")
# référence de l'avertissement « échantillon réduit » : rules.oversized_model.MIN_CALLS, non lu ici pour
# ne pas dépendre de l'ordre d'import (cf. DW_MIN_CALLS, tests/test_min_calls_env.py).
MIN_CALLS_DEFAULT = 30


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


def min_calls_env(env=os.environ):
    """DW_MIN_CALLS : seuil unique lu par les règles de fréquence (cf. tests/test_min_calls_env.py).
    Valeur invalide ou absente : le défaut (30), rien n'abaissé."""
    try:
        return int(env.get("DW_MIN_CALLS", MIN_CALLS_DEFAULT))
    except ValueError:
        return MIN_CALLS_DEFAULT


def json_lines(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def describe(wf, events_path, source):
    """Nom, nœuds, appels IA, exécutions, étapes IA et modèles : lus dans la source, jamais supposés."""
    events = json_lines(events_path)
    folder = Path(events_path).parent
    wf_json = folder / "workflow.json"
    name, nodes = None, None
    if wf_json.is_file():
        wf_data = json.loads(wf_json.read_text(encoding="utf-8"))
        name, nodes = wf_data.get("name"), len(wf_data.get("nodes") or [])
    elif (entry := catalog(wf)) and source.startswith("n8n:"):
        name, nodes = entry["nom"], entry["noeuds"]
    apps = sorted({e.get("app_id") for e in events if e.get("app_id")})
    name = name or Path(source).name
    traces = {(e.get("trace") or {}).get("id") for e in events} - {None}
    executions = len(traces) if traces else None
    models = sorted({e.get("model") for e in events if e.get("model")})
    return {"nom": name, "noeuds": nodes, "appels": len(events), "executions": executions,
            "etapes": apps, "modeles": models}


def _quiet(fn, argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = fn(argv)
    return code, buf.getvalue()


def _optimize(events, optim, repo=None, open_prs=False):
    argv = [str(events), "--out", str(optim)]
    argv += ["--repo", str(repo)] + (["--open-prs"] if open_prs else []) if repo else []
    return _quiet(optimize_main, argv)[0]


def review(optim, repo, s):
    """Sans REPO : la page développeur (diff des propositions), rien à relire sur disque puisque rien
    n'a été préparé pour un dépôt cible. Avec REPO : le vrai diff de chaque micro-PR prouvée."""
    if not repo:
        print(f"    Page développeur (diff des propositions) : "
              f"{s(str(Path(optim) / 'propositions.html'), 'bold')}")
        return
    diffs = sorted(Path(optim).glob("*.diff"))
    if not diffs:
        print(f"    {s('Aucune PR préparée.', 'dim')}")
    for d in diffs:
        pr = d.with_suffix(".pr.md")
        title = pr.read_text(encoding="utf-8").splitlines()[0].lstrip("# ") if pr.is_file() else d.stem
        print(f"\n    {s(title, 'bold')}")
        print(f"    {s(str(d), 'dim')}\n")
        ui.diff_lines(d.read_text(encoding="utf-8"), s)


def push(events, optim, repo, items, s, wf=None, source=None):
    if not repo:
        cmd = f"make tester WF={wf}" + (f" SOURCE={source}" if source else "") + " REPO=chemin/du/depot"
        print(f"    PR prête mais REPO non fourni : {s(cmd, 'bold')} pour la pousser.")
        return True
    if _optimize(events, optim, repo, open_prs=True):
        print("erreur : ouverture de la PR impossible", file=sys.stderr)
        return False
    for pr in json.loads((Path(optim) / "prs.json").read_text(encoding="utf-8")):
        print(f"    {s('✓', 'green')} PR ouverte : {pr['url']}")
    for p in items:
        if p["verdict"] != "pass":
            print(f"    {s(p['app_id'], 'dim')} : PR non ouverte, preuve incomplète ({'; '.join(p['raisons'])})")
    return True


def buttons(proved, webhook):
    """Review et Push apparaissent dès qu'un gain est prouvé, avec ou sans REPO (chacun s'adapte :
    ``review``/``push`` ci-dessus)."""
    keys = [("R", "Review la PR"), ("P", "Push la PR")] if proved else []
    keys += [("S", "Envoyer sur Slack")] if webhook and proved else []
    return keys + [("Q", "Quitter")]


def actions(ctx, keys, yes, interactive, read_key):
    """Boutons du bas. ``--oui`` : Push puis Slack sans rien demander (``push`` dit lui-même si ``REPO``
    manque). Sans terminal : aucun bouton actionné. Dans les deux cas, un bouton absent du menu (pas de
    micro-PR prouvée, pas de webhook) n'est jamais actionné."""
    s, allowed = ctx["s"], {k for k, _ in keys}
    if yes:
        for choice in (k for k in ("P", "S") if k in allowed):
            code = handle(choice, ctx)
            if code:
                return code
        return 0
    if not interactive:
        ui.menu(keys, s)
        print(f"    {s('(terminal non interactif : aucun bouton actionné)', 'dim')}")
        return 0
    while True:
        choice = ui.choose(keys, s, read_key=read_key, out=sys.stdout)
        if choice == "Q" or choice not in allowed:
            return 0
        code = handle(choice, ctx)
        if code:
            return code


def handle(choice, ctx):
    s, optim = ctx["s"], ctx["optim"]
    if choice == "R":
        review(optim, ctx["repo"], s)
    elif choice == "P":
        if ctx["pushed"]:
            print(f"    {s('PR déjà ouverte.', 'dim')}")
        elif not push(ctx["events"], optim, ctx["repo"], ctx["items"], s, ctx["wf"], ctx["source"]):
            return 1
        ctx["pushed"] = bool(ctx["repo"])
    elif choice == "S":
        state = notify(optim, webhook=ctx["webhook"], sender=ctx["sender"])
        if state == "erreur":
            return 1
        print(f"    {s('✓', 'green')} message Slack envoyé")
    return 0


def print_slack_preview(optim, webhook, proved):
    """Slack jamais proposé (pas de webhook, ou aucun gain prouvé) : le message reste visible, préparé."""
    print("\nMessage Slack " + ("(SLACK_WEBHOOK_URL absent, non envoyé)" if not webhook
                                else "(aucun gain prouvé, non envoyé)") + " :\n")
    print((optim / "slack.md").read_text(encoding="utf-8"))


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
        webhook=None, sender=send, env=os.environ, get=None, animate=None, color=None, read_key=ui.read_key):
    out = Path(out)
    interactive = sys.stdin.isatty() if interactive is None else interactive
    s = ui.Style(ui.colors_on(env=env) if color is None else color)
    animate = s.enabled if animate is None else animate
    given_source = source
    source = source or default_source(wf, env)
    if source is None:
        print(f"Aucune source d'exécutions pour {wf} (ni N8N_URL, ni dossier private/n8n/{wf}).")
        return structure_only(wf, get=get)
    events, log = _quiet(lambda _: detect(source, out), None)
    if events is None:
        print(log, end="")
        return 1
    info = describe(wf, events, source)
    if not info["appels"]:
        return structure_only(wf, Path(events).parent, get)
    ui.header(wf, s, given_source)
    print(f"\n  Workflow trouvé : {s(info['nom'], 'bold')} ({info['appels']} appels IA)")
    min_calls = min_calls_env(env)
    if min_calls < MIN_CALLS_DEFAULT:
        print(f"  {s(f'échantillon réduit : seuil abaissé à {min_calls} appels par étape, chiffres indicatifs', 'yellow')}")
    if not ask("  Lancer l'analyse ?", yes, interactive, read):
        return 0
    if _quiet(audit_main, [str(events), "-o", str(out / "audit.html")])[0]:
        print("erreur : l'audit a échoué", file=sys.stderr)
        return 1
    ui.analysis(info, s)
    optim = out / "optim"
    if _optimize(events, optim, repo):
        print("erreur : l'optimisation a échoué", file=sys.stderr)
        return 1
    proposals = json.loads((optim / "propositions.json").read_text(encoding="utf-8"))
    items = ui.shown(proposals)
    excluded_line = ui.excluded_summary(proposals)
    ui.modifications(items, s)
    ui.tests(items, s, animate=animate)
    history = json_lines(events)
    gains = global_gains(history, items, info["executions"]) if items else None
    ui.summary(items, s, gains, excluded_line)
    show_pending(history, info["executions"])
    proved = bool(items)  # ui.shown ne garde que les propositions prouvées (verdict pass, précision ≥ 95 %)
    print(f"\n    {s('Détail : ' + str(optim / 'propositions.html') + '  ·  audit : ' + str(out / 'audit.html'), 'dim')}")
    keys = buttons(proved, webhook)
    ctx = {"s": s, "optim": optim, "events": events, "repo": repo, "items": items, "webhook": webhook,
           "sender": sender, "pushed": False, "wf": wf, "source": given_source}
    code = actions(ctx, keys, yes, interactive, read_key)
    if code:
        return code
    if not any(k == "S" for k, _ in keys):  # jamais proposé (pas de webhook, ou aucun gain prouvé) : l'aperçu
        print_slack_preview(optim, webhook, proved)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Scénario testeur guidé : analyse, gains, PR, Slack")
    ap.add_argument("wf", help="id du workflow n8n (ex. 4553)")
    ap.add_argument("--source", help="remplace la source par défaut (n8n:<id>, dossier n8n, events.jsonl…)")
    ap.add_argument("--repo", help="dépôt où ouvrir la micro-PR prouvée (gh)")
    ap.add_argument("--out", default="out/tester")
    ap.add_argument("-y", "--oui", action="store_true", help="répond oui à tout (tournage)")
    args = ap.parse_args(argv)
    return run(args.wf, args.source, args.out, args.repo, args.oui, webhook=os.environ.get("SLACK_WEBHOOK_URL"))


if __name__ == "__main__":
    sys.exit(main())
