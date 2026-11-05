"""Experiment 2b report: delay sweep with timeout accounting and central-minus-local vs measured-RTT regression."""
import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def read_lines(path):
    path = Path(path)
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()] if path.exists() else []


def percentile(rows, key, quantile):
    values = [row[key] for row in rows if row.get(key) is not None]
    return float(np.percentile(values, quantile)) if values else None


def ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def is_timeout(row):
    """Controller reply did not arrive within the (1 s) trial timeout: fail-open, no mitigation."""
    if row.get('failure_kind') == 'timeout':
        return True
    text = str(row.get('error', '')).lower()
    return row.get('status') == 'controller_failure' and ('timed out' in text or 'timeouterror' in text)


def cell_row(scheduled, latest):
    """One condition (seed/delay/mode/rate or a pooled union of those)."""
    terminal = [latest[row['trial_id']] for row in scheduled if row['trial_id'] in latest]
    blocks = [row for row in terminal if row['status'] == 'ok_block']
    allows = [row for row in terminal if row['status'] == 'ok_allow']
    decisions = [row for row in terminal if row.get('expected_action') == 'block']
    timeouts = [row for row in terminal if is_timeout(row)]
    decisions_lost = [row for row in decisions if is_timeout(row)]
    attacks_assigned = sum(row.get('label') == 1 for row in scheduled)
    attacks = [row for row in terminal if row.get('label') == 1]
    cell = {'assigned': len(scheduled), 'terminal': len(terminal),
            'unexecuted_or_incomplete': len(scheduled) - len(terminal),
            'block_decisions': len(decisions), 'verified_blocks': len(blocks),
            'verified_block_share': ratio(len(blocks), len(decisions)),
            'block_decisions_lost_to_timeout': len(decisions_lost),
            'block_within_timeout_share': None if not decisions else ratio(sum(row.get('controller_ms') is not None or row['status'] in ['ok_block', 'ok_allow', 'enforcement_failure'] for row in decisions), len(decisions)),
            'timeout_failures': len(timeouts),
            'other_failures': sum(row['status'] not in ['ok_block', 'ok_allow'] for row in terminal) - len(timeouts),
            'attacks_assigned': attacks_assigned,
            'attacks_mitigated': sum(row['status'] == 'ok_block' for row in attacks),
            'attacks_unblocked_by_timeout': sum(is_timeout(row) and row.get('expected_action') == 'block' for row in attacks),
            'attacks_unblocked_by_timeout_share': ratio(sum(is_timeout(row) and row.get('expected_action') == 'block' for row in attacks), attacks_assigned),
            'detector_missed_attacks': sum(row.get('expected_action') == 'allow' for row in attacks),
            'false_block_decisions': sum(row.get('label') == 0 and row.get('expected_action') == 'block' for row in terminal),
            'block_median_ms': percentile(blocks, 'feature_to_firewall_command_ms', 50),
            'block_p95_ms': percentile(blocks, 'feature_to_firewall_command_ms', 95),
            'verification_upper_bound_median_ms': percentile(blocks, 'feature_to_verification_observation_ms', 50),
            'firewall_command_median_ms': percentile(blocks, 'firewall_command_ms', 50),
            'inference_median_ms': percentile(terminal, 'inference_ms', 50),
            'controller_median_ms': percentile(blocks + allows, 'controller_ms', 50),
            'timeout_elapsed_median_ms': percentile(timeouts, 'failure_elapsed_ms', 50),
            'allow_median_ms': percentile(allows, 'decision_ms', 50),
            'allow_p95_ms': percentile(allows, 'decision_ms', 95),
            'status_counts': dict(Counter(row['status'] for row in terminal))}
    if any('chain_arrived_packets' in row for row in terminal):  # rate profile only
        cell.update(arrived_median=percentile(blocks, 'chain_arrived_packets', 50),
                    dropped_median=percentile(blocks, 'drop_packets', 50),
                    passed_in_counter_interval_median=percentile(blocks, 'passed_in_counter_interval_packets', 50),
                    passed_in_counter_interval_p95=percentile(blocks, 'passed_in_counter_interval_packets', 95),
                    achieved_rate_pps_median=percentile(terminal, 'counter_ingress_rate_pps', 50))
    return cell


