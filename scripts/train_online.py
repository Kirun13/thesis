"""Fixed detector study, with episode holdout, FedMLP and partition variation."""
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch
from sklearn.metrics import precision_recall_curve

from train import MLP, GRUAttention, seed_all, metrics, fedavg
from prepare_data import partition_clients

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / 'runs/online/detectors-v1'
ARTIFACTS = ROOT / 'data/online'


def choose_threshold(labels, scores):
    candidates = np.unique(np.r_[scores, scores.max() + 1e-6])
    best = (-1, -1)
    chosen = float(candidates[-1])
    for threshold in candidates:
        prediction = scores >= threshold
        fp = np.sum(prediction & (labels == 0))
        if fp / max(np.sum(labels == 0), 1) > 0.01:
            continue
        tp = np.sum(prediction & (labels == 1))
        fn = np.sum(~prediction & (labels == 1))
        f1 = 2 * tp / max(2 * tp + fp + fn, 1)
        if (f1, float(threshold)) > best:
            best, chosen = (f1, float(threshold)), float(threshold)
    return chosen


def episode_interval(labels, scores, threshold, episodes):
    contributions = []
    prediction = scores >= threshold
    for episode in np.unique(episodes):
        selected = episodes == episode
        contributions.append([np.sum(selected & prediction & (labels == 1)),
                              np.sum(selected & prediction & (labels == 0)),
                              np.sum(selected & ~prediction & (labels == 1))])
    contributions = np.array(contributions)
    rng = np.random.default_rng(20261108)
    totals = contributions[rng.integers(0, len(contributions), size=(2000, len(contributions)))].sum(axis=1)
    f1 = 2 * totals[:, 0] / np.maximum(2 * totals[:, 0] + totals[:, 1] + totals[:, 2], 1)
    return np.percentile(f1, [2.5, 97.5]).tolist()


def predictions(model, x):
    model.eval()
    with torch.inference_mode():
        return torch.sigmoid(model(x)).cpu().numpy()


