"""Blocs HTML lisibles en 30 secondes pour audit.html : actions en tête, une carte par problème, vue par
workflow, vérifications sans résultat, barres avant → après des gains prouvés.

Les chiffres viennent de report.regroupe (vue regroupée des mêmes constats) ; rien n'est recalculé ici.
"""
import html
import re

from report.fmt import ms, usd
from report.regroupe import actions, groupes, nom_workflow, par_workflow

TOP_TABLE = 5       # workflows montrés par carte de problème
TOP_WORKFLOWS = 10  # lignes montrées dans la vue par workflow

CSS = """
.todo-top{list-style:none;margin:0;padding:0;counter-reset:a}
.todo-top li{counter-increment:a;border:1px solid var(--line);border-left:4px solid var(--warn);border-radius:8px;
padding:10px 14px;margin:8px 0}
.todo-top li:before{content:counter(a) ". ";font-weight:700}
.todo-top .why{display:block;color:var(--mute);font-size:13px;margin-top:2px}
.tag{display:inline-block;border:1px solid var(--line);border-radius:10px;padding:0 8px;font-size:12px;
color:var(--mute);margin:1px 4px 1px 0;white-space:nowrap}
.tag.ok{color:var(--ok);border-color:var(--ok)}.tag.warn{color:var(--warn);border-color:var(--warn)}
.bar{display:inline-block;width:90px;height:8px;background:var(--line);border-radius:4px;vertical-align:middle;
margin-right:6px;overflow:hidden}.bar i{display:block;height:100%;background:var(--warn)}
.bar.good i{background:var(--ok)}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.card .head{display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap;align-items:baseline}
details>summary{cursor:pointer;color:var(--mute);font-size:13px;margin:6px 0}
.hero{border:2px solid var(--ok);border-radius:10px;padding:4px 16px 12px;margin:16px 0}
.hero h2{color:var(--ok)}.cmp{margin:6px 0}.cmp .lab{display:inline-block;width:110px;color:var(--mute);font-size:13px}
.cmp .bar{width:160px}.cmp .val{font-size:13px;font-variant-numeric:tabular-nums}
code{background:var(--line);border-radius:4px;padding:0 4px;font-size:13px}
"""


def _txt(text):
    """Texte échappé ; les `extraits de code` deviennent <code>."""
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", html.escape(text or ""))


def _pct(part):
    return "—" if part is None else f"{part * 100:.0f} %" if part >= 0.01 or part == 0 else "< 1 %"


def _bar(part, good=False):
    width = 0 if part is None else min(100, max(part * 100, 1 if part else 0))
    return f'<span class="bar{" good" if good else ""}"><i style="width:{width:.0f}%"></i></span>'


def _lat(row):
    return f"{ms(row['p50'])} / {ms(row['p95'])}" if row["p50"] or row["p95"] else "non mesuré"


def _rows(rows, metric):
    return "".join(
        f"<tr><td>{html.escape(r['nom'])}</td><td class=\"n\">{r['appels']}</td><td class=\"n\">{usd(r['cout'])}</td>"
        f"<td class=\"n\">{_bar(r['part'])}{_pct(r['part'])}</td><td class=\"n\">{_lat(r)}</td>"
        + (f"<td class=\"n\">{html.escape(r['metrique'] or '—')}</td>" if metric else "") + "</tr>" for r in rows)


def _table(rows, metric):
    head = ("<tr><th>Workflow</th><th class=\"n\">Appels</th><th class=\"n\">Coût</th><th class=\"n\">Part du coût</th>"
            "<th class=\"n\">Latence p50 / p95</th>" + (f"<th class=\"n\">{html.escape(metric)}</th>" if metric else "")
            + "</tr>")
    return f"<table>{head}{_rows(rows, metric)}</table>"


def vue(report):
    """Vue regroupée du rapport : groupes par problème, actions, lignes par workflow."""
    total = _total(report)
    grps = groupes(report["constats"], total, [a["app_id"] for a in report.get("applications") or []] or None)
    return {"total": total, "groupes": grps, "actions": actions(grps),
            "workflows": par_workflow(report.get("applications") or [], grps, total)}


def _total(report):
    g = (report["resume"] or {}).get("global") or {}
    return g.get("cout_mensuel_usd") if g.get("cout_mensuel_usd") is not None else g.get("cout_observe_usd")