def regression(points):
    """OLS of paired (central - local) added time on the measured policy-RPC RTT. points: [(rtt_ms, delta_ms)]."""
    n = len(points)
    result = {'n': n, 'slope': None, 'intercept': None, 'r2': None, 'slope_se': None}
    if n < 3:
        return result
    x, y = np.array([p[0] for p in points], float), np.array([p[1] for p in points], float)
    if np.ptp(x) == 0:
        return result
    slope, intercept = np.polyfit(x, y, 1)
    residual = y - (intercept + slope * x)
    ss_res, ss_tot = float((residual ** 2).sum()), float(((y - y.mean()) ** 2).sum())
    result.update(slope=float(slope), intercept=float(intercept),
                  r2=None if ss_tot == 0 else 1 - ss_res / ss_tot,
                  slope_se=None)  # descriptive fit; shared block RTTs are not independent samples
    return result


def summarize(ledger, attempts, calibrations):
    """Pure function over the three journals; returns everything the files and markdown are built from."""
    if not attempts:
        raise RuntimeError('No attempted full-run trials.')
    latest, groups = {}, defaultdict(dict)
    all_terminal = [row for row in attempts if row.get('terminal')]
    for row in all_terminal:
        latest[row['trial_id']] = row
        groups[(row['segment'], row['pair_id'])][row['mode']] = row
    chosen_pairs = {pair: modes for (segment, pair), modes in groups.items() if set(modes) == {'local', 'central'}}
    by_cell, by_pooled, assigned_pairs = defaultdict(list), defaultdict(list), Counter()
    for row in ledger:
        rate = row.get('probe_rate_pps')
        by_cell[(row['seed'], rate, row['delay_ms'], row['mode'])].append(row)
        by_pooled[(rate, row['delay_ms'], row['mode'])].append(row)
        if row['mode'] == 'local':
            assigned_pairs[(row['seed'], rate, row['delay_ms'])] += 1
    seed_rows = [{'seed': seed, 'probe_rate_pps': rate, 'one_way_delay_ms': delay, 'mode': mode,
                  **cell_row(rows, latest)} for (seed, rate, delay, mode), rows in sorted(by_cell.items(), key=lambda item: (item[0][0], item[0][1] or 0, item[0][2], item[0][3]))]
    pooled_rows = [{'probe_rate_pps': rate, 'one_way_delay_ms': delay, 'mode': mode, **cell_row(rows, latest)}
                   for (rate, delay, mode), rows in sorted(by_pooled.items(), key=lambda item: (item[0][0] or 0, item[0][1], item[0][2]))]
    rtt_by_block = {}
    for item in calibrations:
        values = item['edge']['rpc_rtt_ms']
        rtt_by_block[(item['segment'], item['block_id'])] = float(np.median(values))
    pair_rows, points = [], defaultdict(list)
    missing_calibration = 0
    for (seed, rate, delay), assigned in sorted(assigned_pairs.items(), key=lambda item: (item[0][0], item[0][1] or 0, item[0][2])):
        matching = [modes for modes in chosen_pairs.values()
                    if modes['local']['seed'] == seed and modes['local']['delay_ms'] == delay
                    and modes['local'].get('probe_rate_pps') == rate]
        comparable = [modes for modes in matching if modes['local']['status'] == modes['central']['status'] == 'ok_block']
        deltas = []
        for modes in comparable:
            delta = modes['central']['feature_to_firewall_command_ms'] - modes['local']['feature_to_firewall_command_ms']
            deltas.append(delta)
            key = (modes['central']['segment'], modes['central']['block_id'])
            if key in rtt_by_block:
                points[rate].append((rtt_by_block[key], delta, delay))
            else:
                missing_calibration += 1
        pair_rows.append({'seed': seed, 'probe_rate_pps': rate, 'one_way_delay_ms': delay, 'assigned_pairs': assigned,
                          'completed_pairs': len(matching), 'comparable_block_pairs': len(comparable),
                          'excluded_from_block_latency': assigned - len(comparable),
                          'paired_delta_median_ms': float(np.median(deltas)) if deltas else None,
                          'paired_delta_p95_ms': float(np.percentile(deltas, 95)) if deltas else None,
                          'decision_disagreements': sum(m['local'].get('expected_action') != m['central'].get('expected_action') for m in matching),
                          'exclusion_status_pairs': dict(Counter(f'{m["local"]["status"]}/{m["central"]["status"]}'
                                                                 for m in matching if m not in comparable))})
    regression_rows = []
    for rate, items in sorted(points.items(), key=lambda item: item[0] or 0):
        fit = regression([(rtt, delta) for rtt, delta, _ in items])
        regression_rows.append({'probe_rate_pps': rate, **fit,
                                'rtt_min_ms': min(p[0] for p in items), 'rtt_max_ms': max(p[0] for p in items),
                                'delays_included_ms': sorted({p[2] for p in items})})
    calibration_rows = []
    for rate_delay in sorted({item['edge']['delay_ms'] for item in calibrations}):
        mine = [item for item in calibrations if item['edge']['delay_ms'] == rate_delay]
        values = [v for item in mine for v in item['edge']['rpc_rtt_ms']]
        calibration_rows.append({'one_way_delay_ms': rate_delay, 'blocks': len(mine),
                                 'rpc_rtt_median_ms': float(np.median(values)), 'rpc_rtt_p95_ms': float(np.percentile(values, 95)),
                                 'trial_connection_warm_failures': sum(not item['edge'].get('trial_connection_warm_ok', True) for item in mine)})
    audit = {'assigned_trials': len(ledger), 'unique_terminal_trials': len(latest),
             'unexecuted_or_incomplete_trials': len(ledger) - len(latest),
             'terminal_attempts': len(all_terminal), 'superseded_terminal_attempts': len(all_terminal) - len(latest),
             'started_attempts': sum(not row.get('terminal') for row in attempts),
             'all_terminal_attempt_status_counts': dict(Counter(row['status'] for row in all_terminal)),
             'latest_unique_trial_status_counts': dict(Counter(row['status'] for row in latest.values())),
             'timeout_failures_latest': sum(is_timeout(row) for row in latest.values()),
             'completed_pairs': len(chosen_pairs), 'pairs_without_calibration': missing_calibration,
             'quantiles': 'numpy percentile, linear interpolation'}
    return {'audit': audit, 'pooled': pooled_rows, 'by_seed': seed_rows, 'pairs': pair_rows,
            'regression': regression_rows, 'calibration': calibration_rows}


