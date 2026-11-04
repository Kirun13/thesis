"""Prepare a conservative numeric, per-record benchmark without target/ID features."""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

ROOT = Path(__file__).resolve().parents[1]
# Fixed before reading labels. Excludes IPs, ports, payloads, timestamps, checksums,
# stream/transaction identifiers and raw acknowledgement numbers. Retain relative
# TCP seq/ack and ICMP sequence fields as protocol-state features; session
# correlation remains an explicit limitation of this random-record benchmark.
FEATURES = [
    'arp.opcode', 'arp.hw.size', 'icmp.unused', 'http.content_length',
    'http.response', 'http.tls_port', 'tcp.connection.fin', 'tcp.connection.rst',
    'tcp.connection.syn', 'tcp.connection.synack', 'tcp.flags', 'tcp.flags.ack',
    'tcp.len', 'tcp.seq', 'tcp.ack', 'icmp.seq_le', 'udp.time_delta',
    'dns.qry.name.len', 'dns.qry.qu', 'dns.qry.type',
    'dns.retransmission', 'dns.retransmit_request', 'dns.retransmit_request_in',
    'mqtt.conflag.cleansess', 'mqtt.conflags', 'mqtt.hdrflags', 'mqtt.len',
    'mqtt.msg_decoded_as', 'mqtt.msgtype', 'mqtt.proto_len', 'mqtt.topic_len',
    'mqtt.ver', 'mbtcp.len', 'mbtcp.unit_id',
]


def feature_hashes(values):
    # Float32 is the model's actual input precision. Hash before splitting.
    return pd.util.hash_pandas_object(pd.DataFrame(values), index=False).to_numpy(np.uint64)


