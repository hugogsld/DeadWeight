"""Une proposition validée -> une micro-modification du dépôt du client (une par PR).

Recettes, volontairement simples et vérifiables à la relecture :
- ``regles``  : aucun code touché. La preuve (règles + verdict) est ajoutée dans ``deadweight/preuves/`` et
  la passerelle l'applique (``GATEWAY_SHORTCIRCUIT``). Accepter la PR active le gain ; la retirer l'annule.
- ``modele``  : l'identifiant du modèle remplacé là où il apparaît. Si le même identifiant sert à plusieurs
  étapes, la PR le dit : à vérifier avant d'accepter.
- ``plafond`` : ``max_tokens`` ajouté aux appels ``chat.completions.create`` qui n'en ont pas, dans les
  fichiers de l'application concernée.

Rien n'est poussé sans ``open_pr`` : par défaut, on écrit le diff et le texte de la PR.
"""
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

SKIP = {".git", ".venv", "venv", "node_modules", "__pycache__", "out", "private"}
TEXT = {".py", ".js", ".ts", ".mjs", ".json", ".yaml", ".yml", ".toml", ".md", ".example", ".env"}


def _files(repo):
    for p in Path(repo).rglob("*"):
        if p.is_file() and not SKIP & set(p.relative_to(repo).parts) and (p.suffix in TEXT or p.name.endswith(".example")):
            yield p


def _app_files(repo, app_id):
    """Fichiers qui déclarent l'application (en-tête x-deadweight-app ou nom de service)."""
    hits = [p for p in _files(repo) if p.suffix in {".py", ".js", ".ts", ".mjs"} and app_id in p.read_text(errors="ignore")]
    return hits or [p for p in _files(repo) if p.suffix in {".py", ".js", ".ts", ".mjs"}]


def _apply_regles(repo, proposal):
    slug = re.sub(r"[^a-z0-9-]+", "-", proposal["app_id"].lower()).strip("-")
    target = Path(repo) / "deadweight" / "preuves" / f"proof-{slug}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(proposal["preuve"], ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    env = Path(repo) / ".env.example"
    text = env.read_text(encoding="utf-8") if env.exists() else ""
    if "GATEWAY_SHORTCIRCUIT" not in text:
        env.write_text(text + ("\n" if text and not text.endswith("\n") else "")
                       + "# Deadweight : règles prouvées appliquées par la passerelle (retirer la ligne pour désactiver)\n"
                       + "GATEWAY_SHORTCIRCUIT=deadweight/preuves\n", encoding="utf-8")
    return []


def _apply_modele(repo, proposal):
    old, new = proposal["model"], proposal["nouveau_modele"]
    where = []
    for p in _files(repo):
        text = p.read_text(errors="ignore")
        if re.search(rf"(?<![\w.-]){re.escape(old)}(?![\w.-])", text):
            lines = [i + 1 for i, line in enumerate(text.splitlines()) if old in line]
            where += [f"{p.relative_to(repo)}:{n}" for n in lines]
            p.write_text(re.sub(rf"(?<![\w.-]){re.escape(old)}(?![\w.-])", new, text), encoding="utf-8")
    return ([f"`{old}` apparaît à {len(where)} endroits : vérifier qu'il ne sert qu'à cette étape"]
            if len(where) > 1 else []) + ([] if where else [f"`{old}` introuvable dans le dépôt"])


def _apply_plafond(repo, proposal):
    cap, notes, changed = proposal["plafond"], [], 0
    for p in _app_files(repo, proposal["app_id"]):
        text = p.read_text(errors="ignore")
        new = re.sub(r"chat\.completions\.create\((?![^)]*max_tokens)", f"chat.completions.create(max_tokens={cap}, ", text)
        if new != text:
            changed += text.count("chat.completions.create(") - new.count("chat.completions.create(max_tokens=") + \
                new.count(f"chat.completions.create(max_tokens={cap}, ")
            p.write_text(new, encoding="utf-8")
    if not changed:
        notes.append("aucun appel chat.completions.create sans plafond trouvé")
    return notes


RECIPES = {"regles": _apply_regles, "modele": _apply_modele, "plafond": _apply_plafond}


def make_patch(repo, proposal):
    """Applique la recette sur une copie du dépôt ; rend (diff unifié, remarques pour la relecture)."""
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "repo"
        shutil.copytree(repo, work, ignore=shutil.ignore_patterns(*SKIP - {".git"}))
        notes = RECIPES[proposal["type"]](work, proposal)
        subprocess.run(["git", "add", "-A"], cwd=work, check=True, capture_output=True)
        diff = subprocess.run(["git", "diff", "--cached"], cwd=work, check=True, capture_output=True, text=True).stdout
    return diff, notes


def pr_text(proposal, notes):
    """Titre et corps de la micro-PR : la modification, ses mesures avec leur statut, ce qu'il faut vérifier."""
    m = proposal["mesures"]
    lines = [f"**{proposal['changement']}**", "", "| Mesure | Valeur | Statut |", "|---|---|---|"]
    for key, v in m.items():
        if v["valeur"] is not None:
            unit = f" {v['unite']}" if v["unite"] else ""
            lines.append(f"| {key.replace('_', ' ')} | {v['valeur']}{unit} | {v['statut']}"
                         + (f" ({v['hypothese']})" if v.get("hypothese") else "") + " |")
    lines += ["", "Mesuré sur l'historique réel : mêmes entrées rejouées, comparées aux anciennes réponses."]
    if notes:
        lines += ["", "**À vérifier avant d'accepter :**"] + [f"- {n}" for n in notes]
    lines += ["", "Généré par Deadweight."]
    return f"Deadweight : {proposal['changement'][:90]}", "\n".join(lines)


def open_pr(repo, proposal, branch):
    """Crée la branche, le commit et la PR dans le dépôt du client (gh). Seulement sur demande explicite."""
    title, body = pr_text(proposal, make_patch(repo, proposal)[1])
    run = lambda *a: subprocess.run(a, cwd=repo, check=True, capture_output=True, text=True).stdout  # noqa: E731
    base = run("git", "rev-parse", "--abbrev-ref", "HEAD").strip()
    run("git", "switch", "-c", branch)
    try:
        RECIPES[proposal["type"]](repo, proposal)
        run("git", "add", "-A")
        run("git", "commit", "-m", title)
        run("git", "push", "-u", "origin", branch)
        return run("gh", "pr", "create", "--base", base, "--head", branch, "--title", title, "--body", body).strip()
    finally:
        run("git", "switch", base)
