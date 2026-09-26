"""B1.1 : vérification de l'instance et récupération de l'historique, contre un faux n8n local."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

from importers.n8n.__main__ import main
from importers.n8n.api import N8nClient, N8nError
from importers.n8n.check import check, render, verdict
from importers.n8n.fetch import fetch, load_done

KEY = "n8n-api-NE-DOIT-JAMAIS-SORTIR"

AGENT_WF = {
    "id": "wf1", "name": "Tri des tickets", "active": True, "settings": {},
    "nodes": [
        {"name": "Webhook", "type": "n8n-nodes-base.webhook"},
        {"name": "AI Agent", "type": "@n8n/n8n-nodes-langchain.agent"},
        {"name": "OpenAI Chat Model", "type": "@n8n/n8n-nodes-langchain.lmChatOpenAi",
         "parameters": {"model": {"value": "gpt-4o"}}},
    ],
    "connections": {"OpenAI Chat Model": {"ai_languageModel": [[{"node": "AI Agent", "type": "ai_languageModel"}]]}},
}
QUIET_WF = {"id": "wf2", "name": "Sauvegarde", "active": False, "settings": {"saveDataSuccessExecution": "none"},
            "nodes": [{"name": "Chat", "type": "@n8n/n8n-nodes-langchain.lmChatAnthropic"}], "connections": {}}
PLAIN_WF = {"id": "wf3", "name": "Sans IA", "active": True, "nodes": [{"name": "Cron", "type": "n8n-nodes-base.cron"}]}


def _executions(n):
    # l'API renvoie les plus récentes d'abord
    return [{"id": str(1000 - i), "workflowId": "wf1", "status": "error" if i % 10 == 9 else "success",
             "startedAt": f"2026-09-{25 - i // 5:02d}T10:{i % 60:02d}:00.000Z"} for i in range(n)]


class FakeN8n:
    """Imite /api/v1 : clé obligatoire, pagination par curseur, includeData."""

    def __init__(self, workflows, executions, page=4):
        self.workflows = {w["id"]: w for w in workflows}
        self.executions = executions
        self.page = page
        self.detail_calls = []
        self.fail_once = set()

    def handle(self, path, q, key):
        if key != KEY:
            return 401, {"message": "unauthorized"}
        if path == "/api/v1/workflows":
            return 200, self._page(list(self.workflows.values()), q)
        if path.startswith("/api/v1/workflows/"):
            wf = self.workflows.get(path.rsplit("/", 1)[1])
            return (200, wf) if wf else (404, {"message": "not found"})
        if path == "/api/v1/executions":
            assert q.get("includeData") in (None, "false"), "la liste doit rester légère"
            rows = [e for e in self.executions if e["workflowId"] == q.get("workflowId", e["workflowId"])]
            return 200, self._page(rows, q)
        if path.startswith("/api/v1/executions/"):
            ex_id = path.rsplit("/", 1)[1]
            if ex_id in self.fail_once:
                self.fail_once.discard(ex_id)
                return 503, {"message": "busy"}
            self.detail_calls.append(ex_id)
            assert q.get("includeData") == "true"
            ex = next(e for e in self.executions if e["id"] == ex_id)
            return 200, {**ex, "data": {"resultData": {"runData": {"AI Agent": [{"executionTime": 12}]}}}}
        return 404, {"message": "no route"}

    def _page(self, rows, q):
        limit = min(int(q.get("limit", 100)), self.page)
        start = int(q.get("cursor", 0))
        nxt = start + limit
        return {"data": rows[start:nxt], "nextCursor": str(nxt) if nxt < len(rows) else None}


@pytest.fixture
def n8n():
    fake = FakeN8n([AGENT_WF, QUIET_WF, PLAIN_WF], _executions(11))

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            code, body = fake.handle(u.path, q, self.headers.get("X-N8N-API-KEY"))
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    fake.url = f"http://127.0.0.1:{srv.server_address[1]}"
    yield fake
    srv.shutdown()


def client(fake, key=KEY):
    return N8nClient(fake.url, key, timeout=5, retries=1)


# --- étape 1 : check ---

def test_check_classe_les_workflows(n8n):
    res = {r["id"]: r for r in check(client(n8n))}
    assert res["wf1"]["llm_nodes"] == ["OpenAI Chat Model"]
    assert res["wf1"]["executions"] == {"success": 10, "error": 1}
    assert res["wf1"]["oldest"].startswith("2026-09-23") and res["wf1"]["newest"].startswith("2026-09-25")
    assert verdict(res["wf1"]).startswith("OK")
    assert verdict(res["wf2"]).startswith("PROBLÈME")
    assert verdict(res["wf3"]) == "pas d'appel LLM, rien à importer"
    text = render(list(res.values()))
    assert "Tri des tickets" in text and "2026-09-23 → 2026-09-25" in text


def test_seulement_des_echecs_alerte():
    r = {"llm_nodes": ["x"], "save_success": "défaut instance", "executions": {"error": 3}}
    assert verdict(r).startswith("ATTENTION")


def test_mauvaise_cle_message_clair(n8n):
    with pytest.raises(N8nError, match="401"):
        check(client(n8n, key="mauvaise"))


def test_instance_injoignable():
    with pytest.raises(N8nError, match="injoignable"):
        N8nClient("http://127.0.0.1:9", KEY, timeout=1, retries=0).workflow("x")


def test_parametres_manquants():
    with pytest.raises(N8nError, match="N8N_API_KEY"):
        N8nClient("http://x", "")
    with pytest.raises(N8nError, match="N8N_URL"):
        N8nClient("", KEY)


# --- B1.1 : fetch ---

def test_fetch_ecrit_workflow_et_executions(n8n, tmp_path):
    res = fetch(client(n8n), "wf1", tmp_path, log=lambda *_: None)
    assert res["fetched"] == 11 and res["total"] == 11
    wf = json.loads((tmp_path / "wf1/workflow.json").read_text())
    assert wf["name"] == "Tri des tickets"
    lines = (tmp_path / "wf1/executions.jsonl").read_text().splitlines()
    assert [json.loads(line)["id"] for line in lines] == [str(1000 - i) for i in range(11)]
    assert "runData" in json.loads(lines[0])["data"]["resultData"]


def test_fetch_limite_et_date(n8n, tmp_path):
    assert fetch(client(n8n), "wf1", tmp_path / "a", limit=3, log=lambda *_: None)["fetched"] == 3
    # 2026-09-25 : les 5 plus récentes
    assert fetch(client(n8n), "wf1", tmp_path / "b", since="2026-09-25", log=lambda *_: None)["fetched"] == 5


def test_fetch_reprend_sans_retelecharger(n8n, tmp_path):
    fetch(client(n8n), "wf1", tmp_path, limit=4, log=lambda *_: None)
    n8n.detail_calls.clear()
    res = fetch(client(n8n), "wf1", tmp_path, log=lambda *_: None)
    assert res["fetched"] == 7 and res["total"] == 11
    assert len(n8n.detail_calls) == 7


def test_fetch_ligne_tronquee_reparee(n8n, tmp_path):
    fetch(client(n8n), "wf1", tmp_path, limit=2, log=lambda *_: None)
    path = tmp_path / "wf1/executions.jsonl"
    with path.open("a") as f:
        f.write('{"id": "998", "data": {"resu')  # coupure pendant l'écriture
    assert load_done(path) == {"1000", "999"}
    res = fetch(client(n8n), "wf1", tmp_path, log=lambda *_: None)
    ids = [json.loads(line)["id"] for line in path.read_text().splitlines()]
    assert res["total"] == 11 and len(ids) == len(set(ids)) == 11


def test_fetch_reessaie_une_erreur_passagere(n8n, tmp_path):
    n8n.fail_once.add("1000")
    assert fetch(client(n8n), "wf1", tmp_path, limit=1, log=lambda *_: None)["fetched"] == 1


def test_la_cle_n_est_jamais_ecrite(n8n, tmp_path):
    fetch(client(n8n), "wf1", tmp_path, log=lambda *_: None)
    for p in (tmp_path / "wf1").iterdir():
        assert KEY not in p.read_text()


def test_commande(n8n, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("N8N_API_KEY", KEY)
    monkeypatch.setenv("N8N_URL", n8n.url)
    assert main(["check"]) == 0
    assert "Tri des tickets" in capsys.readouterr().out
    assert main(["fetch", "--workflow", "wf1", "--out", str(tmp_path), "--limit", "2"]) == 0
    assert len((tmp_path / "wf1/executions.jsonl").read_text().splitlines()) == 2
    assert main(["fetch", "--workflow", "inconnu", "--out", str(tmp_path)]) == 1
    assert "404" in capsys.readouterr().err
