"""Execute predeclared independent MQTT episodes through management network."""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, '/app')
from lab import RPC

ROOT = Path('/results')
ARTIFACTS = Path('/artifacts')
PORT = 18500


def main():
    phase = sys.argv[1]
    plan = json.loads((ARTIFACTS / 'episode-plan.json').read_text())
    if phase == 'system':
        episodes = plan['system_episodes']
    elif phase == 'smoke-model':
        base_config = next(e for e in plan['dataset_episodes'] if e['episode_id'] == 'commissioning-002')
        episodes = [{**base_config, 'episode_id': f'smoke-model-{mode}', 'mode': mode,
                     'delay_ms': 50, 'model_id': 'fedmlp-noniid-p42-s42'} for mode in ['local', 'central']]
    else:
        episodes = [e for e in plan['dataset_episodes'] if e['split'] == phase]
    clients = {role: RPC(address, PORT, timeout=15) for role, address in
               [('edge', '172.30.98.2'), ('broker', '172.30.98.20'), ('controller', '172.30.98.3'),
                ('source0', '172.30.98.10'), ('source1', '172.30.98.11'), ('source2', '172.30.98.12')]}
    clocks = {}
    for role, client in clients.items():
        deadline = time.monotonic() + 60
        while True:
            try:
                clocks[role] = client.call('ping')
                break
            except Exception:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.1)
    assert len({c['kernel_boot_id'] for c in clocks.values()}) == 1
    assert len({c['clock_offsets'] for c in clocks.values()}) == 1, 'Unequal monotonic clock offsets'
    base = ROOT / 'v1'
    base.mkdir(exist_ok=True)
    (base / 'clock-domains.json').write_text(json.dumps(clocks, indent=2))
    for index, config in enumerate(episodes):
        target = base / config['episode_id']
        if (target / 'COMPLETED.json').exists():
            print(f'Skip completed {config["episode_id"]}', flush=True)
            continue
        if target.exists():
            raise RuntimeError(f'Incomplete episode retained at {target}; do not silently overwrite it.')
        target.mkdir()
        config = {**config, 'relative_path': f'v1/{config["episode_id"]}', 'start_ns': time.monotonic_ns() + 2_000_000_000}
        (target / 'config.json').write_text(json.dumps(config, indent=2))
        try:
            delay = config.get('delay_ms', 0)
            clients['controller'].call('configure', delay_ms=delay)
            calibration = clients['edge'].call('configure', delay_ms=delay)
            (target / 'calibration.json').write_text(json.dumps(calibration, indent=2))
            clients['broker'].call('start', config=config)
            clients['edge'].call('start', config=config)
            if config.get('outage'):
                clients['edge'].call('outage')
            for source in range(3):
                clients[f'source{source}'].call('start', config=config)
            # This waits for a bounded episode; no wall-clock waits over 60 s.
            remaining = (config['start_ns'] + int((config['duration'] + 0.3) * 1e9) - time.monotonic_ns()) / 1e9
            time.sleep(max(remaining, 0))
            for source in range(3):
                clients[f'source{source}'].call('stop')
            clients['edge'].call('stop')
            clients['broker'].call('stop')
            required = ['ingress-events.json', 'egress-events.json', 'windows.json', 'subscriber.json',
                        'source-0.json', 'source-1.json', 'source-2.json', 'edge-resources.json']
            assert all((target / name).exists() for name in required), 'Incomplete episode artifacts'
            (target / 'COMPLETED.json').write_text(json.dumps({'completed': True, 'required_files': required}))
            print(f'{phase} {index+1}/{len(episodes)} {config["episode_id"]} captured', flush=True)
        except Exception as error:
            (target / 'FAILED.json').write_text(json.dumps({'error': repr(error)}))
            raise
        finally:
            for role in ['source0', 'source1', 'source2', 'edge', 'broker']:
                try:
                    clients[role].call('stop')
                except Exception:
                    pass
    print(f'{phase} completed: {len(episodes)} independent episodes.', flush=True)


if __name__ == '__main__':
    main()