def actions_html(acts, equivalent_api=False, projection=True):
    """« Ce qu'il faut faire » : au plus trois lignes (action, où, effet attendu, statut)."""
    if not acts:
        return ""
    items = []
    for a in acts:
        names = ", ".join(a["workflows"]) + (f" (+{a['nb_workflows'] - len(a['workflows'])} autres)"
                                             if a["nb_workflows"] > len(a["workflows"]) else "")
        unit = " équiv. API" if equivalent_api else ""
        # sous une journée observée, une économie « par mois » extrapole du bruit : on dit la part du coût
        effect = (f"jusqu'à ~{usd(a['economie'])} par mois{unit} (estimé)" if a["economie"] and projection else
                  f"touche {_pct(a['part'])} du coût{unit}" if a["part"] is not None else "à mesurer")
        tone = "ok" if a["statut"] == "prouvé" else "warn"
        items.append(f"<li><b>{_txt(a['action'])}</b><span class=\"why\">Où : {html.escape(names)} · Effet attendu : "
                     f"{html.escape(effect)} · <span class=\"tag {tone}\">{a['statut']}</span></span></li>")
    return f"<h2>Ce qu'il faut faire</h2><ol class=\"todo-top\">{''.join(items)}</ol>"


def _notes(items, global_reasons, shared_reason):
    """Notes d'une carte, dites une fois : statut, rejeu de l'agent, chiffres manquants propres."""
    out, e = [], html.escape
    proofs = [c for c in items if c.get("preuve_agent")]
    for c in proofs:
        p = c["preuve_agent"]
        how = {"llm": "règles extraites par IA", "offline": "règles extraites sans IA"}.get(p.get("methode"), "")
        where = f" Workflow : {nom_workflow(c['app_id'])}." if len(items) > 1 else ""
        out.append(f"Rejoué par l'agent auditeur : {p['verdict'].upper()}, {p['accord_pct']:g} % d'accord"
                   + (f" ({how})." if how else ".") + where)
    if len(proofs) < len(items) and not all(c["prouve"] for c in items):
        out.append("Constat statistique, pas encore vérifié par rejeu.")
    own = sorted({r for c in items for r in c["raisons_manquantes"]
                  if r not in global_reasons and not r.startswith(shared_reason)})
    if own:
        out.append("Chiffre manquant : " + "; ".join(own) + ".")
    return "".join(f'<p class="note">{e(x)}</p>' for x in out)


def groupe_html(g, alternatives, global_reasons, shared_reason):
    """Une carte par problème : tableau des workflows (5 premiers, le reste replié), « Que faire » une fois."""
    e = html.escape
    rows, metric = g["workflows"], g["metrique"]
    more = (f"<details><summary>{len(rows) - TOP_TABLE} autre{'s' if len(rows) - TOP_TABLE > 1 else ''} "
            f"workflow{'s' if len(rows) - TOP_TABLE > 1 else ''}</summary>{_table(rows[TOP_TABLE:], metric)}</details>"
            if len(rows) > TOP_TABLE else "")
    n = len(rows)
    phrase = f"<p>{e(g['constats'][0]['phrase'])}</p>" if len(g["constats"]) == 1 else ""
    alt = "".join(alternatives(c) for c in g["constats"] if c.get("alternatives"))
    return f"""<div class="card"><div class="head"><h3>{e(g['titre'])}</h3>
<span class="note">{n} workflow{'s' if n > 1 else ''} · {_pct(g['part'])} du coût</span></div>
{phrase}{_table(rows[:TOP_TABLE], metric)}{more}
<p class="todo"><b>Que faire :</b> {_txt(g['action'].removeprefix('Quoi changer : '))}</p>
{alt}{_notes(g['constats'], global_reasons, shared_reason)}</div>"""


