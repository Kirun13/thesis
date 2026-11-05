"""Experiment 2b: declare the controller-delay sweep ledger before any network execution.

Reads ONLY data/response/ (manifest.json, observations.json, smoke-observations.json, model-*.pt),
never data/processed/benchmark.npz, and never modifies or reads experiment 2's ledger.
Writes copies of the inputs, a new ledger and a new manifest with SHA-256 checksums to data/response_2b/.

    python scripts/prepare_response_2b.py                  # base sweep: 0,10,50,100,250 ms
    python scripts/prepare_response_2b.py --include-500    # additionally 500 ms (expected to exceed the 1 s RPC timeout)
    python scripts/prepare_response_2b.py --profile rate   # separate flow-rate profile (stage 2)
"""
import argparse
import hashlib
import json
import random
import shutil
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'data/response'
TARGET = ROOT / 'data/response_2b'

SCHEDULER_SEED = 20261109       # experiment 2 used 20261105
RATE_SCHEDULER_SEED = 20261110  # separate stream for the rate profile
SEEDS = [42, 43, 44]
DELAYS = [0, 10, 50, 100, 250]
OPTIONAL_DELAY = 500
RATES = [200, 800, 2500]
RATE_DEFAULT_SEEDS = [42]
RATE_DEFAULT_DELAYS = [0, 50]
BLOCK = 20
PROFILE_FILES = {'base': ('ledger.jsonl', 'manifest.json'), 'rate': ('ledger-rate.jsonl', 'manifest-rate.json')}


def digest(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, allow_nan=False), encoding='utf-8')


