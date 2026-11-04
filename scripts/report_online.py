"""Episode-level quality/availability and real arrival-to-response reporting."""
import collections
import csv
import json
import re
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'online'))
from reconcile import reconcile


def read(path):
    return json.loads(path.read_text())


def quantile(values, q):
    return float(np.percentile(values, q)) if values else None


def counters(events):
    total = collections.Counter()
    for event in events:
        for line in event['counters'].splitlines():
            fields = line.split()
            if len(fields) > 8 and fields[0].isdigit() and fields[2] == 'DROP':
                source = fields[7]
                if event['event'] == 'stop' or source == event.get('source'):
                    total[source] += int(fields[0])
    return dict(total)


def episode(path):
    config = read(path / 'config.json')
    audit = reconcile(path, strict=False)
    subscriber = read(path / 'subscriber.json')['records']
    offered, accepted = {}, {}
    for source in range(3):
        for sequence, stamp, tag in read(path / f'source-{source}-offered.json'):
            offered[(source, sequence)] = (stamp, tag)
        for sequence, stamp, tag in read(path / f'source-{source}.json')['records']:
            accepted[(source, sequence)] = (stamp, tag)
    delivered = {}
    for source, sequence, sent, received, tag in subscriber:
        assert (source, sequence) in offered
        delivered[(source, sequence)] = (sent, received, tag)
    benign = {key for key, (_, tag) in offered.items() if tag == 'B'}
    malicious = set(offered) - benign
    delivered_benign = benign & delivered.keys()
    latencies = [(delivered[key][1] - delivered[key][0]) / 1e6 for key in delivered_benign]
    decisions = read(path / 'decisions.json')
    blocks = [d for d in decisions if d['status'] == 'blocked']
    attacker = f'172.30.95.{10 + config["attacker"]}'
    onset = audit['first_attack_ingress_ns']
    successful = [d for d in blocks if d['source'] == attacker and onset is not None and d['command_end_ns'] >= onset]
    response = min(successful, key=lambda d: d['command_end_ns']) if successful else None
    ground_truth = {(row['window'], row['source']): row['label'] for row in read(path / 'labeled-windows.json')}
    resources = read(path / 'edge-resources.json')
    drops = counters(read(path / 'rule-events.json'))
    first_command = response['command_end_ns'] if response else None
    row = {'episode_id': config['episode_id'], 'workload_id': config.get('workload_id'),
           'traffic_seed': config['traffic_seed'], 'mode': config['mode'], 'delay_ms': config.get('delay_ms', 0),
           'rate_level': config.get('rate_level'), 'nominal_attack_rate': config['attack_rate'],
           'outage': config.get('outage', False), 'attacker_source': attacker,
           'scheduled_benign': len(benign), 'socket_accepted_benign': len(benign & accepted.keys()),
           'delivered_benign': len(delivered_benign), 'benign_delivery_ratio': len(delivered_benign) / max(len(benign), 1),
           'normal_message_median_ms': quantile(latencies, 50), 'normal_message_p95_ms': quantile(latencies, 95),
           'scheduled_attack_messages': len(malicious), 'delivered_attack_messages': len(malicious & delivered.keys()),
           'attack_messages_received_before_command': sum(key in malicious and value[1] <= first_command for key, value in delivered.items()) if first_command else None,
           'first_attack_ingress_ns': onset, 'response_observed': response is not None,
           'attack_arrival_to_command_ms': (first_command - onset) / 1e6 if response else None,
           'feature_ready_to_command_ms': response['feature_to_command_ms'] if response else None,
           'feature_accumulation_and_holdback_ms': (response['ready_ns'] - onset) / 1e6 if response else None,
           'all_block_commands': len(blocks),
           'false_block_commands': sum(not ground_truth.get((d['window'], d['source']), 0) for d in blocks),
           'other_source_block_commands': sum(d['source'] != attacker for d in blocks),
           'response_failures': sum(d['status'] == 'response_failure' for d in decisions),
           'observed_windows': audit['live_windows'], 'completed_inference_windows': len(decisions),
           'unprocessed_windows_at_episode_stop': audit['live_windows'] - len(decisions),
           'kernel_drop_packets': sum(drops.values()), 'drops_by_source': drops,
           'edge_cpu_core_fraction': resources['active_cpu_seconds'] / max(resources['active_wall_seconds'], 1e-9),
           'edge_sampled_peak_rss_mb': resources['sampled_peak_rss_kb'] / 1024,
           'capture_kernel_drops': audit['kernel_drops'], 'capture_late_packets': audit['late_packets'],
           'feature_replay_max_error': audit['max_online_offline_feature_error'],
           'tcp_reassembly_missing_bytes': audit['missing_tcp_bytes'], 'mqtt_parse_errors': len(audit['mqtt_parse_errors'])}
    return row


