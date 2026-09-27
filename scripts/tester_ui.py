"""Rendu terminal du scénario testeur : en-tête encadré, couleurs, barre de progression. ANSI pur.

Couleurs et animation seulement sur un terminal, et jamais si ``NO_COLOR`` est défini : les tests et
les journaux restent du texte brut, stable.
"""
import os
import sys
import time

CODES = {"vert": "32", "gris": "90", "gras": "1", "jaune": "33", "cyan": "36"}
BAR = 24


def colors_on(stream=None, env=os.environ):
    stream = stream or sys.stdout
    return "NO_COLOR" not in env and hasattr(stream, "isatty") and stream.isatty()


def paint(text, *styles, on=None):
    on = colors_on() if on is None else on
    if not on or not styles:
        return text
    return f"\033[{';'.join(CODES[s] for s in styles)}m{text}\033[0m"


def number(n):
    """1872 → « 1 872 »."""
    return f"{n:,}".replace(",", " ")


def header(title="DeadWeight", subtitle="scénario testeur", on=None):
    inner = f"  {title}  ·  {subtitle}  "
    line = "─" * len(inner)
    return "\n".join([f"╭{line}╮", f"│{paint(inner, 'gras', on=on)}│", f"╰{line}╯"])


def status(statut, on=None):
    """« mesuré » en vert, « ~estimé » en jaune : visibles d'un coup d'œil."""
    return paint("mesuré", "vert", "gras", on=on) if statut == "mesuré" else paint("~estimé", "jaune", on=on)


class Progress:
    """Étape x/n, barre █░, temps écoulé. Hors terminal : une ligne simple par étape, sans temps."""

    def __init__(self, labels, on=None, clock=time.monotonic, out=None):
        self.labels, self.clock, self.out = labels, clock, out or sys.stdout
        self.on = colors_on(self.out) if on is None else on
        self.start = clock()

    def step(self, i):
        n, label = len(self.labels), self.labels[i - 1]
        if not self.on:
            print(f"[{i}/{n}] {label}", file=self.out)
            return
        filled = round(BAR * (i - 1) / n)
        bar = paint("█" * filled, "vert", on=True) + paint("░" * (BAR - filled), "gris", on=True)
        elapsed = self.clock() - self.start
        self.out.write(f"\r\033[2K  {i}/{n} {bar} {label}  {paint(f'{elapsed:.1f} s', 'gris', on=True)}")
        self.out.flush()

    def done(self):
        if self.on:
            elapsed = self.clock() - self.start
            bar = paint("█" * BAR, "vert", on=True)
            self.out.write(f"\r\033[2K  {len(self.labels)}/{len(self.labels)} {bar} terminé  "
                           f"{paint(f'{elapsed:.1f} s', 'gris', on=True)}\n")
            self.out.flush()