def workflows_html(rows):
    """« Par workflow » : une ligne par workflow, barre de part du coût et problèmes en étiquettes."""
    if len(rows) < 3:
        return ""

    def line(r):
        tags = "".join(f'<span class="tag warn">{html.escape(p)}</span>' for p in r["problemes"]) \
            or '<span class="tag ok">Rien à signaler</span>'
        extra = f" <span class=\"note\">(+{r['dossiers'] - 1} dossiers liés)</span>" if r["dossiers"] > 1 else ""
        return (f"<tr><td>{html.escape(r['nom'])}{extra}</td><td class=\"n\">{_bar(r['part'])}{_pct(r['part'])}</td>"
                f"<td class=\"n\">{r['appels']}</td><td class=\"n\">{usd(r['cout'])}</td><td>{tags}</td></tr>")

    head = ("<tr><th>Workflow</th><th class=\"n\">Part du coût</th><th class=\"n\">Appels</th>"
            "<th class=\"n\">Coût</th><th>Problèmes</th></tr>")
    rest = rows[TOP_WORKFLOWS:]
    more = (f"<details><summary>{len(rest)} autre{'s' if len(rest) > 1 else ''} workflow{'s' if len(rest) > 1 else ''}"
            f"</summary><table>{head}{''.join(map(line, rest))}</table></details>" if rest else "")
    return (f"<h2>Par workflow</h2><table>{head}{''.join(map(line, rows[:TOP_WORKFLOWS]))}</table>{more}")


def sans_resultat_html(report):
    """Une ligne : les vérifications qui n'ont rien trouvé sur cette source, et pourquoi."""
    found = {c["titre"] for c in report["constats"]}
    if report.get("souverainete"):
        found.add("Des données qui partent hors d'Europe")
    silent = [v for v in report["verifications"] if v not in found]
    if not silent or not report["constats"]:
        return ""
    d = report.get("diagnostic") or {}
    hidden = [n for n, seen in (("le prompt système", d.get("systeme_visible", True)),
                                ("la liste des outils", d.get("outils_visibles", True))) if not seen]
    plural = len(hidden) > 1
    why = (f"{' et '.join(hidden)} {'ne sont pas écrits' if plural else 'n’est pas écrit'} dans les journaux de cette "
           "source, ou les seuils de volume ne sont pas atteints" if hidden
           else "seuils de volume ou de répétition non atteints")
    return (f'<h2>Vérifications sans résultat sur cette source</h2><p class="note">{len(silent)} vérification'
            f"{'s' if len(silent) > 1 else ''} sans résultat : {html.escape(why)}.</p>"
            f"<details><summary>Lesquelles</summary><ul class=\"note\">"
            f"{''.join(f'<li>{html.escape(v)}</li>' for v in silent)}</ul></details>")


def _cmp(label, before, after, fmt):
    """Deux barres avant / après à la même échelle."""
    if before is None or after is None or not before:
        return ""
    ratio = max(0.0, min(1.0, after / before))
    return (f'<div class="cmp"><span class="lab">{label}</span>{_bar(1.0)}<span class="val">{fmt(before)}</span> '
            f'→ {_bar(ratio, good=True)}<span class="val"><b>{fmt(after)}</b></span></div>')


def gains_barres(rows):
    """Optimisations prouvées : coût, latence et précision, avant → après (mêmes chiffres que le tableau)."""
    out = []
    for r in rows:
        bars = _cmp("Coût", r["cout"]["avant"], r["cout"]["apres"], usd)
        bars += _cmp("Latence", r["latence"]["avant"], r["latence"]["apres"], ms)
        if r.get("precision") is not None:
            bars += (f'<div class="cmp"><span class="lab">Précision</span>{_bar(r["precision"] / 100, good=True)}'
                     f'<span class="val"><b>{r["precision"]:g} %</b> d\'accord avec les anciennes réponses</span></div>')
        out.append(f"<h3>{html.escape(r['app_id'] or '')} : {html.escape(r['changement'] or '')}</h3>{bars}")
    return f'<div class="hero">{"".join(out)}</div>' if out else ""


def console(report):
    """Résumé de la console : une ligne par action (au plus trois), jamais une ligne par constat."""
    v = vue(report)
    n = len(report["constats"])
    if not n:
        return ["0 constat."]
    wf = {w["nom"] for g in v["groupes"] for w in g["workflows"]}
    out = [f"{n} constat{'s' if n > 1 else ''} : {len(v['groupes'])} type{'s' if len(v['groupes']) > 1 else ''} de "
           f"problème sur {len(wf)} workflow{'s' if len(wf) > 1 else ''}. À faire, par part du coût :"]
    for i, a in enumerate(v["actions"], 1):
        where = ", ".join(a["workflows"]) + (f" (+{a['nb_workflows'] - len(a['workflows'])})"
                                             if a["nb_workflows"] > len(a["workflows"]) else "")
        part = f"{a['part'] * 100:.0f} % du coût, " if a["part"] is not None else ""
        out.append(f"  {i}. {a['action'].replace('`', '')} [{part}{a['statut']}] : {where}")
    return out
