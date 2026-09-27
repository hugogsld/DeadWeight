"""Rapport d'audit d'une page (D4.1).

    python -m report.audit <events.jsonl> [-o out/audit.html]

Lance toutes les regles presentes dans rules/, chiffre chaque constat avec
report/cost.py, et ecrit une page HTML autonome lisible sans explication :
constats tries par cout mensuel decroissant, puis ce qu'on n'a PAS signale.
"""
import argparse
import html
import importlib
import json
import pkgutil
from datetime import datetime
from pathlib import Path

import rules
from catalog.recommend import recommend
from report.cost import MIN_WINDOW_SECONDS, MONTH_SECONDS, chiffrer, runs, window_seconds

# En dessous d'une heure de trafic, projeter sur un mois multiplie du bruit :
# 36 appels en 0,3 s donnaient 315 220 $/mois. On affiche alors le coût réellement dépensé.


def _partial(events, c):
    """Si des appels ne sont pas chiffrables, chiffre les autres plutôt que rien.
    ``part_chiffree`` dit quelle part des appels réussis le chiffre couvre."""
    ids = {e["event_id"] for e in events}
    unpriced = {m.split(": ", 1)[0] for m in c["manquants"]} & ids
    succeeded = [e for e in events if e["error"] is None]
    priced = [e for e in succeeded if e["event_id"] not in unpriced]
    if not unpriced or not priced:
        return c
    p = chiffrer(priced)
    if p["cout_mensuel_usd"] is None:
        return c
    return {**c, "cout_mensuel_usd": p["cout_mensuel_usd"], "part_chiffree": len(priced) / len(succeeded)}


def _figures(events, window=None):
    """chiffrer(), partiel plutôt que rien. ``window`` : période d'observation de tout le rapport, la même
    pour chaque constat (sinon une application active une heure sur sept jours serait projetée comme si
    elle tournait sans arrêt, et la somme des constats dépasserait le total). Sous une journée observée :
    coût réellement dépensé et coût par passage, jamais de projection mensuelle."""
    c = chiffrer(events)
    if c["cout_mensuel_usd"] is None and events:
        c = _partial(events, c)
    if c["cout_mensuel_usd"] is None:
        return c
    own = window_seconds(events)
    observed = c["cout_mensuel_usd"] * own / MONTH_SECONDS
    ref = max(window or own, own)
    if ref >= MIN_WINDOW_SECONDS:
        return {**c, "cout_mensuel_usd": observed * MONTH_SECONDS / ref}
    n = runs(events)
    # pas de « : » dans la raison, _missing_reasons coupe dessus
    reason = (f"moins d'une journée de trafic observée ({_duration(ref)}, {n} passage{'s' if n > 1 else ''}), "
              "projection sur un mois non fiable, laissez tourner la passerelle au moins une journée")
    return {**c, "cout_mensuel_usd": None, "cout_observe_usd": observed, "passages": n,
            "cout_par_passage_usd": observed / n if n else None, "manquants": [*c["manquants"], reason]}


def _duration(seconds):
    if seconds < 3600:
        return f"{max(seconds / 60, 0.1):.1f} min"
    return f"{seconds / 3600:.1f} h"