def main():
    target = ROOT / 'runs/online/final-v1'
    target.mkdir(exist_ok=True)
    plan = read(ROOT / 'data/online/episode-plan.json')
    rows = []
    for entry in plan['system_episodes']:
        path = ROOT / 'runs/online/v1' / entry['episode_id']
        if (path / 'COMPLETED.json').exists():
            rows.append(episode(path))
    if rows:
        with (target / 'system-episodes.csv').open('w', newline='', encoding='utf-8') as output:
            writer = csv.DictWriter(output, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
    results = read(ROOT / 'runs/online/detectors-v1/results.json')
    groups = collections.defaultdict(list)
    for result in results:
        groups[(result['method'], result.get('partition_seed'))].append(result)
    lines = ['# Traffic-linked MQTT experiment', '',
             'Independent captured episodes; all ambiguous/repeated windows retained. '
             'Packet/window counts are not treated as independent traffic-episode replications.', '',
             '## Detector quality on held-out episodes', '',
             '| Method | Partition seed | Training repeats | F1 mean | FPR mean | Recall mean |',
             '|---|---:|---:|---:|---:|---:|']
    for (method, partition), entries in sorted(groups.items(), key=lambda item: str(item[0])):
        means = [np.mean([e['test_metrics'][key] for e in entries]) for key in ['f1', 'fpr', 'recall']]
        lines.append(f'| {method} | {partition if partition is not None else "—"} | {len(entries)} | '
                     + ' | '.join(f'{value:.4f}' for value in means) + ' |')
    lines += ['', 'Per-model results, confusion counts and episode-bootstrap intervals are preserved under detectors-v1. '
              'The rate-threshold baseline uses the same validation FPR constraint as neural models.', '',
              '## Service and response, episode-level aggregation', '',
              f'Completed independent condition episodes: {len(rows)}/{len(plan["system_episodes"])}.', '',
              '| Rate level | Control delay | Mode | Outage | Episodes | Benign delivery mean | Attack messages mean | Response median (ms) |',
              '|---:|---:|---|---|---:|---:|---:|---:|']
    cells = collections.defaultdict(list)
    for row in rows:
        cells[(row['rate_level'], row['delay_ms'], row['mode'], row['outage'])].append(row)
    summary = []
    for (rate, delay, mode, outage), entries in sorted(cells.items()):
        responses = [e['attack_arrival_to_command_ms'] for e in entries if e['response_observed']]
        aggregate = {'rate_level': rate, 'delay_ms': delay, 'mode': mode, 'outage': outage,
                     'episodes': len(entries), 'responded_episodes': len(responses),
                     'benign_delivery_mean': float(np.mean([e['benign_delivery_ratio'] for e in entries])),
                     'attack_messages_mean': float(np.mean([e['delivered_attack_messages'] for e in entries])),
                     'arrival_to_command_median_ms': quantile(responses, 50),
                     'normal_p95_mean_ms': float(np.mean([e['normal_message_p95_ms'] for e in entries if e['normal_message_p95_ms'] is not None])),
                     'false_block_commands': sum(e['false_block_commands'] for e in entries),
                     'kernel_drop_packets': sum(e['kernel_drop_packets'] for e in entries),
                     'response_failures': sum(e['response_failures'] for e in entries)}
        summary.append(aggregate)
        latency = f'{aggregate["arrival_to_command_median_ms"]:.2f}' if responses else 'N/A'
        lines.append(f'| {rate} | {delay} | {mode} | {outage} | {len(entries)} | '
                     f'{aggregate["benign_delivery_mean"]:.4f} | {aggregate["attack_messages_mean"]:.1f} | {latency} |')
    lines += ['', 'A missing response is retained as a coverage outcome, not zero latency. '
              'Window accumulation and the fixed20ms capture holdback are included in arrival-to-command latency. '
              'Command return is an observed installation upper bound; historical kernel DROP counters and real subscriber delivery provide separate enforcement evidence.', '',
              '## Scope and limits', '',
              'Synthetic MQTT publish-flood episodes on one Docker Desktop VM. The new12-field causal source-window model '
              'is separately trained; earlier34-field public-dataset scores do not transfer to this experiment. '
              'The broker sees edge SNAT; publisher attribution is via independent generator/subscriber message IDs. '
              'Original source addresses remain available to the edge FORWARD policy before SNAT. '
              'No address/port value, payload identifier or ground-truth tag is a model feature. '
              'Controller mode authorizes flagged edge alerts. Fail-open outage and TTL recovery trade-offs remain in reported outcomes. '
              'Full details and predeclared conditions: ONLINE_PROTOCOL.md.']
    (target / 'RESULTS.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    (target / 'summary.json').write_text(json.dumps({'detector_results': results, 'completed_system_episodes': len(rows),
             'assigned_system_episodes': len(plan['system_episodes']), 'system_cells': summary, 'system_episodes': rows}, indent=2))
    if rows:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        fig, axes = plt.subplots(1, 3, figsize=(13, 4))
        for mode, color in [('none', '#777777'), ('local', '#167d69'), ('central', '#b25d1b')]:
            selected = [r for r in summary if r['mode'] == mode and r['delay_ms'] == 50 and not r['outage']]
            for axis, key, title in zip(axes, ['benign_delivery_mean', 'attack_messages_mean', 'arrival_to_command_median_ms'],
                                       ['Legitimate message delivery', 'Attack messages delivered', 'Arrival-to-command response (ms)']):
                values = [r for r in selected if r[key] is not None]
                axis.plot([r['rate_level'] for r in values], [r[key] for r in values], marker='o', color=color, label=mode)
                axis.set(title=title, xlabel='Offered load level', xticks=[0, 1, 2])
                axis.grid(alpha=0.2)
        axes[0].set_ylim(0, 1.05)
        axes[1].legend()
        fig.tight_layout()
        fig.savefig(target / 'service-and-response.png', dpi=180)
        plt.close(fig)
    print('\n'.join(lines[:25]), flush=True)
    print(f'Report saved: {target}')


if __name__ == '__main__':
    main()
