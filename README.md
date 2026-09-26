# DeadWeight — votre premier audit en dix minutes

DeadWeight relaie vos appels OpenAI, les enregistre **localement** et produit un
rapport HTML sur les usages à examiner. Vous gardez votre clé, vos modèles et votre
application ; seul le `base_url` change. Aucun remplacement automatique des appels.

## Prérequis

- **Python 3.11 ou plus récent**, avec `venv` et `pip` (`python3 --version`).
- **Git** et **Make** (`git --version`, `make --version`).
- macOS ou Linux ; sous Windows, utilisez WSL2 et suivez les commandes Linux.
- Une connexion Internet pour cloner et installer les dépendances. La démo n’appelle
  aucun fournisseur ; votre trafic réel nécessite votre accès habituel à OpenAI.

Sur Debian/Ubuntu, si nécessaire : `sudo apt install python3 python3-venv make git`.
Sur macOS, installez les outils de ligne de commande (`xcode-select --install`) et
Python 3.11+ avant de commencer. Les commandes ci-dessous sont à lancer depuis le repo.

## 1. Installer et lancer la passerelle

```sh
git clone https://github.com/hugogsld/DeadWeight.git
cd DeadWeight
make dev
```

`make dev` crée `.venv`, installe les dépendances, prépare `.env.local` puis lance
la passerelle sur **http://127.0.0.1:8080/v1**. Gardez ce terminal ouvert.
Vous n’avez aucune clé à renseigner dans DeadWeight : l’application continue
à transmettre sa propre clé. Si Python est nommé autrement : `make dev PY=python3.11`.

**Vérifier sans clé avant de brancher votre application :** dans un second terminal,
placez-vous dans le même dossier puis lancez :

```sh
make demo
```

La démo démarre un faux serveur OpenAI et une passerelle sur des ports locaux libres,
envoie 36 appels, puis affiche le chemin `out/demo-…/audit.html`. Ouvrez-le dans votre
navigateur. Chaque lancement utilise une base séparée et arrête ses serveurs à la fin :
votre passerelle et vos captures réelles restent intactes. Les chiffres de ce rapport
sont **fictifs**, destinés à vérifier le parcours. Après installation des dépendances,
la démo doit prendre moins d’une minute ; elle fonctionne sans Internet ni clé API.

## 2. Changer uniquement l’adresse dans votre application

Python, avec votre SDK OpenAI et votre clé habituelle :

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8080/v1")
# OPENAI_API_KEY reste configurée dans votre application, comme avant.
```

JavaScript / Node.js, avec votre SDK OpenAI existant :

```javascript
import OpenAI from "openai";