# Texte humain par regle : aucun code de regle ne doit apparaitre dans la page.
RULE_TEXT = {
    'harness_overhead': ('Un cadre d’exécution lourd pour des tâches répétitives',
        'Tester un appel direct avec des instructions minimales ; activer le cache et contrôler la qualité.'),
    'mergeable_steps': ('Une réponse retravaillée par un deuxième appel',
        'Tester une consigne qui produit directement la forme finale et comparer la qualité.'),
    'per_item_calls': ('Un appel séparé pour chaque élément',
        'Tester un appel groupé ou un traitement par lots, puis vérifier la qualité.'),
    'parallelizable_steps': ('Des étapes indépendantes attendent leur tour',
        'Confirmer les dépendances puis tester une exécution parallèle.'),
    "llm_judge": ("Une deuxième IA relit presque chaque réponse",
                  "Tester une relecture par échantillon ou par règle, en vérifiant la qualité conservée."),
    "image_heavy": ("Des images très coûteuses pour une réponse simple",
                    "Tester une résolution plus basse et vérifier que la réponse reste aussi fiable."),
    "batch_eligible": ("Des tâches régulières pourraient attendre",
                       "Confirmer le délai acceptable puis tester une API de traitement par lots à tarif réduit."),
    "tool_bloat": ("Des descriptions d’outils renvoyées inutilement",
                   "Ne passer que les outils utiles à l’étape et raccourcir leurs descriptions."),
    "low_entropy_output": ("Une IA qui répond toujours la même chose",
                           "Remplacer par quelques règles fixes, avec l'IA en secours pour les cas imprévus."),
    "oversized_model": ("Un modèle haut de gamme pour une tâche simple",
                        "Tester un modèle plus petit sur ces appels ; l'économie reste à démontrer par rejeu."),
    "raw_context": ("Tout l'historique renvoyé à chaque message",
                    "Ne renvoyer que la partie utile du contexte (résumé ou fenêtre glissante)."),
    "no_cache": ("Les mêmes demandes payées plusieurs fois",
                 "Mettre en cache les réponses ou activer le cache de prompt du fournisseur."),
    "unbounded_loop": ("Un agent qui tourne en rond",
                       "Fixer un nombre maximal d'étapes et une condition d'arrêt explicite."),
    "agent_where_chain": ("Un agent qui suit toujours le même chemin",
                          "Remplacer l'agent par une chaîne d'étapes fixe."),
    "excess_reasoning": ("Un modèle qui réfléchit longtemps pour une réponse triviale",
                        "Réduire l'effort de raisonnement demandé, à vérifier par rejeu."),
    "duplicate_calls": ("La même question payée plusieurs fois, mot pour mot",
                       "Mettre en cache la réponse plutôt que de rappeler le modèle."),
    "paid_errors": ("Des échecs facturés puis payés une seconde fois en relance",
                    "Corriger la cause de l'échec (limite de longueur, filtre) avant de relancer."),
    "verbose_output": ("Des réponses bien plus longues que nécessaire",
                       "Poser un plafond de longueur raisonnable, à vérifier par rejeu."),
    "data_outside_eu": ("Des données qui partent hors d'Europe",
                        "Passer par la région UE du fournisseur, ou tester un modèle européen au banc."),
    "context_reread": ("Chaque appel relit (presque) toute la conversation",
                       "Raccourcir les sessions ou activer une compaction, alléger le contexte de démarrage, "
                       "et partager un même préfixe entre agents pour que le cache serve à tous."),
}
DEFAULT_TEXT = ("Usage à examiner", "Examiner ces appels avec l'équipe concernée.")


def _discover_detectors():
    """Toute regle ajoutee dans rules/ avec une fonction detect() entre dans le rapport."""
    found = []
    for mod in pkgutil.iter_modules(rules.__path__):
        detect = getattr(importlib.import_module(f"rules.{mod.name}"), "detect", None)
        if callable(detect):
            found.append((mod.name, detect))
    return found


def _check_title(module_name):
    code = next((c for c in RULE_TEXT if c.startswith(module_name)), None)
    return RULE_TEXT[code][0] if code else module_name.replace("_", " ")


def _missing_reasons(manquants):
    """Raisons dedupliquees, sans l'identifiant d'evenement."""
    return sorted({m.split(": ", 1)[-1] for m in manquants})


def load_banc(directory):
    """Résultats de python -m bench m2 (banc-*.json), par finding_id. Dossier absent : rien."""
    results = {}
    for path in sorted(Path(directory).glob("banc-*.json")) if directory and Path(directory).is_dir() else []:
        result = json.loads(path.read_text(encoding="utf-8"))
        results[result["finding_id"]] = result
    return results


