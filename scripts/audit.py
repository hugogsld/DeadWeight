"""Export SQLite puis rapport HTML, sans conserver une copie des prompts en JSONL."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile

NEXT_STEPS = (
    'Lancez make dev, réglez le base_url de votre application sur '
    'http://127.0.0.1:8080/v1, envoyez des appels puis relancez make audit. '
    'Vérifiez GATEWAY_DB dans .env.local si vous utilisez une autre base.'
)


def audit(db, output, banc=None):
    """Utilise les deux CLI publiques ; conserve l'ancien rapport en cas d'échec."""
    db, output = Path(db), Path(output)
    if not db.is_file():
        print(f'Base absente : {db}. {NEXT_STEPS}', file=sys.stderr)
        return 1
    try:
        with tempfile.TemporaryDirectory(prefix='deadweight-audit-') as temporary:
            events = Path(temporary) / 'events.jsonl'
            with events.open('w', encoding='utf-8') as stream:
                exported = subprocess.run(
                    [sys.executable, '-m', 'gateway.store', 'export', '--db', str(db)],
                    stdout=stream, stderr=subprocess.PIPE, text=True,
                )
            if exported.returncode:
                print(f'Impossible de lire la base {db}. Vérifiez GATEWAY_DB et les droits '
                      'de lecture ; la base doit être une base DeadWeight valide.', file=sys.stderr)
                return 1
            if not events.stat().st_size:
                print(f'Aucun appel capturé dans {db}. {NEXT_STEPS}', file=sys.stderr)
                return 1
            output.parent.mkdir(parents=True, exist_ok=True)
            # Même système de fichiers que le rapport pour une publication atomique.
            with tempfile.TemporaryDirectory(prefix='.audit-', dir=output.parent) as stage:
                staged = Path(stage) / 'audit.html'
                rendered = subprocess.run(
                    [sys.executable, '-m', 'agent.audit', str(events), '-o', str(staged),
                     *(['--banc', str(banc)] if banc and Path(banc).is_dir() else [])],
                    capture_output=True, text=True,
                )
                if rendered.returncode:
                    print('Rapport non généré : vérifiez les événements de la base avec '
                          'python -m gateway.store export et lancez make test.', file=sys.stderr)
                    return 1
                staged.replace(output)
    except OSError:
        print('Impossible de lire ou écrire les fichiers : vérifiez GATEWAY_DB, '
              'le dossier du rapport et vos droits d’accès.', file=sys.stderr)
        return 1
    print(f'Rapport prêt : {output.resolve()}\nOuvrez ce fichier HTML dans votre navigateur.')
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', default=os.environ.get('GATEWAY_DB', 'out/events.db'))
    parser.add_argument('--out', default='out/audit.html')
    parser.add_argument('--banc', default=os.environ.get('AUDIT_BANC', 'out/banc'),
                        help='verdicts du banc (python -m bench m2), lus s’ils existent')
    args = parser.parse_args()
    return audit(args.db, args.out, args.banc)


if __name__ == '__main__':
    sys.exit(main())
