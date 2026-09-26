"""Tableau d'avancement (v1 et v2) a partir des issues et PR GitHub.

    python scripts/roadmap_status.py            # lit GitHub via `gh`, reecrit ROADMAP.md
    python scripts/roadmap_status.py --check    # affiche seulement

Regle : une issue ou une PR dont le titre commence par l'identifiant (ex. "D2.3 — ...")
est rattachee au livrable. Lance par .github/workflows/roadmap.yml a chaque evenement.
"""
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROADMAP = Path(__file__).resolve().parent.parent / "ROADMAP.md"
BEGIN, END = "<!-- STATUT:DEBUT -->", "<!-- STATUT:FIN -->"
REPO = "hugogsld/DeadWeight"

# id, livrable, heures, dependances, hors plan de base
DELIVERABLES = [
    ("D0.1", "Schéma d'événement et fixtures", 3, [], False),
    ("D0.2", "Repo, CI, make dev, enregistrement", 3, [], False),
    ("D0.3", "Jeu de données réaliste", 4, ["D0.1"], False),
    ("D1.1", "Proxy passe-plat OpenAI, streaming", 5, ["D0.2"], False),
    ("D1.2", "Capture et persistance", 3, ["D0.1", "D1.1"], False),
    ("D1.3", "Anthropic et Gemini", 4, ["D1.1"], False),
    ("D1.4", "Regroupement par trace", 3, ["D1.2"], False),
    ("D2.1", "R1 entropie", 2, ["D0.3"], False),
    ("D2.2", "R2 modèle surdimensionné", 3, ["D0.3"], False),
    ("D2.3", "R3 contexte brut + R4 absence de cache", 3, ["D0.3"], False),
    ("D2.4", "R5 boucle + R6 agent inutile", 5, ["D0.3", "D1.4"], False),
    ("D2.5", "Chiffrage coût et latence", 3, ["D0.1"], False),
    ("D3.1", "Extraction des règles", 3, ["D2.1"], False),
    ("D3.2", "Rejeu et seuil 0,95", 4, ["D3.1"], False),
    ("D3.3", "Court-circuit", 4, ["D3.2"], True),
    ("D4.1", "Rapport d'audit", 3, ["D2.5"], False),
    ("D4.2", "Installation dix minutes", 4, ["D1.1", "D4.1"], False),
    ("D4.3", "Mode miroir", 3, ["D1.2"], True),
    ("D4.4", "Test par un tiers", 2, ["D4.2"], False),
]
# Roadmap v2 (ROADMAP_V2.md) : lots A, B, C, M (modeles), E (partenaires), Q (tests), V (video)
DELIVERABLES_V2 = [
    ("A1", "Agent auditeur", 3, [], False),
    ("A2", "Section « construit pendant le hackathon »", 0.5, [], False),
    ("A3", "Inscriptions X-IA et Luma", 0.25, [], False),
    ("B1", "Banc n8n branché sur la passerelle", 2, [], False),
    ("B2", "Convertisseur de logs", 1, [], False),
    ("B3", "Analyse des vrais workflows", 3, [], False),
    ("B4", "Trouver un 3e workflow", 1, [], False),
    ("B5", "Confidentialité des données clients", 0.5, [], False),
    ("C1", "Relais HTTP générique (outils)", 2, [], False),
    ("C2", "Constats outils", 1.5, ["C1"], False),
    ("M1", "Catalogue de modèles", 1.5, [], False),
    ("M2", "Recommandations concrètes", 2, ["M1"], False),
    ("E1", "Export Pipelex", 2, [], True),
    ("E2", "Résumé vocal Gradium", 1, [], True),
    ("E3", "Agent Dust", 1.5, [], True),
    ("Q1", "Test de bout en bout en CI", 1, ["D4.2"], False),
    ("Q2", "Tests dorés sur vrais workflows", 1, ["B3"], False),
    ("V1", "Script de la vidéo", 1, [], False),
    ("V2", "Tournage et montage", 2, ["V1"], False),
    ("V3", "Description et README final", 0.5, ["A2"], False),
    ("V4", "Dépôt X-IA", 0.25, ["V2", "V3"], False),
]
ID_RE = re.compile(r"^\s*\[?(D\d\.\d|[ABCMEQV]\d)\b")


def _id(title):
    m = ID_RE.match(title or "")
    return m.group(1) if m else None


