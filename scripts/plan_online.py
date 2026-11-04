"""Predeclare independent commissioning/train/validation/test episodes."""
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    directory = ROOT / 'data/online'
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / 'episode-plan.json'
    if path.exists() and json.loads(path.read_text())['version'] >= 2:
        print('Existing episode plan retained.')
        return
    episodes = []
    for split, count, seedbase in [('commissioning', 3, 100), ('train', 36, 1000), ('validation', 12, 2000), ('test', 12, 3000)]:
        for index in range(count):
            seed = seedbase + index
            rng = random.Random(seed)
            episodes.append({'episode_id': f'{split}-{index:03d}', 'split': split,
                  'traffic_seed': seed, 'attacker': (index // 3) % 3,
                  'attack_rate': [200, 800, 2500][index % 3] * rng.uniform(0.85, 1.15),
                  'benign_rate': rng.uniform(8, 25), 'benign_burst_rate': rng.uniform(80, 180),
                  'payload_bytes': rng.choice([128, 192, 256]),
                  'duration': 6.0, 'attack_start': 1.125 + rng.random() * 0.25,
                  'attack_end': 3.875,
                  'block_ttl': 1.0, 'model_id': None, 'mode': 'none'})
    scheduler = random.Random(20261107)
    system = []
    # Three independent workload episodes per rate, repeated across conditions.
    # Training/validation/system seeds are disjoint; no test-driven tuning.
    for index in range(9):
        rng = random.Random(4000 + index)
        common = {'traffic_seed': 4000 + index, 'attacker': (index // 3) % 3,
                  'attack_rate': [200, 800, 2500][index % 3] * rng.uniform(0.9, 1.1),
                  'benign_rate': 15.0, 'benign_burst_rate': 120.0,
                  'payload_bytes': rng.choice([128, 192, 256]), 'duration': 6.0,
                  'attack_start': 1.125 + rng.random() * 0.25, 'attack_end': 3.875, 'block_ttl': 1.0,
                  'workload_id': f'workload-{index:02d}', 'rate_level': index % 3}
        for delay in [0, 50]:
            for mode in ['none', 'local', 'central']:
                system.append({**common, 'episode_id': f'system-{index:02d}-d{delay}-{mode}',
                               'split': 'system', 'mode': mode, 'delay_ms': delay,
                               'model_id': 'fedmlp-noniid-p42-s42'})
    # Outage is real 100% loss on the edge-controller control interface.
    for index in range(3):
        for mode in ['local', 'central']:
            rng = random.Random(5000 + index)
            system.append({'episode_id': f'outage-{index}-{mode}', 'split': 'system', 'outage': True,
                           'traffic_seed': 5000 + index, 'attacker': index, 'attack_rate': 800.0,
                           'benign_rate': 15.0, 'benign_burst_rate': 120.0, 'payload_bytes': 192,
                           'duration': 6.0, 'attack_start': 1.125 + rng.random() * 0.25, 'attack_end': 3.875, 'block_ttl': 1.0,
                           'workload_id': f'outage-{index}', 'rate_level': 1, 'mode': mode, 'delay_ms': 0,
                           'model_id': 'fedmlp-noniid-p42-s42'})
    scheduler.shuffle(system)
    plan = {'version': 2, 'window_seconds': 0.25, 'window_holdback_ms': 20,
            'observation_unit': 'active source in a non-overlapping causal 250 ms window',
            'target': 'window containing independently instrumented attack PUBLISH data; legitimate sources stay benign during attack episodes',
            'features_exclude': ['source/destination addresses', 'port numbers', 'payload contents and identifiers', 'episode IDs', 'ground-truth tags'],
            'dataset_episodes': episodes, 'system_episodes': system,
            'system_deployment_choice': 'Fixed FedMLP non-IID partition42/training42; no best-test model selection',
            'limitations': 'Synthetic controlled MQTT publish-flood scenario on one VM; no claim of broad unseen-attack or physical-city generalization.'}
    if path.exists():
        (directory / 'episode-plan-commissioning-v1.json').write_bytes(path.read_bytes())
    path.write_text(json.dumps(plan, indent=2), encoding='utf-8')
    print(f'Frozen plan: {len(episodes)} capture episodes and {len(system)} system episodes')


if __name__ == '__main__':
    main()
