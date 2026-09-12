"""
LE TEST QUI DECIDE DE TA DEMO. Lance-le AVANT d'ecrire le patcher.
Il verifie que n8n accepte un workflow genere par POST /api/v1/workflows.

    export N8N_URL=http://localhost:5678
    export N8N_API_KEY=...
    python patcher/validate_reimport.py fixtures/patch.json
"""
import json, os, sys, urllib.request

N8N_URL = os.environ.get("N8N_URL", "http://localhost:5678").rstrip("/")
API_KEY = os.environ["N8N_API_KEY"]

# n8n REFUSE tout champ hors de cette liste sur POST /workflows.
# id, active, tags, versionId, createdAt -> "must NOT have additional properties"
ALLOWED = {"name", "nodes", "connections", "settings"}


def clean(wf: dict) -> dict:
    return {k: v for k, v in wf.items() if k in ALLOWED}


def post_workflow(wf: dict):
    body = json.dumps(clean(wf)).encode()
    req = urllib.request.Request(
        f"{N8N_URL}/api/v1/workflows",
        data=body,
        headers={"X-N8N-API-KEY": API_KEY, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as r:
            out = json.load(r)
            print(f"OK  workflow cree: id={out.get('id')}  name={out.get('name')}")
            print(f"    ouvre {N8N_URL}/workflow/{out.get('id')} et verifie qu'il s'affiche")
            return out
    except urllib.error.HTTPError as e:
        print(f"ECHEC  HTTP {e.code}")
        print(e.read().decode()[:1200])
        sys.exit(1)


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "fixtures/patch.json"
    patch = json.load(open(path))
    post_workflow(patch["patched_workflow"])
