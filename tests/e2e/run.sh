#!/bin/bash
# Boucle complète de bout en bout (Q1) : installation, démo, passerelle réelle avec les trois
# fournisseurs simulés, capture, traces, rapport, rejeu, miroir, court-circuit.
# Aucune vraie clé, aucun réseau externe. Lancé par `make e2e` et par la CI.
set -u
E2E=$(cd "$(dirname "$0")" && pwd)
cd "$E2E/../.." || exit 1
rm -rf out/e2e && mkdir -p out/e2e
ok() { echo "  OK   $*"; }
ko() { echo "  ÉCHEC $*"; FAILS=$((FAILS+1)); }
FAILS=0
PY=.venv/bin/python
KEY=sk-e2e-NE-DOIT-JAMAIS-SORTIR

echo "== 1. Installation ($(git log --oneline -1))"
T0=$(date +%s); make install >/dev/null 2>&1 && ok "make install ($(( $(date +%s)-T0 )) s)" || ko "make install"

echo "== 2. Démo sans clé"
make demo 2>&1 | grep -q "Démo terminée" && ok "make demo" || ko "make demo"
grep -q "coût observé total" "$(ls -td out/demo-*/ | head -1)audit.html" && ok "démo : coût observé (pas de projection absurde)" || ko "démo : chiffre de coût"

echo "== 3. Passerelle réelle + trafic des trois fournisseurs"
PYTHONPATH=. $PY "$E2E/fakes.py" 9301 > out/e2e/fakes.log 2>&1 &
FAKES=$!
GW=
trap 'kill $FAKES $GW 2>/dev/null' EXIT  # rien ne reste en arrière-plan, même en cas d'échec
sleep 1.5
start_gw() {  # $1 = port, reste = variables d'environnement
  local port=$1; shift
  env GATEWAY_PORT=$port GATEWAY_OPENAI_UPSTREAM=http://127.0.0.1:9301 \
      GATEWAY_ANTHROPIC_UPSTREAM=http://127.0.0.1:9302 GATEWAY_GEMINI_UPSTREAM=http://127.0.0.1:9303 \
      "$@" $PY -m gateway > "out/e2e/gw$port.log" 2>&1 &
  GW=$!
  for _ in $(seq 50); do curl -s -o /dev/null "http://127.0.0.1:$port/v1/models" && return; sleep 0.2; done
}
start_gw 9310 GATEWAY_DB=out/e2e/e2e.db
OUT=$($PY "$E2E/traffic.py" http://127.0.0.1:9310 full 2>&1 | tail -1); echo "       trafic : $OUT"
kill -TERM $GW; wait $GW 2>/dev/null
N=$($PY -m gateway.store count --db out/e2e/e2e.db); [ "$N" = 68 ] && ok "68 appels relayés = 68 événements en base" || ko "événements en base : $N (attendu 68)"
$PY - <<'PY' && ok "3 fournisseurs, schéma valide, boucle regroupée en une trace de 8" || ko "contenu de la base"
import json, jsonschema
from collections import Counter
from gateway.store import read_events
from gateway.traces import assign_traces
ev = assign_traces(read_events("out/e2e/e2e.db"))
schema = json.load(open("schemas/event.schema.json"))
for e in ev: jsonschema.validate(e, schema)
prov = Counter(e["provider"] for e in ev)
assert prov == {"openai": 58, "anthropic": 5, "gemini": 5}, prov
loop = Counter(e["trace"]["id"] for e in ev if e["app_id"] == "agent")
assert sorted(loop.values()) == [8], loop
PY
if grep -l "$KEY" out/e2e/e2e.db* out/e2e/gw9310.log >/dev/null 2>&1; then ko "la clé apparaît dans la base ou le journal"; else ok "clé absente de la base (et -wal/-shm) et du journal"; fi
env -u DW_LLM_API_KEY $PY -m scripts.audit --db out/e2e/e2e.db --out out/e2e/e2e.html 2>&1 | grep -q "Rapport prêt" && ok "audit (sans clé : jamais d'appel payant en test)" || ko "audit"
$PY - <<'PY'
import re, html
t = open("out/e2e/e2e.html").read()
t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"<style.*?</style>", "", t, flags=re.S))))
i = t.find("appels observés"); print("       rapport :", t[i-4:i+170])
print("       constats :", "; ".join(re.findall(r"Constats, du plus coûteux au moins coûteux (.{0,160})", t)))
PY

echo "== 4. Preuve, miroir, court-circuit"
$PY -m proof.replay fixtures/dataset/v1/events.jsonl --out out/e2e/proofs 2>&1 | grep -E "VERDICT" | sed 's/^/       /'
start_gw 9311 GATEWAY_DB=out/e2e/mirror.db GATEWAY_MIRROR=out/e2e/proofs GATEWAY_MIRROR_LOG=out/e2e/mirror.jsonl
OUT=$($PY "$E2E/traffic.py" http://127.0.0.1:9311 triage 2>&1 | tail -1)
kill -TERM $GW; wait $GW 2>/dev/null
echo "$OUT" | grep -q "\"shortcircuit\": 0" && echo "$OUT" | grep -q "\"openai\": 40" && ok "miroir : 40 appels, aucune réponse remplacée" || ko "miroir : $OUT"
$PY -m gateway.mirror stats --log out/e2e/mirror.jsonl | sed 's/^/       /'
grep -q "Gagnez" out/e2e/mirror.jsonl && ko "contenu client dans le journal du miroir" || ok "journal du miroir sans contenu client"
start_gw 9312 GATEWAY_DB=out/e2e/sc.db GATEWAY_SHORTCIRCUIT=out/e2e/proofs
OUT=$($PY "$E2E/traffic.py" http://127.0.0.1:9312 triage 2>&1 | tail -1); echo "       court-circuit : $OUT"
kill -TERM $GW; wait $GW 2>/dev/null
echo "$OUT" | grep -qE '"shortcircuit": [1-9]' && ok "court-circuit déclenché sur les requêtes couvertes" || ko "court-circuit : $OUT"

kill $FAKES 2>/dev/null
echo "== Résultat : $FAILS échec(s)"
exit $FAILS
