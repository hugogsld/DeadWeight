"""A1.5 — Rapport d'audit mené par l'agent. Même entrée et même sortie que report.audit.

    python -m agent.audit events.jsonl -o out/audit.html

Avec DW_LLM_API_KEY (la clé du client, dans .env.local), l'agent enquête et publie un plan
d'action ; sans clé, le rapport est celui de report.audit, sans agent.
DW_LLM_BASE_URL (défaut https://api.openai.com/v1), DW_AGENT_MODEL (défaut gpt-5-mini).
"""
import argparse
import json
import os
from pathlib import Path

from agent.loop import OpenAIChatTools, run_agent
from agent.tools import AuditTools
from proof.extract import OpenAICompatibleLLM
from report.audit import build_report, load_banc, render_html

DEFAULT_MODEL = "gpt-5-mini"


def audit(events, llm=None, extract_llm=None, model_name=None, banc=None):
    """Rapport + section agent. Sans llm, rapport déterministe. banc : verdicts de python -m bench m2."""
    events = list(events)
    report = build_report(events, banc=banc)
    if llm is not None and events:
        report["agent"] = run_agent(AuditTools(events, llm=extract_llm), llm, model_name=model_name)
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description="Rapport d'audit mené par l'agent auditeur")
    ap.add_argument("events", help="fichier .jsonl d'événements")
    ap.add_argument("-o", "--out", default="out/audit.html")
    ap.add_argument("--journal", help="écrit aussi le journal de l'agent (JSON)")
    ap.add_argument("--banc", help="dossier des verdicts du banc (python -m bench m2), ex. out/banc")
    args = ap.parse_args(argv)
    events = [json.loads(line) for line in Path(args.events).read_text(encoding="utf-8").splitlines() if line.strip()]
    key = os.environ.get("DW_LLM_API_KEY")
    base = os.environ.get("DW_LLM_BASE_URL", "https://api.openai.com/v1")
    model = os.environ.get("DW_AGENT_MODEL", DEFAULT_MODEL)
    llm = OpenAIChatTools(base, key, model) if key else None
    extract_llm = OpenAICompatibleLLM(base, key, model) if key else None
    report = audit(events, llm, extract_llm, model, banc=load_banc(args.banc))
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
