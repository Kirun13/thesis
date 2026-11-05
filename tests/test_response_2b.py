import hashlib
import json
import random
import re
import socket
import threading
import time
from unittest.mock import patch, Mock
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'response_2b'))
sys.path.insert(0, str(ROOT / 'scripts'))
import lab_2b  # noqa: E402  (module name differs from experiment 2's `lab` on purpose)
import prepare_response_2b as prepare  # noqa: E402
import report_response_2b as report  # noqa: E402


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def synthetic_observations(count=200):
    return [{'observation_id': f'test-{i}', 'test_index': i, 'processed_row_id': 1000 + i,
             'feature_hash_u64': str(i), 'label': i % 2, 'attack_type': 'DDoS_UDP' if i % 2 else 'Normal',
             'features': [float(i)] * 3} for i in range(count)]


def make_source(directory, with_decoy_ledger=True):
    """A stand-in for data/response/ containing only what experiment 2 froze."""
    directory.mkdir(parents=True)
    files = {'observations.json': json.dumps(synthetic_observations()).encode(),
             'smoke-observations.json': json.dumps({'42': []}).encode()}
    for seed in [42, 43, 44]:
        files[f'model-{seed}.pt'] = f'fake-model-{seed}'.encode()
    for name, payload in files.items():
        (directory / name).write_bytes(payload)
    if with_decoy_ledger:  # experiment 2's own ledger must not be read or changed
        (directory / 'ledger.jsonl').write_text('{"decoy": true}\n')
    manifest = {'prepared_data_sha256': 'abc', 'features': ['a', 'b', 'c'], 'sampling_seed': 20261104,
                'models': [{'seed': seed, 'threshold': 0.5, 'model_file': f'model-{seed}.pt',
                            'expected_probabilities': [0.1]} for seed in [42, 43, 44]],
                'artifact_checksums': {name: hashlib.sha256(payload).hexdigest() for name, payload in files.items()}}
    (directory / 'manifest.json').write_text(json.dumps(manifest))
    return directory


class ScheduleChecks(unittest.TestCase):
    def test_base_ledger_covers_five_delays_and_is_balanced(self):
        ledger = prepare.build_ledger(synthetic_observations(), prepare.SEEDS, prepare.DELAYS, prepare.SCHEDULER_SEED)
        self.assertEqual(len(ledger), 3 * 5 * 200 * 2)
        audit = prepare.validate_ledger(ledger, prepare.SEEDS, prepare.DELAYS, 200)
        self.assertEqual((audit['pairs'], audit['blocks']), (3000, 150))
        self.assertEqual({row['delay_ms'] for row in ledger}, {0, 10, 50, 100, 250})
        self.assertNotIn(500, {row['delay_ms'] for row in ledger})
        self.assertEqual({row['label'] for row in ledger}, {0, 1})

    def test_optional_500_ms_flag_adds_a_sixth_delay(self):
        delays = prepare.DELAYS + [prepare.OPTIONAL_DELAY]
        ledger = prepare.build_ledger(synthetic_observations(), prepare.SEEDS, delays, prepare.SCHEDULER_SEED)
        self.assertEqual(len(ledger), 3 * 6 * 200 * 2)
        prepare.validate_ledger(ledger, prepare.SEEDS, delays, 200)

    def test_scheduler_seed_is_new_and_deterministic(self):
        self.assertNotEqual(prepare.SCHEDULER_SEED, 20261105)
        a = prepare.build_ledger(synthetic_observations(), [42], [0, 10], prepare.SCHEDULER_SEED)
        b = prepare.build_ledger(synthetic_observations(), [42], [0, 10], prepare.SCHEDULER_SEED)
        c = prepare.build_ledger(synthetic_observations(), [42], [0, 10], 20261105)
        self.assertEqual(a, b)
        self.assertNotEqual([row['trial_id'] for row in a], [row['trial_id'] for row in c])

    def test_validation_rejects_broken_ledgers(self):
        ledger = prepare.build_ledger(synthetic_observations(), [42], [0], prepare.SCHEDULER_SEED)
        broken = [dict(row) for row in ledger]
        broken[0]['mode'] = broken[1]['mode']
        with self.assertRaises(ValueError):
            prepare.validate_ledger(broken, [42], [0], 200)
        with self.assertRaises(ValueError):
            prepare.validate_ledger(ledger[:-2], [42], [0], 200)

    def test_rate_ledger_is_separate_and_carries_rate(self):
        ledger = prepare.build_ledger(synthetic_observations(), [42], [0, 50], prepare.RATE_SCHEDULER_SEED, prepare.RATES)
        self.assertEqual(len(ledger), 1 * 2 * 3 * 200 * 2)
        self.assertEqual({row['probe_rate_pps'] for row in ledger}, {200, 800, 2500})
        prepare.validate_ledger(ledger, [42], [0, 50], 200, prepare.RATES)
        self.assertNotEqual(prepare.RATE_SCHEDULER_SEED, prepare.SCHEDULER_SEED)


