"""Rendu terminal du scénario testeur : en-tête, étapes numérotées, barres de rejeu animées, tableau
des gains, menu de boutons. ANSI pur.

Couleurs et animation seulement sur un vrai terminal, et jamais si ``NO_COLOR`` est défini ou hors TTY :
les tests, les journaux et la CI restent du texte brut, stable, sans attente.
"""
import os
import re
import sys
import time

CODES = {"vert": "32", "gris": "90", "gras": "1", "jaune": "33", "cyan": "36", "inverse": "7"}
ANSI = re.compile(r"\033\[[0-9;]*m")
BAR = 24
MIN_BAR_SECONDS = 1.5  # durée minimale d'affichage d'une barre de rejeu (fixtures : rejeu quasi instantané)
FRAMES = 12            # images de l'animation, réparties sur MIN_BAR_SECONDS


def colors_on(stream=None, env=os.environ):
    stream = stream or sys.stdout
    return "NO_COLOR" not in env and hasattr(stream, "isatty") and stream.isatty()


def paint(text, *styles, on=None):
    on = colors_on() if on is None else on
    if not on or not styles:
        return text
    return f"\033[{';'.join(CODES[s] for s in styles)}m{text}\033[0m"


def width(text):
    return len(ANSI.sub("", text))


def pad(text, n):
    return text + " " * max(0, n - width(text))


def number(n):
    """1872 → « 1 872 »."""
    return f"{n:,}".replace(",", " ")


def header(wf, source=None, title="DeadWeight", on=None):
    """Source explicite (``--source``) affichée en premier ; sans elle, c'est bien le workflow n8n."""
    subtitle = f"test sur {source}  ·  WF {wf}" if source else f"test du workflow n8n {wf}"
    inner = f"  {title}  ·  {subtitle}  "
    line = "─" * width(inner)
    return "\n".join([f"╭{line}╮", f"│{paint(inner, 'gras', on=on)}│", f"╰{line}╯"])


def step(n, total, title, on=None):
    print(f"\n  {paint(f'[{n}/{total}]', 'cyan', 'gras', on=on)} {paint(title, 'gras', on=on)}")


def measure(p, keys):
    """Première mesure présente parmi ``keys``, ou ``None``."""
    return next((p["mesures"][k] for k in keys if (p["mesures"].get(k) or {}).get("valeur") is not None), None)


def cell(m, level=False):
    """Une mesure en cellule de tableau : « -71.7 % », « ~-35.7 % », « — » si non mesurée.
    ``level`` : un niveau (précision), pas une variation, donc jamais de signe."""
    if not m or m.get("valeur") is None:
        return "—"
    unit = m.get("unite") or ""
    sign = "+" if unit == "%" and m["valeur"] > 0 and not level else ""
    text = f"{sign}{m['valeur']:g}{' ' + unit if unit else ''}"
    return text if m.get("statut") == "mesuré" else f"~{text}"


def latency_cell(p):
    """Latence médiane : « -24.4 % » d'ordinaire ; « 812 ms → 0 ms » quand le pourcentage seul
    (-100 %, plus aucun appel au modèle) ressemblerait à un bug plutôt qu'à un vrai gain."""
    m = measure(p, ("latence_mediane",))
    if m and m.get("valeur") == -100.0:
        ms = p.get("latence_ms") or {}
        if ms.get("avant") is not None and ms.get("apres") is not None:
            return f"{ms['avant']:.0f} ms → {ms['apres']:.0f} ms"
    return cell(m)


# colonnes du tableau « Résumé des gains » : (titre, fonction de cellule)
COLUMNS = (("Précision", lambda p: cell(measure(p, ("precision",)), level=True)),
           ("Coût", lambda p: cell(measure(p, ("cout",)))),
           ("Latence méd.", latency_cell),
           ("Latence p95", lambda p: cell(measure(p, ("latence_p95",)))),
           ("Jetons", lambda p: cell(measure(p, ("jetons_envoyes", "jetons_sortie")))))
LEGEND = "mesuré = rejeu des mêmes entrées sur votre historique · ~estimé = calcul avec hypothèse · — non mesuré"


def precision_candidates(proposals):
    """Les propositions qu'on peut montrer : une précision mesurée au rejeu. Prouvées d'abord, puis la
    précision la plus haute. (Le seuil d'affichage à 95 % s'applique ensuite, cf. ``above_threshold``.)"""
    kept = [p for p in proposals if (p["mesures"].get("precision") or {}).get("valeur") is not None]
    return sorted(kept, key=lambda p: (p["verdict"] != "pass", -p["mesures"]["precision"]["valeur"]))


def above_threshold(items, floor_pct):
    """Ne garde que les propositions à au moins ``floor_pct`` de précision : sous ce seuil, une
    proposition n'apparaît ni dans les étapes du testeur, ni dans le tableau, ni dans la PR."""
    return [p for p in items if p["mesures"]["precision"]["valeur"] >= floor_pct]


