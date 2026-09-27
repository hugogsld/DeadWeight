"""Gains globaux du workflow (étape 4 du testeur, sous le tableau par modification) : coût total sur
l'historique rejoué, avant/après les modifications retenues (prouvées, précision ≥ 95 %), et l'économie
à l'usage (coût par exécution, projection). Rien n'est estimé ici : chaque chiffre vient soit du
chiffrage global de l'historique (``report.cost.chiffrer``), soit des ``cout_usd`` déjà mesurés par
tâche dans ``propositions.json``. Une valeur non calculable reste ``None`` (affichée « — » par
l'appelant, jamais fabriquée).
"""
from report.cost import MONTH_SECONDS, chiffrer, window_seconds


def _pct_change(before, after):
    return None if not before or after is None else round((after - before) / before * 100, 1)


def global_gains(events, items, executions=None, pricing=None):
    """``items`` : les propositions déjà filtrées à l'affichage (précision ≥ seuil). Seules celles
    « pass » avec un coût mesuré avant/après comptent dans la dépense totale : une piste refusée ou
    non chiffrée ne change rien au total, elle reste une piste."""
    events = list(events)
    c = chiffrer(events, pricing)
    duree = window_seconds(events)
    avant = (c["cout_mensuel_usd"] * duree / MONTH_SECONDS) if c["cout_mensuel_usd"] is not None else None
    mesurables = [p for p in items if p["verdict"] == "pass" and (p.get("cout_usd") or {}).get("apres") is not None]
    apres = None
    if avant is not None:
        delta = sum(p["cout_usd"]["avant"] - p["cout_usd"]["apres"] for p in mesurables)
        apres = avant - delta
    par_exec_avant = avant / executions if avant is not None and executions else None
    par_exec_apres = apres / executions if apres is not None and executions else None
    return {
        "cout_avant": avant, "cout_apres": apres, "cout_pct": _pct_change(avant, apres),
        "executions": executions,
        "cout_par_execution_avant": par_exec_avant, "cout_par_execution_apres": par_exec_apres,
        "projection_1000_usd": par_exec_apres * 1000 if par_exec_apres is not None else None,
        "modifications_comptees": len(mesurables),
    }
