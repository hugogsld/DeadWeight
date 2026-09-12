#!/usr/bin/env bash
# Deadweight, une passe complete : scan -> patch -> preuve -> Slack
set -e
sep () { printf '\n\033[1m── %s ─────────────────────────────────────\033[0m\n' "$1"; }

sep "1/5  SCAN     entropie des noeuds LLM sur l'historique reel"
python3 detector/scan.py "$@"

sep "2/5  PATCH    generation du workflow corrige"
python3 patcher/patch.py fixtures/finding.json ${DW_NO_LLM:+--no-llm}

sep "3/5  VALIDATE n8n accepte-t-il le patch ?"
python3 patcher/validate_reimport.py out/patch.json

sep "4/5  PROVE    replay des inputs reels, verdict"
python3 prover/prove.py out/patch.json fixtures/finding.json

cp out/proof.json fixtures/proof.json
cp out/patch.json fixtures/patch.json

sep "5/5  NOTIFY   revue postee dans Slack"
python3 habitat/notify.py out/proof.json fixtures/finding.json

printf '\n\033[1mfini.\033[0m  verdict: %s\n\n' "$(python3 -c "import json;print(json.load(open('out/proof.json'))['verdict'].upper())")"
