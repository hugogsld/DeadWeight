"""Zéro constat : dire pourquoi, ce qui reste invisible dans cette source, la suite, et ce qui est déjà utile.

Un rapport vide sans explication ressemble à une panne. Les chiffres viennent des événements (volume,
cache, coût), jamais d'une supposition ; le seuil de volume est celui des règles de fréquence.
"""
from collections import Counter, defaultdict

from report.billing import spent_usd
from report.cost import source_kind
from rules.context_reread import _context_cost_share, _context_tokens
from rules.low_entropy import MIN_CALLS, template_of

AGENT_CODE = ("claude-code", "codex")


def _plural(n, word):
    return f"{n} {word}{'s' if n > 1 else ''}"


def _cache_pct(events):
    """Part du contexte envoyé qui vient du cache, ou None si le cache n'est pas rapporté."""
    cached = context = 0
    for e in events:
        ctx, hit = _context_tokens(e), e["usage"].get("cached_input_tokens")
        if ctx and hit is not None and e.get("error") is None:
            cached, context = cached + hit, context + ctx
    return round(cached / context * 100) if context else None


def diagnostic(events):
    """Faits mesurés sur les événements : volume, ce qui est visible, cache, coût, contexte."""
    events = list(events)
    groups = Counter((e["app_id"], e["model"], template_of(e)) for e in events)
    sessions = {e["trace"]["id"] for e in events if e["trace"]["id"]}
    spent = spent_usd(events)
    by_session = defaultdict(list)
    for e in events:
        if e["trace"]["id"]:
            by_session[e["trace"]["id"]].append(e)
    share, _ = _context_cost_share(events) if events else (None, None)
    return {
        "nb_appels": len(events), "nb_sessions": len(sessions),
        "max_par_tache": max(groups.values(), default=0), "minimum": MIN_CALLS,
        "systeme_visible": any(e["request"].get("system") for e in events),
        "outils_visibles": any(e["request"].get("tools") for e in events),
        "source": source_kind(events),
        "agent_code": any((e["app_id"] or "").split(":", 1)[0] in AGENT_CODE for e in events),
        "cache_pct": _cache_pct(events), "cout_observe_usd": spent,
        "cout_par_session_usd": spent / len(sessions) if spent is not None and sessions else None,
        "part_contexte_pct": round(share * 100) if share is not None else None,
    }


def lignes(d):
    """Pourquoi rien : trois phrases (volume, invisible, suite)."""
    out = [f"Volume : {_plural(d['nb_appels'], 'appel')} lus ({_plural(d['nb_sessions'], 'session')}) ; la tâche la plus "
           f"répétée en compte {d['max_par_tache']}. Les règles de fréquence demandent {d['minimum']} appels par tâche "
           "(DW_MIN_CALLS l'abaisse pour une démonstration)."]
    hidden = [name for name, seen in (("le prompt système", d["systeme_visible"]),
                                      ("la liste des outils", d["outils_visibles"])) if not seen]
    if hidden:
        out.append(f"Invisible dans cette source : {' et '.join(hidden)} (non écrits dans les journaux) ; "
                   "les règles qui s'appuient dessus (tâches répétitives, outils inutiles, cache de prompt) "
                   "ne peuvent pas se déclencher.")
    if d["agent_code"]:
        out.append("Pour atteindre le volume : lancez l'audit sur l'ensemble de vos projets "
                   "(`make audit-complet SOURCE=~/.claude/projects ALL=1`, soit `--all-projects`). "
                   "La section Facturation du rapport dit si ces dollars sont payés ou une valeur équivalente API.")
    elif d["source"] == "n8n":
        out.append("Pour atteindre le volume : attendez davantage d'exécutions du workflow, puis relancez l'audit.")
    else:
        out.append("Pour atteindre le volume : laissez tourner la passerelle plus longtemps, puis relancez l'audit.")
    return out


def utile(d):
    """Ce que cette source montre déjà, constat ou pas."""
    out = []
    if d["cout_observe_usd"] is not None:
        per = d["cout_par_session_usd"]
        out.append(f"Coût observé : {d['cout_observe_usd']:.2f} $ (équivalent API)"
                   + (f", {per:.2f} $ par session en moyenne" if per is not None else ""))
    if d["cache_pct"] is not None:
        out.append(f"Cache : {d['cache_pct']} % du contexte envoyé est relu depuis le cache")
    if d["part_contexte_pct"] is not None:
        out.append(f"Contexte relu (entrée + cache) : {d['part_contexte_pct']} % du coût, le reste est la sortie")
    return out
