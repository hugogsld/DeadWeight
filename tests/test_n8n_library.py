"""Bibliothèque publique n8n : récupération (fausse API) et mesure de couverture."""
import json

import pytest

from importers.n8n import library
from importers.n8n.convert import PROVIDERS, _short, model_of
from importers.n8n.nodes import is_llm_node


def _wf(wid, nodes):
    return {"workflow": {"id": wid, "name": f"wf {wid}", "totalViews": 1000 - wid, "description": "long texte",
                         "image": [{"url": "x"}], "categories": [{"id": 1, "name": "AI"}],
                         "workflow": {"nodes": nodes, "connections": {}, "pinData": {"Webhook": [{"email": "a@b.fr"}]}}}}


LC = "@n8n/n8n-nodes-langchain."
LIBRARY = {
    1: _wf(1, [{"type": LC + "agent"}, {"type": LC + "lmChatOpenAi", "typeVersion": 1.2,
                                        "parameters": {"model": {"__rl": True, "value": "gpt-4o-mini"}}},
               {"type": LC + "memoryBufferWindow"}, {"type": LC + "toolSerpApi"}]),
    2: _wf(2, [{"type": LC + "lmChatGoogleGemini", "typeVersion": 1, "parameters": {}},          # défaut n8n
               {"type": LC + "openAi", "typeVersion": 1.8, "parameters": {"resource": "image"}}]),  # pas du texte
    3: _wf(3, [{"type": LC + "lmChatAnthropic", "typeVersion": 1.3,
                "parameters": {"model": {"value": "={{ $json.model }}"}}},                          # formule
               {"type": LC + "lmChatAwsBedrock", "typeVersion": 1, "parameters": {"model": "anthropic.claude-3"}},
               {"type": "n8n-nodes-base.perplexity", "parameters": {}},                              # défaut n8n
               {"type": "n8n-nodes-deepseek.deepSeekChat", "parameters": {}},                        # IA non reconnue
               {"type": "n8n-nodes-base.mistralAi", "parameters": {"binaryProperty": "data"}},       # OCR
               {"type": LC + "chat"}, {"type": LC + "modelSelector"}]),                              # pas des appels
    4: None,  # retiré de la bibliothèque (404)
}


def fake_get(calls):
    def get(url):
        calls.append(url)
        if "/search?" in url:
            page = int(url.split("page=")[1].split("&")[0])
            ids = sorted(LIBRARY) if page == 1 else []
            return {"totalWorkflows": 4, "workflows": [{"id": i} for i in ids]}
        return LIBRARY[int(url.rsplit("/", 1)[1])]
    return get


def test_fetch_garde_l_utile_et_reprend(tmp_path):
    calls = []
    res = library.fetch(tmp_path, limit=10, rate=0, get=fake_get(calls), log=lambda *_: None)
    assert (res["fetched"], res["gone"], res["total"]) == (3, 1, 3)
    assert any("sort=views:desc" in c and "category=AI" in c for c in calls)
    saved = json.loads((tmp_path / "1.json").read_text())
    assert set(saved) == {"id", "name", "totalViews", "categories", "createdAt", "nodes", "connections"}
    assert saved["categories"] == ["AI"]
    assert "a@b.fr" not in (tmp_path / "1.json").read_text()  # pinData (données d'exemple) jamais gardé
    calls.clear()
    again = library.fetch(tmp_path, limit=10, rate=0, get=fake_get(calls), log=lambda *_: None)
    assert again["fetched"] == 0 and not [c for c in calls if "/workflows/1" in c]


def test_fetch_respecte_la_limite(tmp_path):
    assert library.fetch(tmp_path, limit=2, rate=0, get=fake_get([]), log=lambda *_: None)["total"] == 2


def test_couverture(tmp_path):
    library.fetch(tmp_path, limit=10, rate=0, get=fake_get([]), log=lambda *_: None)
    (tmp_path / "coverage.json").write_text("{}")  # le résultat précédent n'est pas un workflow
    r = library.coverage(tmp_path)
    assert (r["workflows"], r["workflows_avec_llm"], r["noeuds_llm"]) == (3, 3, 5)
    assert r["modele_lu"] == 0.4  # gpt-4o-mini et anthropic.claude-3
    assert (r["modele_par_defaut_n8n"], r["modele_en_formule"], r["modele_introuvable"]) == (2, 1, 0)
    assert r["fournisseurs_inconnus"] == {"lmChatAwsBedrock": 1}
    assert r["noeuds_ia_non_reconnus"] == {"n8n-nodes-deepseek.deepSeekChat": 1}
    assert r["ia_non_texte"] == {"openAi : image": 1, "n8n-nodes-base.mistralAi : document (OCR)": 1}
    text = library.render(r)
    assert "laissé(s) au défaut de n8n" in text and "lmChatAwsBedrock" in text


