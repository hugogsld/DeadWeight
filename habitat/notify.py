"""
Filet de securite pour l'end-to-end : poste la revue Deadweight dans Slack
depuis proof.json + finding.json, via un webhook entrant.

    export SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
    python3 habitat/notify.py
"""
import json, os, sys, urllib.request

proof = json.load(open(sys.argv[1] if len(sys.argv) > 1 else "out/proof.json"))
find = json.load(open(sys.argv[2] if len(sys.argv) > 2 else "fixtures/finding.json"))
ev = find.get("evidence", {})

ok = proof["verdict"] == "pass"
head = "Deadweight - performance review" if ok else "Deadweight - patch rejected"
verdict = (f":white_check_mark:  *PASS*  ({proof['agreement_rate']:.1%} agreement, "
           f"threshold {proof['threshold']:.0%})") if ok else (
          f":no_entry:  *REJECTED*  ({proof['agreement_rate']:.1%} agreement, below the "
          f"{proof['threshold']:.0%} threshold - not proposing this patch)")

factor = proof.get("cost_factor")
fields = [
    f"*Workflow*\n{find.get('workflow_name', '-')}",
    f"*Node*\n`{find.get('node_name', '-')}`",
    f"*Evidence*\n{ev.get('distinct_outputs','?')} distinct outputs over "
    f"{ev.get('calls','?')} calls - {ev.get('entropy_bits','?')} bits of entropy",
    f"*Replayed*\n{proof['n_replayed']} real past inputs - "
    f"{proof.get('matched_by_rules','?')} by rules, {proof.get('sent_to_fallback','?')} by fallback",
    f"*Cost*\n{('x' + str(factor) + ' cheaper') if factor else '-'}",
    f"*p95 latency*\n{proof['p95_before_ms']:.0f} ms -> {proof['p95_after_ms']:.0f} ms",
]

blocks = [
    {"type": "header", "text": {"type": "plain_text", "text": head}},
    {"type": "section", "text": {"type": "mrkdwn", "text":
        f"*{find.get('title', 'LLM node flagged')}*\n{find.get('proposed_action', '')}"}},
    {"type": "section", "fields": [{"type": "mrkdwn", "text": f} for f in fields]},
    {"type": "section", "text": {"type": "mrkdwn", "text": verdict}},
]
if ok:
    blocks.append({"type": "actions", "elements": [
        {"type": "button", "text": {"type": "plain_text", "text": "Apply patch"},
         "style": "primary", "value": proof["patch_id"], "action_id": "dw_apply"},
        {"type": "button", "text": {"type": "plain_text", "text": "Ignore"},
         "value": proof["patch_id"], "action_id": "dw_ignore"},
    ]})

payload = {"blocks": blocks, "text": head}
if os.environ.get("DW_DRY_RUN") == "1":
    print(json.dumps(payload, indent=1)[:800]); raise SystemExit
req = urllib.request.Request(os.environ["SLACK_WEBHOOK_URL"],
    data=json.dumps(payload).encode(),
    headers={"Content-Type": "application/json"}, method="POST")
print(urllib.request.urlopen(req).read().decode())
