"""Single-GPU sequential simulation: centralized versus weighted FedAvg."""
import os
os.environ.setdefault('CUBLAS_WORKSPACE_CONFIG', ':4096:8')
import argparse
import copy
import csv
import ctypes
import hashlib
import json
import platform
import random
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import sklearn
import torch
from sklearn.metrics import (accuracy_score, average_precision_score, confusion_matrix,
                             f1_score, precision_recall_curve, precision_score,
                             recall_score, roc_auc_score)
from torch import nn

ROOT = Path(__file__).resolve().parents[1]


def write_json(path, value):
    path = Path(path)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, indent=2, allow_nan=False), encoding='utf-8')
    temp.replace(path)


def save_checkpoint(path, value):
    temp = path.with_suffix('.tmp')
    torch.save(value, temp)
    temp.replace(path)


def seed_all(seed):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


class GRUAttention(nn.Module):
    """Attention over a fixed feature order, NOT a time-series model."""
    def __init__(self, features, hidden=32):
        super().__init__()
        self.feature_embedding = nn.Parameter(torch.randn(features, 7) * 0.02)
        self.gru = nn.GRU(8, hidden, batch_first=True)
        self.attention = nn.Sequential(nn.Linear(hidden, 16), nn.Tanh(), nn.Linear(16, 1))
        self.head = nn.Sequential(nn.LayerNorm(hidden), nn.Linear(hidden, 16),
                                  nn.ReLU(), nn.Dropout(0.1), nn.Linear(16, 1))

    def forward(self, x):
        embedding = self.feature_embedding.unsqueeze(0).expand(len(x), -1, -1)
        tokens = torch.cat([x.unsqueeze(-1), embedding], dim=-1)
        hidden, _ = self.gru(tokens)
        weights = torch.softmax(self.attention(hidden), dim=1)
        return self.head((weights * hidden).sum(dim=1)).squeeze(-1)


class MLP(nn.Module):
    def __init__(self, features):
        super().__init__()
        self.layers = nn.Sequential(nn.Linear(features, 64), nn.ReLU(), nn.Dropout(0.1),
                                    nn.Linear(64, 32), nn.ReLU(), nn.Linear(32, 1))

    def forward(self, x):
        return self.layers(x).squeeze(-1)


def fedavg(states, counts):
    total = sum(counts)
    return {key: sum(state[key].detach().cpu() * (count / total)
                     for state, count in zip(states, counts)) for key in states[0]}


def evaluate(model, x, batch_size=1024):
    model.eval()
    parts = []
    with torch.inference_mode():
        for start in range(0, len(x), batch_size):
            parts.append(torch.sigmoid(model(x[start:start + batch_size])).cpu().numpy())
    return np.concatenate(parts)


def select_threshold(y, probabilities):
    precision, recall, thresholds = precision_recall_curve(y, probabilities)
    f1 = 2 * precision[:-1] * recall[:-1] / np.maximum(precision[:-1] + recall[:-1], 1e-12)
    # Deterministic tie-break: highest threshold among equal validation F1 values.
    candidates = np.flatnonzero(np.isclose(f1, f1.max(), rtol=0, atol=1e-12))
    return float(thresholds[candidates[-1]])


def metrics(y, probabilities, threshold):
    prediction = probabilities >= threshold
    tn, fp, fn, tp = confusion_matrix(y, prediction, labels=[0, 1]).ravel()
    return {'accuracy': float(accuracy_score(y, prediction)),
            'precision': float(precision_score(y, prediction, zero_division=0)),
            'recall': float(recall_score(y, prediction, zero_division=0)),
            'f1': float(f1_score(y, prediction, zero_division=0)),
            'macro_f1': float(f1_score(y, prediction, average='macro', zero_division=0)),
            'pr_auc_ap': float(average_precision_score(y, probabilities)),
            'roc_auc': float(roc_auc_score(y, probabilities)),
            'fpr': float(fp / max(tn + fp, 1)),
            'tn': int(tn), 'fp': int(fp), 'fn': int(fn), 'tp': int(tp)}


class StopRequested(Exception):
    pass


def check_stop(run, deadline):
    if (run / 'STOP').exists():
        raise StopRequested('Stop file requested; last complete epoch/round retained.')
    if time.monotonic() > deadline:
        raise StopRequested('Maximum run duration reached; checkpoints retained.')


