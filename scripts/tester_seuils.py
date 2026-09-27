"""Scénario testeur : ce qui ne peut pas encore conclure faute d'appels, et l'analyse de structure seule.

Les seuils des règles comptent des **appels IA par étape** (même app_id et même modèle), pas des
exécutions : un workflow en essaim en fait plusieurs par exécution. Les seuils sont importés des règles,
jamais recopiés. Sans aucune exécution, seule la structure du workflow est lue ; tout chiffre qui en sort
est une estimation marquée « ~ » avec son hypothèse.
"""
import json
import math
from collections import Counter
from pathlib import Path

from importers.n8n import library
from importers.n8n.convert import model_of
from importers.n8n.nodes import is_llm_node
from proof import replay
from rules import excess_reasoning, harness_overhead, low_entropy, oversized_model, paid_errors, verbose_output

# (vérification, seuil en appels par étape) : les constantes des règles elles-mêmes
CHECKS = (("modèle trop gros", oversized_model.MIN_CALLS),
          ("sortie quasi constante (remplaçable par des règles)", low_entropy.MIN_CALLS),
          ("réponses trop longues", verbose_output.MIN_CALLS),
          ("raisonnement excessif", excess_reasoning.MIN_CALLS),
          ("instructions fixes dominantes", harness_overhead.MIN_CALLS),
          ("erreurs payées", paid_errors.MIN_CALLS),
          ("preuve par rejeu", replay.MIN_REPLAY))
LIBRARY_DIR = "private/n8n-library"


def steps(events):
    """Appels par étape (app_id, modèle), la plus fournie d'abord."""
    return Counter((e.get("app_id"), e.get("model")) for e in events).most_common()


def pending(events, executions=None):
    """Vérifications qui attendent plus d'appels : seuil, appels présents, exécutions nécessaires (~)."""
    counts = steps(events)
    best = counts[0][1] if counts else 0
    per_run = best / executions if executions else None
    out = []
    for name, threshold in CHECKS:
        if best >= threshold:
            continue
        runs = math.ceil(threshold / per_run) if per_run else None
        out.append({"verification": name, "seuil": threshold, "presents": best, "executions_estimees": runs})
    return out


def show_pending(events, executions=None):
    rows = pending(events, executions)
    if not rows:
        return
    print("\nVérifications en attente de données (pas un échec : il faut plus d'appels par étape) :")
    for r in rows:
        more = (f" ; ~{r['executions_estimees']} exécutions au total (hypothèse : même nombre d'appels "
                "par exécution)" if r["executions_estimees"] else "")
        print(f"  • {r['verification']} : {r['seuil']} appels nécessaires, {r['presents']} présents{more}")


def structure(wf):
    """Lecture seule du workflow : nœuds, nœuds modèle, modèles, agents qui appellent un modèle."""
    nodes = wf.get("nodes") or []
    llm = [n for n in nodes if is_llm_node(n)]
    names = {n.get("name") for n in llm}
    callers = set()
    for source, outputs in (wf.get("connections") or {}).items():
        if source in names:
            for branch in outputs.get("ai_languageModel") or []:
                callers.update(t.get("node") for t in branch or [] if isinstance(t, dict))
    models = sorted({m for n in llm if (m := model_of(n, {}))})
    return {"nom": wf.get("name"), "noeuds": len(nodes), "noeuds_llm": len(llm), "modeles": models,
            "appelants": len(callers)}


def load_workflow(wf, folder=None, library_dir=LIBRARY_DIR, get=library._get):
    """workflow.json déjà téléchargé, sinon bibliothèque publique n8n.io (gratuite, sans clé)."""
    for path in ([Path(folder) / "workflow.json"] if folder else []) + [Path(library_dir) / f"{wf}.json"]:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    if not str(wf).isdigit():
        return None
    full = get(f"{library.API}/workflows/{wf}")
    return library.slim(full) if full and (full.get("workflow") or {}).get("workflow") else None


def show_structure(s):
    steps_per_run = s["appelants"] or s["noeuds_llm"]
    print(f"Analyse de structure seule : {s['nom']} ({s['noeuds']} nœuds, {s['noeuds_llm']} nœud(s) modèle"
          f"{', ' + ', '.join(s['modeles']) if s['modeles'] else ''}, {s['appelants']} agent(s) branché(s)).")
    print(f"  ~{steps_per_run} appels IA par exécution (estimé : un appel par agent ou nœud modèle, "
          "sans boucle d'outils)")
    print("  précision, latence, coût, données envoyées au modèle : non mesuré (aucune exécution)")
    for name, threshold in CHECKS:
        print(f"  • {name} : {threshold} appels nécessaires par étape, 0 présents ; ~{threshold} exécutions "
              "(hypothèse : un appel par étape et par exécution)")
    print("\nPour obtenir des mesures : importez le workflow dans n8n, exécutez-le (plus il y a d'exécutions, "
          "plus de vérifications concluent), définissez N8N_URL et N8N_API_KEY, puis relancez make tester.")
