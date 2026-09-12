"""Rend executable un template n8n importe : neutralise les noeuds a credentials,
remplace le trigger par un webhook, garde les noeuds LLM intacts."""
import json, os, sys, urllib.request

U = os.environ.get("N8N_URL", "http://localhost:5678").rstrip("/")
H = {"X-N8N-API-KEY": os.environ["N8N_API_KEY"], "Content-Type": "application/json"}

KEEP = ("n8n-nodes-base.set", "n8n-nodes-base.code", "n8n-nodes-base.if",
        "n8n-nodes-base.switch", "n8n-nodes-base.merge", "n8n-nodes-base.noOp",
        "n8n-nodes-base.filter", "n8n-nodes-base.splitOut", "n8n-nodes-base.webhook",
        "n8n-nodes-base.stickyNote")
KEEP_PREFIX = ("@n8n/n8n-nodes-langchain.",)

ADAPT_CODE = """return $input.all().map(i => {
  const b = i.json.body || {};
  const t = b.text || i.json.text || b.subject || '';
  const now = new Date().toISOString();
  return { json: {
    text: t, subject: t, body: t, snippet: t, message: t, content: t,
    input: t, query: t, chatInput: t, id: 'msg_' + Math.random().toString(36).slice(2),
    date: now, pubDate: now, isoDate: now, createdAt: now,
    link: 'https://example.com',
    headers: { subject: t, from: 'client@example.com' }
  } };
});"""


def call(method, path, body=None):
    req = urllib.request.Request(f"{U}/api/v1{path}",
        data=json.dumps(body).encode() if body is not None else None,
        headers=H, method=method)
    with urllib.request.urlopen(req) as r:
        t = r.read().decode()
        return json.loads(t) if t else {}


def keep(n):
    return n["type"] in KEEP or any(n["type"].startswith(p) for p in KEEP_PREFIX)


wid = sys.argv[1]
path = sys.argv[2] if len(sys.argv) > 2 else f"sandbox-{wid[:6].lower()}"
wf = call("GET", f"/workflows/{wid}")

nodes, replaced, trigger_done = [], [], False
for n in wf["nodes"]:
    is_trig = n["type"].lower().endswith("trigger") or n["type"].endswith(".webhook")
    if is_trig and not trigger_done:
        nodes.append({"parameters": {"httpMethod": "POST", "path": path, "options": {}},
                      "id": n["id"], "name": n["name"], "type": "n8n-nodes-base.webhook",
                      "typeVersion": 2, "position": n.get("position", [0, 0]),
                      "webhookId": n["id"]})
        trigger_done = True
        replaced.append(f"{n['name']} (trigger -> webhook)")
    elif keep(n):
        nodes.append(n)
    else:
        nodes.append({"parameters": {"mode": "raw", "jsonOutput": "={{ JSON.stringify($json) }}",
                                     "options": {}},
                      "id": n["id"], "name": n["name"], "type": "n8n-nodes-base.set",
                      "typeVersion": 3.4, "position": n.get("position", [0, 0])})
        replaced.append(f"{n['name']} ({n['type'].split('.')[-1]} -> Set)")

conns = dict(wf["connections"])
ADAPT = "DW Input"
trig = next((n for n in nodes if n["type"] == "n8n-nodes-base.webhook"), None)
if trig:
    nodes.append({"parameters": {"jsCode": ADAPT_CODE},
                  "id": "dw000000-0000-4000-8000-00000000000a", "name": ADAPT,
                  "type": "n8n-nodes-base.code", "typeVersion": 2,
                  "position": [trig["position"][0] + 180, trig["position"][1]]})
    down = conns.get(trig["name"], {}).get("main", [[]])
    conns[trig["name"]] = {"main": [[{"node": ADAPT, "type": "main", "index": 0}]]}
    conns[ADAPT] = {"main": [list(down[0]) if down else []]}
    replaced.append(f"{ADAPT} (insere apres le trigger)")

new = call("POST", "/workflows", {"name": f"{wf['name']} (sandboxed)", "nodes": nodes,
    "connections": conns, "settings": {"executionOrder": "v1"}})

llm = [n["name"] for n in nodes if n["type"].startswith("@n8n/")]
print(f"cree: {new['id']}   {U}/workflow/{new['id']}")
print(f"webhook path: {path}")
print(f"\n{len(replaced)} noeud(s) neutralises:")
for r in replaced:
    print("  -", r)
print(f"\nnoeuds LangChain conserves intacts ({len(llm)}):", llm or "AUCUN")
print(f"\n-> publie la copie, puis:")
print(f"   DW_WEBHOOK_PATH={path} python3 prover/seed_executions.py 60")