def build_report(events, detectors=None, banc=None):
    """detectors : liste de (nom, detect). Par defaut, toutes les regles de rules/.
    banc : {finding_id: résultat de bench.m2.prove} ; les options M2 testées portent leur verdict."""
    events = list(events)
    by_id = {e["event_id"]: e for e in events}
    detectors = detectors if detectors is not None else _discover_detectors()
    findings = []
    for _, detect in detectors:
        findings.extend(detect(events))

    # Levier 16 : la conformité a sa propre section, elle ne se mélange pas aux gaspillages
    souverainete = [f for f in findings if f["rule"] == "data_outside_eu"]
    findings = [f for f in findings if f["rule"] != "data_outside_eu"]
    souverainete.sort(key=lambda f: -f["evidence"]["calls"])

    period = window_seconds(events)  # une seule période d'observation pour tout le rapport
    constats = []
    for f in findings:
        evts = [by_id[i] for i in f["event_ids"] if i in by_id]
        chiffres = _figures(evts, period)
        titre, action = RULE_TEXT.get(f["rule"], DEFAULT_TEXT)
        # M2 : alternatives hors famille, seulement là où R2 a jugé la tâche simple
        alternatives = recommend(evts)["options"] if f["rule"] == "oversized_model" and evts else None
        tested = ((banc or {}).get(f["finding_id"]) or {}).get("options", {})
        if alternatives and tested:
            alternatives = {k: ({**o, "banc": tested[k]} if o and k in tested and tested[k]["model"] == o["modele"]
                                else o) for k, o in alternatives.items()}
        constats.append({
            "finding_id": f["finding_id"], "app_id": f["app_id"], "model": f["model"], "titre": titre, "phrase": f["title"],
            "action": action, "prouve": f.get("proven", False), "gravite": f.get("severity"),
            "chiffres": chiffres, "raisons_manquantes": _missing_reasons(chiffres["manquants"]),
            "alternatives": alternatives,
        })
    constats.sort(key=lambda c: (_cost(c["chiffres"]) is None, -(_cost(c["chiffres"]) or 0)))

    flagged = {c["app_id"] for c in constats}
    apps = sorted({e["app_id"] for e in events})
    clean = [{"app_id": a, "chiffres": _figures([e for e in events if e["app_id"] == a], period)}
             for a in apps if a not in flagged]

    starts = sorted(e["ts_start"] for e in events)
    global_figures = _figures(events, period) if events else None
    return {
        "verifications": [_check_title(name) for name, _ in detectors],
        "raisons_globales": _missing_reasons(global_figures["manquants"]) if global_figures else [],
        "resume": {"nb_appels": len(events), "nb_applications": len(apps),
                   "debut": starts[0] if starts else None, "fin": starts[-1] if starts else None,
                   "global": global_figures},
        "constats": constats,
        "rien_a_signaler": clean,
        "souverainete": souverainete,
    }


# ---------- rendu ----------

def _cost(n):
    """Coût mensuel projeté, sinon coût observé (fenêtre courte)."""
    return n["cout_mensuel_usd"] if n["cout_mensuel_usd"] is not None else n.get("cout_observe_usd")


def _cost_label(n, monthly="Coût mensuel"):
    label, value = ((monthly, n["cout_mensuel_usd"]) if n.get("cout_observe_usd") is None
                    else ("Coût observé", n["cout_observe_usd"]))
    if n.get("part_chiffree") is not None and value is not None:
        label += f" (partiel, {round(n['part_chiffree'] * 100)} % des appels)"
    if n.get("cout_par_passage_usd") is not None and n.get("passages", 0) > 1:
        label += f" ({n['passages']} passages, {_usd(n['cout_par_passage_usd'])} par passage)"
    return label, value


def _usd(v):
    if v is None:
        return "non disponible"
    if v >= 10:
        return f"{v:,.0f} $".replace(",", " ")
    # sous un centime, « 0.00 $ » cacherait l'ordre de grandeur : deux chiffres significatifs
    return f"{v:.2f} $" if v >= 0.01 or v == 0 else f"{v:.2g} $"


def _ms(v):
    return "non disponible" if v is None else f"{v / 1000:.1f} s" if v >= 1000 else f"{v:.0f} ms"


def _day(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).strftime("%d/%m/%Y") if ts else "—"


