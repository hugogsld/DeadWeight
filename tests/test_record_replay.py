"""D0.2 : le mecanisme d'enregistrement / rejeu fonctionne et ne fuite aucune cle."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import httpx
import pytest
import vcr

from conftest import SECRET_HEADERS, scrub_response

CASSETTE = Path(__file__).parent / "cassettes" / "test_openai_chat_replay.yaml"


class _Fake(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.dumps({"ok": True}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("openai-organization", "org-secret")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def test_cassette_never_contains_keys(tmp_path):
    server = HTTPServer(("127.0.0.1", 0), _Fake)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}/v1/chat?key=AIza-secret"
    path = tmp_path / "c.yaml"
    recorder = vcr.VCR(filter_headers=SECRET_HEADERS, filter_query_parameters=["key"],
                       before_record_response=scrub_response)
    with recorder.use_cassette(str(path)):
        r = httpx.post(url, json={"q": 1}, headers={"Authorization": "Bearer sk-secret",
                                                     "x-api-key": "sk-ant-secret",
                                                     "x-goog-api-key": "AIza-secret"})
    server.shutdown()
    assert r.json() == {"ok": True}
    text = path.read_text()
    assert "/v1/chat" in text  # l'appel a bien ete enregistre
    for secret in ("sk-secret", "sk-ant-secret", "AIza-secret", "org-secret"):
        assert secret not in text


@pytest.mark.vcr
def test_openai_chat_replay():
    if not CASSETTE.exists():
        pytest.skip("cassette absente : lancer `make record` avec OPENAI_API_KEY dans .env.local")
    from openai import OpenAI

    r = OpenAI().chat.completions.create(model="gpt-4o-mini", max_tokens=5,
                                         messages=[{"role": "user", "content": "Reponds juste: ok"}])
    assert r.choices[0].message.content
    assert "sk-" not in CASSETTE.read_text()
