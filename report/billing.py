"""Facturation abonnement vs API dans le rapport (D2.6). Utilisé par report.audit quand un
``comprehension.json`` de ``python -m connectors.agent_logs`` (ou un ``--billing`` explicite)
dit que Claude Code et/ou Codex tournent sur un forfait abonnement plutôt qu'une clé API.

Ce que ça change dans le rapport :
- le montant en dollars n'est plus « payé », mais une valeur consommée en équivalent API,
  clairement étiquetée comme telle ;
- aucun pourcentage d'une limite n'est inventé : ni Anthropic ni OpenAI ne publient de quota
  exact en jetons pour ces forfaits (recherche du 26/09/2026, sources ci-dessous) ; on affiche
  à la place des faits mesurés (pic d'appels sur une fenêtre de 5 heures glissante, et sur une
  semaine glissante), les deux fenêtres officiellement documentées.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from report.cost import MONTH_SECONDS, chiffrer, window_seconds

ABONNEMENT, API, INCONNU = "abonnement", "api", "inconnu"
TOOLS = ("claude-code", "codex")

PLAN_LIMITS_NOTE = {
    "claude-code": (
        "Anthropic ne publie pas de quota exact en jetons ou en messages pour les forfaits Claude "
        "Pro/Max avec Claude Code : seulement des multiplicateurs par rapport au forfait Pro (Max = "
        "×5 ou ×20), une fenêtre glissante de 5 heures et une limite hebdomadaire, partagées entre "
        "Claude et Claude Code. Sources : support.claude.com/articles/11145838, claude.com/pricing."
    ),
    "codex": (
        "OpenAI confirme une fenêtre de 5 heures et une limite hebdomadaire pour Codex et ChatGPT "
        "Work, mais ne publie pas de quota exact en jetons pour les forfaits Pro (Pro = ×5, Pro 20x = "
        "×20 du forfait Plus) ; seul le forfait Plus a une fourchette indicative de messages par "
        "modèle, variable. Sources : help.openai.com/articles/20001507, "
        "help.openai.com/articles/9793128."
    ),
}


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def peak_window(events: list[dict], window_seconds_: float) -> dict:
    """Le plus grand nombre d'appels dans une fenêtre glissante de cette durée : un fait mesuré,
    jamais une part d'une limite (aucun quota officiel à diviser)."""
    starts = sorted(_parse(e["ts_start"]) for e in events)
    if not starts:
        return {"nb_appels": 0, "debut": None, "fin": None}
    best_n, best_i, best_j, i = 0, 0, 0, 0
    for j, end in enumerate(starts):
        while (end - starts[i]).total_seconds() > window_seconds_:
            i += 1
        if j - i + 1 > best_n:
            best_n, best_i, best_j = j - i + 1, i, j
    return {"nb_appels": best_n, "debut": starts[best_i].isoformat(), "fin": starts[best_j].isoformat()}


def spent_usd(events: list[dict]):
    """Dépense réellement mesurée sur la période observée (pas de projection mensuelle)."""
    c = chiffrer(events)
    if c["cout_mensuel_usd"] is None:
        return None
    return c["cout_mensuel_usd"] * window_seconds(events) / MONTH_SECONDS


def billing_section(events: list[dict], billing_by_tool: dict) -> dict | None:
    """billing_by_tool : {"claude-code": {...}, "codex": {...}} (comprehension.json ou --billing).
    Renvoie None si aucun événement ne vient d'un outil reconnu."""
    by_tool: dict[str, list[dict]] = {}
    for e in events:
        tool = (e.get("app_id") or "").split(":", 1)[0]
        if tool in TOOLS:
            by_tool.setdefault(tool, []).append(e)
    if not by_tool:
        return None

    outils = []
    covers_all, all_subscription = True, True
    for tool, evs in by_tool.items():
        info = billing_by_tool.get(tool)
        if not info:
            covers_all = False
            outils.append({"outil": tool, "mode": INCONNU, "source": None, "nb_appels": len(evs)})
            continue
        mode = info.get("mode", INCONNU)
        if mode != ABONNEMENT:
            all_subscription = False
        entry = {"outil": tool, "mode": mode, "source": info.get("source"), "nb_appels": len(evs)}
        if mode == ABONNEMENT:
            entry["pic_5h"] = peak_window(evs, 5 * 3600)
            entry["pic_semaine"] = peak_window(evs, 7 * 24 * 3600)
            entry["limite_note"] = PLAN_LIMITS_NOTE.get(tool, "")
            entry["valeur_equivalente_usd"] = spent_usd(evs)
        outils.append(entry)

    return {"outils": outils, "tout_abonnement": covers_all and all_subscription}


def load_billing(comprehension: str | None = None, override: str | None = None) -> dict | None:
    """{outil: {mode, source}} depuis un comprehension.json de python -m connectors.agent_logs, puis
    ``--billing`` (prioritaire, décision explicite). None si ni l'un ni l'autre n'est fourni."""
    billing = {}
    if comprehension:
        data = json.loads(Path(comprehension).read_text(encoding="utf-8"))
        billing = {tool: r["billing"] for tool, r in data.items() if "billing" in r}
    if override:
        billing = {tool: {"mode": override, "source": "--billing (forcé)"} for tool in (billing or TOOLS)}
    return billing or None


def subscription_only(events: list[dict], billing_by_tool: dict | None) -> bool:
    """Vrai seulement si tous les appels d'agents de code observés passent par un abonnement : alors
    un gain en dollars est une valeur équivalente API, jamais une économie sur la facture."""
    section = billing_section(events, billing_by_tool) if billing_by_tool else None
    return bool(section and section["tout_abonnement"])