def number(value, digits=3):
    return f'{value:.{digits}f}' if value is not None else 'N/A'


def percent(value):
    return f'{100 * value:.1f}%' if value is not None else 'N/A'


def render_markdown(result, manifest=None):
    audit = result['audit']
    rated = any(row['probe_rate_pps'] for row in result['pooled'])
    lines = ['# Experiment 2b: controller-delay sweep', '',
             'Same frozen non-IID FedAvg GRU, 200 replayed records, local vs controller-mediated policy as experiment 2; '
             'only the one-way control delay grid and the timeout accounting are new. Trial RPC timeout is 1 s '
             '(calibration uses a separate 10 s timeout). Controller failure is fail-open with no local fallback.', '',
             f'Assigned trials: {audit["assigned_trials"]}. Unique terminal trials: {audit["unique_terminal_trials"]}. '
             f'Unexecuted/incomplete: {audit["unexecuted_or_incomplete_trials"]}. Completed pairs: {audit["completed_pairs"]}. '
             f'Timeout failures (latest per trial): {audit["timeout_failures_latest"]}.', '',
             '## Latency and timeout accounting (pooled over the three model seeds)', '',
             ('| Rate (pkt/s) ' if rated else '') + '| One-way delay (ms) | Mode | Verified blocks / block decisions | Median (ms) | p95 (ms) '
             '| Blocks within timeout | Attacks unblocked by timeout | Timeouts / assigned |',
             ('|---:' if rated else '') + '|---:|---|---:|---:|---:|---:|---:|---:|']
    for row in result['pooled']:
        lines.append((f'| {row["probe_rate_pps"]} ' if rated else '') +
                     f'| {row["one_way_delay_ms"]} | {row["mode"]} | {row["verified_blocks"]}/{row["block_decisions"]} | '
                     f'{number(row["block_median_ms"])} | {number(row["block_p95_ms"])} | {percent(row["block_within_timeout_share"])} | '
                     f'{row["attacks_unblocked_by_timeout"]}/{row["attacks_assigned"]} ({percent(row["attacks_unblocked_by_timeout_share"])}) | '
                     f'{row["timeout_failures"]}/{row["assigned"]} |')
    lines += ['', '"Blocks within timeout" = block decisions with a recorded successful authorization (local decisions are immediate); other controller failures are excluded. '
              '"Attacks unblocked by timeout" = attack observations (label 1) with a block decision prevented by a controller timeout, '
              'over all assigned attack observations for that condition. Latency statistics use verified blocks only; '
              'timed-out trials are never given a latency.', '',
              '## Matched local/central differences', '',
              'Central minus local within the same record/model/delay pair; only pairs with two verified blocks.', '',
              ('| Rate ' if rated else '') + '| Seed | One-way delay (ms) | Comparable block pairs / assigned pairs | Median added (ms) | p95 added (ms) |',
              ('|---:' if rated else '') + '|---:|---:|---:|---:|---:|']
    for row in result['pairs']:
        lines.append((f'| {row["probe_rate_pps"]} ' if rated else '') +
                     f'| {row["seed"]} | {row["one_way_delay_ms"]} | {row["comparable_block_pairs"]}/{row["assigned_pairs"]} | '
                     f'{number(row["paired_delta_median_ms"])} | {number(row["paired_delta_p95_ms"])} |')
    lines += ['', '## Added time vs measured RTT (regression)', '',
              'OLS of the paired added time (central - local, ms) on the median policy-RPC RTT measured in that block\'s calibration. '
              'A slope near 1 means each measured millisecond of RTT adds about one millisecond; the intercept is the '
              'fitted residual offset after measured RTT. Pairs within a block share one RTT value and the three models share one VM, '
              'so no ordinary independent-sample standard error is reported.', '',
              ('| Rate ' if rated else '') + '| Pairs | Slope | Slope SE | Intercept (ms) | R² | RTT range (ms) | Delays (ms) |',
              ('|---:' if rated else '') + '|---:|---:|---:|---:|---:|---|---|']
    for row in result['regression']:
        lines.append((f'| {row["probe_rate_pps"]} ' if rated else '') +
                     f'| {row["n"]} | {number(row["slope"])} | {number(row["slope_se"])} | {number(row["intercept"])} | '
                     f'{number(row["r2"])} | {number(row["rtt_min_ms"], 1)}-{number(row["rtt_max_ms"], 1)} | {row["delays_included_ms"]} |')
    lines += ['', '## Network calibration', '',
              '| Nominal one-way delay (ms) | Blocks | Measured RTT median (ms) | p95 (ms) | Trial connection failed to warm |', '|---:|---:|---:|---:|---:|']
    for row in result['calibration']:
        lines.append(f'| {row["one_way_delay_ms"]} | {row["blocks"]} | {number(row["rpc_rtt_median_ms"])} | '
                     f'{number(row["rpc_rtt_p95_ms"])} | {row["trial_connection_warm_failures"]} |')
    if rated:
        lines += ['', '## Packet accounting (rate profile)', '',
                  'Counted for packets from the replay client at the edge chain: `arrived` = packets seen by a target-less counting rule placed '
                  'before the DROP, `dropped` = DROP-rule hits, `passed in counter interval` = arrived - dropped. The interval starts before t0 and ends at verification; counter-read boundary uncertainty is journaled. These are not exact t0-to-installation packet counts. Achieved rate uses ingress counters over this interval. Medians over verified blocks.', '',
                  '| Rate (pkt/s) | Delay (ms) | Mode | Achieved rate (pkt/s) | Arrived | Dropped | Passed in counter interval (median / p95) |',
                  '|---:|---:|---|---:|---:|---:|---:|']
        for row in result['pooled']:
            lines.append(f'| {row["probe_rate_pps"]} | {row["one_way_delay_ms"]} | {row["mode"]} | '
                         f'{number(row.get("achieved_rate_pps_median"), 0)} | {number(row.get("arrived_median"), 0)} | '
                         f'{number(row.get("dropped_median"), 0)} | {number(row.get("passed_in_counter_interval_median"), 0)} / '
                         f'{number(row.get("passed_in_counter_interval_p95"), 0)} |')
    lines += ['', '## Measurement limits', '',
              '- Same boundary as experiment 2: t0 is a validated feature vector at edge; command return is an installation upper bound; '
              'capture, extraction and preprocessing are excluded; probe bytes are not classified.',
              '- Netem delay is nominal; the measured RTT above is what the regression uses.',
              '- A timed-out central trial is a fail-open miss: no mitigation, no latency, kept in every denominator.',
              '- At and above ~500 ms one-way delay the RTT exceeds the 1 s trial timeout, so central trials are expected to time out by construction.',
              '- Three frozen model seeds on one VM are not independent hardware replications; p95 is descriptive.']
    return '\n'.join(lines) + '\n'


