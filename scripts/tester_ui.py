"""Écran terminal du scénario testeur : étapes numérotées, barres de précision animées, encadré des
gains, menu de boutons. ANSI pur.

Rien n'est calculé ici : chaque chiffre vient de ``propositions.json`` (ou du chiffrage global de
l'historique pour les gains d'ensemble, ``scripts.tester_gains``). Une estimation porte « ~ », une
mesure absente s'affiche « — », et rien n'est additionné. Couleurs et animation seulement dans un vrai
terminal, jamais avec ``NO_COLOR`` ; l'animation s'arrête aussi hors TTY ou avec ``--no-anim``.

Seuil d'affichage : sous ``PRECISION_FLOOR_PCT`` (même chiffre que le rejeu des règles,
``proof.replay.THRESHOLD`` — pas un deuxième seuil à maintenir), une proposition n'apparaît nulle part :
ni dans les étapes, ni dans le tableau, ni dans la PR (le seuil est aussi appliqué avant diff/PR, dans
``optimize.__main__``).
"""
import os
import re
import shutil
import sys
import time
from collections import Counter

from proof.replay import THRESHOLD

ANSI = re.compile(r"\x1b\[[0-9;]*m")
CODES = {"bold": "1", "dim": "2", "green": "32", "red": "31", "cyan": "36", "yellow": "33", "inverse": "7"}
BAR = 20
MIN_BAR_SECONDS = 1.5  # durée minimale d'affichage d'une barre de rejeu (fixtures : rejeu quasi instantané)
FRAMES = 12            # images de l'animation, réparties sur MIN_BAR_SECONDS
PRECISION_FLOOR_PCT = THRESHOLD * 100
# colonnes de l'encadré « Résumé des gains » : (titre, fonction de cellule)
COLUMNS = (("Précision", lambda p: cell(measure(p, ("precision",)), level=True)),
           ("Coût", lambda p: cell(measure(p, ("cout",)))),
           ("Latence méd.", lambda p: latency_cell(p)),
           ("Latence p95", lambda p: cell(measure(p, ("latence_p95",)))),
           ("Jetons", lambda p: cell(measure(p, ("jetons_envoyes", "jetons_sortie")))))
LEGEND = "Mesuré = vos propres entrées rejouées, comparées aux réponses de l'ancien workflow · ~ estimé · — non mesuré"


def colors_on(stream=sys.stdout, env=os.environ):
    return stream.isatty() and "NO_COLOR" not in env


class Style:
    def __init__(self, enabled):
        self.enabled = enabled

    def __call__(self, text, *names):
        if not self.enabled or not names:
            return text
        return f"\x1b[{';'.join(CODES[n] for n in names)}m{text}\x1b[0m"


def width(text):
    return len(ANSI.sub("", text))


def pad(text, n):
    return text + " " * max(0, n - width(text))


def measure(p, keys):
    """Première mesure présente parmi ``keys`` (une valeur non nulle), ou ``None``."""
    return next((p["mesures"][k] for k in keys if (p["mesures"].get(k) or {}).get("valeur") is not None), None)


def cell(m, level=False):
    """Une mesure en cellule courte : « -71.7 % », « ~-35.7 % », « — » si non mesurée.
    ``level`` : un niveau (précision), pas une variation, donc jamais de signe."""
    if not m or m.get("valeur") is None:
        return "—"
    unit = m.get("unite") or ""
    sign = "+" if m["valeur"] > 0 and not level else ""
    text = f"{sign}{m['valeur']:g}{' ' + unit if unit else ''}"
    return text if m.get("statut") == "mesuré" else f"~{text}"


def latency_cell(p):
    """Latence médiane : « -24.4 % » d'ordinaire ; « 633 ms → 0 ms » quand le pourcentage seul
    (-100 %, plus aucun appel au modèle) ressemblerait à un bug plutôt qu'à un vrai gain."""
    m = measure(p, ("latence_mediane",))
    if m and m.get("valeur") == -100.0:
        ms = p.get("latence_ms") or {}
        if ms.get("avant") is not None and ms.get("apres") is not None:
            return f"{ms['avant']:.0f} ms → {ms['apres']:.0f} ms"
    return cell(m)


def replayed_cell(p):
    n = (measure(p, ("appels_rejoues",)) or {}).get("valeur")
    return f"{n} entrées rejouées" if n else "—"


def _passes(p):
    """Une seule règle pour tout le testeur : prouvée (verdict « pass ») ET au moins
    ``PRECISION_FLOOR_PCT`` de précision mesurée. Sinon la proposition n'apparaît nulle part (étapes
    2/3/4, tableau, PR) : elle reste une piste, comptée dans ``excluded_summary``."""
    v = (p["mesures"].get("precision") or {}).get("valeur")
    return p["verdict"] == "pass" and v is not None and v >= PRECISION_FLOOR_PCT


