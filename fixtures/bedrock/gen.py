"""Génère les fixtures Bedrock. SYNTHÉTIQUES : écrites d'après la documentation AWS, jamais capturées chez un client.

    python3 fixtures/bedrock/gen.py

Aucune donnée réelle, aucun identifiant réel (compte 123456789012, ARN d'exemple).
Les formes de flux et les champs de cache sont des hypothèses tirées de la doc, à valider sur un vrai journal.
"""
import base64
import gzip
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent
ACCOUNT = "123456789012"
ARN = f"arn:aws:sts::{ACCOUNT}:assumed-role/claims-agent-role/session-1"
SONNET_EU = "eu.anthropic.claude-sonnet-4-5-20250929-v1:0"
HAIKU = "anthropic.claude-3-haiku-20240307-v1:0"
TOOLS = {"tools": [{"toolSpec": {"name": "lookup_policy", "description": "Cherche un contrat par numéro",
                                  "inputSchema": {"json": {"type": "object",
                                                           "properties": {"policy_id": {"type": "string"}},
                                                           "required": ["policy_id"]}}}}]}
SYSTEM = [{"text": "Tu instruis des demandes de garantie. Réponds en JSON court."}]


def record(request_id, op, model, ts, inp, out, tags=None, region="eu-west-1", **kw):
    rec = {"schemaType": "ModelInvocationLog", "schemaVersion": "1.0", "timestamp": ts, "accountId": ACCOUNT,
           "region": region, "requestId": request_id, "operation": op, "modelId": model,
           "identity": {"arn": ARN}, "input": inp, "output": out}
    if tags:
        rec["requestMetadata"] = tags
    rec.update(kw)
    return rec


def converse(request_id, ts, messages, reply, usage, stop, tags, tokens, cache=(0, 0), **kw):
    return record(request_id, "Converse", SONNET_EU, ts,
                  {"inputContentType": "application/json",
                   "inputBodyJson": {"messages": messages, "system": SYSTEM, "toolConfig": TOOLS,
                                     "inferenceConfig": {"maxTokens": 512, "temperature": 0.2}},
                   "inputTokenCount": tokens[0], "cacheReadInputTokenCount": cache[0],
                   "cacheWriteInputTokenCount": cache[1]},
                  {"outputContentType": "application/json",
                   "outputBodyJson": {"output": {"message": {"role": "assistant", "content": reply}},
                                      "stopReason": stop, "usage": usage, "metrics": {"latencyMs": 900}},
                   "outputTokenCount": tokens[1]}, tags, **kw)


def usage(i, o, r=0, w=0):
    return {"inputTokens": i, "outputTokens": o, "totalTokens": i + o,
            "cacheReadInputTokens": r, "cacheWriteInputTokens": w}


def s3_records():
    tags = {"workflow_id": "claim-8841", "agent": "triage"}
    u1 = {"role": "user", "content": [{"text": "Sinistre 8841 : lave-linge en panne après 14 mois."}]}
    a1 = [{"toolUse": {"toolUseId": "tu_1", "name": "lookup_policy", "input": {"policy_id": "P-8841"}}}]
    u2 = {"role": "user", "content": [{"toolResult": {"toolUseId": "tu_1", "status": "success",
                                                      "content": [{"json": {"coverage": "24 mois", "active": True}}]}}]}
    final = [{"text": "{\"decision\": \"accepte\"}"}]
    return [
        converse("req-0001", "2026-11-12T09:00:00Z", [u1], a1, usage(420, 35), "tool_use", tags, (420, 35)),
        converse("req-0002", "2026-11-12T09:00:02Z",
                 [u1, {"role": "assistant", "content": a1}, u2], final, usage(80, 20, 380, 0), "end_turn",
                 tags, (80, 20), cache=(380, 0)),
        converse("req-0003", "2026-11-12T09:01:00Z", [u1], a1, usage(60, 35, 0, 400), "tool_use",
                 {"workflow_id": "claim-8842", "agent": "triage"}, (60, 35), cache=(0, 400)),
        record("req-0004", "InvokeModel", "anthropic.claude-3-haiku-20240307-v1:0", "2026-11-12T09:02:00Z",
               {"inputContentType": "application/json",
                "inputBodyJson": {"anthropic_version": "bedrock-2023-05-31", "max_tokens": 200,
                                  "system": "Classe la demande.", "temperature": 0,
                                  "messages": [{"role": "user", "content": [{"type": "text", "text": "Fuite d'eau"}]}]},
                "inputTokenCount": 30, "cacheReadInputTokenCount": 0, "cacheWriteInputTokenCount": 0},
               {"outputContentType": "application/json",
                "outputBodyJson": {"id": "msg_x", "type": "message", "role": "assistant", "model": HAIKU,
                                   "content": [{"type": "text", "text": "dégât des eaux"}],
                                   "stop_reason": "end_turn", "usage": {"input_tokens": 30, "output_tokens": 5}},
                "outputTokenCount": 5}, {"workflow_id": "claim-8842"}),
        record("req-0005", "Converse", SONNET_EU, "2026-11-12T09:03:00Z",
               {"inputContentType": "application/json", "inputBodyS3Path": big_ref("req-0005"),
                "inputTokenCount": 33646, "cacheReadInputTokenCount": 0, "cacheWriteInputTokenCount": 0},
               {"outputContentType": "application/json",
                "outputBodyJson": {"output": {"message": {"role": "assistant", "content": [{"text": "ok"}]}},
                                   "stopReason": "end_turn", "usage": usage(33646, 4), "metrics": {"latencyMs": 3000}},
                "outputTokenCount": 4}, {"workflow_id": "claim-8843"}),
        record("req-0006", "Converse", SONNET_EU, "2026-11-12T09:04:00Z",
               {"inputContentType": "application/json", "inputBodyS3Path": big_ref("req-0006-absent"),
                "inputTokenCount": 40100, "cacheReadInputTokenCount": 0, "cacheWriteInputTokenCount": 0},
               {"outputContentType": "application/json", "outputTokenCount": 7}, {"workflow_id": "claim-8844"}),
    ]