CSS = """
:root{--ink:#16181d;--mute:#5d6470;--line:#e3e5e9;--bg:#fff;--warn:#b4441c;--ok:#1f7a4d}
@media (prefers-color-scheme:dark){:root{--ink:#eceef1;--mute:#9aa1ad;--line:#2c3038;--bg:#121418}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.5 -apple-system,Segoe UI,Helvetica,Arial,sans-serif}
main{max-width:860px;margin:0 auto;padding:32px 16px}
h1{font-size:24px;margin:0 0 4px}h2{font-size:17px;margin:28px 0 8px}
.sub{color:var(--mute);margin:0 0 20px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;margin:0 0 8px}
.kpi{border:1px solid var(--line);border-radius:8px;padding:10px 12px}
.kpi b{display:block;font-size:20px}.kpi span{color:var(--mute);font-size:13px}
.card{border:1px solid var(--line);border-left:4px solid var(--warn);border-radius:8px;padding:14px 16px;margin:10px 0}
.card h3{margin:0;font-size:16px}.card .app{color:var(--mute);font-size:13px}
.card p{margin:6px 0}.nums{display:flex;flex-wrap:wrap;gap:6px 18px;font-size:14px;margin:8px 0}
.nums b{font-variant-numeric:tabular-nums}.todo{font-size:14px}.note{color:var(--mute);font-size:13px}
table{width:100%;border-collapse:collapse;font-size:14px}td,th{text-align:left;padding:6px 4px;border-bottom:1px solid var(--line)}
th{color:var(--mute);font-weight:500}.clean td:first-child{color:var(--ok)}
@media print{main{padding:0}.card{break-inside:avoid}}
"""


ALT_LABELS = {"moins_cher": "moins cher", "meilleur_compromis": "même éditeur", "souverain": "souverain"}


def _alternatives(options):
    """M2 : une ligne par modèle et par route, options identiques regroupées."""
    by_route = {}
    for key, o in (options or {}).items():
        if o:
            by_route.setdefault((o["modele"], o["hebergeur"]), (o, []))[1].append(ALT_LABELS[key])
    if not by_route:
        return ""
    ue = {True: "traitement UE possible", "sous_conditions": "traitement UE sous conditions",
          False: "pas de traitement UE en direct"}
    items = []
    for (name, host), (o, labels) in by_route.items():
        where = (f"via {host}, {ue.get(o['hebergement_ue'], 'hébergement UE non vérifié')}" if host
                 else "au prix du moins cher des hébergeurs, hébergement non garanti")
        measured = (o.get("banc") or {}).get("facteur_mesure")
        monthly = o["cout_mensuel_usd"]
        if measured:  # le banc a mesuré les vrais jetons (réflexion comprise) : ce sont ces chiffres qui comptent
            monthly = (o["cout_mensuel_usd"] + o["economie_usd"]) / measured  # coût actuel ÷ facteur mesuré
            factor = f", ×{measured} moins cher mesuré au banc (estimation ×{o['facteur']})"
        else:
            factor = f", ×{o['facteur']} moins cher" if o["facteur"] else ""
        caveat = (" <i>Modèle à raisonnement : jetons de réflexion non comptés, coût sous-estimé.</i>"
                  if o["raisonnement"] and not o.get("banc") else "")
        items.append(f"<li>{html.escape(' et '.join(labels))} : <b>{html.escape(name)}</b> "
                     f"({html.escape(o['pays'] or '?')}, {html.escape(where)}) — "
                     f"{_usd(monthly)} par mois{factor}.{caveat}{_bench_verdict(o.get('banc'))}</li>")
    tested = all(o.get("banc") for o, _ in by_route.values())
    quality = ("qualité mesurée au banc sur votre trafic" if tested
               else "qualité non prouvée : à tester au banc avant de changer")
    return (f'<p class="todo"><b>Autres modèles compatibles</b> (capacités vérifiées, {quality}) :</p>'
            f'<ul>{"".join(items)}</ul>')


def _bench_verdict(b):
    """M2.2 : le verdict du banc sur cette option, tel que mesuré."""
    if not b:
        return ""
    if b["verdict"] == "not_tested" or b["score"] is None:
        return " <i>Banc : non testé.</i>"
    measure = (f"accord de {b['score'] * 100:.0f} %" if b.get("task_type", "classification") == "classification"
               else f"recouvrement de {b['score']:.2f} (indicatif)")
    tail = "validé" if b["verdict"] == "pass" else "refusé" + (f" ({b['reasons'][0]})" if b["reasons"] else "")
    return f" <b>Banc : {measure} sur {b['n_calls']} requêtes réelles, {html.escape(tail)}.</b>"