def main():
    TARGET.mkdir(parents=True, exist_ok=True)
    if (ARTIFACTS / 'models.json').exists():
        print('Detector study already frozen; no rerun or test-based retuning.')
        return
    data = dict(np.load(ARTIFACTS / 'dataset.npz', allow_pickle=False))
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    torch.set_num_threads(2)
    x = {split: torch.tensor(data['x_' + split], device=device) for split in ['train', 'val', 'test']}
    y = torch.tensor(data['y_train'], dtype=torch.float32, device=device)
    criterion = torch.nn.BCEWithLogitsLoss(pos_weight=torch.tensor(float((len(y) - y.sum()) / y.sum()), device=device))
    recipes = [('mlp-central', None), ('gru-central', None), ('fedmlp-iid', 42)]
    recipes += [('fedmlp-noniid', p) for p in [42, 43, 44]] + [('fedgru-noniid', 42)]
    config = {'epochs_or_rounds': 30, 'train_seeds': [42, 43, 44], 'recipes': recipes,
              'learning_rate': 0.001, 'batch_size': 64, 'clients': 5, 'local_epochs': 1,
              'non_iid_alpha': 0.3, 'threshold': 'max validation F1 with validation FPR <= 1%',
              'checkpoint': 'max validation AP', 'test_selection': False}
    (TARGET / 'config.json').write_text(json.dumps(config, indent=2))
    deployments, results = [], []
    for method, partition_seed in recipes:
        for seed in [42, 43, 44]:
            identity = f'{method}-p{partition_seed}-s{seed}' if partition_seed else f'{method}-s{seed}'
            directory = TARGET / identity
            directory.mkdir(exist_ok=True)
            seed_all(seed)
            model = (GRUAttention(len(data['features'])) if 'gru' in method else MLP(len(data['features']))).to(device)
            central = 'central' in method
            parts = ([np.arange(len(y))] if central else partition_clients(data['y_train'], clients=5,
                        alpha=0.3 if 'noniid' in method else None, seed=partition_seed))
            (directory / 'client-distribution.json').write_text(json.dumps([
                {'records': len(part), 'attack_fraction': float(data['y_train'][part].mean())} for part in parts], indent=2))
            optimizer = torch.optim.AdamW(model.parameters(), lr=0.001, weight_decay=1e-4)
            best, history = -1, []
            began = time.monotonic()
            for epoch in range(30):
                states, counts = [], []
                initial = {key: value.detach().clone() for key, value in model.state_dict().items()}
                losses = []
                for client, part in enumerate(parts):
                    if not central:
                        model.load_state_dict(initial)
                        optimizer = torch.optim.AdamW(model.parameters(), lr=0.001, weight_decay=1e-4)
                    model.train()
                    seed_all(seed * 10000 + epoch * 10 + client)
                    order = np.array(part)[np.random.permutation(len(part))]
                    for start in range(0, len(order), 64):
                        batch = order[start:start+64]
                        optimizer.zero_grad(set_to_none=True)
                        loss = criterion(model(x['train'][batch]), y[batch])
                        assert torch.isfinite(loss)
                        loss.backward()
                        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                        optimizer.step()
                        losses.append(float(loss.detach()))
                    if not central:
                        states.append({key: value.detach().cpu().clone() for key, value in model.state_dict().items()})
                        counts.append(len(part))
                if not central:
                    model.load_state_dict(fedavg(states, counts))
                val = predictions(model, x['val'])
                from sklearn.metrics import average_precision_score
                ap = float(average_precision_score(data['y_val'], val))
                history.append({'epoch_or_round': epoch + 1, 'mean_batch_loss': float(np.mean(losses)), 'val_ap': ap})
                if ap > best:
                    best, best_epoch = ap, epoch + 1
                    torch.save(model.state_dict(), directory / 'best.pt')
            model.load_state_dict(torch.load(directory / 'best.pt', map_location=device, weights_only=True))
            model = model.cpu().eval()
            val = predictions(model, x['val'].cpu())
            threshold = choose_threshold(data['y_val'], val)
            test = predictions(model, x['test'].cpu())
            result = {'id': identity, 'method': method, 'training_seed': seed, 'partition_seed': partition_seed,
                      'best_epoch_or_round': best_epoch, 'threshold': threshold,
                      'test_metrics': metrics(data['y_test'], test, threshold),
                      'f1_episode_bootstrap_95_interval': episode_interval(data['y_test'], test, threshold, data['episode_test']),
                      'training_seconds': time.monotonic() - began,
                      'parameters': sum(p.numel() for p in model.parameters()),
                      'simulated_parameter_bytes_bidirectional': 0 if central else sum(p.numel()*4 for p in model.parameters()) * 2 * 5 * 30}
            np.savez_compressed(directory / 'test-predictions.npz', scores=test, labels=data['y_test'], episodes=data['episode_test'])
            (directory / 'result.json').write_text(json.dumps(result, indent=2))
            (directory / 'history.json').write_text(json.dumps(history))
            model = model.cpu().eval()
            exported = torch.jit.freeze(torch.jit.script(model))
            with torch.inference_mode():
                deployed_scores = torch.sigmoid(exported(x['test'].cpu())).numpy()
            assert np.max(np.abs(test - deployed_scores)) < 1e-5
            assert np.array_equal(test >= threshold, deployed_scores >= threshold)
            file = identity + '.pt'
            exported.save(str(ARTIFACTS / file))
            deployments.append({'id': identity, 'file': file, 'threshold': threshold})
            results.append(result)
            print(f'{identity}: test F1={result["test_metrics"]["f1"]:.4f} FPR={result["test_metrics"]["fpr"]:.4f}', flush=True)
    rate_threshold = choose_threshold(data['y_val'], data['raw_val'][:, 0])
    rate_scores = data['raw_test'][:, 0]
    results.append({'id': 'rate-threshold', 'method': 'rate-threshold', 'threshold': rate_threshold,
                    'test_metrics': metrics(data['y_test'], rate_scores, rate_threshold),
                    'f1_episode_bootstrap_95_interval': episode_interval(data['y_test'], rate_scores, rate_threshold, data['episode_test'])})
    (TARGET / 'results.json').write_text(json.dumps(results, indent=2))
    (ARTIFACTS / 'models.json').write_text(json.dumps({'features': data['features'].tolist(),
          'means': data['means'].tolist(), 'scales': data['scales'].tolist(), 'models': deployments}, indent=2))
    print('Fixed detector study completed; deployment recipe was preselected before test.', flush=True)


if __name__ == '__main__':
    main()