const client = new OpenAI({ baseURL: "http://127.0.0.1:8080/v1" });
// OPENAI_API_KEY reste configurée dans votre application, comme avant.
```

Si vous passiez déjà `api_key` / `apiKey` au constructeur, conservez-le. Ne changez
ni le modèle ni les messages. Ce parcours capture les appels **Chat Completions**
(`/v1/chat/completions`) ; les autres routes sont relayées sans capture.
L’application et la passerelle doivent tourner sur la même machine : `127.0.0.1`
dans un conteneur désigne ce conteneur, pas la machine hôte.

## 3. Laisser passer votre trafic

Utilisez votre application normalement. Les événements sont écrits dans
`out/events.db` au fil des appels. Pour vérifier le compteur depuis un second terminal :

```sh
.venv/bin/python -m gateway.store count
```

Quelques appels suffisent pour produire un rapport ; certaines règles exigent au moins
30 appels comparables. « Aucun gaspillage détecté » est un résultat possible.
En streaming, OpenAI ne fournit les tokens que si votre application demande
`stream_options={"include_usage": True}` (Python) ou
`stream_options: { include_usage: true }` (JS). Sans usage, le rapport affiche les
coûts indisponibles : il n’invente pas de mesure.

## 4. Générer le rapport en une commande

Dans le second terminal, depuis le même dossier :

```sh
make audit
```

Cette commande enchaîne l’export SQLite et `report.audit`, puis écrit **`out/audit.html`**.
Ouvrez ce fichier dans votre navigateur. La passerelle peut rester active pendant
l’audit. L’export intermédiaire est temporaire et supprimé après usage. Pour choisir
le fichier final : `make audit AUDIT_OUT=out/mon-rapport.html`.

La base par défaut est `out/events.db`. Pour la changer, définissez
`GATEWAY_DB=/chemin/vers/events.db` dans `.env.local`, puis relancez `make dev`.
`make audit` charge le même fichier de configuration. Pour le compteur manuel,
ajoutez `--db /chemin/vers/events.db`.

## Prix des modèles

Les coûts viennent de `fixtures/pricing.json`, le catalogue public d'OpenRouter (prix d'entrée,
de sortie et du cache, en dollars par million de jetons). Pour le rafraîchir :

    make prices

Les noms des API sont reconnus tels quels (`claude-sonnet-4-5`, `gpt-4o-2024-08-06`). Si un
modèle reste inconnu, le rapport chiffre les autres appels et indique la part couverte.

Origine et hébergement de chaque éditeur (pays, traitement possible dans l'UE, option souveraine)
dans `fixtures/providers.json`, chaque fiche avec sa source ; un point non vérifié vaut `null`.
Pour rafraîchir les prix et contrôler le catalogue, puis voir la latence mesurée sur votre trafic :

    make catalog
    .venv/bin/python -m catalog --events events.jsonl

Quand le rapport signale un modèle surdimensionné pour une tâche simple, il propose aussi d'autres
modèles, tous fournisseurs confondus : le moins cher, le moins cher chez le même éditeur, et le
moins cher d'un éditeur européen. Chacun sait faire ce que fait votre trafic (outils, JSON, images,
taille du plus gros appel, d'après `fixtures/capabilities.json`) et son coût est recalculé sur vos
propres jetons. Les options « même éditeur » et « souverain » sont chiffrées au prix de la route de
l'éditeur lui-même, pas à celui d'un hébergeur tiers moins cher. Un modèle à raisonnement est
signalé : ses jetons de réflexion ne sont pas dans votre trafic, son coût est donc sous-estimé.
Leur qualité n'est pas prouvée : à vérifier par rejeu avant de changer de modèle.

## Confidentialité

- **La clé n’est jamais stockée** par la passerelle : l’en-tête d’autorisation est
  relayé au fournisseur sans être enregistré dans SQLite ou les journaux.
- **La base reste chez vous.** Elle contient les prompts et réponses : traitez-la
  comme les données de votre application. Le rapport peut aussi contenir des informations
  sur vos applications ; partagez-le uniquement avec les personnes concernées.
- Le fournisseur reçoit toujours vos appels habituels. La génération du rapport ne
  transmet aucune donnée à DeadWeight ou à un modèle externe.
- La démo utilise exclusivement des serveurs locaux et ne lit aucune clé client.

## Si ça ne marche pas

| Symptôme | Action |
| --- | --- |
| `python3`, `make` ou `git` introuvable | Installez les prérequis ci-dessus ; vérifiez Python 3.11+. |
| Création de `.venv` impossible | Sur Debian/Ubuntu, installez `python3-venv` ; vérifiez les droits du dossier. |
| Installation des paquets impossible | Vérifiez Internet et l’accès à PyPI, puis relancez `make dev`. |
| Port 8080 déjà utilisé | Arrêtez l’autre service, ou réglez `GATEWAY_PORT=8081` dans `.env.local` et utilisez ce port dans votre `base_url`. |
| Connexion refusée par votre application | Gardez `make dev` ouvert et vérifiez l’adresse, le port et que l’application tourne sur le même hôte. |
| Réponse 401 / 429 / 502 | Vérifiez respectivement votre clé dans l’application, votre quota fournisseur, ou l’accès réseau au fournisseur. |
| Base absente ou vide | Lancez `make dev`, envoyez des appels Chat Completions via le nouveau `base_url`, puis relancez `make audit`. Vérifiez `GATEWAY_DB`. |
| Rapport sans constat | Collectez davantage de trafic comparable ; les règles peuvent aussi n’avoir rien à signaler. |
| Coût « non disponible » | Vérifiez l’usage des tokens et la présence du modèle dans `fixtures/pricing.json` ; aucune valeur de remplacement n’est utilisée. |
| Démo impossible | Vérifiez les droits dans `out/` et l’autorisation des connexions locales, puis relancez `make demo`. |

Pour diagnostiquer l’installation : `make test` puis `make lint`. `make demo` permet
de distinguer un problème local d’un problème de clé ou de fournisseur.

---

<details>
<summary>Prototype n8n du hackathon — historique et ancien parcours</summary>


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

## Gateway (D1.1, D1.2, D1.3, D1.4) — OpenAI, Anthropic and Gemini pass-through proxy

The gateway sits between your application and OpenAI. You change one line — the
`base_url` — and every call is relayed unchanged, streaming included, while a copy
is captured in the event format of `schemas/event.schema.json`.

    python3 -m venv .venv && .venv/bin/pip install -r gateway/requirements.txt
    .venv/bin/python -m gateway          # listens on http://127.0.0.1:8080

Then, in your application:

    client = OpenAI(base_url="http://127.0.0.1:8080/v1")   # same API key as before
    client = Anthropic(base_url="http://127.0.0.1:8080/anthropic")
    client = genai.Client(http_options={"base_url": "http://127.0.0.1:8080/gemini"})

The three providers produce the same event: the rules and the report never need to know
which one a call came from. Anthropic `POST /v1/messages` and Gemini
`models/<model>:generateContent` / `:streamGenerateContent` are captured (Gemini streaming
both with `?alt=sse` and as a JSON array).

| Variable | Default | |
| --- | --- | --- |
| `GATEWAY_HOST` / `GATEWAY_PORT` | `127.0.0.1` / `8080` | listen address |
| `GATEWAY_OPENAI_UPSTREAM` | `https://api.openai.com` | where OpenAI calls are relayed |
| `GATEWAY_ANTHROPIC_UPSTREAM` | `https://api.anthropic.com` | where `/anthropic/...` is relayed |
| `GATEWAY_GEMINI_UPSTREAM` | `https://generativelanguage.googleapis.com` | where `/gemini/...` is relayed |
| `GATEWAY_DB` | `out/events.db` | SQLite file where captured calls are stored |
| `GATEWAY_LOG_LEVEL` | `INFO` | one summary line per call, never content or headers |

