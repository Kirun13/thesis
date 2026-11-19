"""Paired controller-minus-local tests reported in the paper (exact Wilcoxon signed-rank).

Pairs: the same workload under local and controller authorization, both with a valid, observed response.
Writes results/online/paired-tests.json.
"""
import json
import statistics
from pathlib import Path

from scipy.stats import wilcoxon

ROOT = Path(__file__).resolve().parents[1]
episodes = json.loads((ROOT / 'results/online/summary.json').read_text())['system_episodes']
by = {(e['workload_id'], e['delay_ms'], e['mode']): e for e in episodes if not e['outage']}


def ok(e):
    return e['reconciliation_valid'] and e['response_observed']


out = {}
for key in ['attack_arrival_to_command_ms', 'attack_messages_received_before_command']:
    for delay in [0, 50]:
        diffs = [by[(w, delay, 'central')][key] - by[(w, delay, 'local')][key]
                 for w in sorted({e['workload_id'] for e in episodes if not e['outage']})
                 if ok(by[(w, delay, 'local')]) and ok(by[(w, delay, 'central')])]
        out[f'{key}@{delay}ms'] = {'pairs': len(diffs), 'median_difference': statistics.median(diffs),
                                   'min': min(diffs), 'max': max(diffs),
                                   'wilcoxon_exact_p': float(wilcoxon(diffs, method='exact').pvalue)}
mitigated = [e['benign_delivery_ratio'] for e in episodes if e['mode'] != 'none']
out['worst_benign_delivery_ratio_with_mitigation'] = min(mitigated)
(ROOT / 'results/online/paired-tests.json').write_text(json.dumps(out, indent=2) + '\n')
print(json.dumps(out, indent=2))
