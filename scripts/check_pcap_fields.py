"""Gate legacy model deployment on actual author capture semantics."""
import csv
import json
import subprocess
import io
import math
import re
from datetime import datetime, timezone
from decimal import Decimal
from collections import Counter
from pathlib import Path

from prepare_data import FEATURES

ROOT = Path(__file__).resolve().parents[1]


def main():
    target = ROOT / 'runs/extension-audit'
    base = ['docker', 'run', '--rm', '--network', 'none', '--cap-drop', 'ALL',
            '--mount', f'type=bind,source={ROOT / "data/pcap-audit"},target=/captures,readonly', 'thesis-online:local']
    listing = subprocess.run(base + ['tshark', '-G', 'fields'], capture_output=True, text=True, check=True)
    available = {line.split('\t')[2] for line in listing.stdout.splitlines() if line.startswith('F\t')}
    missing = [field for field in FEATURES if field not in available]
    present = [field for field in FEATURES if field in available]
    args = ['tshark', '-n', '-r', '/captures/Backdoor_attack.pcap', '-c', '100', '-T', 'fields',
            '-E', 'header=y', '-E', 'separator=,', '-E', 'quote=d', '-E', 'occurrence=f']
    for field in ['frame.number', 'frame.time_epoch', 'ip.src', 'ip.dst'] + present:
        args += ['-e', field]
    extracted = subprocess.run(base + args, capture_output=True, text=True, check=True)
    (target / 'backdoor-first-100-extracted.csv').write_text(extracted.stdout, encoding='utf-8')
    with (ROOT / 'data/pcap-audit/Backdoor_attack.csv').open(encoding='utf-8-sig', newline='') as handle:
        rows = list(next(csv.DictReader(handle)) for _ in range(1))
    version = subprocess.run(base + ['tshark', '--version'], capture_output=True, text=True, check=True).stdout
    report = {'tshark_version': version, 'legacy_features': FEATURES, 'available_direct_fields': present,
              'unavailable_direct_fields': missing, 'single_pass_only': True,
              'author_csv_first_row': rows[0], 'author_csv_columns': list(rows[0]),
              'gate': 'failed' if missing else 'needs_semantic_parity',
              'reason': 'Legacy derived fields are not direct dissector fields; authoritative derivation and packet-to-row mapping are not supplied in this workspace. No zero substitution or score-driven remapping is permitted.',
              'next': 'Use a separately versioned causal packet-window schema, validate it offline/live, and train/evaluate a new detector on independent lab episodes.'}
    semantic = []
    def numeric(value):
        if value in ['', None]:
            return 0.0
        if str(value).startswith('0x'):
            return float(int(value, 16))
        return float(value)
    for capture, csv_name in [('Backdoor_attack.pcap', 'Backdoor_attack.csv'),
                              ('Port Scanning attack.pcap', 'Port_Scanning_attack.csv'),
                              ('Heart_Rate.pcap', 'Heart_Rate.csv')]:
        extract_args = list(args)
        extract_args[extract_args.index('/captures/Backdoor_attack.pcap')] = '/captures/' + capture
        extract_args[extract_args.index('100')] = '2000'
        result = subprocess.run(base + extract_args, capture_output=True, text=True, check=True)
        decoded = list(csv.DictReader(io.StringIO(result.stdout)))
        def identity(packet, hour_offset=0):
            value = Decimal(packet['frame.time_epoch'])
            seconds = int(value)
            fraction = int((value - seconds) * 1_000_000_000)
            stamp = datetime.fromtimestamp(seconds + hour_offset * 3600, timezone.utc).strftime('%H:%M:%S') + f'.{fraction:09d}'
            return stamp, packet['ip.src'], packet['ip.dst']
        by_offset = {offset: {identity(packet, offset) for packet in decoded} for offset in range(-12, 15)}
        sought = set().union(*by_offset.values())
        original = {}
        ambiguous = set()
        with (ROOT / 'data/pcap-audit' / csv_name).open(encoding='utf-8-sig', newline='') as handle:
            for row in csv.DictReader(handle):
                match = re.search(r'(\d\d:\d\d:\d\d\.\d+)', row['frame.time'])
                if not match:
                    continue
                key = (match.group(1), row['ip.src_host'], row['ip.dst_host'])
                if key in sought:
                    if key in original:
                        ambiguous.add(key)
                    original[key] = row
        mismatches, compared, matches = Counter(), 0, 0
        offset_matches = {offset: len(keys & (original.keys() - ambiguous)) for offset, keys in by_offset.items()}
        selected_offset = max(offset_matches, key=offset_matches.get)
        offset_unique = list(offset_matches.values()).count(offset_matches[selected_offset]) == 1 and offset_matches[selected_offset] > 0
        for captured in decoded:
            # Explicit row identity gate; no score-driven realignment.
            key = identity(captured, selected_offset)
            if not offset_unique or key not in original or key in ambiguous:
                continue
            author = original[key]
            matches += 1
            for field in present:
                try:
                    left, right = numeric(captured[field]), numeric(author[field])
                    compared += 1
                    if not math.isclose(left, right, abs_tol=1e-6, rel_tol=1e-6):
                        mismatches[field] += 1
                except ValueError:
                    mismatches[field] += 1
        semantic.append({'capture': capture, 'sampled_packets': len(decoded), 'identity_matched_rows': matches,
                         'identity_key': 'exact time-of-day nanoseconds plus source/destination IP within one named capture',
                         'ambiguous_identity_keys': len(ambiguous),
                         'metadata_inferred_timezone_offset_hours': selected_offset if offset_unique else None,
                         'timezone_inference': 'Unique best match of exact timestamp fraction and endpoint metadata over integer-hour offsets; no labels or model scores used.',
                         'compared_numeric_fields': compared, 'mismatches_by_field': dict(mismatches)})
    report['development_capture_semantic_comparison'] = semantic
    report['gate'] = 'limited_development_comparison_only'
    report['reason'] = 'Field availability and limited single-pass CSV comparison do not validate complete live legacy-model compatibility. The new MQTT source-window detector is separately trained and evaluated.'
    (target / 'pcap-extractor-gate.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({key: report[key] for key in ['gate', 'unavailable_direct_fields', 'next']}, indent=2))


if __name__ == '__main__':
    main()
