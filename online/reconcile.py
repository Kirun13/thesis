"""Offline ground truth via TCP byte ranges and generator message IDs, not packet tags."""
import collections
import bisect
import json
import struct
from pathlib import Path

from features import decode, vector, WINDOW_SECONDS


def packets(path, offset):
    with Path(path).open('rb') as handle:
        magic = handle.read(4)
        if magic == b'\x4d\x3c\xb2\xa1':
            multiplier, endian = 1, '<'
        elif magic == b'\xd4\xc3\xb2\xa1':
            multiplier, endian = 1000, '<'
        else:
            raise ValueError(f'Unsupported capture magic {magic!r}')
        handle.read(20)
        while header := handle.read(16):
            seconds, fraction, length, _ = struct.unpack(endian + 'IIII', header)
            frame = handle.read(length)
            item = decode(frame)
            if item is not None:
                item['timestamp_ns'] = seconds * 10**9 + fraction * multiplier - offset
                yield item


def reconcile(directory, strict=True):
    directory = Path(directory)
    config = json.loads((directory / 'config.json').read_text())
    capture_info = json.loads((directory / 'ingress-events.json').read_text())
    events = list(packets(directory / 'ingress.pcap', capture_info['realtime_minus_monotonic_ns']))
    flows = collections.defaultdict(list)
    for index, event in enumerate(events):
        if event['payload']:
            flows[(event['source'], event['sport'], event['destination'], event['dport'])].append((index, event))
    accepted, planned = {}, {}
    for source in range(3):
        original = json.loads((directory / f'source-{source}.json').read_text())
        for sequence, stamp, tag in original['records']:
            accepted[(source, sequence)] = (stamp, tag)
        for sequence, stamp, tag in json.loads((directory / f'source-{source}-offered.json').read_text()):
            planned[(source, sequence)] = (stamp, tag)
    malicious_packets = set()
    seen_messages = set()
    parse_errors = []
    missing_bytes = 0
    for flow, chunks in flows.items():
        base = chunks[0][1]['tcp_seq_raw']
        positions = [((item['tcp_seq_raw'] - base) % 2**32, index, item) for index, item in chunks]
        size = max(position + len(item['payload']) for position, _, item in positions)
        if size > 20_000_000:
            raise RuntimeError('Unexpected TCP sequence discontinuity')
        stream = bytearray(size)
        known = bytearray(size)
        for position, _, item in positions:
            payload = item['payload']
            stream[position:position + len(payload)] = payload
            known[position:position + len(payload)] = b'\x01' * len(payload)
        missing_bytes += known.count(0)
        cursor = 0
        attack_ranges = []
        while cursor < len(stream):
            begin = cursor
            kind = stream[cursor] >> 4
            cursor += 1
            remaining, multiplier = 0, 1
            for _ in range(4):
                if cursor >= len(stream):
                    break
                digit = stream[cursor]
                cursor += 1
                remaining += (digit & 127) * multiplier
                if not digit & 128:
                    break
                multiplier *= 128
            end = cursor + remaining
            if end > len(stream):
                parse_errors.append('Incomplete final MQTT packet')
                break
            if kind == 3:
                topic_length = int.from_bytes(stream[cursor:cursor + 2], 'big')
                body = bytes(stream[cursor + 2 + topic_length:end])
                try:
                    fields = body.decode().split('|')
                    episode, source, sequence, stamp, tag = fields[:5]
                    key = (int(source), int(sequence))
                    assert episode == config['episode_id']
                    assert key in planned and planned[key][1] == tag
                    # Send completion and capture receive may race; the planned
                    # generator ID is authoritative, accepted records are audited separately.
                    seen_messages.add(key)
                    if tag == 'A':
                        attack_ranges.append((begin, end))
                except (ValueError, AssertionError) as error:
                    parse_errors.append(repr(error))
            cursor = end
        attack_ends = [end for _, end in attack_ranges]
        for position, packet_index, item in positions:
            candidate = bisect.bisect_right(attack_ends, position)
            if candidate < len(attack_ranges) and attack_ranges[candidate][0] < position + len(item['payload']):
                malicious_packets.add(packet_index)
    buckets = collections.defaultdict(list)
    tagged_windows = set()
    step = int(WINDOW_SECONDS * 1e9)
    for index, event in enumerate(events):
        if event['timestamp_ns'] < config['start_ns']:
            continue
        window = (event['timestamp_ns'] - config['start_ns']) // step
        key = (int(window), event['source'])
        buckets[key].append(event)
        if index in malicious_packets:
            tagged_windows.add(key)
    live = json.loads((directory / 'windows.json').read_text())
    parity, labeled = [], []
    for row in live:
        key = (row['window'], row['source'])
        samples = sorted(buckets[key], key=lambda p: p['timestamp_ns'])
        replay = vector(samples)
        error = max(abs(a - b) for a, b in zip(replay, row['features']))
        parity.append(error)
        labeled.append({**row, 'label': int(key in tagged_windows), 'episode_id': config['episode_id'],
                        'split': config['split'], 'traffic_seed': config['traffic_seed'],
                        'rate_level': min(range(3), key=lambda i: abs(config['attack_rate'] - [200, 800, 2500][i]))})
    resources = json.loads((directory / 'edge-resources.json').read_text())
    audit = {'live_windows': len(live), 'labels_from_reassembled_message_ids': True,
             'attack_windows': sum(row['label'] for row in labeled),
             'max_online_offline_feature_error': max(parity, default=0),
             'kernel_drops': capture_info['kernel_drops'], 'late_packets': resources['late_packets'],
             'missing_tcp_bytes': missing_bytes, 'mqtt_parse_errors': parse_errors,
             'scheduled_messages': len(planned), 'accepted_messages': len(accepted),
             'reassembled_messages': len(seen_messages),
             'accepted_not_reassembled': len(set(accepted) - seen_messages),
             'ingress_attack_packet_indices': sorted(malicious_packets),
             'first_attack_ingress_ns': min((events[i]['timestamp_ns'] for i in malicious_packets), default=None)}
    if strict:
        assert live and audit['max_online_offline_feature_error'] < 1e-8, audit
        assert not audit['kernel_drops'] and not audit['late_packets'], audit
        assert not missing_bytes and not parse_errors, audit
    (directory / 'reconciliation.json').write_text(json.dumps(audit, indent=2))
    (directory / 'labeled-windows.json').write_text(json.dumps(labeled))
    return audit
