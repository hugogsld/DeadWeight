"""B1.4 : masquer les données personnelles avant analyse, effacer le brut après.

Chaque valeur distincte reçoit une étiquette stable ([email-1], [telephone-2]...) : deux
messages du même client restent reconnaissables comme tels, sans révéler qui il est.
Les règles qui comparent des textes (entropie, boucles) gardent donc leur signal.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){3,7}(?:[ ]?[A-Z0-9]{1,3})?\b")
# suite de chiffres avec séparateurs ; triée ensuite selon le nombre de chiffres
DIGITS = re.compile(r"(?<![\w+])(\+?\(?\d[\d\s().-]{7,24}\d)(?!\w)")


def _luhn(number: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(number)):
        d = int(ch)
        if i % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


class Masker:
    def __init__(self):
        self.seen: dict[tuple[str, str], str] = {}
        self.counts: dict[str, int] = {}

    def _label(self, kind: str, value: str) -> str:
        key = (kind, re.sub(r"[\s().-]", "", value).lower())
        if key not in self.seen:
            self.counts[kind] = self.counts.get(kind, 0) + 1
            self.seen[key] = f"[{kind}-{self.counts[kind]}]"
        return self.seen[key]

    def _digits(self, m: re.Match) -> str:
        raw = m.group(1)
        digits = re.sub(r"\D", "", raw)
        if 13 <= len(digits) <= 19 and _luhn(digits):
            return self._label("carte", raw)
        # un téléphone : 9 à 15 chiffres, commence par + ou 0 (les dates ISO en ont 8)
        if 9 <= len(digits) <= 15 and (raw.startswith("+") or raw.lstrip("(").startswith("0")):
            return self._label("telephone", raw)
        return raw

    def text(self, value):
        if not isinstance(value, str) or not value:
            return value
        value = EMAIL.sub(lambda m: self._label("email", m.group(0)), value)
        value = IBAN.sub(lambda m: self._label("iban", m.group(0)), value)
        return DIGITS.sub(self._digits, value)

    def event(self, ev: dict) -> dict:
        req, resp = ev["request"], ev["response"]
        req["system"] = self.text(req.get("system"))
        for m in req.get("messages", []):
            m["content"] = self.text(m.get("content"))
            for c in m.get("tool_calls") or []:
                c["arguments"] = self.text(c["arguments"])
        resp["content"] = self.text(resp.get("content"))
        for c in resp.get("tool_calls") or []:
            c["arguments"] = self.text(c["arguments"])
        if ev.get("error"):
            ev["error"]["message"] = self.text(ev["error"]["message"])
        return ev

    def summary(self) -> dict:
        return dict(self.counts)


def purge(folder: Path) -> list[str]:
    """Efface un dossier écrit par fetch. Refuse tout autre dossier."""
    folder = Path(folder)
    if not (folder / "workflow.json").exists() and not (folder / "executions.jsonl").exists():
        raise ValueError(f"{folder} n'est pas un dossier d'import n8n (ni workflow.json ni executions.jsonl)")
    removed = sorted(p.name for p in folder.iterdir())
    shutil.rmtree(folder)
    return removed
