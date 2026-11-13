"""Conseils selon la source. Pour des journaux Claude Code, on ne propose que ce que l'utilisateur peut
faire dans Claude Code (commandes et réglages vérifiés dans code.claude.com/docs/en/costs, 13/11/2026) ;
pour une passerelle ou un workflow, les changements de code (SDK) restent valables.

Chaque conseil dit quoi faire, où, et l'effet attendu."""

CLAUDE_CODE = {
    "context_reread": (
        "Quoi changer : `/clear` entre deux tâches sans rapport, `/compact <ce qu'il faut garder>` avant de "
        "continuer une longue session, et une section « Compact instructions » dans CLAUDE.md. Effet : moins de "
        "jetons de conversation relus à chaque appel."),
    "harness_overhead": (
        "Quoi changer : garder CLAUDE.md sous 200 lignes et déplacer les consignes de workflow dans des skills "
        "(chargés à la demande). Effet : un contexte de démarrage plus court sur chaque appel."),
    "tool_bloat": (
        "Quoi changer : `/context` pour voir ce qui occupe l'espace, puis `/mcp` pour désactiver les serveurs "
        "inutilisés. Effet : moins d'outils listés dans le contexte."),
    "oversized_model": (
        "Quoi changer : `/model` (ou `/config` pour le défaut) sur Sonnet pour la plupart des tâches, Opus pour "
        "les cas complexes ; `model: haiku` dans la configuration d'un sous-agent simple. Effet : prix par jeton "
        "plus bas sur les tâches courantes."),
    "excess_reasoning": (
        "Quoi changer : `/effort` (ou `/model`) pour baisser l'effort de raisonnement sur les tâches simples. "
        "Effet : moins de jetons de réflexion facturés en sortie."),
    "duplicate_calls": (
        "Quoi changer : donner la cible précise (fichier, fonction) plutôt qu'une consigne large, et filtrer les "
        "grosses sorties de commandes avec un hook PreToolUse. Effet : moins de lectures et de relances répétées."),
    "unbounded_loop": (
        "Quoi changer : Échap pour interrompre, `/rewind` pour revenir à un point sain, mode plan (Maj+Tab) avant "
        "une tâche longue. Effet : moins de boucles qui tournent en rond."),
    "no_cache": (
        "Quoi changer : rien dans le code, Claude Code gère déjà le cache de prompt ; évitez ce qui l'invalide "
        "(changer les outils MCP en cours de session, longue pause). `/usage` montre la ligne « Prompt cache ». "
        "Effet : plus de jetons relus au tarif du cache."),
}
# types de propositions (optimize.propose) -> règle dont le conseil s'applique
TYPE_TO_RULE = {"cache_prompt": "no_cache", "modele": "oversized_model", "raisonnement": "excess_reasoning"}


def conseil_logs(rule):
    """Conseil Claude Code pour une règle, ou None si aucun n'est vérifié."""
    return CLAUDE_CODE.get(rule)


def conseil_proposition(proposal, kind):
    """« Quoi changer » d'une proposition pour des journaux Claude Code, sinon None (l'appelant garde alors
    la version SDK, ou rien : plafond, règles et lots n'ont pas d'équivalent dans Claude Code)."""
    return conseil_logs(TYPE_TO_RULE.get(proposal.get("type"))) if kind == "logs" else None


# constats sans levier rejouable : (pourquoi, ce qui les rendrait testables)
NON_REJOUABLE = {
    "context_reread": ("la relecture du contexte vient de la longueur des sessions, pas d'un appel remplaçable",
                       "rejouer les mêmes sessions avec un contexte compacté, ce que l'audit ne fait pas : "
                       "appliquez le changement puis comparez avec la période suivante"),
}
NON_REJOUABLE_DEFAULT = ("aucun levier automatique n'existe pour cette règle",
                         "un levier rejouable (règles, cache, plafond, modèle plus petit) pour cette règle")
