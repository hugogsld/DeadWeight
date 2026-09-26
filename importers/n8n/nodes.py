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
}


def is_model_node(node: dict) -> bool:
    """Sous-nœud « Chat Model » branché en ai_languageModel (lmChatOpenAi, lmChatAnthropic...)."""
    t = node.get("type", "")
    return t.startswith(LANGCHAIN) and t[len(LANGCHAIN):].startswith("lm")


def is_llm_node(node: dict) -> bool:
    """Un nœud dont l'exécution produit un appel LLM facturé."""
    return is_model_node(node) or node.get("type") in DIRECT


def llm_nodes(workflow: dict) -> list[dict]:
    return [n for n in workflow.get("nodes", []) if is_llm_node(n) and not n.get("disabled")]