class ArtifactChecks(unittest.TestCase):
    def test_prepare_uses_only_the_frozen_source_and_writes_checksummed_outputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            source = make_source(temporary / 'response')
            before = {path.name: sha(path) for path in source.iterdir()}
            out = temporary / 'response_2b'
            manifest = prepare.prepare(source, out)
            self.assertEqual(before, {path.name: sha(path) for path in source.iterdir()})  # source untouched
            self.assertEqual(manifest['assigned_trials'], 6000)
            self.assertEqual(manifest['delays_ms'], [0, 10, 50, 100, 250])
            self.assertNotEqual(manifest['scheduler_seed'], 20261105)
            self.assertFalse((out / 'benchmark.npz').exists())
            self.assertNotIn('decoy', (out / 'ledger.jsonl').read_text())
            self.assertEqual((out / '.gitignore').read_text().strip(), '*')
            for name, checksum in manifest['artifact_checksums'].items():
                self.assertEqual(sha(out / name), checksum, name)
            self.assertIn('ledger.jsonl', manifest['artifact_checksums'])
            self.assertIn('model-42.pt', manifest['artifact_checksums'])
            self.assertEqual(manifest['source_manifest_sha256'], sha(source / 'manifest.json'))

    def test_rerun_verifies_and_tampering_or_other_settings_are_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            source = make_source(temporary / 'response')
            out = temporary / 'response_2b'
            prepare.prepare(source, out)
            prepare.prepare(source, out)  # verification path
            with self.assertRaisesRegex(RuntimeError, 'different settings'):
                prepare.prepare(source, out, include_500=True)
            with (out / 'ledger.jsonl').open('a') as handle:
                handle.write('\n')
            with self.assertRaisesRegex(RuntimeError, 'Checksum mismatch'):
                prepare.prepare(source, out)

    def test_corrupt_source_artifact_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = make_source(Path(temporary) / 'response')
            (source / 'model-43.pt').write_bytes(b'tampered')
            with self.assertRaisesRegex(RuntimeError, 'checksum'):
                prepare.prepare(source, Path(temporary) / 'out')

    def test_rate_profile_writes_its_own_files_and_leaves_the_base_manifest_alone(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            source = make_source(temporary / 'response')
            out = temporary / 'response_2b'
            base = prepare.prepare(source, out)
            base_sha = sha(out / 'manifest.json')
            rate = prepare.prepare(source, out, profile='rate')
            self.assertEqual(base_sha, sha(out / 'manifest.json'))
            self.assertEqual(rate['rates_pps'], [200, 800, 2500])
            self.assertEqual(rate['assigned_trials'], 1 * 2 * 3 * 200 * 2)
            self.assertTrue((out / 'ledger-rate.jsonl').exists())
            self.assertEqual(base['assigned_trials'], 6000)


class LabChecks(unittest.TestCase):
    def test_rate_verification_records_real_counter_interval(self):
        edge = lab_2b.Application.__new__(lab_2b.Application)
        edge.pending = {'trial': {'status': 'awaiting_verification', 'action': 'block',
            't0_ns': 300, 'health_before': 0, 'arrived_before': 10,
            'counter_start_begin_ns': 100, 'counter_start_end_ns': 200}}
        edge.chain_counters = Mock(return_value=(5, 20))
        edge.echo = Mock()
        edge.echo.count.side_effect = [0, 1]
        with patch.object(lab_2b.time, 'monotonic_ns', side_effect=[1000, 1200]):
            result = edge.verify('trial', 'post')
        self.assertEqual(result['status'], 'ok_block')
        self.assertEqual(result['passed_in_counter_interval_packets'], 5)
        self.assertAlmostEqual(result['counter_ingress_rate_pps'], 10_000_000)
        self.assertAlmostEqual(result['counter_pre_t0_upper_bound_ms'], 0.0002)
        self.assertNotIn('passed_before_block_packets', result)

    def test_total_rpc_deadline_includes_connect_and_reply(self):
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        def serve():
            connection, _ = listener.accept()
            with connection, connection.makefile('rb') as reader:
                request = json.loads(reader.readline())
                time.sleep(0.15)
                try:
                    connection.sendall((json.dumps({'id': request['id']}) + '\n').encode())
                except OSError:
                    pass
        worker = threading.Thread(target=serve, daemon=True)
        worker.start()
        connect = socket.create_connection
        def delayed_connect(*args, **kwargs):
            time.sleep(0.15)
            return connect(*args, **kwargs)
        rpc = lab_2b.RPC(*listener.getsockname(), timeout=0.23)
        try:
            with patch.object(lab_2b.socket, 'create_connection', side_effect=delayed_connect):
                with self.assertRaises(TimeoutError):
                    rpc.call('policy')
            self.assertIsNone(rpc.sock)
        finally:
            rpc.close()
            worker.join(timeout=1)
            listener.close()

    def test_trial_timeout_stays_one_second_and_calibration_is_longer(self):
        self.assertEqual(lab_2b.RPC_TIMEOUT, 1)
        self.assertEqual(lab_2b.RPC('x', 1).timeout, 1)
        self.assertGreater(lab_2b.CALIBRATION_TIMEOUT, 2 * 0.5 * 2)  # > the 2 s RTT-scale worst case (500 ms one way)
        self.assertGreater(lab_2b.CALIBRATION_TIMEOUT, lab_2b.RPC_TIMEOUT)
        source = (ROOT / 'response_2b/lab_2b.py').read_text()
        self.assertRegex(source, r'self\.controller = RPC\(CONTROLLER, CONTROL_PORT, timeout=RPC_TIMEOUT\)')
        self.assertRegex(source, r'self\.calibration = RPC\(CONTROLLER, CONTROL_PORT, timeout=CALIBRATION_TIMEOUT\)')

    def test_timeouts_are_classified_separately_from_other_failures(self):
        self.assertEqual(lab_2b.classify_failure(socket.timeout('timed out')), 'timeout')
        self.assertEqual(lab_2b.classify_failure(TimeoutError()), 'timeout')
        self.assertEqual(lab_2b.classify_failure(ConnectionRefusedError()), 'other')
        self.assertEqual(lab_2b.classify_failure(RuntimeError('Stale/mismatched RPC response ID rejected')), 'other')

    def test_chain_counter_parser_separates_drops_from_the_counting_rule(self):
        listing = ('Chain THESIS_IDS (1 references)\n    pkts      bytes target     prot opt in     out     source               destination\n'
                   '     120     7200            all  --  *      *       172.30.103.10        0.0.0.0/0\n'
                   '      95     5700 DROP       all  --  *      *       172.30.103.10        0.0.0.0/0\n')
        self.assertEqual(lab_2b.parse_chain_counters(listing), (95, 120))
        self.assertEqual(lab_2b.parse_chain_counters(listing.splitlines()[0] + '\n'), (0, None))
        base = '     7      420 DROP       all  --  *      *       172.30.103.10        0.0.0.0/0\n'
        self.assertEqual(lab_2b.parse_chain_counters(base), (7, None))

    def test_resume_accounting_matches_experiment_2_semantics(self):
        ledger = [{'trial_id': 'a-local', 'pair_id': 'a'}, {'trial_id': 'a-central', 'pair_id': 'a'}]
        attempts = [{'trial_id': 'a-local', 'segment': 'old', 'terminal': True, 'status': 'ok_block'},
                    {'trial_id': 'a-central', 'segment': 'new', 'terminal': True, 'status': 'controller_failure'}]
        self.assertEqual(lab_2b.completed_pairs(ledger, attempts), (set(), {'a'}))
        attempts.append({'trial_id': 'a-local', 'segment': 'new', 'terminal': True, 'status': 'ok_block'})
        self.assertEqual(lab_2b.completed_pairs(ledger, attempts), ({'a'}, set()))

    def test_separate_compose_project_and_subnets(self):
        text = (ROOT / 'response_2b/compose.yaml').read_text()
        self.assertRegex(text, r'(?m)^name: thesis-response-2b$')
        subnets = set(re.findall(r'subnet: (\d+\.\d+\.\d+\.\d+/24)', text))
        self.assertEqual(subnets, {'172.30.103.0/24', '172.30.104.0/24'})
        for other in ['172.30.93.', '172.30.94.', '172.30.95.', '172.30.96.', '172.30.97.', '172.30.98.']:
            self.assertNotIn(other, text)  # experiment 2 and experiment 3 networks
        self.assertNotIn('thesis-response:local', text)
        self.assertNotIn('data/response:', text)
        self.assertIn('thesis-response-2b:local', text)
        self.assertTrue(lab_2b.EDGE.startswith('172.30.103.') and lab_2b.CONTROLLER.startswith('172.30.104.'))


def attempt(ledger_row, status, segment='s1', latency=None, **extra):
    row = {**ledger_row, 'segment': segment, 'attempt_id': ledger_row['trial_id'], 'terminal': True,
           'status': status, 'expected_action': 'block' if ledger_row['label'] else 'allow'}
    if latency is not None:
        row['feature_to_firewall_command_ms'] = latency
    row.update(extra)
    return row


class ReportChecks(unittest.TestCase):
    """Synthetic world: local block costs 3.5 ms; central costs 3.5 + 1.0 * RTT + 0.5 ms; delay 250 stays under the
    timeout; delay 500 makes every central attack time out (fail-open)."""
    DELAYS = {0: 1.0, 10: 21.0, 250: 501.0, 500: 1001.0}

    def build(self):
        observations = [dict(o, label=i % 2) for i, o in enumerate(synthetic_observations(40))]
        ledger = prepare.build_ledger(observations, [42], list(self.DELAYS), 7)
        attempts, calibrations = [], []
        for row in ledger:
            rtt = self.DELAYS[row['delay_ms']]
            if row['mode'] == 'local':
                attempts.append(attempt(row, 'ok_block' if row['label'] else 'ok_allow',
                                        latency=3.5 if row['label'] else None, decision_ms=0.4))
            elif row['delay_ms'] == 500:
                attempts.append(attempt(row, 'controller_failure', error="TimeoutError('timed out')",
                                        failure_kind='timeout', failure_elapsed_ms=1004.0))
            else:
                attempts.append(attempt(row, 'ok_block' if row['label'] else 'ok_allow',
                                        latency=3.5 + rtt + 0.5 if row['label'] else None, decision_ms=1.0 + rtt))
        for block in sorted({row['block_id'] for row in ledger}):
            delay = int(re.search(r'-d(\d+)-', block).group(1))
            calibrations.append({'segment': 's1', 'block_id': block,
                                 'edge': {'delay_ms': delay, 'rpc_rtt_ms': [self.DELAYS[delay]] * 6, 'trial_connection_warm_ok': delay != 500}})
        return ledger, attempts, calibrations

    def test_controller_errors_and_detector_misses_are_not_timeout_successes(self):
        scheduled = [{'trial_id': 'a', 'label': 1}]
        for status in ['controller_failure', 'transport_failure']:
            cell = report.cell_row(scheduled, {'a': {'trial_id': 'a', 'label': 1,
                'status': status, 'expected_action': 'block', 'failure_kind': 'other'}})
            self.assertEqual(cell['block_within_timeout_share'], 0.0)
        cell = report.cell_row(scheduled, {'a': {'trial_id': 'a', 'label': 1,
            'status': 'controller_failure', 'expected_action': 'allow', 'failure_kind': 'timeout'}})
        self.assertEqual(cell['attacks_unblocked_by_timeout'], 0)
        self.assertEqual(cell['detector_missed_attacks'], 1)

    def test_medians_p95_and_timeout_shares(self):
        result = report.summarize(*self.build())
        pooled = {(row['one_way_delay_ms'], row['mode']): row for row in result['pooled']}
        self.assertAlmostEqual(pooled[(0, 'local')]['block_median_ms'], 3.5)
        self.assertAlmostEqual(pooled[(250, 'central')]['block_median_ms'], 3.5 + 501.0 + 0.5)
        self.assertAlmostEqual(pooled[(250, 'central')]['block_p95_ms'], 3.5 + 501.0 + 0.5)
        self.assertEqual(pooled[(250, 'central')]['block_within_timeout_share'], 1.0)
        self.assertEqual(pooled[(250, 'central')]['attacks_unblocked_by_timeout'], 0)
        slow = pooled[(500, 'central')]
        self.assertEqual((slow['attacks_assigned'], slow['attacks_unblocked_by_timeout']), (20, 20))
        self.assertEqual(slow['attacks_unblocked_by_timeout_share'], 1.0)
        self.assertEqual(slow['block_within_timeout_share'], 0.0)
        self.assertEqual(slow['verified_blocks'], 0)
        self.assertIsNone(slow['block_median_ms'])  # timeouts never receive a latency
        self.assertEqual(slow['timeout_failures'], 40)  # benign records time out too, but are not attack misses
        self.assertEqual(pooled[(500, 'local')]['timeout_failures'], 0)
        self.assertEqual(result['audit']['timeout_failures_latest'], 40)

    def test_regression_recovers_slope_one_and_excludes_timed_out_pairs(self):
        result = report.summarize(*self.build())
        fit = result['regression'][0]
        self.assertAlmostEqual(fit['slope'], 1.0, places=9)
        self.assertAlmostEqual(fit['intercept'], 0.5, places=9)
        self.assertAlmostEqual(fit['r2'], 1.0, places=9)
        self.assertEqual(fit['delays_included_ms'], [0, 10, 250])
        self.assertEqual(fit['n'], 3 * 20)
        excluded = [row for row in result['pairs'] if row['one_way_delay_ms'] == 500][0]
        self.assertEqual(excluded['comparable_block_pairs'], 0)
        self.assertIn('ok_block/controller_failure', excluded['exclusion_status_pairs'])

    def test_calibration_table_counts_trial_connections_that_could_not_warm(self):
        result = report.summarize(*self.build())
        rows = {row['one_way_delay_ms']: row for row in result['calibration']}
        self.assertEqual(rows[500]['rpc_rtt_median_ms'], 1001.0)
        self.assertEqual(rows[500]['trial_connection_warm_failures'], rows[500]['blocks'])
        self.assertEqual(rows[250]['trial_connection_warm_failures'], 0)

    def test_regression_needs_variation_and_enough_points(self):
        self.assertIsNone(report.regression([(1.0, 2.0)] * 5)['slope'])
        self.assertIsNone(report.regression([(1.0, 2.0), (2.0, 3.0)])['slope'])

    def test_failed_attempts_are_preserved_and_the_latest_outcome_counts(self):
        ledger, attempts, calibrations = self.build()
        first = next(row for row in attempts if row['mode'] == 'local' and row['status'] == 'ok_block')
        attempts.insert(0, {**first, 'status': 'transport_failure', 'segment': 's0'})
        result = report.summarize(ledger, attempts, calibrations)
        self.assertEqual(result['audit']['superseded_terminal_attempts'], 1)
        self.assertEqual(result['audit']['all_terminal_attempt_status_counts']['transport_failure'], 1)

    def test_report_writes_all_files_from_synthetic_run(self):
        ledger, attempts, calibrations = self.build()
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / 'artifacts').mkdir()
            (directory / 'artifacts/ledger.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in ledger))
            (directory / 'attempts.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in attempts))
            (directory / 'calibrations.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in calibrations))
            report.report(directory)
            for name in ['RESULTS.md', 'summary.csv', 'summary-by-seed.csv', 'paired-differences.csv',
                         'regression.csv', 'calibration.csv', 'audit-summary.json']:
                self.assertTrue((directory / name).exists(), name)
            text = (directory / 'RESULTS.md').read_text()
            self.assertIn('Attacks unblocked by timeout', text)
            self.assertIn('Added time vs measured RTT', text)
            self.assertIn('20/20 (100.0%)', text)
            self.assertNotIn('Packet accounting', text)  # base profile has no rate section

    def test_rate_profile_report_includes_packet_accounting(self):
        observations = [dict(o, label=i % 2) for i, o in enumerate(synthetic_observations(20))]
        ledger = prepare.build_ledger(observations, [42], [0], 9, [200, 2500])
        attempts, calibrations = [], []
        for row in ledger:
            rate = row['probe_rate_pps']
            attempts.append(attempt(row, 'ok_block' if row['label'] else 'ok_allow', latency=3.0 if row['label'] else None,
                                    chain_arrived_packets=rate // 100, drop_packets=rate // 100 - 1,
                                    passed_in_counter_interval_packets=1, counter_ingress_rate_pps=rate * 0.9))
        for block in sorted({row['block_id'] for row in ledger}):
            calibrations.append({'segment': 's1', 'block_id': block,
                                 'edge': {'delay_ms': 0, 'rpc_rtt_ms': [1.0] * 6, 'trial_connection_warm_ok': True}})
        result = report.summarize(ledger, attempts, calibrations)
        fast = [row for row in result['pooled'] if row['probe_rate_pps'] == 2500 and row['mode'] == 'central'][0]
        self.assertEqual((fast['arrived_median'], fast['dropped_median'], fast['passed_in_counter_interval_median']), (25, 24, 1))
        self.assertAlmostEqual(fast['achieved_rate_pps_median'], 2250.0)
        self.assertIn('Packet accounting', report.render_markdown(result))


if __name__ == '__main__':
    unittest.main()
