"""Frozen legacy-model sensitivity on the entire previously excluded ambiguous cohort."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import torch

from prepare_data import FEATURES
from train import MLP, GRUAttention

ROOT = Path(__file__).resolve().parents[1]


def main():
    target = ROOT / 'runs/extension-audit'
    cached = target / 'ambiguous-cohort.npz'
    if not cached.exists():
        values, labels = [], []
        for chunk in pd.read_csv(ROOT / 'data/raw/DNN-EdgeIIoT-dataset.csv', usecols=FEATURES + ['Attack_label'],
                                 chunksize=100000, low_memory=False):
            x = chunk[FEATURES].apply(pd.to_numeric, errors='coerce').to_numpy(np.float32, copy=True)
            x[~np.isfinite(x)] = np.nan
            values.append(x)
            labels.append(chunk['Attack_label'].to_numpy(np.int64))
        x, y = np.concatenate(values), np.concatenate(labels)
        hashes = pd.util.hash_pandas_object(pd.DataFrame(x), index=False).to_numpy(np.uint64)
        counts = pd.DataFrame({'hash': hashes, 'label': y}).groupby(['hash', 'label']).size().unstack(fill_value=0)
        mixed = counts[(counts[0] > 0) & (counts[1] > 0)]
        keys, first = np.unique(hashes, return_index=True)
        selected = np.isin(keys, mixed.index)
        raw = x[first[selected]]
        weights = mixed.loc[keys[selected], [0, 1]].to_numpy(np.int64)
        np.savez_compressed(cached, raw=raw, counts=weights)
    data = dict(np.load(cached))
    weights = data['counts']
    source = Path(json.loads((ROOT / 'runs/active.json').read_text())['runDir'])
    torch.set_num_threads(1)
    rows = []
    for method in ['mlp-central', 'gru-central', 'gru-fedavg-iid', 'gru-fedavg-noniid']:
        for seed in [42, 43, 44]:
            job = source / f'{method}-seed{seed}'
            saved = torch.load(job / 'best.pt', map_location='cpu', weights_only=False)
            settings = json.loads((job / 'result.json').read_text())
            transforms = saved['preprocessing']
            raw = np.where(np.isnan(data['raw']), transforms['medians'], data['raw'])
            x = ((raw.astype(np.float64) - transforms['means']) / transforms['scales']).astype(np.float32)
            model = (MLP(len(FEATURES)) if method == 'mlp-central' else GRUAttention(len(FEATURES))).eval()
            model.load_state_dict(saved['model'])
            with torch.inference_mode():
                scores = torch.sigmoid(model(torch.tensor(x))).numpy()
            prediction = scores >= settings['threshold']
            tn, fp = int(weights[~prediction, 0].sum()), int(weights[prediction, 0].sum())
            fn, tp = int(weights[~prediction, 1].sum()), int(weights[prediction, 1].sum())
            rows.append({'method': method, 'seed': seed, 'threshold_unchanged': settings['threshold'],
                         'tn': tn, 'fp': fp, 'fn': fn, 'tp': tp,
                         'accuracy': (tn + tp) / weights.sum(),
                         'f1': 2 * tp / max(2 * tp + fp + fn, 1),
                         'recall': tp / max(tp + fn, 1), 'fpr': fp / max(fp + tn, 1)})
    report = {'cohort_rows': int(weights.sum()), 'distinct_ambiguous_inputs': len(weights),
              'benign': int(weights[:, 0].sum()), 'attack': int(weights[:, 1].sum()),
              'models_and_validation_thresholds_frozen': True, 'results': rows,
              'interpretation': 'Conditional sensitivity on all excluded ambiguous inputs, not a new unbiased whole-dataset test. Cohort prevalence differs from the old filtered test. No model or threshold is retuned.'}
    (target / 'excluded-cohort-sensitivity.json').write_text(json.dumps(report, indent=2))
    lines = ['# Frozen-model sensitivity to the excluded ambiguous cohort', '',
             f'Evaluate all {int(weights.sum()):,} previously excluded records with unchanged legacy models and validation thresholds. '
             'Identical input groups are evaluated once and confusion counts weighted by their original label frequencies.', '',
             '| Model | Seed | Accuracy | Attack F1 | Recall | FPR |', '|---|---:|---:|---:|---:|---:|']
    for row in rows:
        lines.append(f'| {row["method"]} | {row["seed"]} | {row["accuracy"]:.4f} | {row["f1"]:.4f} | {row["recall"]:.4f} | {row["fpr"]:.4f} |')
    lines += ['', report['interpretation'], '', 'The original filtered benchmark remains unchanged. '
              'This audit does not establish generalization to independent captures or real municipal networks.']
    (target / 'EXCLUDED_SENSITIVITY.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
