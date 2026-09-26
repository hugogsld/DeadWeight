"""B1.2 : workflow + exécutions n8n → événements (schemas/event.schema.json).

Ce que n8n enregistre pour un sous-nœud « Chat Model » (source :
packages/@n8n/ai-utilities/src/utils/n8n-llm-tracing.ts), dans
runData[<nœud>][i] :

    inputOverride.ai_languageModel[0][0].json = {messages: [prompt texte], estimatedTokens, options}
    data.ai_languageModel[0][0].json          = {response: {generations: [[{text, generationInfo}]]},
                                                 tokenUsage | tokenUsageEstimate}
    source[0].previousNode                    = le nœud racine qui l'a appelé (agent, chaîne)

Le prompt est aplati par LangChain (« System: …\\nHuman: …\\nAI: … »), on le redécoupe.
Les appels d'outils du modèle ne sont pas gardés par n8n : on les reconstitue depuis les
exécutions des nœuds outils branchés en ai_tool sur le même nœud racine.

L'identifiant d'exécution devient trace.id : le regroupement est exact, pas deviné.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from .nodes import LANGCHAIN, is_llm_node, is_model_node

# type de nœud → (format de requête, hôte appelé)
PROVIDERS = {
    "lmChatOpenAi": ("openai", "api.openai.com"),
    "lmOpenAi": ("openai", "api.openai.com"),
    "lmChatAzureOpenAi": ("openai", "azure"),
    "lmChatAnthropic": ("anthropic", "api.anthropic.com"),
    "lmChatGoogleGemini": ("gemini", "generativelanguage.googleapis.com"),
    "lmChatGoogleVertex": ("gemini", "aiplatform.googleapis.com"),
    "lmChatMistralCloud": ("openai", "api.mistral.ai"),
    "lmChatGroq": ("openai", "api.groq.com"),
    "lmChatDeepSeek": ("openai", "api.deepseek.com"),
    "lmChatOpenRouter": ("openai", "openrouter.ai"),
    "lmChatXAiGrok": ("openai", "api.x.ai"),
    "lmChatOllama": ("openai", "localhost:11434"),
    "lmOllama": ("openai", "localhost:11434"),
}

FINISH = {"stop": "stop", "end_turn": "stop", "stop_sequence": "stop", "STOP": "stop",
          "length": "length", "max_tokens": "length", "MAX_TOKENS": "length",
          "tool_calls": "tool_calls", "tool_use": "tool_calls",
          "content_filter": "content_filter", "SAFETY": "content_filter", "RECITATION": "content_filter"}

ROLES = {"System": "system", "Human": "user", "AI": "assistant", "Tool": "tool", "Function": "tool"}
ROLE_LINE = re.compile(r"^(System|Human|AI|Tool|Function): ?", re.M)


def _short(node_type: str) -> str:
    return node_type[len(LANGCHAIN):] if node_type.startswith(LANGCHAIN) else node_type


def _iso(ms: float) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _first_json(conn: dict | None, kind: str) -> dict:
    try:
        return conn[kind][0][0]["json"] or {}
    except (KeyError, IndexError, TypeError):
        return {}


def split_prompt(prompt: str) -> tuple[str | None, list[dict]]:
    """« System: a\\nHuman: b\\nAI: c » → (system, messages). Sans préfixe : un seul message user."""
    marks = list(ROLE_LINE.finditer(prompt))
    if not marks or marks[0].start() != 0:
        return None, [{"role": "user", "content": prompt}]
    system, messages = [], []
    for m, nxt in zip(marks, marks[1:] + [None]):
        text = prompt[m.end(): nxt.start() if nxt else len(prompt)].rstrip("\n")
        role = ROLES[m.group(1)]
        if role == "system":
            system.append(text)
        else:
            messages.append({"role": role, "content": text})
    return ("\n".join(system) or None), messages


def model_of(node: dict, options: dict) -> str | None:
    for key in ("model", "modelName", "model_name"):
        v = options.get(key)
        if isinstance(v, str) and v:
            return v.removeprefix("models/")
    params = node.get("parameters", {})
    for key in ("model", "modelId", "modelName"):
        v = params.get(key)
        if isinstance(v, dict):
            v = v.get("value") or v.get("cachedResultName")
        if isinstance(v, str) and v and not v.startswith("="):
            return v.removeprefix("models/")
    return None


def _tool_nodes(wf: dict) -> dict[str, str]:
    """nœud outil → nœud racine qui l'utilise (connexions ai_tool)."""
    out = {}
    for src, conns in (wf.get("connections") or {}).items():
        for branch in conns.get("ai_tool", []) or []:
            for c in branch or []:
                out[src] = c.get("node")
    return out


