"""Auditable response summary with assigned-trial and attempt denominators."""
import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def read_lines(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()] if path.exists() else []


def percentile(rows, key, quantile):
    values = [row[key] for row in rows if key in row]
    return float(np.percentile(values, quantile)) if values else None


def report(directory):
    directory = Path(directory)
    ledger = read_lines(directory / 'artifacts/ledger.jsonl')
    attempts = read_lines(directory / 'attempts.jsonl')
    if not attempts:
        raise RuntimeError('No attempted full-run trials.')
    latest, groups = {}, defaultdict(dict)
    all_terminal = [row for row in attempts if row.get('terminal')]
    for row in all_terminal:
        latest[row['trial_id']] = row
        groups[(row['segment'], row['pair_id'])][row['mode']] = row
    chosen_pairs = {}
    for (segment, pair), modes in groups.items():
        if set(modes) == {'local', 'central'}:
            chosen_pairs[pair] = modes
    assigned = defaultdict(list)
    for row in ledger:
        assigned[(row['seed'], row['delay_ms'], row['mode'])].append(row)
    rows = []
    for (seed, delay, mode), scheduled in sorted(assigned.items()):
        terminal = [latest[row['trial_id']] for row in scheduled if row['trial_id'] in latest]
        blocks = [row for row in terminal if row['status'] == 'ok_block']
        allows = [row for row in terminal if row['status'] == 'ok_allow']
        row = {'seed': seed, 'one_way_delay_ms': delay, 'mode': mode, 'assigned': len(scheduled),
               'terminal': len(terminal), 'unexecuted_or_incomplete': len(scheduled) - len(terminal),
               'block_decisions': sum(item.get('expected_action') == 'block' for item in terminal),
               'verified_blocks': len(blocks), 'verified_allows': len(allows),
               'attack_observations_assigned': len(scheduled) // 2,
               'benign_observations_assigned': len(scheduled) // 2,
               'mitigated_attacks': sum(item['label'] == 1 for item in blocks),
               'false_block_decisions': sum(item['label'] == 0 and item.get('expected_action') == 'block' for item in terminal),
               'actual_false_blocks': sum(item['label'] == 0 and item.get('drop_packets', 0) > 0 for item in terminal),
               'failed_terminal_trials': sum(item['status'] not in ['ok_block', 'ok_allow'] for item in terminal),
               'block_median_ms': percentile(blocks, 'feature_to_firewall_command_ms', 50),
               'block_p95_ms': percentile(blocks, 'feature_to_firewall_command_ms', 95),
               'verification_upper_bound_median_ms': percentile(blocks, 'feature_to_verification_observation_ms', 50),
               'firewall_command_median_ms': percentile(blocks, 'firewall_command_ms', 50),
               'inference_median_ms': percentile(terminal, 'inference_ms', 50),
               'controller_median_ms': percentile(terminal, 'controller_ms', 50),
               'allow_median_ms': percentile(allows, 'decision_ms', 50),
               'allow_p95_ms': percentile(allows, 'decision_ms', 95),
               'status_counts': dict(Counter(item['status'] for item in terminal))}
        rows.append(row)
    pair_rows = []
    for seed in [42, 43, 44]:
        for delay in [0, 10, 50]:
            matching = [modes for modes in chosen_pairs.values()
                        if modes['local']['seed'] == seed and modes['local']['delay_ms'] == delay]
            comparable = [modes for modes in matching
                          if modes['local']['status'] == modes['central']['status'] == 'ok_block']
            deltas = [modes['central']['feature_to_firewall_command_ms'] - modes['local']['feature_to_firewall_command_ms']
                      for modes in comparable]
            pair_rows.append({'seed': seed, 'one_way_delay_ms': delay, 'assigned_pairs': 200,
                              'completed_pairs': len(matching), 'comparable_block_pairs': len(comparable),
                              'excluded_from_block_latency': 200 - len(comparable),
                              'paired_delta_median_ms': float(np.median(deltas)) if deltas else None,
                              'paired_delta_p95_ms': float(np.percentile(deltas, 95)) if deltas else None,
                              'decision_disagreements': sum(m['local'].get('expected_action') != m['central'].get('expected_action') for m in matching),
                              'exclusion_status_pairs': dict(Counter(f'{m["local"]["status"]}/{m["central"]["status"]}' for m in matching if m not in comparable))})
    for name, items in [('summary.csv', rows), ('paired-differences.csv', pair_rows)]:
        with (directory / name).open('w', newline='', encoding='utf-8') as output:
            writer = csv.DictWriter(output, fieldnames=items[0].keys())
            writer.writeheader()
            writer.writerows(items)
    audit = {'assigned_trials': len(ledger), 'unique_terminal_trials': len(latest),
             'unexecuted_or_incomplete_trials': len(ledger) - len(latest),
             'terminal_attempts': len(all_terminal), 'superseded_terminal_attempts': len(all_terminal) - len(latest),
             'started_attempts': sum(not row.get('terminal') for row in attempts),
             'all_terminal_attempt_status_counts': dict(Counter(row['status'] for row in all_terminal)),
             'latest_unique_trial_status_counts': dict(Counter(row['status'] for row in latest.values())),
             'completed_pairs': len(chosen_pairs), 'quantiles': 'numpy percentile, linear interpolation',
             'pair_summary': pair_rows, 'cell_summary': rows}
    (directory / 'audit-summary.json').write_text(json.dumps(audit, indent=2), encoding='utf-8')
    lines = ['# Feature-ready to firewall-command completion', '',
             'Same frozen non-IID FedAvg GRU and validation threshold in local and controller-mediated modes. '
             'CPU inference in isolated Linux containers on Docker Desktop; three model seeds on one laptop.', '',
             f'Assigned trials: {len(ledger)}. Unique terminal trials: {len(latest)}. '
             f'Unexecuted/incomplete: {len(ledger) - len(latest)}. Completed pairs: {len(chosen_pairs)}.', '',
             '| Seed | Nominal one-way control delay (ms) | Mode | Successful blocks / block decisions | Median (ms) | p95 (ms) | Failures / assigned |',
             '|---:|---:|---|---:|---:|---:|---:|']
    number = lambda value: f'{value:.3f}' if value is not None else 'N/A'
    for row in rows:
        lines.append(f'| {row["seed"]} | {row["one_way_delay_ms"]} | {row["mode"]} | '
                     f'{row["verified_blocks"]}/{row["block_decisions"]} | {number(row["block_median_ms"])} | '
                     f'{number(row["block_p95_ms"])} | {row["failed_terminal_trials"]}/{row["assigned"]} |')
    lines += ['', '## Matched local/central differences', '',
              'Differences are central minus local within the same record/model/delay pair. '
              'Only pairs with two verified block outcomes enter these conditional latency statistics. '
              'Allow pairs and failed/incomplete pairs remain in the audit denominators.', '',
              '| Seed | One-way delay (ms) | Comparable block pairs / assigned pairs | Median added time (ms) | p95 added time (ms) |',
              '|---:|---:|---:|---:|---:|']
    for row in pair_rows:
        lines.append(f'| {row["seed"]} | {row["one_way_delay_ms"]} | {row["comparable_block_pairs"]}/200 | '
                     f'{number(row["paired_delta_median_ms"])} | {number(row["paired_delta_p95_ms"])} |')
    manifest = json.loads((directory / 'artifacts/manifest.json').read_text())
    calibrations = read_lines(directory / 'calibrations.jsonl')
    lines += ['', '## Network calibration', '', '| Nominal one-way delay (ms) | Measured policy-RPC median RTT (ms) |', '|---:|---:|']
    for delay in [0, 10, 50]:
        values = [value for item in calibrations if item['edge']['delay_ms'] == delay for value in item['edge']['rpc_rtt_ms']]
        lines.append(f'| {delay} | {number(float(np.median(values)) if values else None)} |')
    lines += ['', '## Decisions and verification', '',
              'See summary.csv for mitigated attacks / 100 attack observations, actual false blocks / 100 benign observations, '
              'classification block decisions, allow latency, inference, command execution, verification bounds and every status count, '
              'for each model/delay/mode. Raw append-only attempts and every earlier partial attempt are preserved.', '',
              f'Observation attack-type mix: {json.dumps(manifest["attack_type_counts"])}.', '',
              '## Measurement limits', '',
              '- t0 follows decoding and validation of a complete standardized feature vector; tensor creation and inference are included. '
              'Capture, extraction, preprocessing and delivery to edge are excluded.',
              '- Command return is an observed upper bound on installation time, not an instrumented kernel commit timestamp. '
              'Independent kernel DROP counters and post-command probes confirm actual filtering; the same UDP service remains reachable from the health source.',
              '- Probe interval is 5 ms; a fixed 25 ms post-command observation window and counter-read overhead are included only in the separate verification upper bound.',
              '- Feature vectors are replayed from Edge-IIoTset. Synthetic UDP probe bytes are not classified by the model; they validate enforcement only.',
              '- 100 benign and 100 attack observations form a balanced, small systems sample, not natural traffic prevalence. '
              'No newly observed test result changes a model, threshold or sampling rule.',
              '- Sequential warmed trials describe this virtualized laptop without saturation. Three frozen model seeds are not independent hardware replications; p95 is descriptive.',
              '- All time differences use edge monotonic timestamps. Controller failures are fail-open, with no hidden local retry or fallback.',
              '- This is not raw-packet-arrival-to-response latency and does not show that federated training itself reduces response time.']
    (directory / 'RESULTS.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))
    for seed, color in [(42, '#176b88'), (43, '#a15a13'), (44, '#6b4e9b')]:
        for mode, style in [('local', '--'), ('central', '-')]:
            selected = [row for row in rows if row['seed'] == seed and row['mode'] == mode]
            for axis, key, title in zip(axes, ['block_median_ms', 'block_p95_ms'], ['Median', 'p95']):
                points = [row for row in selected if row[key] is not None]
                axis.plot([row['one_way_delay_ms'] for row in points], [row[key] for row in points],
                          marker='o', color=color, linestyle=style, label=f'{mode}, seed {seed}')
                axis.set(xlabel='Nominal one-way control delay (ms)', ylabel='Feature-ready to command completion (ms)', title=title)
                axis.grid(alpha=0.2)
    axes[1].legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(directory / 'response-latency.png', dpi=180)
    plt.close(fig)
    print('\n'.join(lines[:28]), flush=True)
    return audit


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-dir', type=Path)
    args = parser.parse_args()
    directory = args.run_dir or Path(json.loads((ROOT / 'runs/response/active.json').read_text())['directory'])
    report(directory)