def write_csv(path, rows):
    if not rows:
        return
    with Path(path).open('w', newline='', encoding='utf-8') as output:
        writer = csv.DictWriter(output, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def plot(result, directory):
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError:
        return False
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.5))
    for rate in sorted({row['probe_rate_pps'] for row in result['pooled']}, key=lambda value: value or 0):
        for mode, style in [('local', '--'), ('central', '-')]:
            rows = [row for row in result['pooled'] if row['probe_rate_pps'] == rate and row['mode'] == mode]
            for axis, key, title in zip(axes[:2], ['block_median_ms', 'block_p95_ms'], ['Median', 'p95']):
                points = [row for row in rows if row[key] is not None]
                axis.plot([row['one_way_delay_ms'] for row in points], [row[key] for row in points], marker='o',
                          linestyle=style, label=f'{mode}' + (f', {rate} pkt/s' if rate else ''))
                axis.set(xlabel='Nominal one-way control delay (ms)', ylabel='Feature-ready to command completion (ms)', title=title)
                axis.grid(alpha=0.2)
    axes[1].legend(fontsize=8)
    for row in result['regression']:
        if row['slope'] is not None:
            xs = np.array([row['rtt_min_ms'], row['rtt_max_ms']])
            axes[2].plot(xs, row['intercept'] + row['slope'] * xs, label=f'slope {row["slope"]:.2f}' + (f' ({row["probe_rate_pps"]} pkt/s)' if row['probe_rate_pps'] else ''))
    axes[2].set(xlabel='Measured policy-RPC RTT (ms)', ylabel='Central - local (ms)', title='Added time vs RTT')
    axes[2].grid(alpha=0.2)
    axes[2].legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(Path(directory) / 'response-2b-latency.png', dpi=180)
    plt.close(fig)
    return True