def test_image_et_audio_ne_sont_pas_des_appels_llm():
    assert not is_llm_node({"type": LC + "openAi", "parameters": {"resource": "audio", "operation": "transcribe"}})
    assert not is_llm_node({"type": "n8n-nodes-base.openAi", "parameters": {"resource": "image"}})
    assert is_llm_node({"type": LC + "openAi", "parameters": {"modelId": {"value": "gpt-4o"}}})
    assert is_llm_node({"type": "n8n-nodes-base.openAi", "parameters": {"resource": "chat"}})


# Formes du réglage de modèle relevées sur les 1 000 workflows IA les plus consultés de n8n.io
# (26 formes distinctes, type × version × champ). Seule la forme est reprise, pas les workflows.
SHAPES = [
    ("googleGemini", 1, {"modelId": {"__rl": True, "mode": "list", "value": "models/gemma-3-27b-it"}}, "gemma-3-27b-it"),
    ("lmChatAnthropic", 1.2, {"model": "claude-3-5-sonnet-20241022"}, "claude-3-5-sonnet-20241022"),
    ("lmChatAnthropic", 1.3, {"model": {"__rl": True, "mode": "list", "value": "claude-3-5-haiku-20241022"}},
     "claude-3-5-haiku-20241022"),
    ("lmChatAzureOpenAi", 1, {"model": "gpt-4o-mini"}, "gpt-4o-mini"),
    ("lmChatDeepSeek", 1, {"model": "deepseek-reasoner"}, "deepseek-reasoner"),
    ("lmChatGoogleGemini", 1, {"modelName": "models/gemini-2.0-pro-exp"}, "gemini-2.0-pro-exp"),
    ("lmChatGroq", 1, {"model": "llama-3.1-70b-versatile"}, "llama-3.1-70b-versatile"),
    ("lmChatMistralCloud", 1, {"model": "pixtral-large-latest"}, "pixtral-large-latest"),
    ("lmChatOllama", 1, {"model": "deepseek-r1:14b"}, "deepseek-r1:14b"),
    ("lmChatOpenAi", 1, {"model": "gpt-4o-mini-2024-07-18"}, "gpt-4o-mini-2024-07-18"),
    ("lmChatOpenAi", 1.1, {"model": "gpt-4.1-nano"}, "gpt-4.1-nano"),
    ("lmChatOpenAi", 1.2, {"model": {"__rl": True, "mode": "list", "value": "gpt-4o-mini"}}, "gpt-4o-mini"),
    ("lmChatOpenAi", 1.3, {"model": {"__rl": True, "mode": "list", "value": "gpt-5.1"}}, "gpt-5.1"),
    ("lmChatOpenRouter", 1, {"model": "anthropic/claude-3.5-sonnet"}, "anthropic/claude-3.5-sonnet"),
    ("lmOllama", 1, {"model": "llama3.2-16000:latest"}, "llama3.2-16000:latest"),
    ("lmOpenAi", 1, {"model": {"__rl": True, "mode": "list", "value": "gpt-3.5-turbo-1106"}}, "gpt-3.5-turbo-1106"),
    ("lmOpenHuggingFaceInference", 1, {"model": "mistralai/Mistral-7B-Instruct-v0.1"}, "mistralai/Mistral-7B-Instruct-v0.1"),
    ("n8n-nodes-base.openAi", 1, {"model": "gpt-4o-mini"}, "gpt-4o-mini"),
    ("n8n-nodes-base.perplexity", 1, {"model": "sonar-pro"}, "sonar-pro"),
] + [("openAi", v, {"modelId": {"__rl": True, "mode": "list", "value": "gpt-4o-mini"}}, "gpt-4o-mini")
     for v in (1, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8)]


@pytest.mark.parametrize("short,version,params,expected", SHAPES)
def test_formes_reelles_du_reglage_de_modele(short, version, params, expected):
    node_type = short if "." in short else LC + short
    node = {"type": node_type, "typeVersion": version, "parameters": params}
    assert is_llm_node(node)
    assert _short(node_type) in PROVIDERS
    assert model_of(node, {}) == expected


def test_modele_vide_ou_absent_n_est_pas_invente():
    assert model_of({"type": LC + "openAi", "parameters": {"modelId": {"__rl": True, "value": ""}}}, {}) is None
    assert model_of({"type": LC + "lmChatOpenAi", "parameters": {}}, {}) is None
