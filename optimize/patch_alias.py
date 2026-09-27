"""Recette ``modele_alias`` : renommer le modèle utilisé par des étapes mécaniques
d'un orchestrateur qui nomme ses modèles par alias (ex. ``spawn(fn, {label, model})``).

Ne touche que les appels dont le libellé (``label``) commence par un des préfixes
donnés. Si l'appel n'a pas de champ ``model``, il est ajouté. Aucune dépendance :
un simple appariement de parenthèses pour isoler chaque appel ``spawn(...)``.
"""
from __future__ import annotations

import re

_LABEL = re.compile(r"label:\s*'([^']*)'")
_MODEL = re.compile(r"model:\s*'([^']*)'")


def _spawn_calls(text: str) -> list[tuple[int, int]]:
    """Bornes (début, fin) de chaque appel ``spawn(...)``, parenthèses équilibrées."""
    calls = []
    for m in re.finditer(r"spawn\(", text):
        depth = 0
        for j in range(m.end() - 1, len(text)):
            if text[j] == "(":
                depth += 1
            elif text[j] == ")":
                depth -= 1
                if depth == 0:
                    calls.append((m.start(), j + 1))
                    break
    return calls


def rewrite_model_alias(text: str, label_prefixes: list[str], alias: str) -> tuple[str, list[str]]:
    """Réécrit ``model:`` dans les appels dont le label commence par un des préfixes.

    Rend (texte modifié, libellés touchés). Aucun appel hors des préfixes donnés
    n'est modifié ; un appel sans ``model:`` en reçoit un, juste après ``label:``.
    """
    changed: list[str] = []
    pieces: list[str] = []
    last = 0
    for start, end in _spawn_calls(text):
        call = text[start:end]
        label_match = _LABEL.search(call)
        if not label_match or not any(label_match.group(1).startswith(p) for p in label_prefixes):
            continue
        model_match = _MODEL.search(call)
        if model_match:
            new_call = call[: model_match.start(1)] + alias + call[model_match.end(1) :]
        else:
            insert_at = call.find(",", label_match.end())
            insert_at = insert_at + 1 if insert_at != -1 else label_match.end()
            new_call = call[:insert_at] + f" model: '{alias}'," + call[insert_at:]
        pieces.append(text[last:start])
        pieces.append(new_call)
        last = end
        changed.append(label_match.group(1))
    pieces.append(text[last:])
    return "".join(pieces), changed