def render_table(items, on=None):
    """Le tableau encadré « Résumé des gains ». Une ligne par modification retenue."""
    head = ["Modification"] + [title for title, _ in COLUMNS]
    rows = [[p["app_id"]] + [fn(p) for _, fn in COLUMNS] for p in items]
    widths = [max(width(r[i]) for r in [head] + rows) for i in range(len(head))]
    line = lambda cells, *styles: "  ".join(pad(paint(v, *styles, on=on), widths[i])  # noqa: E731
                                             for i, v in enumerate(cells))
    inner = width(line(head))
    out = [f"    ╭{'─' * (inner + 2)}╮", f"    │ {line(head, 'gras')} │", f"    ├{'─' * (inner + 2)}┤"]
    for row in rows:
        colored = [row[0]] + [paint(v, "vert", on=on) if v.lstrip("~").startswith("-") else v for v in row[1:]]
        out.append(f"    │ {line(colored)} │")
    out.append(f"    ╰{'─' * (inner + 2)}╯")
    out.append(f"    {paint(LEGEND, 'gris', on=on)}")
    return "\n".join(out)


class ReplayBar:
    """La barre de précision d'une modification, étape 3 (« Tests »). Animée : la progression suit le
    vrai nombre d'entrées rejouées (pas une horloge décorative), étalée sur au moins
    ``MIN_BAR_SECONDS`` pour rester visible même si le rejeu est instantané. Le résultat final montre
    la précision réelle. Hors terminal ou sans animation demandée : une seule ligne, directe."""

    def __init__(self, label, pct, total=None, detail="", animate=False, on=None, sleep=time.sleep, out=None,
                 min_seconds=MIN_BAR_SECONDS, frames=FRAMES):
        self.label, self.pct, self.total, self.detail = label, pct, total, detail
        self.animate, self.on = bool(animate and total), on
        self.sleep, self.out = sleep, out or sys.stdout
        self.min_seconds, self.frames = min_seconds, frames

    def _bar(self, fraction, tone):
        filled = round(BAR * max(0.0, min(1.0, fraction)))
        return paint("█" * filled, tone, on=self.on) + paint("░" * (BAR - filled), "gris", on=self.on)

    def render(self):
        if self.animate:
            interval = self.min_seconds / self.frames
            for i in range(1, self.frames + 1):
                done = round(self.total * i / self.frames)  # vrai avancement (entrées rejouées / total)
                self.out.write(f"\r\033[2K  {self.label}  {self._bar(done / self.total, 'cyan')}  "
                                f"{number(done)}/{number(self.total)} entrées rejouées")
                self.out.flush()
                self.sleep(interval)
            self.out.write("\r\033[2K")
        tone = "vert" if self.pct >= 95 else "jaune"
        line = (f"  {self.label}  {self._bar(self.pct / 100, tone)}  "
                f"{paint(f'{self.pct:g} %'.rjust(6), 'gras', on=self.on)}  {paint(self.detail, 'gris', on=self.on)}")
        self.out.write(line + "\n")
        self.out.flush()


def replay_detail(p):
    replayed = (measure(p, ("appels_rejoues",)) or {}).get("valeur")
    return f"réponses identiques · {number(replayed)} entrées rejouées" if replayed else "réponses inchangées"


def menu_line(options, active=None, on=None):
    """``options`` : [(touche, libellé)]. La touche active (sélection aux flèches) est en surbrillance."""
    parts = []
    for key, label in options:
        tag = paint(f" {key} ", "inverse", "gras", on=on) if key == active else paint(f" {key} ", "gras", on=on)
        parts.append(f"{tag} {label}")
    return "  ".join(parts)


def read_key(stream=None):
    """Une frappe : lettre, ``enter``, ou ``up``/``down``/``left``/``right`` pour une flèche. Terminal
    en mode brut le temps de la lecture (POSIX ; termios/tty de la stdlib, aucune dépendance)."""
    import termios
    import tty
    stream = stream or sys.stdin
    fd = stream.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = stream.read(1)
        if ch == "\x1b":
            if stream.read(1) != "[":
                return ""
            return {"A": "up", "B": "down", "C": "right", "D": "left"}.get(stream.read(1), "")
        return "enter" if ch in ("\r", "\n") else ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def choose(options, read_key=read_key, out=None, on=None):
    """Menu interactif : flèches gauche/droite (ou haut/bas) pour déplacer la sélection, Entrée pour la
    valider ; une lettre (R/P/Q...) reste un raccourci direct. Retourne la touche choisie (majuscule)."""
    out = out or sys.stdout
    keys = [k for k, _ in options]
    idx = 0
    out.write("\n    " + menu_line(options, keys[idx], on))
    out.flush()
    while True:
        k = read_key()
        if k in ("right", "down"):
            idx = (idx + 1) % len(keys)
        elif k in ("left", "up"):
            idx = (idx - 1) % len(keys)
        elif k == "enter":
            out.write("\n")
            return keys[idx]
        elif k and k.upper() in keys:
            out.write("\n")
            return k.upper()
        else:
            continue
        out.write("\r\033[2K    " + menu_line(options, keys[idx], on))
        out.flush()
