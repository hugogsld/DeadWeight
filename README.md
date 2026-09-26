# Deadweight

**Companies hired thousands of agents this year. Nobody ever gave them a performance review.**

Deadweight is an agent that lives inside your n8n instance, audits your agentic
workflows against their real execution history, and ships a patch when a node
turns out not to need a model at all.

Built at *Agents, Everywhere — AI Tinkerers x OpenAI*, Paris, September 12 2026.

---

## The problem

Gartner expects **over 40% of agentic AI projects to be cancelled by the end of 2027** —
the top reasons being escalating cost and unclear business value. IBM puts enterprises
on track for roughly **1,600 agents each** by year end, with ~70% admitting they cannot
govern the ones they already run.

The tooling market answers the wrong question. Observability platforms **measure**
(Langfuse, Arize, Helicone, Datadog). Governance platforms **inventory** (Zenity, Astrix).
Cost tools **route and cache** (Sedai, Portkey, LiteLLM). None of them asks the one
question that actually cuts the bill:

> Did this ever need to be an agent?

## What Deadweight does

1. Reads your n8n workflows **and their execution history** through the public API.
2. Flags LLM nodes that are not reasoning — they are classifying.
3. Generates a patched workflow: a deterministic Switch, with a small model as fallback.
4. **Replays real past inputs** through the new path and compares against what the old
   node actually produced. Below the agreement threshold, it refuses to propose the patch.
5. Posts the review to Slack, and writes the patched workflow straight back into n8n.

## The signal: output entropy

Take an LLM node and look at its last 200 executions. If it only ever produced a handful
of distinct outputs, it is not reasoning — it is a switch statement billed at reasoning
prices. Shannon entropy over normalised outputs, three lines of Python, no model call
required to detect it.

On our demo workflow: **4 distinct outputs over 200 calls, 1.58 bits of entropy out of a
possible 7.64.**

## Architecture

    Collector  --> profile.json  --> Detector
    Detector   --> finding.json  --> Patcher
    Patcher    --> patch.json    --> Prover
    Prover     --> proof.json    --> Habitat (Slack + n8n)

Five stages, four JSON contracts. Each stage only knows the file it reads and the file
it writes — which is how three people built this in parallel in one afternoon.

**The LLM never writes the n8n JSON.** It only extracts classification rules from real
examples; Python assembles the workflow deterministically. n8n graphs have too many
structural traps — connections keyed by node name, `typeVersion`, required
`ai_languageModel` sub-nodes — to hand to a model under time pressure.

That is the product thesis applied to the product itself: a model where it earns its
place, code where code is enough. A `--no-llm` mode derives the same rules statistically,
and doubles as a baseline — if plain keyword rules reproduce the node's output, that is
further proof the node was replaceable.

## Measured results

Demo workflow: a support-ticket triage pipeline, GPT-5 classification node, 200 real
executions generated against a live n8n instance.

| | before | after |
| --- | --- | --- |
| agreement on replayed inputs | — | **98.0%** (93 by rules, 7 by fallback) |
| monthly cost | — | **/145** |
| p95 latency | 4,300 ms | **< 1 ms** on rule-matched inputs |
| inputs matched by rules | — | 98 / 100 |

The Prover's first run on real data returned **REJECT at 39% agreement** — rules derived
from too few examples. That is the system working: it refused to propose a patch that
would have broken production. Rebuilt from the real execution history, the same pipeline
returns **PASS at 98.0% agreement**.

## Running it

    export N8N_URL=http://localhost:5678
    export N8N_API_KEY=...        # n8n Settings > n8n API
    export OPENAI_API_KEY=...

    python3 prover/seed_original.py        # seed a workflow to audit
    python3 prover/seed_executions.py 200  # give it a real execution history
    python3 prover/refresh_finding.py      # detect: entropy over real outputs
    python3 patcher/patch.py fixtures/finding.json
    python3 patcher/validate_reimport.py out/patch.json
    python3 prover/prove.py out/patch.json fixtures/finding.json

Add `--no-llm` to the patcher to run the whole pipeline with no API key at all.