Optional headers: `x-deadweight-app` (groups calls by application, default `default`)
and `x-deadweight-trace` (groups calls of one workflow). They are not forwarded to OpenAI.

**Your API key is never stored.** The `Authorization` header (Anthropic `x-api-key`,
Gemini `x-goog-api-key` or `?key=`) is relayed as is and never persisted, logged or written
to an event; a key echoed back in an error message is masked before capture. Only the
completion routes above are captured; every other route is relayed without capture. With streaming, token counts are only known if the client sets
`stream_options: {"include_usage": true}` — the gateway never alters the request.

Every captured call is written to SQLite in a background thread, never on the response
path. The database stays on your machine. Once your normal traffic has run for a while:

    .venv/bin/python -m gateway.store count                          # calls captured so far
    .venv/bin/python -m gateway.store export > out/events.jsonl      # --app <app_id> to filter
    .venv/bin/python -m report.audit out/events.jsonl -o out/audit.html

Stop the gateway with Ctrl+C or SIGTERM: pending events are flushed before it exits.

**Streaming token counts.** OpenAI only reports usage in a stream when the client sets
`stream_options.include_usage`. When the client says nothing, the gateway asks for it and
removes that extra usage chunk before relaying: the client gets the same bytes as a direct
call, and the event gets real token counts. A client that sets `include_usage` either way
is left alone.

