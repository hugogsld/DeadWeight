import json, os, sys, urllib.error, urllib.request
U = os.environ.get("N8N_URL", "http://localhost:5678").rstrip("/")
K = os.environ["N8N_API_KEY"]; OAI = os.environ["OPENAI_API_KEY"]
H = {"X-N8N-API-KEY": K, "Content-Type": "application/json"}

def call(method, path, body=None):
    req = urllib.request.Request(f"{U}/api/v1{path}",
        data=json.dumps(body).encode() if body is not None else None,
        headers=H, method=method)
    try:
        with urllib.request.urlopen(req) as r:
            t = r.read().decode()
            return json.loads(t) if t else {}
    except urllib.error.HTTPError as e:
        print(f"  {method} {path} -> HTTP {e.code}: {e.read().decode()[:300]}"); raise

wid = sys.argv[1] if len(sys.argv) > 1 else json.load(open("fixtures/finding.json"))["workflow_id"]
cred = call("POST", "/credentials", {"name": "Deadweight OpenAI", "type": "openAiApi", "data": {"apiKey": OAI}})
cid = cred["id"]; print("credential creee:", cid)
wf = call("GET", f"/workflows/{wid}")
n = 0
for node in wf["nodes"]:
    if node["type"].endswith("lmChatOpenAi") or node["type"].endswith(".openAi"):
        node["credentials"] = {"openAiApi": {"id": cid, "name": "Deadweight OpenAI"}}; n += 1
print(f"attachee a {n} noeud(s)")
call("PUT", f"/workflows/{wid}", {"name": wf["name"], "nodes": wf["nodes"],
     "connections": wf["connections"], "settings": wf.get("settings", {})})
call("POST", f"/workflows/{wid}/activate")
print(f"PUBLIE -> {U}/workflow/{wid}")
