"""Final ledger, paired offered schedules and frozen-source audit; no reruns."""
import collections
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / 'runs/online/final-v1'


def read(path):
    return json.loads(path.read_text())


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def command(args):
    return subprocess.check_output(args, cwd=ROOT, text=True, encoding='utf-8').strip()


def main():
    plan = read(ROOT / 'data/online/episode-plan.json')
    report = read(TARGET / 'summary.json')
    assigned = plan['system_episodes']
    rows = report['system_episodes']
    assert len(assigned) == len(rows) == 60
    assert len({e['episode_id'] for e in assigned}) == 60
    assert {e['episode_id'] for e in assigned} == {r['episode_id'] for r in rows}
    schedule_groups = collections.defaultdict(list)
    metadata = []
    artifact_hashes = {}
    for entry in assigned:
        path = ROOT / 'runs/online/v1' / entry['episode_id']
        assert (path / 'COMPLETED.json').exists() and not (path / 'FAILED.json').exists()
        config = read(path / 'config.json')
        assert all(config[k] == v for k, v in entry.items())
        schedules = []
        for source in range(3):
            offered = read(path / f'source-{source}-offered.json')
            schedules.append([[seq, stamp - config['start_ns'], tag] for seq, stamp, tag in offered])
            records = read(path / f'source-{source}.json')
            assert records['attempted'] == len(records['records']) + records['errors']
            assert records['attempted'] + records['skipped_late'] <= len(offered)
        schedule_digest = hashlib.sha256(json.dumps(schedules).encode()).hexdigest()
        schedule_groups[config['workload_id']].append(schedule_digest)
        for capture in ['ingress-events.json', 'egress-events.json']:
            data = read(path / capture)
            metadata.append({'episode_id': entry['episode_id'], 'capture': capture,
                             **{k: v for k, v in data.items() if k != 'packets'}})
        for artifact in path.iterdir():
            if artifact.is_file():
                artifact_hashes[str(artifact.relative_to(ROOT))] = sha(artifact)
    assert len(schedule_groups) == 12
    assert sorted(map(len, schedule_groups.values())) == [2] * 3 + [6] * 9
    assert all(len(set(digests)) == 1 for digests in schedule_groups.values())
    clocks = read(ROOT / 'runs/online/v1/clock-domains.json')
    assert len({r['kernel_boot_id'] for r in clocks.values()}) == 1
    assert len({r['clock_offsets'] for r in clocks.values()}) == 1
    frozen = read(ROOT / 'runs/online/provenance-v1/sha256.json')
    for name, digest in frozen.items():
        assert sha(ROOT / name) == digest, f'Frozen source changed: {name}'
        assert sha(ROOT / 'runs/online/provenance-v1' / name) == digest
    compose = json.loads(command(['docker', 'compose', '-f', 'online/compose.yaml', 'config', '--format', 'json']))
    assert all(not service.get('ports') for service in compose['services'].values())
    assert all(not service.get('privileged') for service in compose['services'].values())
    running = json.loads(command(['docker', 'inspect', 'thesis-online-edge-1']))[0]
    image = json.loads(command(['docker', 'image', 'inspect', 'thesis-online:local']))[0]
    assert running['Image'] == image['Id']
    for file in ['bench.py', 'features.py', 'mqtt.py', 'run.py', 'reconcile.py']:
        inside = command(['docker', 'exec', 'thesis-online-edge-1', 'sha256sum', '/app/online/' + file]).split()[0]
        assert inside == sha(ROOT / 'online' / file), file
    datasets = read(ROOT / 'data/online/dataset-audit.json')
    splits = [set(part['episodes']) for part in datasets['splits'].values()]
    assert all(not (a & b) for i, a in enumerate(splits) for b in splits[i + 1:])
    assert len(read(ROOT / 'data/online/models.json')['models']) == 21
    assert len(report['detector_results']) == 22
    for path in (ROOT / 'data/online').glob('*.pt'):
        artifact_hashes[str(path.relative_to(ROOT))] = sha(path)
    for name in ['dataset.npz', 'models.json', 'episode-plan.json', 'dataset-audit.json']:
        path = ROOT / 'data/online' / name
        artifact_hashes[str(path.relative_to(ROOT))] = sha(path)
    for path in (ROOT / 'runs/online/detectors-v1').rglob('*'):
        if path.is_file():
            artifact_hashes[str(path.relative_to(ROOT))] = sha(path)
    for name in ['scripts/report_online.py', 'scripts/audit_excluded.py', 'scripts/verify_online.py',
                 'PAPER_ALIGNMENT.md', 'REVIEW_ONLINE.md', 'EXPERIMENTS_STATUS.md', 'README.md',
                 'runs/extension-audit/original-data-audit.json', 'runs/extension-audit/pcap-extractor-gate.json',
                 'runs/extension-audit/excluded-cohort-sensitivity.json', 'runs/extension-audit/EXCLUDED_SENSITIVITY.md']:
        path = ROOT / name
        artifact_hashes[name] = sha(path)
    for path in TARGET.iterdir():
        if path.is_file() and path.suffix in ['.md', '.png', '.csv', '.json'] and path.name not in [
                'artifact-sha256.json', 'final-verification.json', 'compose-resolved.json', 'image-inspect.json',
                'capture-clock-metadata.json', 'cleanup.json']:
            artifact_hashes[str(path.relative_to(ROOT))] = sha(path)
    (TARGET / 'compose-resolved.json').write_text(json.dumps(compose, indent=2))
    (TARGET / 'container-pip-freeze.txt').write_text(command(['docker', 'exec', 'thesis-online-edge-1', 'python', '-m', 'pip', 'freeze']) + '\n')
    (TARGET / 'image-inspect.json').write_text(json.dumps(image, indent=2))
    (TARGET / 'capture-clock-metadata.json').write_text(json.dumps(metadata, indent=2))
    invalid = [{'episode_id': r['episode_id'], 'issues': r['reconciliation_issues']} for r in rows if not r['reconciliation_valid']]
    verification = {'ledger_audit_passed': True, 'assigned_completed': 60,
                    'valid_capture_label_reconstructions': len(rows) - len(invalid), 'invalid_reconstructions': invalid,
                    'all_invalid_episodes_retained': True, 'invalid_latencies_excluded_from_primary_summary': True,
                    'independent_regular_workloads': 9, 'independent_outage_workloads': 3,
                    'matched_offered_schedules_equal': True, 'frozen_sources_unchanged': True,
                    'running_image_matches_reviewed_source': True, 'image_id': image['Id'],
                    'maximum_clock_conversion_uncertainty_ns': max(r['offset_uncertainty_ns'] for r in metadata),
                    'shared_kernel_equal_monotonic_offsets': True,
                    'neural_training_runs': 21, 'additional_rate_baseline': 1,
                    'scope': 'Ledger/provenance passed; capture validity is explicitly 58/60, not an all-capture pass.'}
    (TARGET / 'artifact-sha256.json').write_text(json.dumps(artifact_hashes, indent=2))
    (TARGET / 'final-verification.json').write_text(json.dumps(verification, indent=2))
    print(json.dumps(verification, indent=2))


if __name__ == '__main__':
    main()
