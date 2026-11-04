"""Project entrypoints for the separately versioned online experiment."""
import argparse
import hashlib
import json
import shutil
import subprocess
import os
import ctypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ['docker', 'compose', '-f', str(ROOT / 'online/compose.yaml')]


def run(args):
    subprocess.run(args, cwd=ROOT, check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['collect', 'study', 'smoke', 'system', 'report'])
    args = parser.parse_args()
    if args.action == 'collect':
        for phase in ['train', 'validation', 'test']:
            run(COMPOSE + ['run', '--rm', '-T', 'runner', 'python', 'online/run.py', phase])
    elif args.action == 'study':
        snapshot = ROOT / 'runs/online/provenance-v1'
        snapshot.mkdir(parents=True, exist_ok=True)
        files = list((ROOT / 'online').glob('*.py')) + [ROOT / 'online/compose.yaml', ROOT / 'ONLINE_PROTOCOL.md',
                 ROOT / 'scripts/train_online.py', ROOT / 'scripts/prepare_online.py', ROOT / 'scripts/plan_online.py',
                 ROOT / 'data/online/episode-plan.json']
        checksums = {}
        for path in files:
            name = str(path.relative_to(ROOT))
            target = snapshot / name
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                assert target.read_bytes() == path.read_bytes(), f'Frozen source changed: {name}'
            else:
                shutil.copy2(path, target)
            checksums[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        (snapshot / 'sha256.json').write_text(json.dumps(checksums, indent=2))
        run(['python', '-u', 'scripts/prepare_online.py'])
        run(['python', '-u', 'scripts/train_online.py'])
    elif args.action in ['smoke', 'system']:
        run(COMPOSE + ['run', '--rm', '-T', 'runner', 'python', 'online/run.py',
                       'smoke-model' if args.action == 'smoke' else 'system'])
    else:
        run(['python', 'scripts/report_online.py'])


if __name__ == '__main__':
    if os.name == 'nt':
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)
    try:
        main()
    finally:
        if os.name == 'nt':
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