def partition_clients(types, clients=5, alpha=None, seed=42):
    rng = np.random.default_rng(seed)
    if alpha is None:
        return [np.sort(part) for part in np.array_split(rng.permutation(len(types)), clients)]
    for _ in range(500):
        partitions = [[] for _ in range(clients)]
        for label in np.unique(types):
            indices = np.flatnonzero(types == label)
            rng.shuffle(indices)
            sizes = rng.multinomial(len(indices), rng.dirichlet(np.full(clients, alpha)))
            for client, part in enumerate(np.split(indices, np.cumsum(sizes)[:-1])):
                partitions[client].extend(part.tolist())
        if min(map(len, partitions)) >= 32:
            return [np.sort(np.array(part, dtype=np.int64)) for part in partitions]
    raise RuntimeError('Cannot construct nonempty non-IID clients.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--max-records', type=int, default=150000)
    args = parser.parse_args()
    source = ROOT / 'data/raw/DNN-EdgeIIoT-dataset.csv'
    target = ROOT / 'data/processed'
    target.mkdir(parents=True, exist_ok=True)
    values, labels, types = [], [], []
    total = 0
    for chunk in pd.read_csv(source, usecols=FEATURES + ['Attack_label', 'Attack_type'],
                             chunksize=100000, low_memory=False):
        numeric = chunk[FEATURES].apply(pd.to_numeric, errors='coerce')
        x = numeric.to_numpy(dtype=np.float32, copy=True)
        x[~np.isfinite(x)] = np.nan
        values.append(x)
        labels.append(chunk['Attack_label'].to_numpy(np.int64))
        types.append(chunk['Attack_type'].astype(str).to_numpy())
        total += len(chunk)
        print(f'Read {total:,} records', flush=True)
    x, y, attack = np.concatenate(values), np.concatenate(labels), np.concatenate(types)
    del values, labels, types
    if set(np.unique(y)) != {0, 1}:
        raise RuntimeError('Expected binary target.')
    # Exclude indistinguishable feature vectors with conflicting binary labels.
    hashes = feature_hashes(x)
    groups = pd.DataFrame({'hash': hashes, 'label': y}).groupby('hash')['label'].nunique()
    conflicts = groups[groups > 1].index.to_numpy()
    valid = ~np.isin(hashes, conflicts)
    unique = ~pd.Series(hashes).duplicated().to_numpy()
    keep = valid & unique
    conflict_rows = int((~valid).sum())
    duplicates = int((valid & ~unique).sum())
    x, y, attack, hashes = x[keep], y[keep], attack[keep], hashes[keep]
    unique_records = len(y)
    eligible_counts = pd.Series(attack).value_counts().to_dict()
    print(f'Unique eligible records: {unique_records}; by type: {eligible_counts}', flush=True)
    # Types with too few unique inputs cannot support an honest three-way split.
    # Exclude them explicitly instead of duplicating them across train and test.
    rare_types = {label: count for label, count in eligible_counts.items() if count < 20}
    eligible = ~np.isin(attack, list(rare_types))
    x, y, attack, hashes = x[eligible], y[eligible], attack[eligible], hashes[eligible]
    indices = np.arange(len(y))
    if len(y) > args.max_records:
        indices, _ = train_test_split(indices, train_size=args.max_records,
                                     stratify=attack, random_state=42)
    # Random record split: no claim of unseen-device/session generalisation.
    train, remainder = train_test_split(indices, test_size=0.30, stratify=attack[indices], random_state=42)
    val, test = train_test_split(remainder, test_size=0.50, stratify=attack[remainder], random_state=42)
    # Train-only missing-value imputation and scaling; preserve fixed schema.
    train_values = x[train]
    medians = np.array([np.nanmedian(col) if np.isfinite(col).any() else 0
                        for col in train_values.T], dtype=np.float32)
    x = np.where(np.isnan(x), medians, x)
    means = x[train].mean(axis=0, dtype=np.float64).astype(np.float32)
    scales = x[train].std(axis=0, dtype=np.float64).astype(np.float32)
    scales[scales < 1e-8] = 1
    # Imputation and float32 rounding can merge initially distinct inputs.
    # Keep training unchanged; drop colliding validation/test inputs without using
    # their labels. Training has precedence over validation, then test.
    x = ((x.astype(np.float64) - means) / scales).astype(np.float32)
    final_hashes = feature_hashes(x)
    original_val, original_test = len(val), len(test)
    val = val[~np.isin(final_hashes[val], final_hashes[train])]
    val = val[~pd.Series(final_hashes[val]).duplicated().to_numpy()]
    test = test[~np.isin(final_hashes[test], np.concatenate([final_hashes[train], final_hashes[val]]))]
    test = test[~pd.Series(final_hashes[test]).duplicated().to_numpy()]
    if any(np.intersect1d(final_hashes[a], final_hashes[b]).size
           for a, b in [(train, val), (train, test), (val, test)]):
        raise RuntimeError('Preprocessing introduced identical model inputs across splits.')
    arrays = {'features': np.array(FEATURES), 'medians': medians, 'means': means, 'scales': scales}
    for name, selected in [('train', train), ('val', val), ('test', test)]:
        arrays[f'x_{name}'] = x[selected]
        arrays[f'y_{name}'] = y[selected]
        arrays[f'type_{name}'] = attack[selected].astype(str)
        arrays[f'row_{name}'] = selected
        arrays[f'hash_{name}'] = final_hashes[selected]
    clients = {}
    for name, alpha in [('iid', None), ('noniid', 0.3)]:
        partitions = partition_clients(attack[train], alpha=alpha)
        for i, part in enumerate(partitions):
            arrays[f'{name}_{i}'] = part
        clients[name] = [{'client': i, 'records': len(part), 'attack_fraction': float(y[train][part].mean()),
                          'attack_types': pd.Series(attack[train][part]).value_counts().to_dict()}
                         for i, part in enumerate(partitions)]
    np.savez_compressed(target / 'benchmark.npz', **arrays)
    report = {'raw_records': total, 'conflicting_label_rows_removed': conflict_rows,
              'duplicate_feature_rows_removed': duplicates, 'unique_eligible_records': unique_records,
              'eligible_counts_before_rare_type_exclusion': eligible_counts,
              'excluded_rare_attack_types': rare_types,
              'post_transform_collisions_removed': {'val': original_val - len(val), 'test': original_test - len(test)},
              'selected_records': len(indices), 'features': FEATURES, 'split_seed': 42,
              'split': {name: {'records': len(part), 'attack_fraction': float(y[part].mean()),
                               'attack_types': pd.Series(attack[part]).value_counts().to_dict()}
                        for name, part in [('train', train), ('val', val), ('test', test)]},
              'clients': clients, 'non_iid_alpha': 0.3, 'cross_split_input_overlap': 0,
              'split_unit': 'deduplicated numeric record, not device or capture session',
              'preprocessing': 'train-only median imputation and standardisation; no clipping',
              'excluded_columns': [c for c in pd.read_csv(source, nrows=0).columns if c not in FEATURES],
              'source': json.loads(source.with_suffix('.source.json').read_text(encoding='utf-8'))}
    (target / 'audit.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k not in ['clients', 'source']}, indent=2), flush=True)


if __name__ == '__main__':
    main()