def big_ref(request_id):
    return (f"s3://bedrock-logs-{ACCOUNT}/AWSLogs/{ACCOUNT}/BedrockModelInvocationLogs/eu-west-1/2026/11/12/09/"
            f"data/{request_id}_input.json.gz")


def stream_records():
    ev = [{"messageStart": {"role": "assistant"}},
          {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": "Je vérifie "}}},
          {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": "le contrat."}}},
          {"contentBlockStop": {"contentBlockIndex": 0}},
          {"contentBlockStart": {"contentBlockIndex": 1, "start": {"toolUse": {"toolUseId": "tu_9",
                                                                              "name": "lookup_policy"}}}},
          {"contentBlockDelta": {"contentBlockIndex": 1, "delta": {"toolUse": {"input": "{\"policy_id\":"}}}},
          {"contentBlockDelta": {"contentBlockIndex": 1, "delta": {"toolUse": {"input": " \"P-9\"}"}}}},
          {"contentBlockStop": {"contentBlockIndex": 1}},
          {"messageStop": {"stopReason": "tool_use"}},
          {"metadata": {"usage": usage(200, 40, 150, 0), "metrics": {"latencyMs": 1200}}}]
    conv = record("req-1001", "ConverseStream", SONNET_EU, "2026-11-12T10:00:00Z",
                  {"inputContentType": "application/json",
                   "inputBodyJson": {"messages": [{"role": "user", "content": [{"text": "Contrat P-9 ?"}]}],
                                     "system": SYSTEM, "toolConfig": TOOLS},
                   "inputTokenCount": 200, "cacheReadInputTokenCount": 150, "cacheWriteInputTokenCount": 0},
                  {"outputContentType": "application/json", "outputBodyJson": ev, "outputTokenCount": 40},
                  {"workflow_id": "claim-9001"})

    def chunk(obj):
        return {"chunk": {"bytes": base64.b64encode(json.dumps(obj).encode()).decode()}}

    anth = [{"type": "message_start", "message": {"usage": {"input_tokens": 50, "output_tokens": 1}}},
            {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Accepté."}},
            {"type": "content_block_stop", "index": 0},
            {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 6}}]
    inv = record("req-1002", "InvokeModelWithResponseStream", SONNET_EU, "2026-11-12T10:00:30Z",
                 {"inputContentType": "application/json",
                  "inputBodyJson": {"anthropic_version": "bedrock-2023-05-31", "max_tokens": 100,
                                    "messages": [{"role": "user", "content": "Décision ?"}]},
                  "inputTokenCount": 50, "cacheReadInputTokenCount": 0, "cacheWriteInputTokenCount": 0},
                 {"outputContentType": "application/json", "outputBodyJson": [chunk(e) for e in anth],
                  "outputTokenCount": 6}, {"workflow_id": "claim-9001"})
    return conv, inv


def main():
    s3 = OUT / "s3/AWSLogs" / ACCOUNT / "BedrockModelInvocationLogs/eu-west-1/2026/11/12/09"
    (s3 / "data").mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(r) for r in s3_records()]
    lines.insert(3, "{ceci n'est pas du json")  # enregistrement malformé
    with gzip.open(s3 / "20261112T0900-synthetic.json.gz", "wt", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    big = {"messages": [{"role": "user", "content": [{"text": "Dossier complet : " + "x" * 120_000}]}],
           "system": SYSTEM}
    with gzip.open(s3 / "data" / "req-0005_input.json.gz", "wt", encoding="utf-8") as f:
        json.dump(big, f)
    conv, inv = stream_records()
    cw = OUT / "cloudwatch"
    cw.mkdir(exist_ok=True)
    # export CloudWatch : horodatage devant le JSON, un évènement par ligne
    (cw / "export.log").write_text(
        "".join(f"{r['timestamp']} {json.dumps(r)}\n" for r in (conv, inv)), encoding="utf-8")
    # sortie de `aws logs filter-log-events` : le JSON est dans `message`
    (cw / "filter-log-events.json").write_text(json.dumps(
        {"events": [{"logStreamName": "aws/bedrock/modelinvocations", "timestamp": 1762941600000,
                     "message": json.dumps(conv), "eventId": "1"}]}), encoding="utf-8")


if __name__ == "__main__":
    main()
