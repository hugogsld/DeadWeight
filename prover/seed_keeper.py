"""Workflow dont le noeud LLM fait un VRAI travail (resumer) -> entropie haute -> KEEP."""
import json, os, urllib.request
U = os.environ.get("N8N_URL", "http://localhost:5678").rstrip("/")
H = {"X-N8N-API-KEY": os.environ["N8N_API_KEY"], "Content-Type": "application/json"}
PATH = os.environ.get("DW_KEEPER_PATH", "summarize-ticket")

def call(m, p, b=None):
    r = urllib.request.Request(f"{U}/api/v1{p}",
        data=json.dumps(b).encode() if b is not None else None, headers=H, method=m)
    with urllib.request.urlopen(r) as x:
        t = x.read().decode(); return json.loads(t) if t else {}

cred = None
model_params = {"model": {"__rl": True, "mode": "list", "value": "gpt-4o-mini",
                          "cachedResultName": "gpt-4o-mini"}, "options": {}}
for w in call("GET", "/workflows?limit=100")["data"]:
    full = call("GET", f"/workflows/{w['id']}")
    for n in full["nodes"]:
        if n["type"].endswith("lmChatOpenAi") and n.get("credentials", {}).get("openAiApi"):
            cred = n["credentials"]
            if isinstance(n["parameters"].get("model"), dict): model_params = n["parameters"]
            break
    if cred: break
print("credential reprise" if cred else "AUCUNE credential - a rattacher a la main")

WF = {"name": "Ticket summariser", "nodes": [
  {"parameters": {"httpMethod": "POST", "path": PATH, "options": {}},
   "id": "c0000000-0000-4000-8000-000000000001", "name": "Webhook",
   "type": "n8n-nodes-base.webhook", "typeVersion": 2, "position": [0, 0],
   "webhookId": "c0000000-0000-4000-8000-000000000001"},
  {"parameters": {"promptType": "define",
    "text": "=Resume ce ticket client en une phrase, en reprenant les details concrets qu'il contient.\n\n{{ $json.body.text }}"},
   "id": "c0000000-0000-4000-8000-000000000002", "name": "Summarise ticket",
   "type": "@n8n/n8n-nodes-langchain.chainLlm", "typeVersion": 1.4, "position": [240, 0]},
  {"parameters": model_params, "id": "c0000000-0000-4000-8000-000000000003",
   "name": "OpenAI Chat Model", "type": "@n8n/n8n-nodes-langchain.lmChatOpenAi",
   "typeVersion": 1.2, "position": [200, 220], **({"credentials": cred} if cred else {})},
  {"parameters": {"options": {}}, "id": "c0000000-0000-4000-8000-000000000004",
   "name": "Store summary", "type": "n8n-nodes-base.set", "typeVersion": 3.4,
   "position": [520, 0]}],
 "connections": {
   "Webhook": {"main": [[{"node": "Summarise ticket", "type": "main", "index": 0}]]},
   "Summarise ticket": {"main": [[{"node": "Store summary", "type": "main", "index": 0}]]},
   "OpenAI Chat Model": {"ai_languageModel": [[{"node": "Summarise ticket", "type": "ai_languageModel", "index": 0}]]}},
 "settings": {"executionOrder": "v1"}}

new = call("POST", "/workflows", WF)
print(f"\ncree: {new['id']}   {U}/workflow/{new['id']}")
try:
    call("POST", f"/workflows/{new['id']}/activate"); print("publie")
except Exception: print("a publier a la main")
print(f"\n-> DW_WEBHOOK_PATH={PATH} python3 prover/seed_executions.py 60")
