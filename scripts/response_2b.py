"""Experiment 2b orchestration: Docker lifecycle, provenance, smoke gates and bounded execution.

    python scripts/response_2b.py build [--host-network]
    python scripts/response_2b.py smoke
    python scripts/response_2b.py run [--resume runs/response_2b/full-...]
    python scripts/response_2b.py rate-smoke      # stage 2, separate profile
    python scripts/response_2b.py rate [--resume ...]
    python scripts/response_2b.py down

Nothing here changes Docker daemon settings. Only the project `thesis-response-2b` is started/stopped.
"""
import argparse
import ctypes
import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ['docker', 'compose', '-f', str(ROOT / 'response_2b/compose.yaml')]
IMAGE = 'thesis-response-2b:local'
# action -> (lab profile, manifest, smoke gate required before the action, gate file written by the action)
ACTIONS = {'smoke': ('smoke', 'manifest.json', None, 'smoke-latest.json'),
           'run': ('full', 'manifest.json', 'smoke-latest.json', None),
           'rate-smoke': ('rate-smoke', 'manifest-rate.json', None, 'rate-smoke-latest.json'),
           'rate': ('rate', 'manifest-rate.json', 'rate-smoke-latest.json', None)}
SOURCE_FILES = ['response_2b/lab_2b.py', 'response_2b/Dockerfile', 'response_2b/compose.yaml',
                'response_2b/PROTOCOL_2B.md', 'scripts/response_2b.py', 'scripts/report_response_2b.py',
                'scripts/prepare_response_2b.py']


def run(args, capture=False):
    result = subprocess.run(args, cwd=ROOT, text=True, capture_output=capture)
    if result.returncode:
        raise RuntimeError(f'Command failed: {args}; {result.stderr if capture else result.returncode}')
    return result.stdout if capture else None


def checksum(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2), encoding='utf-8')


def check_gate(gate_path, lab, manifest):
    """The full run only starts if the matching smoke passed for exactly this code and these artifacts."""
    if not gate_path.exists():
        raise RuntimeError(f'No passed smoke gate ({gate_path.name}); run the matching smoke first.')
    gate = json.loads(gate_path.read_text())
    assert gate['passed'], 'Smoke did not pass.'
    assert gate['lab_sha256'] == checksum(lab), 'Code changed after smoke; rerun smoke.'
    assert gate['manifest_sha256'] == checksum(manifest), 'Artifacts changed after smoke.'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['build', 'down', *ACTIONS])
    parser.add_argument('--resume', type=Path)
    parser.add_argument('--host-network', action='store_true',
                        help='build: run image build steps on the host network (needed when the Docker daemon '
                             'has iptables disabled and containers have no outbound NAT)')
    args = parser.parse_args()
    if args.action == 'build':
        if args.host_network:
            run(['docker', 'build', '--network', 'host', '-t', IMAGE, str(ROOT / 'response_2b')])
        else:
            run(COMPOSE + ['build', 'edge'])
        return
    if args.action == 'down':
        run(COMPOSE + ['down'])
        return
    profile, manifest_name, required_gate, gate_name = ACTIONS[args.action]
    base = ROOT / 'runs/response_2b'
    base.mkdir(parents=True, exist_ok=True)
    os.chmod(base, 0o777)  # containers drop capabilities, so root there cannot write a host-owned 755 folder
    manifest_path = ROOT / 'data/response_2b' / manifest_name
    if not manifest_path.exists():
        raise RuntimeError(f'First run scripts/prepare_response_2b.py ({manifest_name} missing).')
    lab = ROOT / 'response_2b/lab_2b.py'
    if required_gate:
        check_gate(base / required_gate, lab, manifest_path)
    target = args.resume.resolve() if args.resume else base / f'{profile}-{datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")}'
    if target.parent != base:
        raise RuntimeError('Run directory must be directly inside runs/response_2b.')
    target.mkdir(exist_ok=True)
    os.chmod(target, 0o777)
    write(target / 'profile.json', {'profile': profile, 'action': args.action})
    checksums = {name: checksum(ROOT / name) for name in SOURCE_FILES if (ROOT / name).exists()}
    if (target / 'source-checksums.json').exists():
        assert json.loads((target / 'source-checksums.json').read_text()) == checksums, 'Source changed since run.'
    else:
        write(target / 'source-checksums.json', checksums)
        for name in checksums:
            copied = target / 'source' / name
            copied.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, copied)
        for path in (ROOT / 'data/response_2b').iterdir():
            if path.is_file() and path.name != '.gitignore':
                copied = target / 'artifacts' / path.name
                copied.parent.mkdir(exist_ok=True)
                shutil.copy2(path, copied)
    run(COMPOSE + ['up', '-d', 'edge', 'controller', 'health'])
    write(target / 'docker-image.json', json.loads(run(['docker', 'image', 'inspect', IMAGE], capture=True)))
    write(target / 'docker-environment.json', {'docker_info': run(['docker', 'info', '--format', '{{json .}}'], capture=True),
                                              'compose_config': run(COMPOSE + ['config'], capture=True)})
    (target / 'container-packages.txt').write_text(run(COMPOSE + ['exec', '-T', 'edge', 'pip', 'freeze'], capture=True), encoding='utf-8')
    if profile in ['full', 'rate']:
        write(base / 'active.json', {'directory': str(target), 'profile': profile})
    if os.name == 'nt':
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)
    try:
        run(COMPOSE + ['run', '--rm', '-T', '--name', f'thesis-response-2b-client-{profile}', 'client',
                       'python', 'lab_2b.py', 'runner', profile, target.name])
    finally:
        if os.name == 'nt':
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
        logs = run(COMPOSE + ['logs', '--no-color', 'edge', 'controller', 'health'], capture=True)
        (target / 'container-logs.txt').write_text(logs, encoding='utf-8')
    if gate_name:
        result = json.loads((target / 'smoke.json').read_text())
        write(base / gate_name, {'passed': result['passed'], 'directory': str(target),
              'lab_sha256': checksum(lab), 'manifest_sha256': checksum(manifest_path)})
    else:
        from report_response_2b import report
        report(target)
    print(f'Results saved: {target}', flush=True)


if __name__ == '__main__':
    main()