class Stats:
    """B1.3 : ce qu'on a lu, ce qu'on a deviné, ce qu'on n'a pas su lire."""

    def __init__(self):
        self.executions = 0
        self.llm_runs = 0
        self.events = 0
        self.real_tokens = 0
        self.estimated_tokens = 0
        self.no_tokens = 0
        self.errors = 0
        self.unknown_model = 0
        self.unknown_provider: set[str] = set()
        self.skipped: dict[str, int] = {}

    def skip(self, reason: str):
        self.skipped[reason] = self.skipped.get(reason, 0) + 1

    def as_dict(self) -> dict:
        understood = self.real_tokens + self.estimated_tokens + self.errors
        return {
            "executions": self.executions,
            "appels_llm_vus": self.llm_runs,
            "evenements": self.events,
            "jetons_reels": self.real_tokens,
            "jetons_estimes": self.estimated_tokens,
            "sans_jetons": self.no_tokens,
            "erreurs": self.errors,
            "modele_inconnu": self.unknown_model,
            "fournisseur_devine": sorted(self.unknown_provider),
            "ignores": self.skipped,
            "taux_compris": round(understood / self.llm_runs, 3) if self.llm_runs else None,
        }


def convert_execution(wf: dict, ex: dict, stats: Stats) -> list[dict]:
    stats.executions += 1
    run_data = (((ex.get("data") or {}).get("resultData") or {}).get("runData")) or {}
    nodes = {n["name"]: n for n in wf.get("nodes", [])}
    tools = _tool_nodes(wf)
    wf_label = wf.get("name") or str(wf.get("id"))

    # exécutions d'outils par nœud racine, pour reconstituer les appels d'outils
    tool_runs: dict[str, list[tuple[float, dict]]] = {}
    for name, root in tools.items():
        for run in run_data.get(name, []):
            args = _first_json(run.get("inputOverride"), "ai_tool") or _first_json(run.get("data"), "ai_tool")
            tool_runs.setdefault(root, []).append((run.get("startTime") or 0, {
                "id": None, "name": name, "arguments": json.dumps(args.get("query", args), ensure_ascii=False)}))

    events = []
    for name, runs in run_data.items():
        node = nodes.get(name)
        if node is None:
            stats.skip("nœud absent du workflow")
            continue
        if not is_llm_node(node):
            continue
        for index, run in enumerate(runs):
            stats.llm_runs += 1
            ev = (_from_model_node if is_model_node(node) else _from_direct_node)(node, run, stats)
            if ev is None:
                continue
            root = ((run.get("source") or [{}])[0] or {}).get("previousNode") or name
            ev["app_id"] = f"n8n:{wf_label}/{root}"
            ev["event_id"] = f"n8n-{ex.get('id')}-{name}-{index}"
            ev["_root"] = root
            ev["request"]["tools"] = [{"name": t, "description": None, "parameters": None}
                                      for t, r in tools.items() if r == root]
            events.append(ev)

    events.sort(key=lambda e: e["ts_start"])
    for step, ev in enumerate(events):
        ev["trace"] = {"id": f"n8n-{ex.get('id')}", "source": "header", "step": step}
    _attach_tool_calls(events, tool_runs)
    for ev in events:
        del ev["_root"]
    stats.events += len(events)
    return events


def _attach_tool_calls(events: list[dict], tool_runs: dict[str, list[tuple[float, dict]]]):
    """Un outil lancé après un appel LLM du même nœud racine, avant le suivant, a été demandé par lui."""
    for root, runs in tool_runs.items():
        calls = [e for e in events if e["_root"] == root]
        for start, call in sorted(runs, key=lambda r: r[0]):
            owner = None
            for e in calls:
                if _ms(e["ts_end"]) <= start + 1:
                    owner = e
            if owner is not None:
                owner["response"]["tool_calls"].append(call)
                if owner["response"]["finish_reason"] in (None, "stop", "other"):
                    owner["response"]["finish_reason"] = "tool_calls"


def _ms(iso: str) -> float:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000


def _base(node: dict, run: dict, stats: Stats, model: str | None, options: dict) -> dict:
    short = _short(node["type"])
    if short in PROVIDERS:
        provider, upstream = PROVIDERS[short]
    else:
        provider, upstream = "openai", None
        stats.unknown_provider.add(short)
    conf = options.get("configuration") if isinstance(options.get("configuration"), dict) else {}
    base_url = conf.get("baseURL") or options.get("baseUrl") or options.get("baseURL")
    if isinstance(base_url, str) and "://" in base_url:
        upstream = base_url.split("://", 1)[1].split("/", 1)[0]
    if not model:
        stats.unknown_model += 1
    start = run.get("startTime") or 0
    took = run.get("executionTime") or 0
    err = run.get("error")
    return {
        "schema_version": "1",
        "ts_start": _iso(start),
        "ts_end": _iso(start + took),
        "latency_ms": took,
        "ttft_ms": None,
        "provider": provider,
        "upstream": upstream,
        "endpoint": node["type"],
        "model": model or "unknown",
        "model_resolved": None,
        "http_status": _http_status(err),
        "error": {"type": str(err.get("name") or "error"), "message": str(err.get("message") or "")} if err else None,
    }


