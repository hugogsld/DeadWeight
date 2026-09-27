"""Sortie structurée par outil : la ramener à une réponse JSON ordinaire avant les règles.

n8n (agent + « Structured Output Parser ») ne demande pas de JSON au modèle : il lui donne
un seul outil, format_final_json_response, et le modèle « répond » en l'appelant. Ce n'est
pas un agent qui agit, c'est une mise en forme. Sans ce dépliage, les règles qui écartent
les appels à outils (modèle surdimensionné, appel par élément, IA juge...) ne voient aucun
de ces appels : sur le workflow n8n 12382, 171 appels gpt-4o, 0 constat.

Déplié : request.tools vide, response.content = le JSON rendu, response.tool_calls vide.
Un appel qui propose d'autres outils, ou qui en appelle un autre, reste tel quel.
"""
import copy
import json

FORMAT_TOOLS = frozenset({"format_final_json_response"})  # n8n (LangChain), agent v2+


def _format_only(tools):
    return bool(tools) and all(t.get("name") in FORMAT_TOOLS for t in tools)


def unwrap(event):
    """L'événement, déplié si sa seule « action » est de rendre la réponse structurée."""
    request, response = event.get("request") or {}, event.get("response") or {}
    if not _format_only(request.get("tools")):
        return event
    calls = response.get("tool_calls") or []
    if any(c.get("name") not in FORMAT_TOOLS for c in calls) or len(calls) > 1:
        return event
    out = copy.deepcopy(event)
    out["request"]["tools"] = []
    if calls:
        try:
            args = json.loads(calls[0].get("arguments") or "")
        except (TypeError, ValueError):
            return event
        if isinstance(args, dict) and set(args) == {"output"}:
            args = args["output"]
        out["response"]["content"] = json.dumps(args, ensure_ascii=False)
        out["response"]["tool_calls"] = []
        if out["response"].get("finish_reason") == "tool_calls":
            out["response"]["finish_reason"] = "stop"
    return out


def unwrap_all(events):
    return [unwrap(e) for e in events]