## Gateway (D1.1) — OpenAI pass-through proxy

The gateway sits between your application and OpenAI. You change one line — the
`base_url` — and every call is relayed unchanged, streaming included, while a copy
is captured in the event format of `schemas/event.schema.json`.

    python3 -m venv .venv && .venv/bin/pip install -r gateway/requirements.txt
    .venv/bin/python -m gateway          # listens on http://127.0.0.1:8080

Then, in your application:

    client = OpenAI(base_url="http://127.0.0.1:8080/v1")   # same API key as before

| Variable | Default | |
| --- | --- | --- |
| `GATEWAY_HOST` / `GATEWAY_PORT` | `127.0.0.1` / `8080` | listen address |
| `GATEWAY_OPENAI_UPSTREAM` | `https://api.openai.com` | where calls are relayed |
| `GATEWAY_LOG_LEVEL` | `INFO` | one summary line per call, never content or headers |

Optional headers: `x-deadweight-app` (groups calls by application, default `default`)
and `x-deadweight-trace` (groups calls of one workflow). They are not forwarded to OpenAI.

**Your API key is never stored.** The `Authorization` header is relayed as is and never
persisted, logged or written to an event; a key echoed back in an OpenAI error message is
masked before capture. Only `POST /v1/chat/completions` is captured; every other route is
relayed without capture. With streaming, token counts are only known if the client sets
`stream_options: {"include_usage": true}` — the gateway never alters the request.

Checks, no API key needed (a local fake OpenAI stands in):

    .venv/bin/pip install pytest jsonschema openai
    .venv/bin/python -m pytest tests/test_gateway.py   # byte-identical relay, no buffering, key never captured
    .venv/bin/python -m gateway.bench                   # added latency, p50 / p95

Measured on a laptop, capture on: **+0.2 ms p95** sequential, **+3.6 ms p95** at 20
concurrent requests (target: < 30 ms). Checked against the real OpenAI API with the
official SDK, plain and streaming.

## Replay (D3.2) — agreement threshold at 0.95

Replays the extracted rules (D3.1) on real captured events and compares against what
the original model actually answered. Extraction examples are excluded: the proof runs
on independent data. Inputs no rule covers stay on the original call; agreement is
measured on the inputs the new path replaces, and at least 30 are needed to conclude.

    python3 -m proof.replay fixtures/dataset/v1/events.jsonl   # writes out/proof-<finding>.json

A **reject** is a result, not an error: the verdict lists its reasons and the exit code is 0.
Costs are in USD, `null` when not measurable — never a default value.

Optional fallback model for uncovered inputs, via any OpenAI-compatible endpoint:

    export DW_LLM_BASE_URL=https://api.openai.com/v1 DW_LLM_API_KEY=...
    python3 -m proof.replay events.jsonl --fallback-model gpt-4o-mini --max-calls 50 --min-interval 1

The fallback is the only thing that calls an API: hard cap of 200 calls per replay
(`--max-calls` cannot exceed it) and a minimum interval between two calls.

## Stack

**n8n** — the audited target: the only orchestrator exposing both workflow JSON and
execution history over an API. **OpenAI** — rule extraction via structured outputs.
**OpenRouter** — model pricing catalogue, which turns "this node is oversized" into a
cost factor. **CopilotKit** — the Slack habitat, with human-in-the-loop approval in the
channel. **Google Cloud Run** — deployment.

## Not done yet

Five of the six detector rules (`oversized_model`, `raw_context`, `no_cache`,
`unbounded_loop`, `agent_where_chain`) — only output entropy is wired end to end.
Scheduled weekly scans via Trigger.dev. Generalisation beyond n8n through
OpenTelemetry GenAI traces. Patch strategies other than `rule_switch`.

## Team

Built in one afternoon at Le Wagon Paris. Three people, three lanes, four JSON contracts.

## Rapport d'audit (D4.1)

    python -m report.audit fixtures/dataset/v1/events.jsonl -o out/audit.html

Lance toutes les règles présentes dans `rules/`, chiffre chaque constat et écrit une page HTML
autonome dans `out/audit.html`.