def _http_status(err) -> int:
    if not err:
        return 200
    for key in ("httpCode", "status", "statusCode"):
        try:
            return int(err.get(key))
        except (TypeError, ValueError):
            continue
    return 500


def _params(options: dict) -> dict:
    def num(*keys):
        for k in keys:
            if isinstance(options.get(k), (int, float)) and not isinstance(options.get(k), bool):
                return options[k]
        return None
    max_tokens = num("maxTokens", "max_tokens", "maxOutputTokens")
    return {"stream": bool(options.get("streaming")), "temperature": num("temperature"), "top_p": num("topP", "top_p"),
            "max_tokens": int(max_tokens) if max_tokens is not None and max_tokens > 0 else None,
            "stop": None, "response_format": None}


def _usage(out: dict, stats: Stats, failed: bool = False) -> dict:
    real, est = out.get("tokenUsage"), out.get("tokenUsageEstimate")
    usage = real if isinstance(real, dict) else est if isinstance(est, dict) else None
    if failed and not usage:
        stats.errors += 1
    elif usage is real and usage:
        stats.real_tokens += 1
    elif usage:
        stats.estimated_tokens += 1
    else:
        stats.no_tokens += 1
    usage = usage or {}

    def tok(k):
        v = usage.get(k)
        return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None
    # n8n ne sépare pas la part servie par le cache (promptTokens la contient) : champ omis,
    # le chiffrage compte alors tout au prix plein, un plafond plutôt qu'un coût inconnu
    return {"input_tokens": tok("promptTokens"), "output_tokens": tok("completionTokens")}


def _from_model_node(node: dict, run: dict, stats: Stats) -> dict | None:
    inp = _first_json(run.get("inputOverride"), "ai_languageModel")
    out = _first_json(run.get("data"), "ai_languageModel")
    options = inp.get("options") if isinstance(inp.get("options"), dict) else {}
    if not inp and not out and not run.get("error"):
        stats.skip("appel sans entrée ni sortie")
        return None

    prompts = inp.get("messages") or []
    prompt = prompts[0] if isinstance(prompts, list) and prompts else prompts if isinstance(prompts, str) else ""
    if not isinstance(prompt, str):
        prompt = json.dumps(prompt, ensure_ascii=False)
    system, messages = split_prompt(prompt) if prompt else (None, [])

    gens = ((out.get("response") or {}).get("generations")) or []
    first = gens[0][0] if gens and gens[0] else {}
    info = first.get("generationInfo") or {}
    raw = info.get("finish_reason") or info.get("stop_reason") or info.get("finishReason")

    ev = _base(node, run, stats, model_of(node, options), options)
    ev["request"] = {"system": system, "messages": messages, "tools": [], "params": _params(options)}
    ev["response"] = {"content": first.get("text"), "tool_calls": [],
                      "finish_reason": "error" if run.get("error") else FINISH.get(raw, "other" if raw else None),
                      "finish_reason_raw": raw}
    ev["usage"] = _usage(out, stats, failed=bool(run.get("error")))
    return ev


def _from_direct_node(node: dict, run: dict, stats: Stats) -> dict | None:
    """Nœud qui appelle le fournisseur lui-même (nœud « OpenAI », « Anthropic »…) : sortie main."""
    out = _first_json(run.get("data"), "main")
    params = node.get("parameters", {})
    msg = out.get("message") if isinstance(out.get("message"), dict) else {}
    content = msg.get("content") if isinstance(msg.get("content"), str) else out.get("text") or out.get("content")
    raw_usage = out.get("usage") or {}
    ev = _base(node, run, stats, model_of(node, {}), {})
    prompts = ((params.get("messages") or {}).get("values")) or []
    prompts = [p for p in prompts if isinstance(p, dict)]
    system = "\n".join(p.get("content") or "" for p in prompts if p.get("role") == "system") or None
    messages = [{"role": p["role"] if p.get("role") in ("assistant", "tool") else "user", "content": p.get("content")}
                for p in prompts if p.get("role") != "system"]
    ev["request"] = {"system": system, "messages": messages, "tools": [], "params": _params(params.get("options") or {})}
    ev["response"] = {"content": content if isinstance(content, str) else None, "tool_calls": [],
                      "finish_reason": "error" if run.get("error") else FINISH.get(out.get("finish_reason"), None),
                      "finish_reason_raw": out.get("finish_reason")}
    tokens = {"promptTokens": raw_usage.get("prompt_tokens", raw_usage.get("input_tokens")),
              "completionTokens": raw_usage.get("completion_tokens", raw_usage.get("output_tokens"))}
    ev["usage"] = _usage({"tokenUsage": tokens} if tokens["promptTokens"] is not None else {}, stats,
                         failed=bool(run.get("error")))
    return ev


def convert(wf: dict, executions, stats: Stats | None = None) -> tuple[list[dict], Stats]:
    stats = stats or Stats()
    events = []
    for ex in executions:
        events.extend(convert_execution(wf, ex, stats))
    return events, stats

