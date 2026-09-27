"""Reconnaître les nœuds n8n qui appellent un modèle de langage."""
from __future__ import annotations

LANGCHAIN = "@n8n/n8n-nodes-langchain."

# nœuds qui appellent un fournisseur eux-mêmes, sans sous-nœud modèle
DIRECT = {
    "n8n-nodes-base.openAi",
    LANGCHAIN + "openAi",
    LANGCHAIN + "anthropic",
    LANGCHAIN + "googleGemini",
    LANGCHAIN + "mistralAi",
    LANGCHAIN + "ollama",
    "n8n-nodes-base.perplexity",
}

# nœuds d'IA qui ne produisent pas de texte par un modèle de langage (OCR de documents…)
NOT_TEXT_NODES = {"n8n-nodes-base.mistralAi"}


def is_model_node(node: dict) -> bool:
    """Sous-nœud « Chat Model » branché en ai_languageModel (lmChatOpenAi, lmChatAnthropic...)."""
    t = node.get("type", "")
    return t.startswith(LANGCHAIN) and t[len(LANGCHAIN):].startswith("lm")


# ressources des nœuds directs qui ne sont pas du texte (image, audio, vidéo…) : pas un appel de LLM
NON_TEXT = {"image", "audio", "video", "file", "moderation", "edit"}


def is_llm_node(node: dict) -> bool:
    """Un nœud dont l'exécution produit un appel LLM facturé."""
    if is_model_node(node):
        return True
    if node.get("type") not in DIRECT:
        return False
    return (node.get("parameters") or {}).get("resource") not in NON_TEXT


def llm_nodes(workflow: dict) -> list[dict]:
    return [n for n in workflow.get("nodes", []) if is_llm_node(n) and not n.get("disabled")]
