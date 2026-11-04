"""Causal source-window features, identical for captured/live packet events."""
import math
import struct

WINDOW_SECONDS = 0.25
FEATURES = ['log_packet_rate', 'log_byte_rate', 'mean_frame_bytes', 'std_frame_bytes',
            'mean_iat_ms', 'std_iat_ms', 'syn_fraction', 'ack_fraction', 'rst_fraction',
            'log_source_port_count', 'mean_tcp_payload_bytes', 'payload_packet_fraction']


def decode(frame):
    if len(frame) < 54 or frame[12:14] != b'\x08\x00':
        return None
    ihl = (frame[14] & 15) * 4
    if frame[23] != 6 or len(frame) < 14 + ihl + 20:
        return None
    start = 14 + ihl
    sport, dport = struct.unpack_from('!HH', frame, start)
    offset = (frame[start + 12] >> 4) * 4
    total = struct.unpack_from('!H', frame, 16)[0]
    payload = frame[start + offset:14 + total]
    return {'source': '.'.join(map(str, frame[26:30])), 'destination': '.'.join(map(str, frame[30:34])),
            'sport': sport, 'dport': dport, 'flags': frame[start + 13], 'frame_bytes': 14 + total,
            'tcp_seq_raw': struct.unpack_from('!I', frame, start + 4)[0],
            'payload_bytes': len(payload),
            # Ground-truth instrumentation only: never included in FEATURES.
            'attack_tag': b'|A|' in payload, 'payload': payload}


def vector(events):
    n = len(events)
    if not n:
        raise ValueError('Empty windows are not classified')
    sizes = [e['frame_bytes'] for e in events]
    gaps = [(b['timestamp_ns'] - a['timestamp_ns']) / 1e6 for a, b in zip(events, events[1:])]
    mean = lambda values: sum(values) / len(values) if values else 0.0
    std = lambda values: math.sqrt(mean([(v - mean(values)) ** 2 for v in values])) if values else 0.0
    return [math.log1p(n / WINDOW_SECONDS), math.log1p(sum(sizes) / WINDOW_SECONDS),
            mean(sizes), std(sizes), mean(gaps), std(gaps),
            sum(bool(e['flags'] & 2) for e in events) / n,
            sum(bool(e['flags'] & 16) for e in events) / n,
            sum(bool(e['flags'] & 4) for e in events) / n,
            math.log1p(len({e['sport'] for e in events})),
            mean([e['payload_bytes'] for e in events]),
            sum(e['payload_bytes'] > 0 for e in events) / n]