def shown(proposals):
    """Les modifications affichées : prouvées, au moins ``PRECISION_FLOOR_PCT`` de précision. Triées,
    la précision la plus haute d'abord."""
    kept = [p for p in proposals if _passes(p)]
    return sorted(kept, key=lambda p: -p["mesures"]["precision"]["valeur"])


def exclusion_reason(p):
    """Raison courte d'une proposition écartée : sa précision est mesurée et sous le seuil, ou
    l'échantillon ne suffit pas à conclure (verdict refusé pour une autre raison, ou rien à mesurer)."""
    v = (p["mesures"].get("precision") or {}).get("valeur")
    return "précision < 95 %" if v is not None and v < PRECISION_FLOOR_PCT else "échantillon insuffisant"


def excluded_summary(proposals):
    """« N proposition(s) écartée(s) (raison, raison…) », ou ``None`` si rien n'est écarté."""
    reasons = Counter(exclusion_reason(p) for p in proposals if not _passes(p))
    if not reasons:
        return None
    total = sum(reasons.values())
    detail = ", ".join(f"{n} {reason}" for reason, n in reasons.items())
    suffix = "s" if total > 1 else ""
    return f"{total} proposition{suffix} écartée{suffix} ({detail})"


def bar(pct, s, tone=None):
    full = round(BAR * pct / 100)
    tone = tone or ("green" if pct >= 95 else "yellow")
    return s("█" * full, tone) + s("░" * (BAR - full), "dim")


def step(n, title, s, out=None):
    (out or sys.stdout).write(f"\n  {s(f'[{n}/4]', 'cyan', 'bold')} {s(title, 'bold')}\n")


def header(wf, s, source=None):
    """Source explicite (``--source``) affichée en premier ; sans elle, c'est bien le workflow n8n."""
    subtitle = f"test sur {source}  ·  WF {wf}" if source else f"test du workflow n8n {wf}"
    print(f"\n  {s(' DEADWEIGHT ', 'inverse', 'bold')}  {s(subtitle, 'dim')}")


def plural(n):
    return "s" if n > 1 else ""


def analysis(info, s):
    step(1, "Analyse du workflow", s)
    parts = [f"{info['appels']} appels IA"]
    parts += [f"{info['executions']} exécution{plural(info['executions'])}"] if info["executions"] else []
    parts += [f"{info['noeuds']} nœuds"] if info["noeuds"] else []
    print(f"    {s('✓', 'green')} {s(info['nom'], 'bold')} · {' · '.join(parts)}")
    found = [f"{len(info['etapes'])} étape{plural(len(info['etapes']))} IA"] if info["etapes"] else []
    found += [f"{len(info['modeles'])} modèle{plural(len(info['modeles']))} ({', '.join(info['modeles'][:4])}"
              f"{', …' if len(info['modeles']) > 4 else ''})"] if info["modeles"] else []
    if found:
        print(f"    {s('✓', 'green')} {' · '.join(found)}")


def modifications(items, s):
    step(2, "Modifications proposées", s)
    if not items:
        print(f"    {s('Aucune modification testable sur cet historique.', 'dim')}")
        return
    name_w = max(len(p["app_id"]) for p in items)
    for i, p in enumerate(items, 1):
        print(f"    {s(str(i), 'cyan')}  {s(pad(p['app_id'], name_w), 'bold')}  {p['changement']}")


def tests(items, s, animate=True, sleep=time.sleep, min_seconds=MIN_BAR_SECONDS, frames=FRAMES, out=None,
          columns=None):
    """Étape 3 : une barre par modification. Animée, la progression suit le vrai nombre d'entrées
    rejouées (pas une horloge décorative), étalée sur au moins ``min_seconds`` pour rester visible même
    si le rejeu est instantané. Hors TTY ou sans animation demandée : la barre finale, directement."""
    out = out or sys.stdout
    step(3, "Tests : l'historique rejoué, nouveau workflow comparé à l'ancien", s, out)
    name_w = max((len(p["app_id"]) for p in items), default=0)
    for i, p in enumerate(items, 1):
        pct = p["mesures"]["precision"]["valeur"]
        total = (measure(p, ("appels_rejoues",)) or {}).get("valeur")
        detail = f"réponses identiques · {total} entrées rejouées" if total else "réponses inchangées"
        label = f"{s(str(i), 'cyan')}  {pad(p['app_id'], name_w)}"
        if animate and total:
            interval = min_seconds / frames
            cols = columns or shutil.get_terminal_size((80, 24)).columns
            for f in range(1, frames + 1):
                done = round(total * f / frames)  # vrai avancement (entrées rejouées / total)
                frame = f"    {label}  {bar(100 * done / total, s, 'cyan')}  "
                # une image plus large que le terminal passe à la ligne : le \r ne l'effacerait plus
                tail = next((t for t in (f"{done}/{total} entrées rejouées", f"{done}/{total}", "")
                             if width(frame + t) < cols), "")
                out.write(f"\r\033[2K{frame}{tail}")
                out.flush()
                sleep(interval)
            out.write("\r\033[2K")
        out.write(f"    {label}  {bar(pct, s)}  {s(f'{pct:g} %'.rjust(6), 'bold')}  {s(detail, 'dim')}\n")