def _sovereignty(findings):
    """Levier 16 : où partent les données, et les pistes européennes."""
    if not findings:
        return ""
    e, rows = html.escape, []
    for f in findings:
        ev = f["evidence"]
        status = "hors UE" if ev["traitement_ue"] is False else "UE non garantie"
        where = f"{ev['hote']} ({ev['pays']})" if ev["pays"] else ev["hote"]
        if ev["certitude"] == "deduite":
            where += " *"
        pistes = []
        if ev["meme_modele_en_ue"]:
            pistes.append(f"même modèle : {ev['meme_modele_en_ue']}")
        alt = ev["alternative_europeenne"]
        pistes.append(f"européen : {alt['modele']} via {alt['hebergeur']} ({_usd(alt['cout_mensuel_usd'])} par mois)"
                      if alt else "européen : à choisir au banc")
        rows.append(f"<tr><td>{e(f['app_id'])}</td><td>{e(f['model'])}</td><td>{e(where)}</td>"
                    f"<td>{e(status)}</td><td>{ev['calls']}</td><td>{e(' ; '.join(pistes))}</td></tr>")
    deduced = any(f["evidence"]["certitude"] == "deduite" for f in findings)
    return f"""<h2>Où partent vos données</h2>
<p class="note">Appels traités hors d'Europe, ou sans garantie de l'être en Europe, et les pistes pour y rester.
Aucune piste n'est prouvée : un modèle européen se teste au banc avant de changer.</p>
<table><tr><th>Application</th><th>Modèle</th><th>Destination</th><th>Traitement</th><th>Appels</th><th>Pistes</th></tr>
{"".join(rows)}</table>
{'<p class="note">* Destination déduite du format d’appel : le trafic n’est pas passé par la passerelle.</p>' if deduced else ''}"""


def _card(c):
    n, e = c["chiffres"], html.escape
    notes = []
    proof = c.get("preuve_agent")
    if proof:
        how = {"llm": "règles extraites par IA", "offline": "règles extraites sans IA"}.get(proof.get("methode"), "")
        notes.append(f"Rejoué par l'agent auditeur : {proof['verdict'].upper()}, {proof['accord_pct']:g} % d'accord"
                     + (f" ({how})." if how else "."))
    elif not c["prouve"]:
        notes.append("Constat statistique, pas encore vérifié par rejeu.")
    if c["raisons_manquantes"]:
        notes.append("Chiffre manquant : " + "; ".join(c["raisons_manquantes"]) + ".")
    return f"""<div class="card"><h3>{e(c['titre'])}</h3>
<div class="app">Application {e(c['app_id'])} · modèle {e(c['model'])}</div>
<p>{e(c['phrase'])}</p>
<div class="nums"><span>{_cost_label(n)[0]} <b>{_usd(_cost_label(n)[1])}</b></span>
<span>Latence médiane <b>{_ms(n['latence_mediane_ms'])}</b></span>
<span>Latence p95 <b>{_ms(n['latence_p95_ms'])}</b></span>
<span>Appels <b>{n['nb_appels']}</b></span></div>
<p class="todo"><b>Que faire :</b> {e(c['action'])}</p>
{_alternatives(c.get('alternatives'))}
{''.join(f'<p class="note">{e(x)}</p>' for x in notes)}</div>"""


TOOL_TEXT = {"vue_ensemble": "a regardé l'ensemble du trafic", "lancer_regles": "a lancé les vérifications",
             "detail_constat": "a examiné un constat", "prouver": "a rejoué des règles fixes sur l'historique",
             "publier_plan": "a publié son plan"}


def _step_text(step):
    """Le texte d'une étape ; le nombre de vérifications vient du résultat, jamais d'un chiffre figé."""
    text = TOOL_TEXT.get(step["outil"], step["outil"])
    n = (step.get("resultat") or {}).get("nb_verifications")
    return text.replace("les vérifications", f"les {n} vérifications") if n else text


