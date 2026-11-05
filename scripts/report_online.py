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
    attempted = skipped = attempt_errors = benign_attempt_upper = 0
    for source in range(3):
        for sequence, stamp, tag in read(path / f'source-{source}-offered.json'):
            offered[(source, sequence)] = (stamp, tag)
        source_log = read(path / f'source-{source}.json')
        attempted += source_log['attempted']
        skipped += source_log['skipped_late']
        attempt_errors += source_log['errors']
        offered_benign = sum(tag == 'B' for _, _, tag in read(path / f'source-{source}-offered.json'))
        accepted_benign = sum(tag == 'B' for _, _, tag in source_log['records'])
        benign_attempt_upper += min(offered_benign, accepted_benign + source_log['errors'])
        for sequence, stamp, tag in source_log['records']:
            accepted[(source, sequence)] = (stamp, tag)
    delivered = {}
    for source, sequence, sent, received, tag in subscriber:
        assert (source, sequence) in offered
        delivered[(source, sequence)] = (sent, received, tag)
    benign = {key for key, (_, tag) in offered.items() if tag == 'B'}
    malicious = set(offered) - benign
    delivered_benign = benign & delivered.keys()
    latencies = [(delivered[key][1] - delivered[key][0]) / 1e6 for key in delivered_benign]
    planned_latencies = [(delivered[key][1] - offered[key][0]) / 1e6 for key in delivered_benign]
    decisions = read(path / 'decisions.json')
    blocks = [d for d in decisions if d['status'] == 'blocked']
    attacker = f'172.30.95.{10 + config["attacker"]}'
    onset = audit['first_attack_ingress_ns']
    labeled = read(path / 'labeled-windows.json')
    ground_truth = {(row['window'], row['source']): row['label'] for row in labeled}
    successful = [d for d in blocks if d['source'] == attacker and onset is not None
                  and d['command_end_ns'] >= onset and ground_truth.get((d['window'], d['source'])) == 1]
    response = min(successful, key=lambda d: d['command_end_ns']) if successful else None
    positive = [r for r in labeled if r['source'] == attacker and r['label']]
    first_positive = min(positive, key=lambda r: r['window']) if positive else None
    invalid = []
    for key in ['kernel_drops', 'late_packets', 'missing_tcp_bytes', 'mqtt_parse_errors']:
        if audit[key]:
            invalid.append(key)
    if audit['max_online_offline_feature_error'] >= 1e-8:
        invalid.append('feature_parity')
    if not audit['live_windows']:
        invalid.append('no_windows')
    resources = read(path / 'edge-resources.json')
    drops = counters(read(path / 'rule-events.json'))
    first_command = response['command_end_ns'] if response else None
    recovery_start = config['start_ns'] + int((config['attack_end'] + config['block_ttl']) * 1e9)
    recovery = {key for key in benign if offered[key][0] >= recovery_start}
    other_benign = {key for key in benign if key[0] != config['attacker']}
    row = {'episode_id': config['episode_id'], 'workload_id': config.get('workload_id'),
           'traffic_seed': config['traffic_seed'], 'mode': config['mode'], 'delay_ms': config.get('delay_ms', 0),
           'rate_level': config.get('rate_level'), 'nominal_attack_rate': config['attack_rate'],
           'outage': config.get('outage', False), 'attacker_source': attacker,
           'reconciliation_valid': not invalid, 'reconciliation_issues': ','.join(invalid),
           'scheduled_all_messages': len(offered), 'attempted_all_messages': attempted,
           'socket_accepted_all_messages': len(accepted), 'generator_skipped_late': skipped,
           'generator_attempt_errors': attempt_errors,
           'attempted_benign_lower_bound': len(benign & accepted.keys()), 'attempted_benign_upper_bound': benign_attempt_upper,
           'scheduled_benign': len(benign), 'socket_accepted_benign': len(benign & accepted.keys()),
           'delivered_benign': len(delivered_benign), 'benign_delivery_ratio': len(delivered_benign) / max(len(benign), 1),
           'normal_message_median_ms': quantile(latencies, 50), 'normal_message_p95_ms': quantile(latencies, 95),
           'normal_planned_to_delivery_p95_ms': quantile(planned_latencies, 95),
           'other_sources_benign_delivery_ratio': len(other_benign & delivered.keys()) / max(len(other_benign), 1),
           'post_attack_recovery_benign_delivery_ratio': len(recovery & delivered.keys()) / max(len(recovery), 1),
           'scheduled_attack_messages': len(malicious), 'delivered_attack_messages': len(malicious & delivered.keys()),
           'attack_messages_received_before_command': sum(key in malicious and value[1] <= first_command for key, value in delivered.items()) if first_command else None,
           'first_attack_ingress_ns': onset, 'response_candidate_observed': response is not None,
           'response_observed': response is not None and not invalid,
           'attack_arrival_to_command_ms': (first_command - onset) / 1e6 if response else None,
           'feature_ready_to_command_ms': response['feature_to_command_ms'] if response else None,
           'onset_to_first_attack_window_ready_ms': (first_positive['ready_ns'] - onset) / 1e6 if first_positive and onset is not None else None,
           'subsequent_window_wait_ms': (response['ready_ns'] - first_positive['ready_ns']) / 1e6 if response and first_positive else None,
           'trigger_window_queue_ms': (response['inference_start_ns'] - response['ready_ns']) / 1e6 if response else None,
           'trigger_window_inference_ms': (response['decision_ns'] - response['inference_start_ns']) / 1e6 if response else None,
           'authorization_and_enforcement_ms': (first_command - response['decision_ns']) / 1e6 if response else None,
           'all_block_commands': len(blocks),
           'false_block_commands': sum(ground_truth.get((d['window'], d['source'])) == 0 for d in blocks),
           'unknown_label_block_commands': sum((d['window'], d['source']) not in ground_truth for d in blocks),
           'pre_onset_block_commands': sum(onset is not None and d['command_end_ns'] < onset for d in blocks),
           'attacker_benign_window_post_onset_blocks': sum(d['source'] == attacker and onset is not None
                and d['command_end_ns'] >= onset and ground_truth.get((d['window'], d['source'])) == 0 for d in blocks),
           'other_source_block_commands': sum(d['source'] != attacker for d in blocks),
           'response_failures': sum(d['status'] == 'response_failure' for d in decisions),
           'observed_windows': audit['live_windows'], 'completed_inference_windows': len(decisions),
           'unprocessed_windows_at_episode_stop': audit['live_windows'] - len(decisions),
           'kernel_drop_packets': sum(drops.values()), 'drops_by_source': drops,
           'edge_cpu_core_fraction': resources['active_cpu_seconds'] / max(resources['active_wall_seconds'], 1e-9),
           'edge_sampled_peak_rss_mb': resources['sampled_peak_rss_kb'] / 1024,
           'capture_kernel_drops': audit['kernel_drops'], 'capture_late_packets': audit['late_packets'],
           'feature_replay_max_error': audit['max_online_offline_feature_error'],
           'tcp_reassembly_missing_bytes': audit['missing_tcp_bytes'], 'mqtt_parse_errors': len(audit['mqtt_parse_errors']),
           'socket_accepted_not_reassembled': audit['accepted_not_reassembled']}
    if response:
        total = sum(row[k] for k in ['onset_to_first_attack_window_ready_ms', 'subsequent_window_wait_ms',
                    'trigger_window_queue_ms', 'trigger_window_inference_ms', 'authorization_and_enforcement_ms'])
        assert abs(total - row['attack_arrival_to_command_ms']) < 1e-6
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
              f'Completed condition episodes: {len(rows)}/{len(plan["system_episodes"])}; '
              f'valid capture/label reconstructions: {sum(r["reconciliation_valid"] for r in rows)}/{len(rows)}. '
              'The regular matrix repeats nine independent workload seeds across six conditions; '
              'three additional workload seeds are paired across local/central outage conditions. '
              'Repeated conditions are paired measurements, not additional independent workloads.', '',
              '| Rate level | One-way delay (ms) | Mode | Outage | Episodes | Valid | Responded / assigned | Benign delivery mean | Attack messages mean | Conditional response median (ms) |',
              '|---:|---:|---|---|---:|---:|---:|---:|---:|---:|']
    cells = collections.defaultdict(list)
    for row in rows:
        cells[(row['rate_level'], row['delay_ms'], row['mode'], row['outage'])].append(row)
    summary = []
    for (rate, delay, mode, outage), entries in sorted(cells.items()):
        responses = [e['attack_arrival_to_command_ms'] for e in entries if e['response_observed']]
        aggregate = {'rate_level': rate, 'delay_ms': delay, 'mode': mode, 'outage': outage,
                     'episodes': len(entries), 'responded_episodes': len(responses),
                     'valid_episodes': sum(e['reconciliation_valid'] for e in entries),
                     'benign_delivery_mean': float(np.mean([e['benign_delivery_ratio'] for e in entries])),
                     'attack_messages_mean': float(np.mean([e['delivered_attack_messages'] for e in entries])),
                     'arrival_to_command_median_ms': quantile(responses, 50),
                     'normal_p95_mean_ms': float(np.mean([e['normal_message_p95_ms'] for e in entries if e['normal_message_p95_ms'] is not None])),
                     'false_block_commands_valid_episodes': sum(e['false_block_commands'] for e in entries if e['reconciliation_valid']),
                     'kernel_drop_packets': sum(e['kernel_drop_packets'] for e in entries),
                     'response_failures': sum(e['response_failures'] for e in entries)}
        for key in ['onset_to_first_attack_window_ready_ms', 'subsequent_window_wait_ms', 'trigger_window_queue_ms',
                    'trigger_window_inference_ms', 'authorization_and_enforcement_ms', 'feature_ready_to_command_ms']:
            aggregate[key + '_median'] = quantile([e[key] for e in entries if e['response_observed']], 50)
        summary.append(aggregate)
        latency = f'{aggregate["arrival_to_command_median_ms"]:.2f}' if responses else 'N/A'
        lines.append(f'| {rate} | {delay} | {mode} | {outage} | {len(entries)} | {aggregate["valid_episodes"]} | {len(responses)}/{len(entries)} | '
                     f'{aggregate["benign_delivery_mean"]:.4f} | {aggregate["attack_messages_mean"]:.1f} | {latency} |')
    indexed = {(r['workload_id'], r['delay_ms'], r['mode'], r['outage']): r for r in rows}
    pairs = []
    for local in rows:
        if local['mode'] != 'local':
            continue
        central = indexed.get((local['workload_id'], local['delay_ms'], 'central', local['outage']))
        if central is None:
            continue
        both = local['response_observed'] and central['response_observed']
        pairs.append({'workload_id': local['workload_id'], 'rate_level': local['rate_level'],
                      'delay_ms': local['delay_ms'], 'outage': local['outage'],
                      'local_episode': local['episode_id'], 'central_episode': central['episode_id'],
                      'both_valid': local['reconciliation_valid'] and central['reconciliation_valid'],
                      'local_responded': local['response_observed'], 'central_responded': central['response_observed'],
                      'central_minus_local_response_ms': central['attack_arrival_to_command_ms'] - local['attack_arrival_to_command_ms'] if both else None,
                      'central_minus_local_benign_delivery': central['benign_delivery_ratio'] - local['benign_delivery_ratio'],
                      'central_minus_local_attack_messages': central['delivered_attack_messages'] - local['delivered_attack_messages']})
    with (target / 'paired-conditions.csv').open('w', newline='', encoding='utf-8') as output:
        writer = csv.DictWriter(output, fieldnames=list(pairs[0]) if pairs else ['workload_id'])
        writer.writeheader()
        writer.writerows(pairs)
    lines += ['', '## Matched local/controller comparisons', '',
              '| One-way delay (ms) | Outage | Assigned pairs | Both valid | Both responded | Median central minus local response (ms) |',
              '|---:|---|---:|---:|---:|---:|']
    for delay, outage in sorted({(p['delay_ms'], p['outage']) for p in pairs}):
        selected = [p for p in pairs if p['delay_ms'] == delay and p['outage'] == outage]
        differences = [p['central_minus_local_response_ms'] for p in selected if p['central_minus_local_response_ms'] is not None]
        difference = f'{quantile(differences, 50):.2f}' if differences else 'N/A'
        lines.append(f'| {delay} | {outage} | {len(selected)} | {sum(p["both_valid"] for p in selected)} | {len(differences)} | {difference} |')
    lines += ['', '## Response decomposition (conditional on a valid attack-window-triggered response)', '',
              '| Delay | Mode | Outage | Responded | First attack window ready (ms) | Subsequent-window wait (ms) | Queue (ms) | Inference (ms) | Authorization + enforcement (ms) |',
              '|---:|---|---|---:|---:|---:|---:|---:|---:|']
    for delay, mode, outage in sorted({(r['delay_ms'], r['mode'], r['outage']) for r in rows if r['mode'] != 'none'}):
        selected = [r for r in rows if r['delay_ms'] == delay and r['mode'] == mode and r['outage'] == outage and r['response_observed']]
        values = [quantile([r[k] for r in selected], 50) for k in ['onset_to_first_attack_window_ready_ms',
                  'subsequent_window_wait_ms', 'trigger_window_queue_ms', 'trigger_window_inference_ms', 'authorization_and_enforcement_ms']]
        lines.append(f'| {delay} | {mode} | {outage} | {len(selected)} | ' + ' | '.join(f'{v:.2f}' if v is not None else 'N/A' for v in values) + ' |')
    lines += ['', 'A missing response is retained as a coverage outcome, not zero latency. '
              'A successful detection response requires that the actual triggering source window contains independently reconciled malicious message bytes. '
              'Pre-onset blocks and post-onset blocks triggered by benign windows are separately counted in system-episodes.csv. '
              'Invalid capture/label reconstructions are retained and flagged; their candidate latencies are excluded from primary response summaries. '
              'Service summaries include all completed episodes using independent subscriber records. '
              'First-window readiness includes accumulation and the fixed20ms holdback; waiting for later triggering windows is a separate term. '
              'Queue, inference and combined authorization/enforcement are directly timestamped; RPC and firewall installation cannot be separately estimated from this journal. '
              'Component medians need not sum to the median total. '
              'Command return is an observed installation upper bound; historical kernel DROP counters and real subscriber delivery provide separate enforcement evidence.', '',
              '## Service cost, capture reliability and interpretation', '',
              'Without mitigation, legitimate-message delivery was 100% in every episode. Thus this workload does not demonstrate an availability improvement. '
              'Mitigation reduces delivered attacking messages, but can also suppress legitimate messages from the blocked source. '
              'Both other publishers retain 100% legitimate-message delivery in all 60 episodes. '
              'Delivery is divided by the independently preplanned offered message count, including messages never attempted or socket-accepted. '
              'Normal-message median/p95 columns measure actual send-to-subscriber receipt, conditional on delivery; '
              'normal_planned_to_delivery_p95_ms additionally includes scheduling/connection delay. '
              'The generator saves exact aggregate attempts/errors/skips and per-message accepted IDs; attempted benign counts are only bounded when a failed attempt lacks a tag. '
              'Socket acceptance is not proof of packet ingress or service delivery.', '',
              f'Worst post-attack recovery delivery ratio (scheduled after attack end + nominal TTL): '
              f'{min(r["post_attack_recovery_benign_delivery_ratio"] for r in rows):.4f}. '
              'TTL expiry alone does not guarantee immediate recovery: later decisions and TCP state can extend service disruption.', '',
              '| Invalid episode | Capture/label reconstruction issues | Kernel capture drops | Late packets |',
              '|---|---|---:|---:|']
    for row in rows:
        if not row['reconciliation_valid']:
            lines.append(f'| {row["episode_id"]} | {row["reconciliation_issues"]} | {row["capture_kernel_drops"]} | {row["capture_late_packets"]} |')
    valid = [r for r in rows if r['reconciliation_valid']]
    primary = next(r for r in results if r['id'] == 'fedmlp-noniid-p42-s42')
    lines += ['', f'Valid reconstructed episodes: {len(valid)}; false triggering-window block commands within them: '
              f'{sum(r["false_block_commands"] for r in valid)}. '
              'Invalid reconstruction cannot establish absence of false blocks. '
              f'Observed historical firewall DROP packets across all completed episodes: {sum(r["kernel_drop_packets"] for r in rows)}. '
              f'Controller response failures: {sum(r["response_failures"] for r in rows)}. '
              'In central outage episodes, 42/43/44 windows respectively remained unprocessed at episode stop; '
              'timeout-induced inference-queue backlog is part of the fail-open outcome.', '',
              f'Primary deployed model was preselected independently of test scores: {primary["id"]}, '
              f'threshold {primary["threshold"]:.6f}; held-out F1={primary["test_metrics"]["f1"]:.4f}, '
              f'recall={primary["test_metrics"]["recall"]:.4f}. '
              'Non-IID partition43 failures are retained. This study does not establish that FedAvg or GRU outperforms centralized MLP or a rate threshold.', '',
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
             'assigned_system_episodes': len(plan['system_episodes']), 'system_cells': summary, 'system_episodes': rows,
             'paired_conditions': pairs}, indent=2))
    if rows:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        fig, axes = plt.subplots(1, 3, figsize=(13, 4))
        for mode, color in [('none', '#777777'), ('local', '#167d69'), ('central', '#b25d1b')]:
            selected = [r for r in summary if r['mode'] == mode and r['delay_ms'] == 50 and not r['outage']]
            for axis, key, title in zip(axes, ['benign_delivery_mean', 'attack_messages_mean', 'arrival_to_command_median_ms'],
                                       ['Legitimate message delivery', 'Attack messages delivered', 'Conditional response (ms)']):
                values = [r for r in selected if r[key] is not None]
                axis.plot([r['rate_level'] for r in values], [r[key] for r in values], marker='o', color=color, label=mode)
                if key == 'arrival_to_command_median_ms':
                    for r in values:
                        axis.annotate(f'{r["responded_episodes"]}/{r["episodes"]}',
                                      (r['rate_level'], r[key]), xytext=(5, 7), textcoords='offset points', color=color, fontsize=8)
                axis.set(title=title, xlabel='Offered load level', xticks=[0, 1, 2])
                axis.grid(alpha=0.2)
        axes[0].set_ylim(0, 1.05)
        observed_response = [r['arrival_to_command_median_ms'] for r in summary
                             if r['delay_ms'] == 50 and not r['outage'] and r['arrival_to_command_median_ms'] is not None]
        if observed_response:
            axes[2].set_ylim(0, max(observed_response) * 1.18)
        axes[1].legend()
        fig.suptitle('50 ms one-way control delay; 3 episodes per cell. Response coverage: see RESULTS.md', fontsize=10)
        fig.tight_layout()
        fig.savefig(target / 'service-and-response.png', dpi=180)
        plt.close(fig)
    print('\n'.join(lines[:25]), flush=True)
    print(f'Report saved: {target}')


if __name__ == '__main__':
    main()