def build_ledger(observations, seeds, delays, scheduler_seed, rates=None):
    """Blocks of 20 observations randomized across model/delay(/rate) conditions,
    with record order shuffled and balanced local-first/central-first pair order."""
    if len(observations) % BLOCK:
        raise ValueError('Observation count must be a multiple of the block size')
    blocks_per_condition = len(observations) // BLOCK
    scheduler = random.Random(scheduler_seed)
    blocks = [(seed, delay, rate, block) for seed in seeds for delay in delays
              for rate in (rates or [None]) for block in range(blocks_per_condition)]
    scheduler.shuffle(blocks)
    ledger = []
    for block_order, (seed, delay, rate, block) in enumerate(blocks):
        positions = list(range(block * BLOCK, (block + 1) * BLOCK))
        scheduler.shuffle(positions)
        orders = [('local', 'central')] * (BLOCK // 2) + [('central', 'local')] * (BLOCK // 2)
        scheduler.shuffle(orders)
        tag = f's{seed}-d{delay}' + (f'-r{rate}' if rate else '')
        for position, order in zip(positions, orders):
            observation = observations[position]
            pair = f'{tag}-o{position}'
            for mode in order:
                row = {'ordinal': len(ledger), 'trial_id': f'{pair}-{mode}', 'pair_id': pair,
                       'block_id': f'{tag}-b{block}', 'block_order': block_order,
                       'seed': seed, 'delay_ms': delay, 'mode': mode,
                       'observation_index': position, 'observation_id': observation['observation_id'],
                       'label': observation['label'], 'attack_type': observation['attack_type']}
                if rate:
                    row['probe_rate_pps'] = rate
                ledger.append(row)
    return ledger


def validate_ledger(ledger, seeds, delays, observation_count, rates=None):
    """Structural audit used both when building and when verifying an existing ledger."""
    conditions = len(seeds) * len(delays) * len(rates or [None])
    expected = conditions * observation_count * 2
    if len(ledger) != expected:
        raise ValueError(f'Ledger has {len(ledger)} trials, expected {expected}')
    if len({row['trial_id'] for row in ledger}) != expected:
        raise ValueError('Duplicate trial IDs')
    if [row['ordinal'] for row in ledger] != list(range(expected)):
        raise ValueError('Ordinals are not 0..n-1 in file order')
    pairs, blocks, covered = {}, {}, Counter()
    for row in ledger:
        pairs.setdefault(row['pair_id'], []).append(row)
        blocks.setdefault(row['block_id'], []).append(row)
        covered[(row['seed'], row['delay_ms'], row.get('probe_rate_pps'), row['mode'], row['observation_index'])] += 1
    for pair, rows in pairs.items():
        if len(rows) != 2 or {row['mode'] for row in rows} != {'local', 'central'}:
            raise ValueError(f'Pair {pair} is not one local plus one central trial')
        if len({(row['seed'], row['delay_ms'], row.get('probe_rate_pps'), row['observation_index'],
                 row['block_id']) for row in rows}) != 1:
            raise ValueError(f'Pair {pair} mixes conditions')
    if set(covered.values()) != {1}:
        raise ValueError('An observation is repeated or missing within a condition/mode')
    for block, rows in blocks.items():
        if len(rows) != BLOCK * 2:
            raise ValueError(f'Block {block} has {len(rows)} trials')
        ordinals = sorted(row['ordinal'] for row in rows)
        if ordinals[-1] - ordinals[0] != len(rows) - 1:
            raise ValueError(f'Block {block} is not contiguous')
        seen, central_first = set(), 0
        for row in sorted(rows, key=lambda item: item['ordinal']):
            if row['pair_id'] not in seen:
                seen.add(row['pair_id'])
                central_first += row['mode'] == 'central'
        if central_first != BLOCK // 2:
            raise ValueError(f'Block {block} is not balanced local-first/central-first')
    return {'trials': expected, 'pairs': len(pairs), 'blocks': len(blocks)}


def source_inputs(source):
    """Verify and list the only files taken from experiment 2's frozen directory."""
    source = Path(source)
    manifest = read_json(source / 'manifest.json')
    names = ['observations.json', 'smoke-observations.json'] + [item['model_file'] for item in manifest['models']]
    for name in names:
        expected = manifest['artifact_checksums'].get(name)
        if expected is None or digest(source / name) != expected:
            raise RuntimeError(f'Source artifact failed its recorded checksum: {name}')
    return manifest, names


def copy_inputs(source, out, names):
    for name in names:
        target = Path(out) / name
        if target.exists():
            if digest(target) != digest(Path(source) / name):
                raise RuntimeError(f'{target} differs from the frozen source copy; refusing to overwrite.')
        else:
            shutil.copy2(Path(source) / name, target)


def verify_existing(out, ledger_name, manifest_name, seeds, delays, rates, observation_count):
    manifest = read_json(Path(out) / manifest_name)
    for name, checksum in manifest['artifact_checksums'].items():
        if digest(Path(out) / name) != checksum:
            raise RuntimeError(f'Checksum mismatch in existing 2b artifacts: {name}')
    if manifest['delays_ms'] != delays or manifest['seeds'] != seeds or manifest.get('rates_pps') != rates:
        raise RuntimeError('Existing 2b artifacts were built with different settings '
                           f'(delays {manifest["delays_ms"]}); delete the directory deliberately to rebuild.')
    ledger = [json.loads(line) for line in (Path(out) / ledger_name).read_text(encoding='utf-8').splitlines()]
    validate_ledger(ledger, seeds, delays, observation_count, rates)
    return manifest


def prepare(source=SOURCE, out=TARGET, include_500=False, profile='base',
            rate_seeds=None, rate_delays=None):
    source, out = Path(source), Path(out)
    ledger_name, manifest_name = PROFILE_FILES[profile]
    if profile == 'rate':
        seeds, delays, rates = list(rate_seeds or RATE_DEFAULT_SEEDS), list(rate_delays or RATE_DEFAULT_DELAYS), list(RATES)
        scheduler_seed = RATE_SCHEDULER_SEED
    else:
        seeds, delays, rates = list(SEEDS), DELAYS + ([OPTIONAL_DELAY] if include_500 else []), None
        scheduler_seed = SCHEDULER_SEED
    source_manifest, names = source_inputs(source)
    observations = read_json(source / 'observations.json')
    out.mkdir(parents=True, exist_ok=True)
    (out / '.gitignore').write_text('*\n', encoding='utf-8')  # generated artifacts must not enter git
    copy_inputs(source, out, names)
    if (out / manifest_name).exists():
        print(f'Existing {manifest_name} found; verifying rather than overwriting.')
        manifest = verify_existing(out, ledger_name, manifest_name, seeds, delays, rates, len(observations))
        print('Existing 2b artifacts verified.')
        return manifest
    ledger = build_ledger(observations, seeds, delays, scheduler_seed, rates)
    audit = validate_ledger(ledger, seeds, delays, len(observations), rates)
    with (out / ledger_name).open('w', encoding='utf-8') as output:
        output.writelines(json.dumps(row) + '\n' for row in ledger)
    files = names + [ledger_name]
    manifest = {'experiment': '2b', 'profile': profile,
                'source_dir': 'data/response', 'source_manifest_sha256': digest(source / 'manifest.json'),
                'prepared_data_sha256': source_manifest['prepared_data_sha256'],
                'features': source_manifest['features'], 'observations': len(observations),
                'attack_type_counts': dict(Counter(item['attack_type'] for item in observations)),
                'sampling_seed': source_manifest['sampling_seed'], 'scheduler_seed': scheduler_seed,
                'seeds': seeds, 'delays_ms': delays, 'rates_pps': rates, 'include_500': include_500,
                'block_size': BLOCK, 'assigned_trials': audit['trials'], 'assigned_pairs': audit['pairs'],
                'models': source_manifest['models'], 'artifact_checksums': {name: digest(out / name) for name in files},
                'rpc_timeout_seconds': 1, 'calibration_rpc_timeout_seconds': 10,
                'enforcement_timeout_seconds': 2, 'verification_timeout_seconds': 1,
                'endpoint': 'feature-ready-to-firewall-command-completion (installation upper bound)'}
    write_json(out / manifest_name, manifest)
    print(json.dumps({key: value for key, value in manifest.items()
                      if key not in ['models', 'features', 'artifact_checksums']}, indent=2))
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, default=SOURCE)
    parser.add_argument('--out', type=Path, default=TARGET)
    parser.add_argument('--include-500', action='store_true',
                        help='add the optional 500 ms one-way delay (RTT above the 1 s trial timeout)')
    parser.add_argument('--profile', choices=['base', 'rate'], default='base')
    parser.add_argument('--rate-seeds', type=int, nargs='+', default=RATE_DEFAULT_SEEDS)
    parser.add_argument('--rate-delays', type=int, nargs='+', default=RATE_DEFAULT_DELAYS)
    args = parser.parse_args(argv)
    prepare(args.source, args.out, args.include_500, args.profile, args.rate_seeds, args.rate_delays)


if __name__ == '__main__':
    main()