def compute(issues, prs, plan=DELIVERABLES):
    """issues/prs : dicts GitHub (title, state, number, assignees, labels, merged).
    Les dependances peuvent viser l'autre plan (Q1 attend D4.2)."""
    rows, done = [], set()
    by_issue = {_id(i["title"]): i for i in sorted(issues, key=lambda i: i["number"]) if _id(i["title"])}
    by_pr = {}
    for p in sorted(prs, key=lambda p: p["number"]):
        if _id(p["title"]):
            by_pr[_id(p["title"])] = p
    for did in set(by_issue) | set(by_pr):
        issue, pr = by_issue.get(did), by_pr.get(did)
        if (pr and pr["merged"]) or (issue and issue["state"] == "closed"):
            done.add(did)
    for did, name, hours, deps, extra in plan:
        issue, pr = by_issue.get(did), by_pr.get(did)
        missing = [d for d in deps if d not in done]
        if did in done:
            status = "Fait"
        elif pr and pr["state"] == "open":
            status = "En relecture"
        elif issue:
            status = "En cours"
        elif missing:
            status = "Bloqué (attend " + ", ".join(missing) + ")"
        else:
            status = "Prenable"
        who = sorted({a for a in (issue or {}).get("assignees", [])} |
                     {l.replace("agent:", "") for l in (issue or {}).get("labels", []) if l.startswith("agent:")})
        links = []
        if issue:
            links.append(f"#{issue['number']}")
        if pr:
            links.append(f"PR #{pr['number']}")
        rows.append({"id": did, "name": name + (" *(hors plan)*" if extra else ""), "hours": hours,
                     "deps": ", ".join(deps) or "—", "status": status, "who": ", ".join(who) or "—",
                     "links": " · ".join(links) or "—", "extra": extra, "done": did in done})
    return rows


def _h(hours):
    return f"{hours:g}".replace(".", ",")


def render(rows, now, label="livrables du plan de base faits"):
    base = [r for r in rows if not r["extra"]]
    done_h = sum(r["hours"] for r in base if r["done"])
    total_h = sum(r["hours"] for r in base)
    lines = [
        f"**{sum(r['done'] for r in base)} / {len(base)} {label}** "
        f"({_h(done_h)} h sur {_h(total_h)} h). Mis à jour automatiquement le {now}.",
        "",
        "| Id | Livrable | Durée | Dépend de | Statut | Qui | Issue / PR |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        status = f"**{r['status']}**" if r["status"] in ("Fait", "En relecture", "En cours") else r["status"]
        lines.append(f"| {r['id']} | {r['name']} | {_h(r['hours'])} h | {r['deps']} | {status} | {r['who']} | {r['links']} |")
    return "\n".join(lines)


def replace_block(text, block):
    start, end = text.index(BEGIN) + len(BEGIN), text.index(END)
    return text[:start] + "\n" + block + "\n" + text[end:]


def _gh(args):
    return json.loads(subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout)


def fetch():
    issues = _gh(["issue", "list", "-R", REPO, "--state", "all", "--limit", "200",
                  "--json", "number,title,state,assignees,labels"])
    prs = _gh(["pr", "list", "-R", REPO, "--state", "all", "--limit", "200",
               "--json", "number,title,state,mergedAt"])
    issues = [{"number": i["number"], "title": i["title"], "state": i["state"].lower(),
               "assignees": [a["login"] for a in i["assignees"]],
               "labels": [l["name"] for l in i["labels"]]} for i in issues]
    prs = [{"number": p["number"], "title": p["title"], "state": p["state"].lower(),
            "merged": bool(p["mergedAt"])} for p in prs]
    return issues, prs


def main():
    now = datetime.now(timezone.utc).astimezone().strftime("%d/%m à %H:%M")
    issues, prs = fetch()
    block = render(compute(issues, prs), now)
    if "--check" in sys.argv:
        # publie dans l'issue épinglée : v2 d'abord (le travail en cours), puis v1
        v2 = render(compute(issues, prs, DELIVERABLES_V2), now, "tâches de la v2 faites (hors partenaires)")
        print("## Roadmap v2 — samedi après-midi → dimanche\n\n" + v2 + "\n\n## Roadmap v1\n\n" + block)
        return
    ROADMAP.write_text(replace_block(ROADMAP.read_text(encoding="utf-8"), block), encoding="utf-8")


if __name__ == "__main__":
    main()
