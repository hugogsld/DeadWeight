"""Socle commun aux connecteurs de journaux : lecture, clés masquées, rapport de compréhension.

Contrat d'un connecteur (docs/analyser-un-workflow.md) : lire(source) -> événements au schéma
commun + un rapport de compréhension (lus, ignorés et pourquoi, niveau atteint). Aucune clé
gardée : toute chaîne qui ressemble à une clé d'API est masquée avant d'entrer dans un événement.
"""
from __future__ import annotations

import json
import re
import zipfile
from datetime import datetime
from pathlib import Path

# clés d'API courantes ; une sortie de commande dans un journal peut en afficher une
SECRETS = re.compile(
    r"sk-ant-[A-Za-z0-9_-]{20,}"
    r"|sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}"
    r"|AIza[0-9A-Za-z_-]{35}"
    r"|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}"
    r"|xox[abprs]-[A-Za-z0-9-]{10,}"
    r"|AKIA[0-9A-Z]{16}"
    r"|(?i:bearer)\s+[A-Za-z0-9._~+/-]{20,}=*"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"
)


def mask_secrets(text):
    if not isinstance(text, str) or not text:
        return text
    return SECRETS.sub("[secret]", text)


def _lines(text: str) -> list[str]:
    # pas splitlines() : il coupe aussi sur U+2028, présent dans les textes des journaux
    return text.split("\n")


def iter_files(source: str | Path):
    """(nom, lignes) pour chaque .jsonl d'un fichier, d'un dossier (récursif) ou d'une archive .zip."""
    source = Path(source)
    if source.is_dir():
        for path in sorted(source.rglob("*.jsonl")):
            yield str(path), _lines(path.read_text(encoding="utf-8", errors="replace"))
    elif source.suffix == ".zip":
        with zipfile.ZipFile(source) as z:
            for name in sorted(n for n in z.namelist() if n.endswith(".jsonl") and "__MACOSX" not in n):
                with z.open(name) as f:
                    yield f"{source}!{name}", _lines(f.read().decode("utf-8", errors="replace"))
    elif source.exists():
        yield str(source), _lines(source.read_text(encoding="utf-8", errors="replace"))
    else:
        raise FileNotFoundError(f"introuvable : {source}")


def parse_lines(lines) -> tuple[list[dict], int]:
    """Objets JSON d'un fichier, et nombre de lignes illisibles (comptées par le lecteur du fichier)."""
    entries, bad = [], 0
    for line in lines:
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            bad += 1
            continue
        if isinstance(obj, dict):
            entries.append(obj)
    return entries, bad


def ts(value) -> float | None:
    """Horodatage ISO (…Z) ou secondes epoch → secondes epoch."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value) / (1000 if value > 1e11 else 1)
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def iso(seconds: float) -> str:
    from datetime import timezone
    return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def num(value) -> int | None:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


class Comprehension:
    """Ce qu'on a lu, ce qu'on a ignoré et pourquoi, le niveau de données atteint."""

    def __init__(self, source: str):
        self.source = source
        self.files = 0
        self.sessions: set[str] = set()
        self.calls = 0
        self.ignored: dict[str, int] = {}
        self.with_content = 0
        self.with_trace = 0
        self.notes: list[str] = []
        self.extra: dict[str, int] = {}

    def ignore(self, reason: str, n: int = 1):
        self.ignored[reason] = self.ignored.get(reason, 0) + n

    def add(self, key: str, n: int):
        self.extra[key] = self.extra.get(key, 0) + n

    def note(self, text: str):
        if text not in self.notes:
            self.notes.append(text)

    def level(self) -> int | None:
        """1 usage, 2 contenu, 3 structure (docs/analyser-un-workflow.md)."""
        if not self.calls:
            return None
        if self.with_content and self.with_trace:
            return 3
        return 2 if self.with_content else 1

    def as_dict(self) -> dict:
        return {
            "source": self.source,
            "fichiers": self.files,
            "sessions": len(self.sessions),
            "appels_lus": self.calls,
            "ignores": dict(sorted(self.ignored.items())),
            "niveau": self.level(),
            **self.extra,
            "limites": self.notes,
        }
