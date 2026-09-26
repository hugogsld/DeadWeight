"""CLI du banc de modeles (M2.2) : preuve avant recommandation.

    python -m bench run events.jsonl --app APP --model MODEL \\
        [--template GABARIT] [--candidates small,local] [--max-cases 50] \\
        [--max-calls 50] [--min-interval 1] [--dry-run] [--out out/bench.json]

    python -m bench m2 events.jsonl --finding FINDING_ID [--max-cases 50] [--max-calls 50] \\
        [--min-interval 1] [--dry-run] [--out out/banc]     # les options de M2 au banc

--dry-run n'emet aucun appel : il affiche ce qui serait appele et un cout estime.
"""
import argparse
import json
import sys
from pathlib import Path

from bench import m2
from bench.catalog import load_candidates, resolve_api_key
from bench.pricing import load_prices
from bench.report import dry_run_estimate, rank, to_dict
from bench.runner import DEFAULT_MIN_INTERVAL_S, Throttle, run_candidate
from bench.scoring import detect_task_type, threshold_for
from bench.testset import DEFAULT_MAX_CASES, build_test_cases


def _load_events(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def _select_candidates(spec):
    """--candidates : classes de taille et/ou identifiants de candidat, separes par des
    virgules, melanges ou non (probleme 17). Sans cle configuree, un candidat est ignore
    par defaut ; demande par son identifiant exact, il est teste quand meme (et obtient alors
    un verdict « non testé » plutôt qu'un rejet, si l'authentification echoue vraiment)."""
    tokens = set(spec.split(',')) if spec else None
    all_candidates = load_candidates()
    candidates = ([c for c in all_candidates if c.id in tokens or c.size_class in tokens]
                  if tokens is not None else all_candidates)
    explicit_ids = {c.id for c in candidates if tokens and c.id in tokens}
    kept, skipped = [], []
    for c in candidates:
        if c.id not in explicit_ids and c.api_key_env is not None and resolve_api_key(c) is None:
            skipped.append(c)
        else:
            kept.append(c)
    return kept, skipped


def _print_dry_run(cases, task_type, candidates, prices):
    plan = [dry_run_estimate(c, cases, prices) for c in candidates]
    print(f'{len(cases)} cas de test, {len(candidates)} candidat(s), tache « {task_type} »\n')
    total = 0.0
    for p in plan:
        cost = p['estimated_cost_usd']
        detail = f"~{cost:.4f} $" if cost is not None else p['note']
        print(f"  {p['candidate_id']:30} {p['n_calls_planned']:>4} appel(s) prevu(s)   {detail}")
        total += cost or 0.0
    print(f'\nTotal estime : ~{total:.4f} $ USD (aucun appel effectue)')


def _print_results(report):
    print(f"{report['n_cases']} cas, tache « {report['task_type']} », "
          f"seuil {report['threshold']:.2f}\n")
    for c in report['candidates']:
        print(f"  {c['candidate_id']:30} {c['verdict']:11} score={c['score']} "
              f"p95={c['latency_p95_ms']}ms cout/1000={c['cost_per_1000_calls_usd']} "
              f"origine={c['origin']}")
        for reason in c['reasons']:
            print(f'      - {reason}')


def _build_report(args, cases, task_type, candidates, prices):
    results = [
        run_candidate(c, cases, task_type,
                      Throttle(args.max_calls or len(cases), args.min_interval), prices)
        for c in candidates
    ]
    return {
        'app_id': args.app, 'model': args.model, 'template': args.template,
        'task_type': task_type, 'threshold': threshold_for(task_type),
        'n_cases': len(cases), 'candidates': [to_dict(r) for r in rank(results)],
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='command', required=True)
    run = sub.add_parser('run', help="teste les candidats sur le trafic reel d'un groupe")
    run.add_argument('events', help='evenements au schema v1 (jsonl)')
    run.add_argument('--app', required=True, dest='app')
    run.add_argument('--model', required=True, dest='model')
    run.add_argument('--template', default=None)
    run.add_argument('--candidates', default=None,
                     help='classes de taille et/ou identifiants de candidat, separes par des virgules '
                          '(ex. small,local ou openai-gpt-5-nano,openai-gpt-5-mini)')
    run.add_argument('--max-cases', type=int, default=DEFAULT_MAX_CASES)
    run.add_argument('--max-calls', type=int, default=None)
    run.add_argument('--min-interval', type=float, default=DEFAULT_MIN_INTERVAL_S)
    run.add_argument('--dry-run', action='store_true')
    run.add_argument('--out', default=None, help='ecrit le rapport JSON a ce chemin')
    opt = sub.add_parser('m2', help="teste les options de recommend() pour un constat « modele trop gros »")
    opt.add_argument('events', help='evenements au schema v1 (jsonl)')
    opt.add_argument('--finding', required=True)
    opt.add_argument('--max-cases', type=int, default=DEFAULT_MAX_CASES)
    opt.add_argument('--max-calls', type=int, default=None)
    opt.add_argument('--min-interval', type=float, default=DEFAULT_MIN_INTERVAL_S)
    opt.add_argument('--dry-run', action='store_true')
    opt.add_argument('--options', default=None,
                     help='options a tester, separees par des virgules (moins_cher,meilleur_compromis,souverain)')
    opt.add_argument('--out', default='out/banc', help='dossier ou ecrire banc-<finding>.json (lu par le rapport)')
    args = ap.parse_args(argv)
    if args.command == 'm2':
        return _m2(args)

    events = _load_events(args.events)
    cases = build_test_cases(events, args.app, args.model, args.template, args.max_cases)
    if not cases:
        print(f'aucun cas exploitable pour {args.app}/{args.model}', file=sys.stderr)
        return 1
    task_type = detect_task_type(cases)
    candidates, skipped = _select_candidates(args.candidates)
    for c in skipped:
        print(f"{c.id} ignoré par défaut : clé absente ({c.api_key_env} non définie)", file=sys.stderr)
    if not candidates:
        print('aucun candidat ne correspond au filtre --candidates', file=sys.stderr)
        return 1
    prices = load_prices()

    if args.dry_run:
        _print_dry_run(cases, task_type, candidates, prices)
        return 0

    report = _build_report(args, cases, task_type, candidates, prices)
    _print_results(report)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(report, indent=2, ensure_ascii=False))
        print(f"\n            -> {args.out}")
    return 0


