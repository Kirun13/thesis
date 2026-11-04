"""Retain all active windows, reconcile labels and split only by whole episodes."""
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'online'))
from features import FEATURES
from reconcile import reconcile


def main():
    destination = ROOT / 'data/online'
    plan = json.loads((destination / 'episode-plan.json').read_text())
    arrays, reports, episode_sets = {}, [], {}
    for split in ['train', 'validation', 'test']:
        rows = []
        episodes = [e for e in plan['dataset_episodes'] if e['split'] == split]
        for episode in episodes:
            path = ROOT / 'runs/online/v1' / episode['episode_id']
            assert (path / 'COMPLETED.json').exists(), f'Not collected: {path}'
            audit = reconcile(path, strict=True)
            reports.append({'episode': episode['episode_id'], **{key: value for key, value in audit.items() if key != 'ingress_attack_packet_indices'}})
            rows.extend(json.loads((path / 'labeled-windows.json').read_text()))
        name = 'val' if split == 'validation' else split
        arrays['raw_' + name] = np.array([row['features'] for row in rows], dtype=np.float32)
        arrays['y_' + name] = np.array([row['label'] for row in rows], dtype=np.int64)
        arrays['episode_' + name] = np.array([row['episode_id'] for row in rows])
        arrays['rate_' + name] = np.array([row['rate_level'] for row in rows])
        episode_sets[name] = set(arrays['episode_' + name])
    for a, b in [('train', 'val'), ('train', 'test'), ('val', 'test')]:
        assert not episode_sets[a] & episode_sets[b]
    means = arrays['raw_train'].mean(axis=0, dtype=np.float64).astype(np.float32)
    scales = arrays['raw_train'].std(axis=0, dtype=np.float64).astype(np.float32)
    scales[scales < 1e-6] = 1
    arrays.update(means=means, scales=scales, features=np.array(FEATURES))
    for name in ['train', 'val', 'test']:
        arrays['x_' + name] = ((arrays['raw_' + name] - means) / scales).astype(np.float32)
    np.savez_compressed(destination / 'dataset.npz', **arrays)
    manifest = {'features': FEATURES, 'split_unit': 'independently executed traffic episode',
                'retained_all_ambiguous_and_repeated_inputs': True, 'label_source': 'generator IDs reconciled to TCP PUBLISH byte ranges',
                'splits': {name: {'windows': len(arrays['y_' + name]), 'positive': int(arrays['y_' + name].sum()),
                                  'episodes': sorted(episode_sets[name])} for name in ['train', 'val', 'test']},
                'episode_audits': reports,
                'plan_sha256': hashlib.sha256((destination / 'episode-plan.json').read_bytes()).hexdigest(),
                'dataset_sha256': hashlib.sha256((destination / 'dataset.npz').read_bytes()).hexdigest()}
    (destination / 'dataset-audit.json').write_text(json.dumps(manifest, indent=2))
    print(json.dumps(manifest['splits'], indent=2))


if __name__ == '__main__':
    main()
