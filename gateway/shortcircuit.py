"""D3.3 — Court-circuit : la passerelle répond elle-même quand une preuve PASS le permet.

Désactivé par défaut. GATEWAY_SHORTCIRCUIT pointe vers un fichier proof-*.json ou un
dossier qui en contient (sortie de `python3 -m proof.replay`). Seules les preuves au
verdict « pass » sont chargées ; une requête n'est court-circuitée que si elle tombe
dans le même groupe que le constat prouvé (application × modèle × gabarit, comme R1)
ET qu'une règle la couvre. Tout le reste part chez OpenAI comme avant.
"""
import json
import time
import uuid
from pathlib import Path

from gateway.capture import normalize_request
from proof.extract import build_router
from rules.low_entropy import template_of

RESOLVED = "deadweight-rules"


def load(path, verdicts=("pass",)):
    """{(app_id, model, template): (finding_id, route)} depuis les preuves PASS.
    Le mode miroir (D4.3) charge aussi les REJECT : il sert justement à les observer."""
    path = Path(path)
    files = sorted(path.glob("proof-*.json")) if path.is_dir() else [path]
    table = {}
    for f in files:
        proof = json.loads(f.read_text())
        if proof.get("verdict") not in verdicts or not proof.get("rules"):
            continue
        key = (proof.get("app_id"), proof.get("model"), proof.get("template"))
        if None in key:
            continue
        table[key] = (proof["finding_id"], build_router({"categories": proof["rules"]}))
    return table


def _eligible(body):
    """Seulement le cas prouvé : une complétion texte simple, sans outil ni image."""
    if body.get("tools") or body.get("functions") or body.get("n", 1) != 1 or body.get("logprobs"):
        return False
    rf = body.get("response_format")
    if isinstance(rf, dict) and rf.get("type") not in (None, "text"):
        return False
    return True


def match(table, req_body, app_id):
    """(finding_id, sortie) si la requête peut être court-circuitée, sinon None."""
    if not table:
        return None
    try:
        body = json.loads(req_body)
    except ValueError:
        return None
    if not isinstance(body, dict) or not _eligible(body):
        return None
    model, request = normalize_request(body)
    if any(m.get("n_images") for m in request["messages"]):
        return None
    hit = table.get((app_id, model, template_of({"request": request})))
    if hit is None:
        return None
    finding_id, route = hit
    text = user_text(request)
    out = route(text) if text.strip() else None
    return (finding_id, out) if out is not None else None


def user_text(request):
    """Texte des messages utilisateur d'une requête normalisée : ce que lisent les règles."""
    return "\n".join(m["content"] for m in request["messages"]
                     if m["role"] == "user" and isinstance(m.get("content"), str))


def completion(output):
    """Corps chat.completion (non streamé). Zéro token : aucun modèle n'a tourné."""
    return json.dumps({
        "id": "chatcmpl-dw-" + uuid.uuid4().hex, "object": "chat.completion",
        "created": int(time.time()), "model": RESOLVED,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": output},
                     "logprobs": None, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }).encode()


def stream(output):
    """Même réponse en SSE : un morceau de contenu, la fin, l'usage, [DONE]."""
    base = {"id": "chatcmpl-dw-" + uuid.uuid4().hex, "object": "chat.completion.chunk",
            "created": int(time.time()), "model": RESOLVED}
    chunks = [
        {**base, "choices": [{"index": 0, "delta": {"role": "assistant", "content": output},
                              "logprobs": None, "finish_reason": None}]},
        {**base, "choices": [{"index": 0, "delta": {}, "logprobs": None, "finish_reason": "stop"}]},
        {**base, "choices": [], "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}},
    ]
    return b"".join(b"data: " + json.dumps(c).encode() + b"\n\n" for c in chunks) + b"data: [DONE]\n\n"
