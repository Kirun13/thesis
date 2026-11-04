import sys
import unittest
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from prepare_data import partition_clients
from train import fedavg, select_threshold, metrics


class ExperimentalChecks(unittest.TestCase):
    def test_weighted_fedavg_matches_manual_reference(self):
        states = [{'weight': torch.tensor([1., 3.])}, {'weight': torch.tensor([5., 7.])}]
        self.assertTrue(torch.equal(fedavg(states, [1, 3])['weight'], torch.tensor([4., 6.])))

    def test_partition_conserves_records_without_overlap(self):
        labels = np.repeat(np.arange(15), 200)
        for alpha in [None, 0.3]:
            parts = partition_clients(labels, alpha=alpha)
            np.testing.assert_array_equal(np.sort(np.concatenate(parts)), np.arange(len(labels)))
            self.assertEqual(len(np.unique(np.concatenate(parts))), len(labels))
            self.assertGreaterEqual(min(map(len, parts)), 32)

    def test_threshold_and_false_positive_denominator(self):
        y = np.array([0, 0, 1, 1])
        p = np.array([0.1, 0.7, 0.8, 0.9])
        threshold = select_threshold(y, p)
        self.assertAlmostEqual(threshold, 0.8)
        self.assertEqual(metrics(y, p, threshold)['f1'], 1)
        self.assertEqual(metrics(y, p, 0.5)['fpr'], 0.5)

    def test_actual_data_integrity(self):
        path = Path(__file__).resolve().parents[1] / 'data/processed/benchmark.npz'
        self.assertTrue(path.exists(), 'Prepare real data before preflight checks.')
        with np.load(path, allow_pickle=False) as data:
            for split in ['train', 'val', 'test']:
                self.assertTrue(np.isfinite(data['x_' + split]).all())
                self.assertEqual(set(np.unique(data['y_' + split])), {0, 1})
            for a, b in [('train', 'val'), ('train', 'test'), ('val', 'test')]:
                self.assertEqual(np.intersect1d(data['hash_' + a], data['hash_' + b]).size, 0)
            for regime in ['iid', 'noniid']:
                combined = np.concatenate([data[f'{regime}_{i}'] for i in range(5)])
                np.testing.assert_array_equal(np.sort(combined), np.arange(len(data['y_train'])))
            self.assertFalse(any('Attack' in name or 'ip.' in name for name in data['features']))


if __name__ == '__main__':
    unittest.main()
