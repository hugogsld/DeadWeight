import json, os, sys, urllib.request

proof = json.load(open(sys.argv[1] if len(sys.argv) > 1 else "out/proof.json"))
find = json.load(open(sys.argv[2] if len(sys.argv) > 2 else "fixtures/finding.json"))
ev = find.get("evidence", {})
ok = proof["verdict"] == "pass"

head = "Deadweight - performance review" if ok else "Deadweight - patch rejected"
verdict = (f":white_check_mark:  *PASS*  ({proof['agreement_rate']:.1%} agreement, "
           f"threshold {proof['threshold']:.0%})") if ok else (
          f":no_entry:  *REJECTED*  ({proof['agreement_rate']:.1%} agreement, below the "
          f"{proof['threshold']:.0%} threshold - this patch is not proposed)")

lat = ("not measured" if not proof.get("p95_before_ms") else
       f"{proof['p95_before_ms']:.0f} ms p95 (median {proof['median_before_ms']:.0f}) "
       f"-> {proof.get('p95_rules_path_ms')} ms on the rule path")
factor = proof.get("cost_factor")

fields = [
    f"*Workflow*\n{proof.get('workflow_name') or find.get('workflow_name', '-')}",
    f"*Node*\n`{proof.get('node_name') or find.get('node_name', '-')}`",
    f"*Evidence*\n{ev.get('distinct_outputs','?')} distinct outputs over "
    f"{ev.get('calls','?')} calls - {ev.get('entropy_bits','?')} bits of entropy",
    f"*Replayed*\n{proof['n_replayed']} real inputs - {proof.get('matched_by_rules','?')} "
    f"by rules, {proof.get('sent_to_fallback','?')} by fallback",
    f"*No model needed for*\n{proof.get('rules_coverage', 0):.0%} of inputs",
    f"*Cost*\n{('x' + str(factor) + ' cheaper') if factor else '-'}",
    f"*Latency*\n{lat}",
]

blocks = [
    {"type": "header", "text": {"type": "plain_text", "text": head}},
    {"type": "section", "text": {"type": "mrkdwn",
        "text": f"*{find.get('title', 'LLM node flagged')}*\n{find.get('proposed_action', '')}"}},
    {"type": "section", "fields": [{"type": "mrkdwn", "text": f} for f in fields[:8]]},
    {"type": "section", "text": {"type": "mrkdwn", "text": verdict}},
]
if ok:
    blocks.append({"type": "actions", "elements": [
        {"type": "button", "text": {"type": "plain_text", "text": "Apply patch"},
         "style": "primary", "value": proof["patch_id"], "action_id": "dw_apply"},
        {"type": "button", "text": {"type": "plain_text", "text": "Ignore"},
         "value": proof["patch_id"], "action_id": "dw_ignore"}]})

payload = {"blocks": blocks, "text": head}
if os.environ.get("DW_DRY_RUN") == "1":
    print(json.dumps(payload, indent=1)[:600]); raise SystemExit
req = urllib.request.Request(os.environ["SLACK_WEBHOOK_URL"],
    data=json.dumps(payload).encode(),
    headers={"Content-Type": "application/json"}, method="POST")
print(urllib.request.urlopen(req).read().decode())
