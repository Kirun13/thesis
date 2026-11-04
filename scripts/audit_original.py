"""Audit selection bias and provenance before expanding detector evaluation."""
import hashlib
import json
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

from prepare_data import FEATURES

ROOT = Path(__file__).resolve().parents[1]


def main():
    target = ROOT / 'runs/extension-audit'
    target.mkdir(parents=True, exist_ok=True)
    source = ROOT / 'data/raw/DNN-EdgeIIoT-dataset.csv'
    labels, types, hashes, times = [], [], [], []
    missing = Counter()
    first_times, last_times = [], []
    columns = list(pd.read_csv(source, nrows=0).columns)
    metadata = ['frame.time', 'ip.src_host', 'ip.dst_host', 'tcp.srcport', 'tcp.dstport', 'udp.port', 'udp.stream']
    total = 0
    for chunk in pd.read_csv(source, usecols=FEATURES + ['Attack_label', 'Attack_type'] + metadata,
                             chunksize=100000, low_memory=False):
        numeric = chunk[FEATURES].apply(pd.to_numeric, errors='coerce')
        values = numeric.to_numpy(dtype=np.float32, copy=True)
        values[~np.isfinite(values)] = np.nan
        for index, name in enumerate(FEATURES):
            missing[name] += int(np.isnan(values[:, index]).sum())
        hashes.append(pd.util.hash_pandas_object(pd.DataFrame(values), index=False).to_numpy(np.uint64))
        labels.append(chunk['Attack_label'].to_numpy(np.int64))
        types.append(chunk['Attack_type'].astype(str).to_numpy())
        stamp = chunk['frame.time'].astype(str)
        times.extend(stamp.sample(min(5, len(stamp)), random_state=42).tolist())
        if not first_times:
            first_times = stamp.head(5).tolist()
        last_times = stamp.tail(5).tolist()
        total += len(chunk)
        print(f'Audited {total:,} source rows', flush=True)
    y, attack, keys = np.concatenate(labels), np.concatenate(types), np.concatenate(hashes)
    frame = pd.DataFrame({'hash': keys, 'label': y, 'type': attack})
    counts = frame.groupby(['hash', 'label']).size().unstack(fill_value=0)
    mixed = counts[(counts.get(0, 0) > 0) & (counts.get(1, 0) > 0)]
    is_mixed = frame['hash'].isin(mixed.index).to_numpy()
    is_duplicate = frame['hash'].duplicated().to_numpy()
    per_type = []
    for label in sorted(set(attack)):
        selected = attack == label
        per_type.append({'attack_type': label, 'original': int(selected.sum()),
                         'in_ambiguous_input_groups': int((selected & is_mixed).sum()),
                         'discarded_as_repeated_input': int((selected & ~is_mixed & is_duplicate).sum()),
                         'retained_unique_unambiguous': int((selected & ~is_mixed & ~is_duplicate).sum())})
    # Descriptive empirical bound for a deterministic classifier using only these
    # raw float32 input vectors. Not an out-of-sample performance estimate.
    empirical_errors = int(counts.min(axis=1).sum())
    report = {'source_rows': total, 'columns': columns, 'original_class_counts': dict(Counter(map(int, y))),
              'ambiguous_input_groups': len(mixed), 'ambiguous_rows': int(is_mixed.sum()),
              'ambiguous_row_fraction': float(is_mixed.mean()),
              'ambiguous_class_counts': dict(Counter(map(int, y[is_mixed]))),
              'all_repeated_feature_rows': int(is_duplicate.sum()),
              'empirical_minority_label_errors_for_same_input': empirical_errors,
              'empirical_deterministic_accuracy_ceiling_on_original_inputs': 1 - empirical_errors / total,
              'ceiling_caveat': 'Descriptive in-sample representation ambiguity; not a test estimate or data-cleaning justification.',
              'first_timestamps': first_times, 'last_timestamps': last_times, 'sample_timestamps': times,
              'capture_id_available': any('capture' in c.lower() or 'pcap' in c.lower() for c in columns),
              'provenance_limit': 'Aggregated selected CSV has no authoritative capture ID. Do not equate inferred flow ID with capture session.',
              'coerced_missing_counts': dict(missing), 'by_attack_type': per_type,
              'decision': 'Keep old benchmark as filtered sensitivity analysis; do not drop conflicting labels in the new primary evaluation.'}
    (target / 'original-data-audit.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    lines = ['# Audit of the original selected Edge-IIoTset CSV', '',
             f'Original rows: {total:,}. Rows in ambiguous selected-input groups: {int(is_mixed.sum()):,} ({is_mixed.mean():.2%}).', '',
             'A selected feature vector shared by benign and attack labels is not proof of a mislabeled event. '
             'Deleting these groups removes ambiguity specific to the chosen representation. Repeated feature vectors '
             'are not necessarily duplicate underlying packet events.', '',
             f'The empirical minimum number of label disagreements for deterministic classification of these raw inputs is {empirical_errors:,}. '
             f'The corresponding in-sample accuracy ceiling is {1 - empirical_errors / total:.2%}; this is not an out-of-sample estimate.', '',
             '| Type | Original rows | Ambiguous rows | Repeated unambiguous input rows | Retained unique unambiguous |',
             '|---|---:|---:|---:|---:|']
    for row in per_type:
        lines.append('| ' + ' | '.join(str(v) for v in row.values()) + ' |')
    lines += ['', 'No authoritative capture identifier is present in the aggregated CSV. '
              'Session/capture generalization must use verified provenance or independent captured laboratory episodes.', '',
              'The previous benchmark is preserved. New primary evaluation must retain ambiguous observations and '
              'split independent episodes before fitting transforms or selecting models.']
    (target / 'AUDIT.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps({k: report[k] for k in ['source_rows', 'ambiguous_rows', 'ambiguous_class_counts',
                     'empirical_deterministic_accuracy_ceiling_on_original_inputs', 'capture_id_available']}, indent=2))


if __name__ == '__main__':
    main()
