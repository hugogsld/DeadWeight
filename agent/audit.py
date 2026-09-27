"""A1.5 — Rapport d'audit mené par l'agent. Même entrée et même sortie que report.audit.

    python -m agent.audit events.jsonl -o out/audit.html

Avec DW_LLM_API_KEY (la clé du client, dans .env.local), l'agent enquête et publie un plan
d'action ; sans clé, le rapport est celui de report.audit, sans agent.
DW_LLM_BASE_URL (défaut https://api.openai.com/v1), DW_AGENT_MODEL (défaut gpt-5-mini).

Avec --local (ou DW_AUDIT_LOCAL=1), l'agent tourne sur un modèle Ollama de la machine
(DW_LOCAL_BASE_URL, défaut http://localhost:11434/v1 ; DW_LOCAL_MODEL, défaut qwen2.5:3b ;
DW_LOCAL_TIMEOUT, délai par appel en secondes, défaut 600) :
aucune clé lue, et tout hôte non local est refusé (agent.local).
"""
import argparse
import json
import os
from pathlib import Path

from agent.local import LOCAL_API_KEY, LOCAL_BASE_URL, LOCAL_MODEL, LOCAL_TIMEOUT, install_network_guard, require_local
from agent.loop import OpenAIChatTools, run_agent
from agent.tools import AuditTools
from proof.extract import OpenAICompatibleLLM
from report.audit import build_report, render_html

DEFAULT_MODEL = "gpt-5-mini"


def audit(events, llm=None, extract_llm=None, model_name=None):
    """Rapport + section agent. Sans llm, rapport déterministe."""
    events = list(events)
    report = build_report(events)
    if llm is not None and events:
        report["agent"] = run_agent(AuditTools(events, llm=extract_llm), llm, model_name=model_name)
        proofs = report["agent"].get("preuves") or {}
        report["constats"] = [{**c, "preuve_agent": proofs.get(c.get("finding_id"))} for c in report["constats"]]
    return report


def llm_config(env, local=False):
    """(base_url, clé, modèle) de l'agent, ou None sans modèle. En local : adresse vérifiée, clé factice."""
    if local or env.get("DW_AUDIT_LOCAL") == "1":
        base = require_local(env.get("DW_LOCAL_BASE_URL", LOCAL_BASE_URL))
        return base, LOCAL_API_KEY, env.get("DW_LOCAL_MODEL", LOCAL_MODEL)
    key = env.get("DW_LLM_API_KEY")
    if not key:
        return None
    return env.get("DW_LLM_BASE_URL", "https://api.openai.com/v1"), key, env.get("DW_AGENT_MODEL", DEFAULT_MODEL)


def local_timeout(env):
    """Délai par appel au modèle local, en secondes (DW_LOCAL_TIMEOUT) : un portable chargé est lent."""
    try:
        value = float(env.get("DW_LOCAL_TIMEOUT", LOCAL_TIMEOUT))
    except ValueError:
        raise SystemExit("DW_LOCAL_TIMEOUT doit être un nombre de secondes") from None
    if value <= 0:
        raise SystemExit("DW_LOCAL_TIMEOUT doit être positif")
    return value


def main(argv=None):
    ap = argparse.ArgumentParser(description="Rapport d'audit mené par l'agent auditeur")
    ap.add_argument("events", help="fichier .jsonl d'événements")
    ap.add_argument("-o", "--out", default="out/audit.html")
    ap.add_argument("--journal", help="écrit aussi le journal de l'agent (JSON)")
    ap.add_argument("--local", action="store_true", help="modèle Ollama local, aucun hôte non local joignable")
    args = ap.parse_args(argv)
    events = [json.loads(line) for line in Path(args.events).read_text(encoding="utf-8").splitlines() if line.strip()]
    config = llm_config(os.environ, args.local)
    local = args.local or os.environ.get("DW_AUDIT_LOCAL") == "1"
    if local:
        install_network_guard()
    base, key, model = config or (None, None, DEFAULT_MODEL)
    llm = OpenAIChatTools(base, key, model, local_timeout(os.environ) if local else 120) if config else None
    extract_llm = OpenAICompatibleLLM(base, key, model) if config else None
    report = audit(events, llm, extract_llm, model)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_html(report), encoding="utf-8")
    agent = report.get("agent")
    if args.journal and agent:
        Path(args.journal).write_text(json.dumps(agent, ensure_ascii=False, indent=1), encoding="utf-8")
    status = f"agent : {agent['statut']}" if agent else "sans agent (DW_LLM_API_KEY absente)"
    print(f"{len(report['constats'])} constat(s), {status}, rapport écrit dans {out}")


if __name__ == "__main__":
    main()