**Traces.** `export` groups the calls of one workflow into traces (`trace.id`, `trace.step`),
which the loop and context rules need. If your application sets `x-deadweight-trace`, that
id is used as is. Otherwise the gateway infers it: a call continues an earlier one when it
carries that call's last input message followed by its answer — what every chat client and
agent loop sends back — within 30 minutes, same app and same system prompt. Isolated calls
stay out of traces. Details and known blind spots in `gateway/traces.py`; on the reference
dataset it recovers 79 / 79 traces with no header and no false positive. `--raw` exports
without grouping.

Checks, no API key needed (a local fake OpenAI stands in):

    .venv/bin/pip install pytest jsonschema openai
    .venv/bin/python -m pytest tests/test_gateway.py tests/test_store.py tests/test_traces.py
    .venv/bin/python -m gateway.bench                   # added latency, with and without SQLite

Measured on a laptop, p95 added over a direct call: **+0.3 ms** sequential and **+3.0 ms**
at 20 concurrent requests with SQLite on — SQLite itself adds under 1 ms (target: < 30 ms).
Checked against the real OpenAI API with the official SDK, plain and streaming.

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

## Short-circuit (D3.3) — the gateway answers proven calls itself

Off by default. Point the gateway at the replay output: only **pass** proofs are loaded.

    GATEWAY_SHORTCIRCUIT=out/ .venv/bin/python -m gateway

A call is answered by the gateway, without reaching OpenAI, only when it falls in the
proven group (same `x-deadweight-app`, model and system prompt template) **and** a rule
covers its input. Tools, images, JSON output, `n > 1` and uncovered inputs are relayed
unchanged. Streaming works. The response carries `x-deadweight-shortcircuit: <finding_id>`
and is still captured, with `upstream: "deadweight"`, `model_resolved: "deadweight-rules"`
and zero tokens.

On the D0.3 dataset (`mail-triage`): **0.24 ms p95** instead of 764 ms for the original
gpt-4o call, no upstream request.

## Mirror mode (D4.3) — measure the rules on live traffic, never apply them

The step before the short-circuit. Off by default; loads **pass and reject** proofs, since
a rule refused at replay is exactly what you want to keep watching.

    GATEWAY_MIRROR=out/ .venv/bin/python -m gateway
    .venv/bin/python -m gateway.mirror stats        # agreement per finding

Every captured call (OpenAI, Anthropic or Gemini) that falls in a proven group is compared
with what the rules would have answered. **The client always gets the model's answer**:
the mirror hooks into capture, not into the relay. `out/mirror.jsonl` (`GATEWAY_MIRROR_LOG`)
holds the rules' label and whether it agreed — never the prompt or the model's text.
`stats` says, per finding, how many calls were covered, the agreement rate, and whether it
reaches the 0.95 threshold to switch on the short-circuit. Short-circuited calls are not
mirrored (there is no model answer to compare).

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

## Démarrer (D0.2)

Python 3.11+ requis.

    git clone https://github.com/hugogsld/DeadWeight.git && cd DeadWeight
    make dev       # cree .venv, installe, cree .env.local depuis .env.example, lance la passerelle

Tes clés vont dans `.env.local` (jamais commité). Personne ne tape `export`.

    make test      # tests, sans réseau ni clé : les réponses fournisseurs sont rejouées
    make lint      # ruff, sur gateway/ rules/ report/ tests/ scripts/
    make record    # appelle les vraies API une fois et écrit tests/cassettes/

Un test qui parle à un fournisseur se marque `@pytest.mark.vcr` : il rejoue sa cassette
dans `tests/cassettes/`. Les clés sont retirées avant l'écriture (voir `tests/conftest.py`).

</details>
