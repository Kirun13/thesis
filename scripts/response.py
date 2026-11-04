"""npm-facing Docker orchestration, provenance and bounded experiment execution."""
import argparse
import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ['docker', 'compose', '-f', str(ROOT / 'response/compose.yaml')]


def run(args, capture=False):
    result = subprocess.run(args, cwd=ROOT, text=True, capture_output=capture)
    if result.returncode:
        raise RuntimeError(f'Command failed: {args}; {result.stderr if capture else result.returncode}')
    return result.stdout if capture else None


def checksum(path):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, indent=2), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['smoke', 'run'])
    parser.add_argument('--resume', type=Path)
    args = parser.parse_args()
    base = ROOT / 'runs/response'
    base.mkdir(parents=True, exist_ok=True)
    manifest_path = ROOT / 'data/response/manifest.json'
    if not manifest_path.exists():
        raise RuntimeError('First run npm run response:prepare.')
    if args.action == 'run':
        gate = json.loads((base / 'smoke-latest.json').read_text())
        assert gate['passed']
        assert gate['lab_sha256'] == checksum(ROOT / 'response/lab.py'), 'Code changed after smoke; rerun smoke.'
        assert gate['manifest_sha256'] == checksum(manifest_path), 'Artifacts changed after smoke.'
    profile = 'smoke' if args.action == 'smoke' else 'full'
    target = args.resume.resolve() if args.resume else base / f'{profile}-{datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")}'
    if target.parent != base:
        raise RuntimeError('Run directory must be directly inside runs/response.')
    target.mkdir(exist_ok=True)
    source_files = [ROOT / 'response/lab.py', ROOT / 'response/Dockerfile', ROOT / 'response/compose.yaml',
                    ROOT / 'scripts/response.py', ROOT / 'scripts/report_response.py',
                    ROOT / 'scripts/prepare_response.py', ROOT / 'PLAN_RESPONSE.md', ROOT / 'REVIEW_RESPONSE.md']
    checksums = {str(path.relative_to(ROOT)): checksum(path) for path in source_files}
    if (target / 'source-checksums.json').exists():
        assert json.loads((target / 'source-checksums.json').read_text()) == checksums, 'Source changed since run.'
    else:
        write(target / 'source-checksums.json', checksums)
        for path in source_files:
            copied = target / 'source' / path.relative_to(ROOT)
            copied.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, copied)
        for path in (ROOT / 'data/response').iterdir():
            if path.is_file():
                copied = target / 'artifacts' / path.name
                copied.parent.mkdir(exist_ok=True)
                shutil.copy2(path, copied)
    run(COMPOSE + ['up', '-d', 'edge', 'controller', 'health'])
    write(target / 'docker-image.json', json.loads(run(['docker', 'image', 'inspect', 'thesis-response:local'], capture=True)))
    write(target / 'docker-environment.json', {'docker_info': run(['docker', 'info', '--format', '{{json .}}'], capture=True),
                                              'compose_config': run(COMPOSE + ['config'], capture=True)})
    (target / 'container-packages.txt').write_text(run(COMPOSE + ['exec', '-T', 'edge', 'pip', 'freeze'], capture=True), encoding='utf-8')
    if profile == 'full':
        write(base / 'active.json', {'directory': str(target)})
    if os.name == 'nt':
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)
    try:
        run(COMPOSE + ['run', '--rm', '-T', '--name', f'thesis-response-client-{profile}', 'client',
                       'python', 'lab.py', 'runner', profile, target.name])
    finally:
        if os.name == 'nt':
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
        logs = run(COMPOSE + ['logs', '--no-color', 'edge', 'controller', 'health'], capture=True)
        (target / 'container-logs.txt').write_text(logs, encoding='utf-8')
    if profile == 'smoke':
        result = json.loads((target / 'smoke.json').read_text())
        write(base / 'smoke-latest.json', {'passed': result['passed'], 'directory': str(target),
              'lab_sha256': checksum(ROOT / 'response/lab.py'), 'manifest_sha256': checksum(manifest_path)})
    else:
        write(base / 'active.json', {'directory': str(target)})
        from report_response import report
        report(target)
    print(f'Results saved: {target}', flush=True)


if __name__ == '__main__':
    main()
