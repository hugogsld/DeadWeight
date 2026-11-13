"""Regroupe les constats pour qu'un rapport reste lisible à n'importe quel volume.

Un constat existe par (application, modèle, règle) : sur 55 dossiers, la même phrase revenait 52 fois.
Ici on ne change ni les constats ni les chiffres, seulement la vue : une entrée par problème (règle), une
ligne par workflow touché, et au plus trois actions classées par part du coût mesuré.

Un « workflow » est le nom de l'application sans le préfixe de l'outil (``claude-code:``). Les sous-agents
(``/sous-agent``) et les dossiers dont le nom prolonge celui d'un autre (``deadweight-fusion`` sous
``deadweight``) sont rangés sous le parent.
"""
from collections import defaultdict

SEPARATEURS = ("-", "_", "/", " ")
NOM_MIN_PARENT = 4  # un parent trop court (« a », « ai ») avalerait des dossiers sans rapport
TOP_ACTIONS = 3

# libellé court d'un problème, pour les étiquettes de la vue par workflow
COURT = {
    "context_reread": "contexte relu", "tool_bloat": "outils inutiles", "harness_overhead": "cadre lourd",
    "oversized_model": "modèle trop gros", "excess_reasoning": "trop de raisonnement",
    "duplicate_calls": "appels en double", "unbounded_loop": "boucle", "no_cache": "pas de cache",
    "raw_context": "historique brut", "verbose_output": "réponses longues", "paid_errors": "échecs payés",
}

# métrique propre à une règle : (libellé de colonne, valeur lue dans la preuve du constat)
METRIQUES = {
    "context_reread": ("jetons relus / appel", lambda ev: f"{ev['median_context_tokens']:,.0f}".replace(",", " ")),
    "tool_bloat": ("outils inutilisés", lambda ev: f"{ev['unused_tool_share'] * 100:.0f} %"),
}


def nom_workflow(app_id):
    """Nom lisible : sans préfixe d'outil ni suffixe de sous-agent."""
    name = (app_id or "").split(":", 1)[-1]
    return name.removesuffix("/sous-agent")


def _parent(name, others):
    """Le plus long autre nom dont celui-ci est un prolongement (``parent-xxx``), sinon lui-même."""
    low = name.lower()
    best = None
    for o in others:
        ol = o.lower()
        if o != name and len(o) >= NOM_MIN_PARENT and low.startswith(ol) and low[len(ol):][:1] in SEPARATEURS:
            if best is None or len(o) > len(best):
                best = o
    return best or name


def parents(app_ids):
    """{app_id: nom du workflow regroupé}. Résolu en un seul tour : un parent n'est jamais lui-même rangé."""
    names = {nom_workflow(a) for a in app_ids}
    roots = {n for n in names if _parent(n, names) == n}
    return {a: _parent(nom_workflow(a), roots) for a in app_ids}


def _cout(n):
    """Coût mensuel projeté, sinon coût observé (fenêtre courte)."""
    return n["cout_mensuel_usd"] if n["cout_mensuel_usd"] is not None else n.get("cout_observe_usd")


def _ligne(items, regle, total):
    """Une ligne de tableau : les constats d'un même workflow regroupé, additionnés ; latence et métrique
    viennent du constat qui porte le plus d'appels."""
    main = max(items, key=lambda c: c["chiffres"]["nb_appels"])
    cout = sum(_cout(c["chiffres"]) or 0 for c in items)
    label, fmt = METRIQUES.get(regle, (None, None))
    ev = main.get("evidence") or {}
    try:
        metrique = fmt(ev) if fmt else None
    except (KeyError, TypeError):
        metrique = None
    return {"nom": items[0]["workflow"], "appels": sum(c["chiffres"]["nb_appels"] for c in items), "cout": cout,
            "part": cout / total if total else None, "p50": main["chiffres"]["latence_mediane_ms"],
            "p95": main["chiffres"]["latence_p95_ms"], "metrique": metrique,
            "economie": sum((c.get("evidence") or {}).get("est_saving_month_usd") or 0 for c in items)}


def groupes(constats, total, tous_les_ids=None):
    """Un groupe par règle, workflows triés par coût décroissant. ``total`` : coût de tout le rapport.
    Les groupes sont triés par coût décroissant (des constats sans coût chiffré à la fin)."""
    mapping = parents(tous_les_ids or {c["app_id"] for c in constats})
    par_regle = defaultdict(list)
    for c in constats:
        par_regle[c.get("regle") or c["titre"]].append({**c, "workflow": mapping[c["app_id"]]})
    out = []
    for regle, items in par_regle.items():
        par_wf = defaultdict(list)
        for c in items:
            par_wf[c["workflow"]].append(c)
        lignes = sorted((_ligne(v, regle, total) for v in par_wf.values()), key=lambda r: -r["cout"])
        out.append({"regle": regle, "titre": items[0]["titre"], "action": items[0]["action"],
                    "prouve": all(c["prouve"] for c in items), "constats": items, "workflows": lignes,
                    "cout": sum(r["cout"] for r in lignes), "part": sum(r["cout"] for r in lignes) / total if total else None,
                    "economie": sum(r["economie"] for r in lignes),
                    "metrique": METRIQUES.get(regle, (None,))[0]
                    if any(r["metrique"] for r in lignes) else None})
    return sorted(out, key=lambda g: -g["cout"])


def action_courte(texte):
    """L'action sans le préfixe « Quoi changer : » ni la phrase « Effet : … » (dite à part)."""
    return texte.removeprefix("Quoi changer : ").split(" Effet :")[0].strip()


def actions(grps, n=TOP_ACTIONS):
    """Au plus ``n`` actions, classées par part du coût mesuré : [{action, workflows, nb_workflows, part,
    economie, statut}]. Un conseil « rien à changer » (cache déjà géré par l'outil) n'est pas une action."""
    grps = [g for g in grps if not action_courte(g["action"]).lower().startswith("rien ")]
    return [{"action": action_courte(g["action"]), "titre": g["titre"], "workflows": [w["nom"] for w in g["workflows"][:3]],
             "nb_workflows": len(g["workflows"]), "part": g["part"], "economie": g["economie"],
             "statut": "prouvé" if g["prouve"] else "statistique"} for g in grps[:n]]


def par_workflow(applications, grps, total):
    """Une ligne par workflow regroupé : coût, part, problèmes (libellés courts), triée par coût."""
    mapping = parents([a["app_id"] for a in applications])
    cout, appels, dossiers = defaultdict(float), defaultdict(int), defaultdict(int)
    for a in applications:
        nom = mapping[a["app_id"]]
        cout[nom] += _cout(a["chiffres"]) or 0
        appels[nom] += a["chiffres"]["nb_appels"]
        dossiers[nom] += 1
    problemes = defaultdict(list)
    for g in grps:
        for w in g["workflows"]:
            problemes[w["nom"]].append(COURT.get(g["regle"], g["titre"]))
    rows = [{"nom": n, "appels": appels[n], "cout": cout[n], "part": cout[n] / total if total else None,
             "dossiers": dossiers[n], "problemes": problemes.get(n, [])} for n in cout]
    return sorted(rows, key=lambda r: -r["cout"])
