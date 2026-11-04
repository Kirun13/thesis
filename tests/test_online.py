import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'online'))
from features import vector, decode
from mqtt import packet, text
from reconcile import reconcile


class OnlineChecks(unittest.TestCase):
    def test_features_do_not_use_identity_or_ground_truth(self):
        events = [{'timestamp_ns': t, 'frame_bytes': 180, 'payload_bytes': 120,
                   'flags': 24, 'sport': p, 'source': 'one', 'attack_tag': False}
                  for t, p in [(1, 40000), (100001, 40001)]]
        altered = [{**e, 'source': 'other', 'sport': e['sport'] + 1000, 'attack_tag': True} for e in events]
        self.assertEqual(vector(events), vector(altered))

    def test_reassembly_labels_message_split_across_packets_and_windows(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            body = b'synthetic|0|0|123|A|padding'
            message = packet(0x30, text('utility/readings') + body)
            split = message.index(b'|A|') + 2
            chunks = [message[:split], message[split:]]
            frames, events = [], []
            seq = 1000
            for chunk, timestamp in zip(chunks, [100_000_000, 300_000_000]):
                ethernet = b'\x00' * 12 + b'\x08\x00'
                ip = bytearray(20)
                ip[0], ip[9] = 0x45, 6
                struct.pack_into('!H', ip, 2, 40 + len(chunk))
                ip[12:16], ip[16:20] = bytes([172, 30, 95, 10]), bytes([172, 30, 95, 2])
                tcp = bytearray(20)
                struct.pack_into('!HHI', tcp, 0, 40000, 1883, seq)
                tcp[12], tcp[13] = 0x50, 24
                frame = ethernet + ip + tcp + chunk
                event = decode(frame)
                event['timestamp_ns'] = timestamp
                self.assertFalse(event['attack_tag'])
                frames.append((timestamp, frame))
                events.append(event)
                seq += len(chunk)
            with (root / 'ingress.pcap').open('wb') as output:
                output.write(struct.pack('<IHHIIII', 0xa1b23c4d, 2, 4, 0, 0, 65535, 1))
                for timestamp, frame in frames:
                    output.write(struct.pack('<IIII', 0, timestamp, len(frame), len(frame)))
                    output.write(frame)
            files = {'config.json': {'episode_id': 'synthetic', 'start_ns': 0, 'split': 'test', 'traffic_seed': 1, 'attack_rate': 200},
                     'ingress-events.json': {'realtime_minus_monotonic_ns': 0, 'kernel_drops': 0},
                     'edge-resources.json': {'late_packets': 0},
                     'windows.json': [{'window': i, 'source': '172.30.95.10', 'features': vector([event])} for i, event in enumerate(events)]}
            for i in range(3):
                files[f'source-{i}.json'] = {'records': [[0, 123, 'A']] if i == 0 else []}
                files[f'source-{i}-offered.json'] = [[0, 123, 'A']] if i == 0 else []
            for name, value in files.items():
                (root / name).write_text(json.dumps(value))
            result = reconcile(root)
            self.assertEqual(result['attack_windows'], 2)
            self.assertEqual(result['accepted_not_reassembled'], 0)
            self.assertEqual(result['mqtt_parse_errors'], [])

    def test_episode_plan_separates_seeds_and_balances_roles_rates(self):
        plan = json.loads((ROOT / 'data/online/episode-plan.json').read_text())
        sets = []
        for split in ['train', 'validation', 'test']:
            rows = [e for e in plan['dataset_episodes'] if e['split'] == split]
            sets.append({e['traffic_seed'] for e in rows})
            combinations = {(e['attacker'], e['episode_id'].split('-')[-1] and int(e['episode_id'].split('-')[-1]) % 3) for e in rows}
            self.assertEqual(len(combinations), 9)
            self.assertTrue(all(abs(e['attack_start'] / 0.25 - round(e['attack_start'] / 0.25)) > 1e-6 for e in rows))
        self.assertFalse(sets[0] & sets[1] or sets[0] & sets[2] or sets[1] & sets[2])


if __name__ == '__main__':
    unittest.main()
