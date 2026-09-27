"""Audit 100 % local : garde-fous réseau du mode Ollama. Aucun Ollama ni réseau requis."""
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from agent.audit import llm_config, local_timeout
from agent.local import LOCAL_API_KEY, LOCAL_BASE_URL, LOCAL_MODEL, LOCAL_TIMEOUT, NonLocalHostError, is_local_host, require_local

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "127.3.2.1", "::1", "[::1]", b"localhost"])
def test_loopback_hosts_are_local(host):
    assert is_local_host(host)


@pytest.mark.parametrize("host", ["api.openai.com", "1.1.1.1", "192.168.1.10", "0.0.0.0", "", None,
                                  "localhost.evil.com", "10.0.0.1"])
def test_other_hosts_are_not_local(host):
    assert not is_local_host(host)


def test_require_local_refuses_a_remote_model_url():
    assert require_local("http://127.0.0.1:11434/v1") == "http://127.0.0.1:11434/v1"
    with pytest.raises(NonLocalHostError):
        require_local("https://api.openai.com/v1")


def test_local_config_never_reads_the_client_key():
    env = {"DW_LLM_API_KEY": "sk-secret", "DW_LLM_BASE_URL": "https://api.openai.com/v1"}
    assert llm_config(env, local=True) == (LOCAL_BASE_URL, LOCAL_API_KEY, LOCAL_MODEL)
    assert llm_config({**env, "DW_AUDIT_LOCAL": "1", "DW_LOCAL_MODEL": "llama3.2:3b"})[2] == "llama3.2:3b"
    with pytest.raises(NonLocalHostError):
        llm_config({"DW_LOCAL_BASE_URL": "https://ollama.example.com/v1"}, local=True)


def test_cloud_config_is_unchanged():
    assert llm_config({}) is None
    assert llm_config({"DW_LLM_API_KEY": "k"}) == ("https://api.openai.com/v1", "k", "gpt-5-mini")


GUARDED = textwrap.dedent("""
    import socket, urllib.request
    from agent.local import install_network_guard, NonLocalHostError
    install_network_guard()
    outcomes = []
    for attempt in (lambda: socket.getaddrinfo("api.openai.com", 443),
                    lambda: socket.create_connection(("1.1.1.1", 443), timeout=1),
                    lambda: urllib.request.urlopen("https://api.openai.com/v1/models", timeout=1)):
        try:
            attempt()
            outcomes.append("sorti")
        except NonLocalHostError:
            outcomes.append("refusé")
        except Exception as exc:  # urllib enveloppe l'erreur
            outcomes.append("refusé" if isinstance(getattr(exc, "reason", None), NonLocalHostError) else repr(exc))
    server = socket.socket(); server.bind(("127.0.0.1", 0)); server.listen()
    socket.create_connection(server.getsockname(), timeout=1).close()
    outcomes.append("local ok")
    print(",".join(outcomes))
""")


def test_guard_blocks_every_non_local_connection_in_the_process():
    # sous-processus : un crochet d'audit ne se retire pas, il ne doit pas toucher la suite de tests
    out = subprocess.run([sys.executable, "-c", GUARDED], cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert out.stdout.strip() == "refusé,refusé,refusé,local ok", out.stderr


def test_local_cli_refuses_a_remote_model_before_any_call(tmp_path):
    events = ROOT / "fixtures/dataset/v1/events.jsonl"
    env = {"PATH": "", "DW_LOCAL_BASE_URL": "https://api.openai.com/v1"}
    out = subprocess.run([sys.executable, "-m", "agent.audit", "--local", str(events), "-o", str(tmp_path / "a.html")],
                         cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
    assert out.returncode != 0 and "NonLocalHostError" in out.stderr
    assert not (tmp_path / "a.html").exists()


def test_lsof_output_is_parsed_into_remote_endpoints():
    from scripts.audit_local import remote_endpoints
    lsof = ("COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME\n"
            "python 1 n 3u IPv4 0x1 0t0 TCP 127.0.0.1:50000->127.0.0.1:11434 (ESTABLISHED)\n"
            "ollama 2 n 4u IPv6 0x2 0t0 TCP [::1]:11434->[::1]:50001 (ESTABLISHED)\n"
            "ollama 2 n 5u IPv4 0x3 0t0 TCP 127.0.0.1:11434 (LISTEN)\n"
            "python 1 n 6u IPv4 0x4 0t0 TCP 10.0.0.2:50002->104.18.7.192:443 (SYN_SENT)\n")
    assert remote_endpoints(lsof) == {"127.0.0.1:11434", "::1:50001", "104.18.7.192:443"}


def test_local_timeout_is_configurable_and_validated():
    assert local_timeout({}) == LOCAL_TIMEOUT
    assert local_timeout({"DW_LOCAL_TIMEOUT": "1200"}) == 1200
    for bad in ("abc", "0", "-5"):
        with pytest.raises(SystemExit):
            local_timeout({"DW_LOCAL_TIMEOUT": bad})


def test_chat_client_uses_the_given_timeout(monkeypatch):
    from agent import loop
    seen = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b'{"choices": [{"message": {"role": "assistant", "content": "ok"}}]}'

    def fake_urlopen(request, timeout):
        seen["timeout"], seen["url"] = timeout, request.full_url
        return Response()

    monkeypatch.setattr(loop.urllib.request, "urlopen", fake_urlopen)
    loop.OpenAIChatTools(LOCAL_BASE_URL, LOCAL_API_KEY, LOCAL_MODEL, timeout=900).chat([], [])
    assert seen == {"timeout": 900, "url": "http://localhost:11434/v1/chat/completions"}
