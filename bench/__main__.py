"""CLI du banc de modeles (M2.2) : preuve avant recommandation.

    python -m bench run events.jsonl --app APP --model MODEL \\
        [--template GABARIT] [--candidates small,local] [--max-cases 50] \\
        [--max-calls 50] [--min-interval 1] [--dry-run] [--out out/bench.json]

--dry-run n'emet aucun appel : il affiche ce qui serait appele et un cout estime.
"""
import argparse
import json
import sys
from pathlib import Path

from bench.catalog import load_candidates
from bench.pricing import load_prices
from bench.report import dry_run_estimate, rank, to_dict
from bench.runner import DEFAULT_MIN_INTERVAL_S, Throttle, run_candidate
from bench.scoring import detect_task_type, threshold_for
from bench.testset import DEFAULT_MAX_CASES, build_test_cases


def _load_events(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


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
                     help='classes de taille separees par des virgules (small,local,medium)')
    run.add_argument('--max-cases', type=int, default=DEFAULT_MAX_CASES)
    run.add_argument('--max-calls', type=int, default=None)
    run.add_argument('--min-interval', type=float, default=DEFAULT_MIN_INTERVAL_S)
    run.add_argument('--dry-run', action='store_true')
    run.add_argument('--out', default=None, help='ecrit le rapport JSON a ce chemin')
    args = ap.parse_args(argv)

    events = _load_events(args.events)
    cases = build_test_cases(events, args.app, args.model, args.template, args.max_cases)
    if not cases:
        print(f'aucun cas exploitable pour {args.app}/{args.model}', file=sys.stderr)
        return 1
    task_type = detect_task_type(cases)
    size_classes = args.candidates.split(',') if args.candidates else None
    candidates = load_candidates(size_classes=size_classes)
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


if __name__ == '__main__':
    sys.exit(main())
