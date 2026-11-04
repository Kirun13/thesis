"""Freeze deployment artifacts and declare every trial before network execution."""
import hashlib
import json
import random
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import torch

from train import GRUAttention

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / 'data/response'


def digest(path):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def write(path, data):
    path.write_text(json.dumps(data, indent=2, allow_nan=False), encoding='utf-8')


def main():
    TARGET.mkdir(parents=True, exist_ok=True)
    if (TARGET / 'manifest.json').exists():
        print('Frozen response artifacts already exist; verifying rather than overwriting.')
        manifest = json.loads((TARGET / 'manifest.json').read_text())
        for name, checksum in manifest['artifact_checksums'].items():
            assert digest(TARGET / name) == checksum, name
        assert digest(ROOT / 'data/processed/benchmark.npz') == manifest['prepared_data_sha256']
        print('Existing frozen artifacts verified.')
        return
    source = Path(json.loads((ROOT / 'runs/active.json').read_text())['runDir'])
    assert json.loads((source / 'status.json').read_text())['state'] == 'completed'
    path = ROOT / 'data/processed/benchmark.npz'
    data = dict(np.load(path, allow_pickle=False))
    rng = np.random.default_rng(20261104)
    indices = np.concatenate([rng.choice(np.flatnonzero(data['y_test'] == label), 100, replace=False)
                              for label in [0, 1]])
    rng.shuffle(indices)
    observations = [{'observation_id': f'test-{int(index)}', 'test_index': int(index),
                     'processed_row_id': int(data['row_test'][index]),
                     'feature_hash_u64': str(int(data['hash_test'][index])),
                     'label': int(data['y_test'][index]), 'attack_type': str(data['type_test'][index]),
                     'features': data['x_test'][index].tolist()} for index in indices]
    write(TARGET / 'observations.json', observations)
    torch.set_num_threads(1)
    models, smoke = [], {}
    for seed in [42, 43, 44]:
        job = source / f'gru-fedavg-noniid-seed{seed}'
        checkpoint = torch.load(job / 'best.pt', map_location='cpu', weights_only=False)
        result = json.loads((job / 'result.json').read_text())
        assert checkpoint['features'] == data['features'].tolist()
        model = GRUAttention(len(data['features'])).eval()
        model.load_state_dict(checkpoint['model'])
        # Scripting preserves batch-dependent shape operations; no tracing shortcut.
        deployed = torch.jit.freeze(torch.jit.script(model))
        deployed.save(str(TARGET / f'model-{seed}.pt'))
        deployed = torch.jit.load(str(TARGET / f'model-{seed}.pt')).eval()
        with torch.inference_mode():
            x = torch.tensor(data['x_test'][indices])
            reference = torch.sigmoid(model(x)).numpy()
            actual = np.array([torch.sigmoid(deployed(row[None])).item() for row in x])
            error = float(np.max(np.abs(reference - actual)))
            threshold = result['threshold']
            assert error < 1e-5, error
            assert np.array_equal(reference >= threshold, actual >= threshold), 'Export changed decisions'
            vx = torch.tensor(data['x_val'])
            vp = torch.sigmoid(model(vx)).numpy()
        selected_smoke = [int(np.argmin(vp)), int(np.argmax(vp))]
        assert vp[selected_smoke[0]] < threshold <= vp[selected_smoke[1]]
        smoke[str(seed)] = [{'observation_id': f'validation-{index}', 'features': data['x_val'][index].tolist(),
                            'expected_action': 'block' if vp[index] >= threshold else 'allow'}
                           for index in selected_smoke]
        model_info = {'seed': seed, 'recipe': 'gru-fedavg-noniid', 'threshold': threshold,
                      'model_file': f'model-{seed}.pt', 'sha256': digest(TARGET / f'model-{seed}.pt'),
                      'checkpoint_sha256': digest(job / 'best.pt'),
                      'threshold_source_sha256': digest(job / 'result.json'),
                      'export_max_probability_error': error,
                      'expected_probabilities': actual.tolist(), 'threshold_decisions_match': True}
        models.append(model_info)
        print(f'Exported seed {seed}: max probability error {error:.3g}, decisions identical', flush=True)
    write(TARGET / 'smoke-observations.json', smoke)
    scheduler = random.Random(20261105)
    blocks = [(seed, delay, block) for seed in [42, 43, 44]
              for delay in [0, 10, 50] for block in range(10)]
    scheduler.shuffle(blocks)
    ledger = []
    for block_order, (seed, delay, block) in enumerate(blocks):
        positions = list(range(block * 20, (block + 1) * 20))
        scheduler.shuffle(positions)
        orders = [('local', 'central')] * 10 + [('central', 'local')] * 10
        scheduler.shuffle(orders)
        for position, order in zip(positions, orders):
            obs = observations[position]
            pair = f's{seed}-d{delay}-o{position}'
            for mode in order:
                ledger.append({'ordinal': len(ledger), 'trial_id': f'{pair}-{mode}', 'pair_id': pair,
                               'block_id': f's{seed}-d{delay}-b{block}', 'block_order': block_order,
                               'seed': seed, 'delay_ms': delay, 'mode': mode,
                               'observation_index': position, 'observation_id': obs['observation_id']})
    assert len(ledger) == 3600 and len({row['trial_id'] for row in ledger}) == 3600
    with (TARGET / 'ledger.jsonl').open('w', encoding='utf-8') as output:
        output.writelines(json.dumps(row) + '\n' for row in ledger)
    files = ['observations.json', 'smoke-observations.json', 'ledger.jsonl'] + [m['model_file'] for m in models]
    manifest = {'source_run': str(source), 'prepared_data_sha256': digest(path),
                'features': data['features'].tolist(), 'observations': len(observations),
                'attack_type_counts': dict(Counter(obs['attack_type'] for obs in observations)),
                'sampling_seed': 20261104, 'scheduler_seed': 20261105, 'assigned_trials': 3600,
                'models': models, 'artifact_checksums': {name: digest(TARGET / name) for name in files},
                'selection': '100 normal and 100 attack test records sampled independently of scores',
                'endpoint': 'feature-ready-to-firewall-command-completion (installation upper bound)',
                'rpc_timeout_seconds': 1, 'enforcement_timeout_seconds': 2, 'verification_timeout_seconds': 1,
                'torch_export_version': torch.__version__, 'python_export_version': sys.version}
    write(TARGET / 'manifest.json', manifest)
    print(json.dumps({k: v for k, v in manifest.items() if k not in ['models', 'features', 'artifact_checksums']}, indent=2))


if __name__ == '__main__':
    main()
