import io
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'response'))
from lab import RPC, completed_pairs


class FakeSocket:
    def sendall(self, payload):
        self.sent = payload

    def close(self):
        pass


class ResponseChecks(unittest.TestCase):
    def rpc_with_reply(self, reply):
        client = RPC('unused', 1)
        client.sock = FakeSocket()
        client.reader = io.BytesIO((json.dumps(reply) + '\n').encode())
        return client

    def test_explicit_controller_failure_remains_a_trial_result(self):
        client = self.rpc_with_reply({'id': 'trial-1', 'status': 'controller_failure', 'error': 'timeout'})
        result = client.call('trial', request_id='trial-1')
        self.assertEqual(result['status'], 'controller_failure')

    def test_stale_reply_discards_connection(self):
        client = self.rpc_with_reply({'id': 'previous-trial', 'action': 'block'})
        with self.assertRaisesRegex(RuntimeError, 'Stale'):
            client.call('policy', request_id='new-trial')
        self.assertIsNone(client.sock)

    def test_resume_never_pairs_across_segments_or_retries_complete_failures(self):
        ledger = [{'trial_id': 'a-local', 'pair_id': 'a'}, {'trial_id': 'a-central', 'pair_id': 'a'}]
        attempts = [{'trial_id': 'a-local', 'segment': 'old', 'terminal': True, 'status': 'ok_block'},
                    {'trial_id': 'a-central', 'segment': 'new', 'terminal': True, 'status': 'controller_failure'}]
        completed, partial = completed_pairs(ledger, attempts)
        self.assertEqual(completed, set())
        self.assertEqual(partial, {'a'})
        attempts.append({'trial_id': 'a-local', 'segment': 'new', 'terminal': True, 'status': 'ok_block'})
        completed, partial = completed_pairs(ledger, attempts)
        self.assertEqual(completed, {'a'})
        self.assertEqual(partial, set())

    def test_declared_real_ledger_has_3600_unique_paired_trials(self):
        root = Path(__file__).resolve().parents[1] / 'data/response'
        ledger = [json.loads(line) for line in (root / 'ledger.jsonl').read_text().splitlines()]
        self.assertEqual(len(ledger), 3600)
        self.assertEqual(len({row['trial_id'] for row in ledger}), 3600)
        pairs = {}
        for row in ledger:
            pairs.setdefault(row['pair_id'], []).append(row)
        self.assertEqual(len(pairs), 1800)
        for pair in pairs.values():
            self.assertEqual({row['mode'] for row in pair}, {'local', 'central'})
            self.assertEqual(len({(row['seed'], row['delay_ms'], row['observation_index']) for row in pair}), 1)


if __name__ == '__main__':
    unittest.main()