def fit_epoch(model, optimizer, x, y, indices, criterion, batch_size, run, deadline):
    model.train()
    indices = indices[torch.randperm(len(indices), device=indices.device)]
    total_loss, samples = 0.0, 0
    for start in range(0, len(indices), batch_size):
        check_stop(run, deadline)
        selected = indices[start:start + batch_size]
        optimizer.zero_grad(set_to_none=True)
        loss = criterion(model(x[selected]), y[selected])
        if not torch.isfinite(loss):
            raise RuntimeError('Non-finite training loss; run aborted.')
        loss.backward()
        nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
        total_loss += float(loss.detach()) * len(selected)
        samples += len(selected)
    return total_loss / samples


def inference_benchmark(model, x, samples=200):
    # Batch-1 model-only timing on this laptop, not edge or full-response timing.
    model.eval()
    if x.device.type == 'cuda':
        synchronize = torch.cuda.synchronize
    else:
        synchronize = lambda: None
    with torch.inference_mode():
        for _ in range(30):
            model(x[:1])
        synchronize()
        times = []
        for index in range(samples):
            sample = x[index % len(x):index % len(x) + 1]
            synchronize()
            started = time.perf_counter_ns()
            model(sample)
            synchronize()
            times.append((time.perf_counter_ns() - started) / 1e6)
    return {'scope': 'laptop model forward only; input already on device; batch=1',
            'samples': samples, 'median_ms': float(np.median(times)),
            'p95_ms': float(np.percentile(times, 95)), 'mean_ms': float(np.mean(times))}