def _m2(args):
    from rules.oversized_model import detect

    events = _load_events(args.events)
    finding = next((f for f in detect(events) if f['finding_id'] == args.finding), None)
    if finding is None:
        print(f"{args.finding} : aucun constat « modele trop gros » de ce nom", file=sys.stderr)
        return 1
    keys = set(args.options.split(',')) if args.options else None
    if args.dry_run:
        plan = m2.dry_run(events, finding, args.max_cases, keys=keys)
        print(f"{plan['n_cases']} cas de test, aucun appel effectue")
        for key, p in plan['options'].items():
            cost = p['estimated_cost_usd']
            print(f"  {key:20} {p['model']:45} via {p['route'] or 'le moins cher'}  "
                  f"{'~%.4f $' % cost if cost is not None else p['note']}")
        return 0
    result = m2.prove(events, finding, args.max_cases, args.max_calls, args.min_interval, keys=keys)
    if result['raison']:
        print(f"aucune option a tester : {result['raison']}")
    for key, r in result['options'].items():
        print(f"  {key:20} {r['model']:45} {r['verdict']:11} score={r['score']} erreurs={r['n_errors']}")
        for reason in r['reasons']:
            print(f'      - {reason}')
    out = Path(args.out) / f"banc-{args.finding}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"            -> {out} (make audit / python -m report.audit --banc {args.out})")
    return 0


if __name__ == '__main__':
    sys.exit(main())
