"""Scénario testeur : une commande, un parcours guidé, de la source n8n jusqu'à la PR et au message Slack.

    make tester WF=4553 [SOURCE=…] [REPO=chemin/du/depot] [OUI=1]
    python -m scripts.tester 4553 [--source …] [--repo …] [--oui]

Réutilise la chaîne d'``audit_complet`` (détection de la source, audit, ``optimize``, ``optimize.send``).
Aucun chiffre n'est calculé ici : ils viennent tous de ``propositions.json`` ; un chiffre absent est
affiché « non mesuré », une estimation porte « ~ » et rien n'est additionné.

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
from scripts.audit_complet import detect, notify
from optimize.send import send
from report.audit import _discover_detectors
from scripts.tester_ui import Progress, header, number, paint, status
from scripts.tester_seuils import load_workflow, show_pending, show_structure, structure

LIBRARY_CSV = Path(__file__).resolve().parent.parent / "docs" / "bibliotheque-n8n.csv"
LOCAL_DIRS = ("private/n8n",)
NO_HISTORY = ("pas d'exécutions : rien à rejouer, lancez le workflow quelques fois dans n8n puis relancez "
              "cette commande")
# ordre du message Slack (optimize.slack) : contexte envoyé, coût, latence médiane, précision
FIGURES = (("precision", "précision (rejeu de ses propres entrées)"),
           ("latence_mediane", "latence médiane"),
           ("cout", "coût"),
           ("jetons_envoyes", "données envoyées au modèle (jetons)"))


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
    parts += [f"{number(info['noeuds'])} nœuds"] if info.get("noeuds") else []
    parts.append(f"{number(info['appels'])} appels IA")
    parts += [f"{number(info['executions'])} exécutions"] if info.get("executions") else []
    parts += [f"{number(info['etapes'])} étape{'s' if info['etapes'] > 1 else ''}"] if info.get("etapes") else []
    return "Workflow trouvé : " + " · ".join(parts)


def figure(m, level=False):
    """Une mesure de propose : mesurée telle quelle, estimée avec « ~ », absente = « non mesuré ».
    ``level`` : un niveau (précision), pas une variation, donc jamais de signe."""
    if not m or m.get("valeur") is None:
        return "non mesuré"
    unit = m.get("unite") or ""
    sign = "+" if unit == "%" and m["valeur"] > 0 and not level else ""
    value = f"{sign}{m['valeur']:g}{' ' + unit if unit and unit != '%' else ' %' if unit else ''}"
    value = value if m["statut"] == "mesuré" else f"~{value}"
    gain = level or m["valeur"] < 0  # une baisse de latence, de coût ou de jetons est un gain
    return f"{paint(value.rjust(9), 'vert') if gain else value.rjust(9)}  {status(m['statut'])}"


def _quiet(fn, argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = fn(argv)
    return code, buf.getvalue()


def _optimize(events, optim, repo=None, open_prs=False):
    argv = [str(events), "--out", str(optim)]
    argv += ["--repo", str(repo)] + (["--open-prs"] if open_prs else []) if repo else []
    return _quiet(optimize_main, argv)[0]


def report(proposals):
    """Seules les propositions prouvées ; les autres tiennent en une ligne grise (page développeur)."""
    ok = [p for p in proposals if p["verdict"] == "pass"]
    s = "s" if len(ok) > 1 else ""
    if ok:
        print(f"\nWorkflow analysé : {paint(f'{len(ok)} modification{s} prouvée{s}', 'vert', 'gras')}")
    else:
        print("\nWorkflow analysé : aucune modification prouvée sur cet historique.")
    width = max(len(label) for _, label in FIGURES)
    for i, p in enumerate(ok, 1):
        print(f"\n  {paint(f'{i}.', 'gras')} {paint(p['app_id'], 'gras')} — {p['changement']}")
        for key, label in FIGURES:
            print(f"     {label.ljust(width)}  {figure(p['mesures'].get(key), key == 'precision')}")
    hidden = len(proposals) - len(ok)
    if hidden:
        print(paint(f"\n  {hidden} autre{'s' if hidden > 1 else ''} piste{'s' if hidden > 1 else ''} testée"
                    f"{'s' if hidden > 1 else ''} sans preuve suffisante : détail dans la page développeur", "gris"))
    if ok:
        print(paint("  mesuré = rejeu des mêmes entrées sur votre historique ; ~estimé = calcul avec hypothèse, "
                    "jamais additionné", "gris"))


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
        webhook=None, sender=send, env=os.environ, get=None):
    out = Path(out)
    print(header())
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
    print(found_line(info))
    if not ask("Commencer l'analyse ?", yes, interactive, read):
        return 0
    bar = Progress(["lecture de l'historique", f"{len(_discover_detectors())} vérifications",
                    "rejeu des propositions", "préparation de la PR"])
    bar.step(1)
    history = json_lines(events)
    bar.step(2)
    if _quiet(audit_main, [str(events), "-o", str(out / "audit.html")])[0]:
        print("erreur : l'audit a échoué", file=sys.stderr)
        return 1
    bar.step(3)
    optim = out / "optim"
    if _optimize(events, optim, repo):
        print("erreur : l'optimisation a échoué", file=sys.stderr)
        return 1
    bar.step(4)
    proposals = json.loads((optim / "propositions.json").read_text(encoding="utf-8"))
    bar.done()
    report(proposals)
    show_pending(history, info["executions"])
    proved = any(p["verdict"] == "pass" for p in proposals)
    print(paint(f"\nPage développeur : {optim / 'propositions.html'}  ·  rapport : {out / 'audit.html'}", "gris"))
    for d in sorted(optim.glob("*.diff")):
        print(paint(f"Micro-PR préparée : {d}", "gris"))
    if repo and proved and ask("Ouvrir la PR GitHub ?", yes, interactive, read):
        if _optimize(events, optim, repo, open_prs=True):
            print("erreur : ouverture de la PR impossible", file=sys.stderr)
            return 1
        for pr in json.loads((optim / "prs.json").read_text(encoding="utf-8")):
            print(f"PR ouverte : {pr['url']}")
    elif not repo:
        print(paint("PR : REPO non fourni, aucune PR ouverte (make tester … REPO=chemin/du/depot).", "gris"))
    if webhook and proved:
        if ask("Envoyer le message sur Slack ?", yes, interactive, read):
            return 1 if notify(optim, webhook=webhook, sender=sender) == "erreur" else 0
        return 0
    print("\nMessage Slack " + ("(SLACK_WEBHOOK_URL absent, non envoyé)" if not webhook
                                else "(aucun gain prouvé, non envoyé)") + " :\n")
    print((optim / "slack.md").read_text(encoding="utf-8"))
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
