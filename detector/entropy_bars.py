"""How much information each LLM node actually produces, from out/profile.json."""
import json, math, os, sys
W = 30
BOLD, DIM, CYA, GRN, OFF = "\033[1m", "\033[2m", "\033[36m", "\033[32m", "\033[0m"

def bar(r, w=W):
    f = int(round(r * w)); return "\u2588" * f + "\u2591" * (w - f)

path = sys.argv[1] if len(sys.argv) > 1 else "out/profile.json"
if not os.path.exists(path):
    raise SystemExit(f"{path} missing - run detector/scan.py first")

print(f"\n{BOLD}INFORMATION ACTUALLY PRODUCED BY EACH LLM NODE{OFF}")
print(f"{DIM}Shannon entropy of outputs, measured on real execution history{OFF}\n")

rows = [(p["name"], n) for p in json.load(open(path)) for n in p.get("nodes", [])]
if not rows:
    raise SystemExit("no LLM node profiled")

for wf, n in sorted(rows, key=lambda r: r[1].get("entropy_bits", 0)):
    ent = float(n.get("entropy_bits") or 0)
    mx = math.log2(max(n.get("calls", 2), 2))
    ratio = min(1.0, ent / mx) if mx else 0
    col = CYA if ratio < .6 else GRN
    tag = ("routing, not reasoning - replaceable by rules" if ratio < .35
           else "borderline - worth a look" if ratio < .6 else "doing real work - keep it")
    print(f"  {BOLD}{n['name'][:26]:26}{OFF} {DIM}{wf[:24]:24}{OFF}")
    print(f"  {col}{bar(ratio)}{OFF}  {ent:>5.2f} / {mx:.2f} bits   "
          f"{col}{ratio:>4.0%}{OFF} {DIM}of what it could say{OFF}")
    print(f"  {DIM}{n.get('distinct_outputs','?')} distinct outputs over "
          f"{n.get('calls','?')} calls{OFF}   {col}{tag}{OFF}")
    outs = n.get("output_samples") or []
    if outs:
        print(f"  {DIM}-> {', '.join(str(o)[:22] for o in outs[:5])}{OFF}")
    print()