def summary(items, s, gains=None, excluded_line=None):
    step(4, "Résumé des gains", s)
    if not items:
        print(f"    {s('Aucune modification retenue sur cet historique.', 'dim')}")
        if excluded_line:
            print(s(f"    {excluded_line}", "dim"))
        return
    head = ["Modification", "Entrées rejouées"] + [title for title, _ in COLUMNS]
    rows = [[p["app_id"], replayed_cell(p)] + [fn(p) for _, fn in COLUMNS] for p in items]
    widths = [max(width(r[i]) for r in [head] + rows) for i in range(len(head))]
    line = lambda cells, *styles: "  ".join(pad(s(v, *styles), widths[i])  # noqa: E731
                                             for i, v in enumerate(cells))
    inner = width(line(head))
    print(f"    ╭{'─' * (inner + 2)}╮")
    print(f"    │ {line(head, 'bold')} │")
    print(f"    ├{'─' * (inner + 2)}┤")
    for row in rows:
        colored = row[:2] + [s(v, "green") if v.lstrip("~").startswith("-") else v for v in row[2:]]
        print(f"    │ {line(colored)} │")
    print(f"    ╰{'─' * (inner + 2)}╯")
    print(f"    {s(LEGEND, 'dim')}")
    if gains:
        gains_block(gains, s)
    if excluded_line:
        print(s(f"    {excluded_line}", "dim"))


def _money(v):
    return f"{v:.4g} $" if v is not None else "—"


def _pct(v):
    return f"{v:+.1f} %" if v is not None else "—"


def gains_block(gains, s):
    """Gains sur l'ensemble du workflow (pas seulement les modifications retenues), sous le tableau."""
    print(f"\n    {s('Gains sur l’ensemble du workflow (historique rejoué) :', 'bold')}")
    if gains["cout_avant"] is None:
        # au moins un appel réussi sans jetons ou sans prix connu : le total serait faux, on le dit
        print("      coût total : non chiffrable sur cet historique (appels sans jetons ou sans prix connus) ;"
              " seuls les gains par modification ci-dessus sont mesurés")
        return
    print(f"      coût total : {_money(gains['cout_avant'])} → {_money(gains['cout_apres'])} "
          f"({_pct(gains['cout_pct'])})")
    if gains["executions"]:
        print(f"      coût par exécution : {_money(gains['cout_par_execution_avant'])} → "
              f"{_money(gains['cout_par_execution_apres'])}  ·  projection pour 1 000 exécutions : "
              f"{_money(gains['projection_1000_usd'])} (sur la base de {gains['executions']} exécutions observées)")
    else:
        print("      coût par exécution : — (nombre d'exécutions non mesuré)")


def menu_line(buttons, s, active=None):
    """``buttons`` : [(touche, libellé)]. La touche active (sélection aux flèches) est en surbrillance."""
    parts = []
    for k, label in buttons:
        tag = s(f" {k} ", "inverse", "bold") if k == active else s(f" {k} ", "bold")
        parts.append(f"{tag} {label}")
    return "  ".join(parts)


def menu(buttons, s):
    print("\n    " + menu_line(buttons, s))


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


def choose(buttons, s, read_key=read_key, out=None):
    """Menu interactif : flèches gauche/droite (ou haut/bas) pour déplacer la sélection, Entrée pour la
    valider ; une lettre (R/P/Q...) reste un raccourci direct. Retourne la touche choisie (majuscule)."""
    out = out or sys.stdout
    keys = [k for k, _ in buttons]
    idx = 0
    out.write("\n    " + menu_line(buttons, s, keys[idx]))
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
        out.write("\r\033[2K    " + menu_line(buttons, s, keys[idx]))
        out.flush()


def diff_lines(text, s, limit=60):
    """Diff unifié coloré, coupé à ``limit`` lignes (le fichier complet reste sur disque)."""
    lines = text.splitlines()
    for ln in lines[:limit]:
        if ln.startswith(("+++", "---", "diff ", "index ", "new file")):
            print("    " + s(ln, "bold"))
        elif ln.startswith("@@"):
            print("    " + s(ln, "cyan"))
        elif ln.startswith("+"):
            print("    " + s(ln, "green"))
        elif ln.startswith("-"):
            print("    " + s(ln, "red"))
        else:
            print("    " + ln)
    if len(lines) > limit:
        print("    " + s(f"… {len(lines) - limit} lignes de plus", "dim"))