def run_job(name, seed, config, data, run, deadline, device):
    job = run / f'{name}-seed{seed}'
    job.mkdir(exist_ok=True)
    if (job / 'result.json').exists():
        print(f'Skip completed {job.name}', flush=True)
        return
    seed_all(seed)
    model = (MLP(data['x_train'].shape[1]) if name == 'mlp-central'
             else GRUAttention(data['x_train'].shape[1])).to(device)
    xtrain = torch.tensor(data['x_train'], device=device)
    ytrain = torch.tensor(data['y_train'], dtype=torch.float32, device=device)
    xval = torch.tensor(data['x_val'], device=device)
    central = name.endswith('central')
    partitions = ([np.arange(len(ytrain))] if central else
                  [data[f'{"noniid" if name.endswith("noniid") else "iid"}_{i}'] for i in range(5)])
    if config['profile'] == 'smoke':
        # Stratified train subsample; retain every client's data for FL topology check.
        rng = np.random.default_rng(123)
        partitions = [rng.choice(part, min(len(part), 512), replace=False) for part in partitions]
        xval = xval[:min(1024, len(xval))]
        val_labels = data['y_val'][:len(xval)]
    else:
        val_labels = data['y_val']
    partitions = [torch.tensor(part, device=device, dtype=torch.long) for part in partitions]
    positive = float(ytrain.sum())
    pos_weight = (len(ytrain) - positive) / max(positive, 1)
    criterion = nn.BCEWithLogitsLoss(pos_weight=torch.tensor(pos_weight, device=device))
    optimizer = torch.optim.AdamW(model.parameters(), lr=config['learning_rate'], weight_decay=1e-4)
    start_step, best, best_step, elapsed_before = 0, -1.0, 0, 0.0
    last_path = job / 'last.pt'
    if last_path.exists():
        last = torch.load(last_path, map_location=device, weights_only=False)
        model.load_state_dict(last['model'])
        optimizer.load_state_dict(last['optimizer'])
        start_step, best, best_step = last['step'], last['best_val_ap'], last['best_step']
        elapsed_before = last['elapsed_seconds']
    started = time.monotonic()
    for step in range(start_step + 1, config['steps'] + 1):
        check_stop(run, deadline)
        step_start = time.monotonic()
        # Seed by step/client so resuming a completed checkpoint preserves the trajectory.
        if central:
            seed_all(seed * 100000 + step)
            loss = fit_epoch(model, optimizer, xtrain, ytrain, partitions[0], criterion,
                             config['batch_size'], run, deadline)
        else:
            initial = copy.deepcopy(model.state_dict())
            states, counts, losses = [], [], []
            for client, indices in enumerate(partitions):
                seed_all(seed * 100000 + step * 10 + client)
                model.load_state_dict(initial)
                local_optimizer = torch.optim.AdamW(model.parameters(), lr=config['learning_rate'], weight_decay=1e-4)
                losses.append(fit_epoch(model, local_optimizer, xtrain, ytrain, indices, criterion,
                                        config['batch_size'], run, deadline))
                states.append({key: value.detach().cpu().clone() for key, value in model.state_dict().items()})
                counts.append(len(indices))
            model.load_state_dict(fedavg(states, counts))
            loss = float(np.average(losses, weights=counts))
        probabilities = evaluate(model, xval)
        val_ap = float(average_precision_score(val_labels, probabilities))
        val_f1 = float(f1_score(val_labels, probabilities >= 0.5, zero_division=0))
        if val_ap > best:
            best, best_step = val_ap, step
            save_checkpoint(job / 'best.pt', {'model': model.state_dict(), 'step': step,
                            'features': data['features'].tolist(), 'architecture': name,
                            'preprocessing': {key: data[key] for key in ['medians', 'means', 'scales']}})
        elapsed = elapsed_before + time.monotonic() - started
        record = {'step': step, 'train_loss': loss, 'val_ap': val_ap, 'val_f1_at_0_5': val_f1,
                  'step_seconds': time.monotonic() - step_start, 'elapsed_seconds': elapsed}
        # Checkpoint first; JSON history can contain at most one extra row after an interrupted write.
        save_checkpoint(last_path, {'model': model.state_dict(), 'optimizer': optimizer.state_dict(),
                        'step': step, 'best_val_ap': best, 'best_step': best_step, 'elapsed_seconds': elapsed})
        with (job / 'history.jsonl').open('a', encoding='utf-8') as output:
            output.write(json.dumps(record) + '\n')
        write_json(run / 'status.json', {'state': 'running', 'job': job.name,
                   'step': step, 'steps': config['steps'], **record,
                   'updated_utc': datetime.now(timezone.utc).isoformat()})
        print(f'{job.name} {step}/{config["steps"]} loss={loss:.4f} val_AP={val_ap:.4f} '
              f'val_F1@0.5={val_f1:.4f} step={record["step_seconds"]:.1f}s', flush=True)
    checkpoint = torch.load(job / 'best.pt', map_location=device, weights_only=False)
    model.load_state_dict(checkpoint['model'])
    val_probabilities = evaluate(model, xval)
    threshold = select_threshold(val_labels, val_probabilities)
    if config['profile'] == 'smoke':
        result = {'profile': 'smoke', 'job': job.name, 'validation_only': True,
                  'metrics': metrics(val_labels, val_probabilities, threshold),
                  'threshold': threshold, 'best_step': best_step}
    else:
        # Test is evaluated only after checkpoint AND threshold have been selected on validation.
        xtest = torch.tensor(data['x_test'], device=device)
        test_probabilities = evaluate(model, xtest)
        result = {'profile': config['profile'], 'job': job.name, 'method': name, 'seed': seed,
                  'metrics': metrics(data['y_test'], test_probabilities, threshold),
                  'threshold': threshold, 'best_step': best_step, 'best_val_ap': best,
                  'training_seconds': elapsed_before + time.monotonic() - started,
                  'parameters': sum(p.numel() for p in model.parameters()),
                  'model_bytes': sum(p.numel() * p.element_size() for p in model.parameters()),
                  'train_records_per_step': sum(map(len, partitions)),
                  'model_inference': inference_benchmark(model, xtest),
                  'per_attack_recall': {label: float((test_probabilities[data['type_test'] == label] >= threshold).mean())
                                        for label in np.unique(data['type_test']) if label != 'Normal'}}
        np.savez_compressed(job / 'test_predictions.npz', probabilities=test_probabilities,
                            labels=data['y_test'], row_ids=data['row_test'], attack_type=data['type_test'])
    write_json(job / 'result.json', result)
    print(f'Completed {job.name}: {json.dumps(result["metrics"])}', flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--profile', choices=['smoke', 'overnight'], default='smoke')
    parser.add_argument('--run-dir', type=Path)
    args = parser.parse_args()
    config = {'profile': args.profile, 'steps': 2 if args.profile == 'smoke' else 20,
              'seeds': [42] if args.profile == 'smoke' else [42, 43, 44],
              'methods': ['mlp-central', 'gru-central', 'gru-fedavg-iid', 'gru-fedavg-noniid'],
              'batch_size': 256, 'learning_rate': 0.001, 'local_epochs': 1,
              'clients': 5, 'max_hours': 10, 'checkpoint_selection': 'maximum validation average precision',
              'threshold_selection': 'maximum validation binary F1', 'test_used_for_selection': False}
    run = (args.run_dir if args.run_dir else ROOT / 'runs' /
           f'{args.profile}-{datetime.now().strftime("%Y%m%d-%H%M%S")}').resolve()
    run.mkdir(parents=True, exist_ok=True)
    if (run / 'config.json').exists():
        config = json.loads((run / 'config.json').read_text())
        if config['profile'] != args.profile:
            raise RuntimeError('Resume profile mismatch.')
    else:
        write_json(run / 'config.json', config)
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    if args.profile == 'overnight' and device.type != 'cuda':
        raise RuntimeError('Overnight GPU run requested but CUDA unavailable; no silent CPU fallback.')
    torch.set_num_threads(4)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    torch.use_deterministic_algorithms(True)
    torch.backends.cuda.matmul.allow_tf32 = False
    metadata = {'python': sys.version, 'platform': platform.platform(), 'torch': torch.__version__,
                'numpy': np.__version__, 'sklearn': sklearn.__version__, 'cuda_runtime': torch.version.cuda,
                'device': str(device), 'gpu': torch.cuda.get_device_name(0) if device.type == 'cuda' else None,
                'started_utc': datetime.now(timezone.utc).isoformat(), 'pid': os.getpid()}
    if not (run / 'environment.json').exists():
        write_json(run / 'environment.json', metadata)
    with (run / 'invocations.jsonl').open('a', encoding='utf-8') as output:
        output.write(json.dumps(metadata) + '\n')
    # Save executed source and data provenance alongside results.
    snapshot = run / 'source'
    snapshot.mkdir(exist_ok=True)
    for path in (ROOT / 'scripts').glob('*'):
        if path.is_file():
            saved = snapshot / path.name
            if saved.exists() and saved.read_bytes() != path.read_bytes():
                raise RuntimeError(f'Source changed since run started: {path.name}. Use a new run directory.')
            if not saved.exists():
                shutil.copy2(path, saved)
    if not (run / 'PROTOCOL.md').exists():
        shutil.copy2(ROOT / 'PROTOCOL.md', run / 'PROTOCOL.md')
    if not (run / 'data-audit.json').exists():
        shutil.copy2(ROOT / 'data/processed/audit.json', run / 'data-audit.json')
    benchmark = ROOT / 'data/processed/benchmark.npz'
    with benchmark.open('rb') as handle:
        checksum = {'sha256': hashlib.file_digest(handle, 'sha256').hexdigest()}
    if (run / 'data-checksum.json').exists():
        if json.loads((run / 'data-checksum.json').read_text()) != checksum:
            raise RuntimeError('Prepared data changed since run started. Use a new run directory.')
    else:
        write_json(run / 'data-checksum.json', checksum)
    data = dict(np.load(benchmark, allow_pickle=False))
    print(json.dumps(metadata, indent=2), flush=True)
    deadline = time.monotonic() + config['max_hours'] * 3600
    # Prevent idle sleep for the active computation; restore on exit. Does not change power settings.
    if os.name == 'nt':
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)
    try:
        for seed in config['seeds']:
            for method in config['methods']:
                run_job(method, seed, config, data, run, deadline, device)
        write_json(run / 'status.json', {'state': 'completed', 'updated_utc': datetime.now(timezone.utc).isoformat()})
        if args.profile == 'overnight':
            from report import report
            report(run)
    except StopRequested as error:
        write_json(run / 'status.json', {'state': 'stopped', 'reason': str(error)})
        print(str(error), flush=True)
    except Exception as error:
        write_json(run / 'status.json', {'state': 'failed', 'error': repr(error)})
        raise
    finally:
        if os.name == 'nt':
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)


if __name__ == '__main__':
    main()