def report(directory):
    directory = Path(directory)
    profile_file = directory / 'profile.json'
    profile = json.loads(profile_file.read_text())['profile'] if profile_file.exists() else None
    ledger_name = 'ledger-rate.jsonl' if profile == 'rate' or (profile is None and (directory / 'artifacts/ledger-rate.jsonl').exists()
                                                              and not (directory / 'artifacts/ledger.jsonl').exists()) else 'ledger.jsonl'
    ledger = read_lines(directory / 'artifacts' / ledger_name)
    result = summarize(ledger, read_lines(directory / 'attempts.jsonl'), read_lines(directory / 'calibrations.jsonl'))
    write_csv(directory / 'summary.csv', result['pooled'])
    write_csv(directory / 'summary-by-seed.csv', result['by_seed'])
    write_csv(directory / 'paired-differences.csv', result['pairs'])
    write_csv(directory / 'regression.csv', result['regression'])
    write_csv(directory / 'calibration.csv', result['calibration'])
    (directory / 'audit-summary.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    markdown = render_markdown(result)
    (directory / 'RESULTS.md').write_text(markdown, encoding='utf-8')
    plot(result, directory)
    print('\n'.join(markdown.splitlines()[:30]), flush=True)
    return result['audit']


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-dir', type=Path)
    args = parser.parse_args()
    report(args.run_dir or Path(json.loads((ROOT / 'runs/response_2b/active.json').read_text())['directory']))