def _agent_section(agent):
    """A1.4 : plan d'action de l'agent, puis comment il a mené l'audit."""
    if not agent:
        return ""
    e = html.escape
    if not agent.get("plan"):
        return (f'<h2>Plan d\'action</h2><p class="note">L\'agent auditeur n\'a pas conclu '
                f'({e(agent.get("statut", ""))}) : les constats ci-dessous restent valables.</p>')
    plan = agent["plan"]
    actions = "".join(
        f"<li><b>{e(a['action'])}</b> <span class=\"note\">[{e(a.get('statut', 'piste à vérifier'))}]</span>"
        f"<br><span class=\"note\">{e(a['justification'])}</span></li>"
        for a in sorted(plan["actions"], key=lambda a: a["priorite"]))
    steps = "".join(
        f"<li>L'agent {e(_step_text(j))}"
        + (f" — <i>{e(j['pensee'])}</i>" if j.get("pensee") else "")
        + (f" (verdict : {e(j['resultat']['verdict'])}, accord {e(str(j['resultat']['accord_pct']))} %)"
           if j["outil"] == "prouver" and "verdict" in j["resultat"] else "")
        + "</li>" for j in agent["journal"])
    cost = agent.get("cout_audit_usd")
    meta = (f"{agent['appels_modele']} appels au modèle {e(agent.get('modele') or '')}"
            + (f", coût de l'audit {cost:.4f} $" if cost is not None else ""))
    return f"""<h2>Plan d'action</h2>
<p>{e(plan['resume'])}</p><ol class="todo">{actions}</ol>
<details><summary>Comment l'agent a mené l'audit</summary><ol class="note">{steps}</ol>
<p class="note">{meta}. Tous les chiffres viennent des vérifications et du rejeu, pas du modèle.</p></details>"""


def render_html(report):
    r, e = report["resume"], html.escape
    if not r["nb_appels"]:
        body = "<p>Aucun appel capturé pour l'instant : laissez tourner le trafic puis relancez le rapport.</p>"
    else:
        g = r["global"]
        partial = g.get("part_chiffree") is not None or g.get("cout_observe_usd") is not None
        missing = (f'<p class="note">{"Coût à lire avec prudence" if partial else "Coût total non disponible"} : '
                   f'{e("; ".join(report["raisons_globales"]))}.</p>' if report["raisons_globales"] else "")
        checks = e(", ".join(report["verifications"])) or "aucune"
        cards = "".join(_card(c) for c in report["constats"]) or "<p>Aucun gaspillage détecté.</p>"
        rows = "".join(
            f"<tr><td>{e(a['app_id'])}</td><td>{a['chiffres']['nb_appels']}</td>"
            f"<td>{_usd(_cost(a['chiffres']))}</td></tr>" for a in report["rien_a_signaler"])
        body = f"""<div class="kpis">
<div class="kpi"><b>{r['nb_appels']}</b><span>appels observés</span></div>
<div class="kpi"><b>{r['nb_applications']}</b><span>applications</span></div>
<div class="kpi"><b>{_usd(_cost_label(g)[1])}</b><span>{_cost_label(g, "Coût mensuel total")[0].replace("Coût observé", "Coût observé total").lower()}</span></div>
<div class="kpi"><b>{len(report['constats'])}</b><span>constats</span></div></div>
{missing}
<p class="note">Vérifications effectuées : {checks}.</p>
{_agent_section(report.get("agent"))}
<h2>Constats, du plus coûteux au moins coûteux</h2>{cards}
{_sovereignty(report.get("souverainete"))}
<h2>Rien à signaler</h2>
<p class="note">Ces applications ne déclenchent aucune des vérifications ci-dessus.</p>
<table class="clean"><tr><th>Application</th><th>Appels</th><th>Coût mensuel</th></tr>{rows}</table>"""
    return f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Audit Deadweight</title><style>{CSS}</style></head><body><main>
<h1>Audit des appels d'IA</h1>
<p class="sub">Période observée : du {_day(r['debut'])} au {_day(r['fin'])}. Coûts projetés sur 30 jours au volume observé, en dollars, à partir des prix publics des modèles.</p>
{body}
<p class="note">Aucune donnée n'a quitté votre infrastructure pour produire ce rapport.</p>
</main></body></html>
"""


def main():
    ap = argparse.ArgumentParser(description="Rapport d'audit d'une page")
    ap.add_argument("events", help="fichier .jsonl d'evenements")
    ap.add_argument("-o", "--out", default="out/audit.html")
    ap.add_argument("--banc", help="dossier des résultats de python -m bench m2 (banc-*.json)")
    args = ap.parse_args()
    lines = Path(args.events).read_text(encoding="utf-8").splitlines()
    report = build_report((json.loads(line) for line in lines if line.strip()), banc=load_banc(args.banc))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_html(report), encoding="utf-8")
    print(f"{len(report['constats'])} constat(s), rapport ecrit dans {out}")


if __name__ == "__main__":
    main()
