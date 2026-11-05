"""Experiment 2b: controller-delay sweep. Self-contained variant of response/lab.py (which is untouched).

Differences from experiment 2, all declared in PROTOCOL_2B.md:
  * own subnets, so the project can coexist with experiment 2;
  * the trial RPC timeout stays 1 s, but RTT calibration (and the runner->edge API) use a longer, separate timeout;
  * timed-out controller exchanges are classified (failure_kind='timeout') for fail-open accounting;
  * profiles: smoke / full (base sweep) and rate-smoke / rate (separate flow-rate profile with packet counting).
"""
import collections
import hashlib
import json
import math
import os
import platform
import re
import socket
import socketserver
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

DATA_NET = '172.30.103'
CONTROL_NET = '172.30.104'
EDGE = f'{DATA_NET}.2'
DATA_GATEWAY = f'{DATA_NET}.1'
CLIENT = f'{DATA_NET}.10'
HEALTH = f'{DATA_NET}.11'
EDGE_CONTROL = f'{CONTROL_NET}.2'
CONTROLLER = f'{CONTROL_NET}.3'
API_PORT = 18000
CONTROL_PORT = 18001
HEALTH_PORT = 18002
PROBE_PORT = 19000
ARTIFACTS = Path('/artifacts')
RESULTS = Path('/results')
CHAIN = 'THESIS_IDS'

RPC_TIMEOUT = 1               # controller exchange inside a trial: unchanged from experiment 2
CALIBRATION_TIMEOUT = 10      # RTT calibration only; must exceed the largest RTT (2 x 500 ms)
EDGE_API_TIMEOUT = 60         # runner -> edge; 'configure' includes calibration at large delays
BASE_PROBE_RATE_PPS = 200     # 5 ms probe interval, as in experiment 2
SMOKE_DELAYS = [0, 10, 50, 100, 250]
SLOW_DELAY = 500
PROFILES = ['smoke', 'full', 'rate-smoke', 'rate']
PROFILE_MANIFEST = {'smoke': 'manifest.json', 'full': 'manifest.json',
                    'rate-smoke': 'manifest-rate.json', 'rate': 'manifest-rate.json'}


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False), encoding='utf-8')
    temporary.replace(path)


def append_json(path, value):
    with Path(path).open('a', encoding='utf-8') as output:
        output.write(json.dumps(value, allow_nan=False) + '\n')
        output.flush()
        os.fsync(output.fileno())


def policy(score, threshold):
    return 'block' if score >= threshold else 'allow'


def classify_failure(error):
    """Fail-open accounting: a controller reply that did not arrive within the trial timeout is a 'timeout'."""
    return 'timeout' if isinstance(error, (socket.timeout, TimeoutError)) else 'other'


def parse_chain_counters(listing):
    """Parse `iptables -nvxL CHAIN`: (total DROP packets, packets seen by a target-less counting rule or None)."""
    drops, counted = 0, None
    for line in listing.splitlines():
        parts = line.split()
        if len(parts) < 8 or not (parts[0].isdigit() and parts[1].isdigit()):
            continue
        if parts[2] == 'DROP':
            drops += int(parts[0])
        elif len(parts) == 8 and parts[3] == '--':  # no target column: a pure counter rule
            counted = (counted or 0) + int(parts[0])
    return drops, counted


class RPC:
    def __init__(self, host, port, timeout=RPC_TIMEOUT):
        self.host, self.port, self.timeout = host, port, timeout
        self.sock = self.reader = None
        self.buffer = b''

    def close(self):
        if self.reader:
            self.reader.close()
        if self.sock:
            self.sock.close()
        self.sock = self.reader = None
        self.buffer = b''

    def call(self, op, **payload):
        identifier = payload.pop('request_id', uuid.uuid4().hex)
        deadline = time.monotonic() + self.timeout
        def remaining():
            budget = deadline - time.monotonic()
            if budget <= 0:
                raise TimeoutError('RPC total deadline exceeded')
            return budget
        try:
            if self.sock is None:
                self.sock = socket.create_connection((self.host, self.port), timeout=remaining())
                self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self.sock.settimeout(remaining())
            self.sock.sendall((json.dumps({'op': op, 'id': identifier, **payload}, allow_nan=False) + '\n').encode())
            while b'\n' not in self.buffer:
                self.sock.settimeout(remaining())
                chunk = self.sock.recv(4096)
                if not chunk or len(self.buffer) + len(chunk) > 262144:
                    raise RuntimeError('Closed or invalid RPC response')
                self.buffer += chunk
            raw, self.buffer = self.buffer.split(b'\n', 1)
            remaining()
            if not raw or len(raw) > 262144:
                raise RuntimeError('Closed or invalid RPC response')
            reply = json.loads(raw)
            if reply.get('id') != identifier:
                raise RuntimeError('Stale/mismatched RPC response ID rejected')
            if 'rpc_error' in reply:
                raise RuntimeError(reply['rpc_error'])
            remaining()
            return reply
        except Exception:
            self.close()
            raise


class Echo:
    def __init__(self):
        self.counts = {}
        self.lock = threading.Lock()
        threading.Thread(target=self.run, daemon=True).start()

    def run(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(('0.0.0.0', PROBE_PORT))
        while True:
            payload, address = sock.recvfrom(4096)
            token = payload.decode().split('|')[0]
            with self.lock:
                key = (address[0], token)
                self.counts[key] = self.counts.get(key, 0) + 1
            sock.sendto(payload, address)

    def count(self, source, token):
        with self.lock:
            return self.counts.get((source, token), 0)


class Probes:
    """UDP probe stream. paced=False reproduces experiment 2 (sleep `interval` after each send);
    paced=True schedules against absolute deadlines so that 800-2500 packets/s are reachable."""

    def __init__(self, interval=1 / BASE_PROBE_RATE_PPS, token='idle', paced=False):
        self.interval, self.token, self.paced = interval, token, paced
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(0.05)
        self.lock = threading.Lock()
        self.sent, self.received = {}, {}
        self.rtt_ms = collections.deque(maxlen=1000)
        self.stopped = threading.Event()
        threading.Thread(target=self.send, daemon=True).start()
        threading.Thread(target=self.receive, daemon=True).start()

    def set_rate(self, packets_per_second):
        self.interval = 1.0 / packets_per_second

    def send(self):
        next_time = time.monotonic()
        while not self.stopped.is_set():
            token = self.token
            stamp = time.monotonic_ns()
            self.sock.sendto(f'{token}|{stamp}'.encode(), (EDGE, PROBE_PORT))
            with self.lock:
                self.sent[token] = self.sent.get(token, 0) + 1
            if self.paced:
                next_time += self.interval
                now = time.monotonic()
                if next_time - now < -0.05:  # never burst to catch up more than 50 ms
                    next_time = now
                self.stopped.wait(max(0.0, next_time - now))
            else:
                self.stopped.wait(self.interval)

    def receive(self):
        while not self.stopped.is_set():
            try:
                payload, _ = self.sock.recvfrom(4096)
                token, stamp = payload.decode().split('|')
                rtt = (time.monotonic_ns() - int(stamp)) / 1e6
                with self.lock:
                    self.received[token] = self.received.get(token, 0) + 1
                    self.rtt_ms.append(rtt)
            except socket.timeout:
                pass

    def wait_echo(self, token, timeout=1):
        self.token = token
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self.lock:
                if self.received.get(token, 0):
                    return True
            self.stopped.wait(0.002)
        return False

    def snapshot(self):
        with self.lock:
            values = sorted(list(self.rtt_ms)[-100:])
            return {'sent': sum(self.sent.values()), 'received': sum(self.received.values()),
                    'recent_rtt_median_ms': values[len(values) // 2] if values else None}

    def token_counts(self, token):
        with self.lock:
            return {'sent': self.sent.get(token, 0), 'received': self.received.get(token, 0)}


class Application:
    def __init__(self, role):
        self.role = role
        self.lock = threading.Lock()
        if role == 'health':
            self.probes = Probes(interval=0.01, token='health')
        if role == 'edge':
            import torch
            self.torch = torch
            torch.set_num_threads(1)
            torch.set_num_interop_threads(1)
            # Models and feature order are identical in both manifests; either profile may have been prepared alone.
            self.manifest = read_json(next(path for path in [ARTIFACTS / 'manifest.json', ARTIFACTS / 'manifest-rate.json']
                                           if path.exists()))
            self.models = {str(item['seed']): item for item in self.manifest['models']}
            self.loaded = {}
            self.current = None
            self.pending = {}
            self.count_rule = False
            self.controller = RPC(CONTROLLER, CONTROL_PORT, timeout=RPC_TIMEOUT)               # timed trials
            self.calibration = RPC(CONTROLLER, CONTROL_PORT, timeout=CALIBRATION_TIMEOUT)      # calibration only
            command(['iptables', '-w', '1', '-N', CHAIN], check=False)
            jump = ['INPUT', '-p', 'udp', '--dport', str(PROBE_PORT), '-j', CHAIN]
            if command(['iptables', '-w', '1', '-C', *jump], check=False).returncode:
                command(['iptables', '-w', '1', '-I', *jump])
            self.reset()
            self.echo = Echo()

    def reset(self):
        command(['iptables', '-w', '1', '-F', CHAIN])
        if self.count_rule:
            # Rate profile only: a target-less rule that counts every packet from the replay client reaching
            # the chain, placed before any later DROP. It never changes a packet's fate.
            command(['iptables', '-w', '1', '-A', CHAIN, '-s', CLIENT])

    def infer(self, vector):
        torch = self.torch
        with torch.inference_mode():
            return float(torch.sigmoid(self.loaded[self.current](torch.tensor([vector], dtype=torch.float32))).item())

    def chain_counters(self):
        return parse_chain_counters(command(['iptables', '-nvxL', CHAIN], timeout=1).stdout)

    def configure(self, seed, delay, count_rule=False):
        self.count_rule = bool(count_rule)
        self.reset()
        key = str(seed)
        if key not in self.loaded:
            self.loaded[key] = self.torch.jit.load(str(ARTIFACTS / self.models[key]['model_file'])).eval()
        self.current = key
        for _ in range(30):
            self.infer([0.0] * len(self.manifest['features']))
        # Calibration uses its own long-timeout connection: at 500 ms one-way the policy RTT exceeds the
        # 1 s trial timeout, and calibration must still be able to record the actual RTT.
        remote = self.calibration.call('configure', delay_ms=delay)
        local = netem(CONTROLLER, delay)
        for _ in range(2):
            self.calibration.call('policy', score=0.0, threshold=1.0, model_id=key)
        rtts = []
        for _ in range(6):
            start = time.monotonic_ns()
            self.calibration.call('policy', score=0.0, threshold=1.0, model_id=key)
            rtts.append((time.monotonic_ns() - start) / 1e6)
        # Warm the established trial connection with the real (1 s) timeout. A failure here is data, not an error.
        warm_errors = []
        for _ in range(2):
            try:
                self.controller.call('policy', score=0.0, threshold=1.0, model_id=key)
            except Exception as error:
                warm_errors.append(repr(error))
        return {'edge_netem': local, 'controller_netem': remote['netem'], 'rpc_rtt_ms': rtts,
                'seed': seed, 'delay_ms': delay, 'count_rule': self.count_rule,
                'rpc_timeout_s': RPC_TIMEOUT, 'calibration_timeout_s': CALIBRATION_TIMEOUT,
                'trial_connection_warm_ok': not warm_errors, 'trial_connection_warm_errors': warm_errors,
                'torch': self.torch.__version__, 'kernel': platform.release(),
                'torch_threads': self.torch.get_num_threads(),
                'firewall_backend': command(['iptables', '--version']).stdout.strip()}

    def trial(self, request):
        vector = request['features']
        if len(vector) != len(self.manifest['features']) or not all(isinstance(x, (int, float)) and math.isfinite(x) for x in vector):
            raise ValueError('Invalid standardized feature vector')
        identifier = request['id']
        result = {'trial_id': identifier, 'mode': request['mode'], 'seed': int(self.current)}
        if self.count_rule:  # outside the timed interval
            result['counter_start_begin_ns'] = time.monotonic_ns()
            result['arrived_before'] = self.chain_counters()[1] or 0
            result['counter_start_end_ns'] = time.monotonic_ns()
        t0 = time.monotonic_ns()  # Complete vector decoded and validated, before tensor creation.
        score = self.infer(vector)
        t_inference = time.monotonic_ns()
        threshold = self.models[self.current]['threshold']
        expected = policy(score, threshold)
        result.update(score=score, threshold=threshold, expected_action=expected,
                      inference_ms=(t_inference - t0) / 1e6, t0_ns=t0,
                      health_before=self.echo.count(HEALTH, 'health'))
        action = None
        fault = request.get('fault')
        try:
            control_started = time.monotonic_ns()
            if request['mode'] == 'central':
                if fault == 'outage':
                    client = RPC(CONTROLLER, CONTROL_PORT + 99, timeout=RPC_TIMEOUT)
                else:
                    client = self.controller
                reply = client.call('policy', request_id=identifier, score=score, threshold=threshold,
                                    model_id=self.current, fault=fault if fault in ['late', 'stale'] else None)
                action = reply['action']
                result['controller_ms'] = (time.monotonic_ns() - control_started) / 1e6
            else:
                action = expected
                result['controller_ms'] = 0.0
            if action != expected:
                raise RuntimeError('Policy disagreement between local and controller')
        except Exception as error:
            result.update(status='controller_failure', error=repr(error), action=None,
                          failure_kind=classify_failure(error),
                          failure_elapsed_ms=(time.monotonic_ns() - t0) / 1e6)
            self.pending[identifier] = result
            return result
        result['action'] = action
        result['decision_ms'] = (time.monotonic_ns() - t0) / 1e6
        if action == 'block':
            enforcement_started = time.monotonic_ns()
            try:
                chain = 'THESIS_DOES_NOT_EXIST' if fault == 'enforcement' else CHAIN
                command(['iptables', '-w', '1', '-A', chain, '-s', CLIENT, '-j', 'DROP'])
                ended = time.monotonic_ns()
                result.update(status='awaiting_verification', firewall_command_ms=(ended - enforcement_started) / 1e6,
                              feature_to_firewall_command_ms=(ended - t0) / 1e6, t_command_end_ns=ended)
            except Exception as error:
                result.update(status='enforcement_failure', error=repr(error), failure_kind='other',
                              failure_elapsed_ms=(time.monotonic_ns() - t0) / 1e6)
        else:
            result['status'] = 'awaiting_verification'
        self.pending[identifier] = result
        return result

    def verify(self, trial_id, token):
        result = dict(self.pending.pop(trial_id))
        counter_end_begin = time.monotonic_ns()
        drops, counted = self.chain_counters()
        stamp = time.monotonic_ns()
        delivered = self.echo.count(CLIENT, token)
        health = self.echo.count(HEALTH, 'health') - result['health_before']
        result.update(drop_packets=drops, post_command_probe_delivered=delivered,
                      health_delivered=health, t_verification_ns=stamp,
                      feature_to_verification_observation_ms=(stamp - result['t0_ns']) / 1e6)
        if 'arrived_before' in result:
            before = result.pop('arrived_before')
            arrived = None if counted is None else counted - before
            result.update(chain_arrived_packets=arrived,
                          passed_in_counter_interval_packets=None if arrived is None else arrived - drops,
                          counter_end_begin_ns=counter_end_begin, counter_end_end_ns=stamp,
                          counter_interval_ms=(stamp-result['counter_start_end_ns'])/1e6,
                          counter_pre_t0_upper_bound_ms=(result['t0_ns']-result['counter_start_begin_ns'])/1e6,
                          counter_boundary_uncertainty_ms=((result['counter_start_end_ns']-result['counter_start_begin_ns'])+(stamp-counter_end_begin))/1e6)
            interval = stamp - result['counter_start_end_ns']
            result['counter_ingress_rate_pps'] = arrived * 1e9 / interval if arrived is not None and interval > 0 else None
        if result['status'] == 'awaiting_verification':
            if result['action'] == 'block':
                result['status'] = 'ok_block' if drops > 0 and delivered == 0 and health > 0 else 'verification_failure'
            else:
                result['status'] = 'ok_allow' if not drops and delivered > 0 and health > 0 else 'verification_failure'
        return result

    def dispatch(self, request):
        op = request['op']
        if op == 'ping':
            return {'ready': True, 'role': self.role}
        if self.role == 'health':
            return self.probes.snapshot()
        if self.role == 'controller':
            if op == 'configure':
                return {'netem': netem(EDGE_CONTROL, request['delay_ms'])}
            if op == 'policy':
                if request.get('fault') == 'late':
                    time.sleep(1.2)  # Explicit smoke fault injection, never the netem substitute.
                result = {'action': policy(request['score'], request['threshold']), 'model_id': request['model_id']}
                if request.get('fault') == 'stale':
                    result['_id_override'] = 'expired-trial-id'
                return result
        if self.role == 'edge':
            with self.lock:
                if op == 'configure':
                    return self.configure(request['seed'], request['delay_ms'], request.get('count_rule', False))
                if op == 'reset':
                    self.reset()
                    return {'reset': True}
                if op == 'infer':
                    return {'score': self.infer(request['features'])}
                if op == 'trial':
                    return self.trial(request)
                if op == 'verify':
                    return self.verify(request['trial_id'], request['token'])
        raise ValueError(f'Unknown operation {op}')


def serve(role):
    application = Application(role)

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            self.request.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            while raw := self.rfile.readline(262145):
                if len(raw) > 262144:
                    break
                request = json.loads(raw)
                try:
                    payload = application.dispatch(request)
                    identifier = payload.pop('_id_override', request['id'])
                    reply = {'id': identifier, **payload}
                except Exception as error:
                    reply = {'id': request['id'], 'rpc_error': repr(error)}
                try:
                    self.wfile.write((json.dumps(reply, allow_nan=False) + '\n').encode())
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    break

    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True

    port = {'edge': API_PORT, 'controller': CONTROL_PORT, 'health': HEALTH_PORT}[role]
    print(f'{role} ready on {port}', flush=True)
    with Server(('0.0.0.0', port), Handler) as server:
        server.serve_forever()


def command(args, timeout=2, check=True):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(f'{args}: {result.stderr.strip()}')
    return result


def interface_to(peer):
    return json.loads(command(['ip', '-j', 'route', 'get', peer]).stdout)[0]['dev']


def netem(peer, delay):
    interface = interface_to(peer)
    command(['tc', 'qdisc', 'replace', 'dev', interface, 'root', 'netem', 'delay', f'{delay}ms'])
    return {'interface': interface, 'delay_ms': delay,
            'qdisc': command(['tc', '-s', 'qdisc', 'show', 'dev', interface]).stdout}


def preflight():
    print(command(['iptables', '--version']).stdout.strip(), flush=True)
    command(['iptables', '-w', '1', '-N', 'THESIS_IDS'])
    command(['iptables', '-w', '1', '-I', 'INPUT', '1', '-p', 'udp', '--dport', str(PROBE_PORT), '-j', 'THESIS_IDS'])
    command(['iptables', '-w', '1', '-A', 'THESIS_IDS', '-s', CLIENT, '-j', 'DROP'])
    print(command(['iptables', '-nvxL', 'THESIS_IDS']).stdout, flush=True)
    command(['iptables', '-w', '1', '-F', 'THESIS_IDS'])
    command(['iptables', '-w', '1', '-D', 'INPUT', '-p', 'udp', '--dport', str(PROBE_PORT), '-j', 'THESIS_IDS'])
    command(['iptables', '-w', '1', '-X', 'THESIS_IDS'])
    print(command(['ip', '-j', 'address']).stdout, flush=True)
    print(json.dumps(netem(DATA_GATEWAY, 10)), flush=True)
    print('Kernel firewall and netem commands supported.', flush=True)


def wait_ready(client, seconds=60):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            client.call('ping')
            return
        except Exception:
            time.sleep(0.2)
    raise RuntimeError(f'Service not ready: {client.host}:{client.port}')


def one_trial(edge, probes, request, features, fault=None):
    identifier = request['trial_id']
    edge.call('reset')
    baseline = f'pre-{identifier}'
    if not probes.wait_echo(baseline):
        return {'trial_id': identifier, 'status': 'baseline_failure'}
    try:
        result = edge.call('trial', request_id=identifier, mode=request['mode'], features=features, fault=fault)
        post = f'post-{identifier}'
        verification_start = time.monotonic()
        probes.token = post
        time.sleep(0.025)  # Fixed verification window; excluded from primary command endpoint.
        result = edge.call('verify', trial_id=identifier, token=post)
        counts = probes.token_counts(post)
        window = time.monotonic() - verification_start
        result['post_probe_sent'] = counts['sent']
        result['post_probe_received'] = counts['received']
        result['post_probe_rate_pps_achieved'] = counts['sent'] / window if window > 0 else None
        if counts['sent'] == 0 or window > 1:
            result['status'] = 'verification_failure'
    except Exception as error:
        result = {'trial_id': identifier, 'status': 'transport_failure', 'error': repr(error)}
    finally:
        edge.call('reset')
    restored = probes.wait_echo(f'restore-{identifier}')
    result['delivery_restored'] = restored
    if not restored:
        result['status'] = 'reset_failure'
    return result


def validate_artifacts(profile):
    manifest = read_json(ARTIFACTS / PROFILE_MANIFEST[profile])
    for name, expected in manifest['artifact_checksums'].items():
        with (ARTIFACTS / name).open('rb') as handle:
            actual = hashlib.file_digest(handle, 'sha256').hexdigest()
        if actual != expected:
            raise RuntimeError(f'Artifact checksum mismatch: {name}')
    return manifest


def completed_pairs(ledger, attempts):
    expected = {}
    for row in ledger:
        expected.setdefault(row['pair_id'], set()).add(row['trial_id'])
    finished = {}
    for row in attempts:
        if row.get('terminal'):
            finished.setdefault(row.get('segment', 'fixture'), set()).add(row['trial_id'])
    touched = {row['trial_id'] for row in attempts}
    completed = {pair for pair, trials in expected.items() if any(trials <= group for group in finished.values())}
    partial = {pair for pair, trials in expected.items() if trials & touched and pair not in completed}
    return completed, partial


def parity(edge, observations, manifest):
    results = []
    for model in manifest['models']:
        edge.call('configure', seed=model['seed'], delay_ms=0)
        maximum = 0.0
        for observation, expected in zip(observations, model['expected_probabilities']):
            actual = edge.call('infer', features=observation['features'])['score']
            maximum = max(maximum, abs(actual - expected))
            assert policy(actual, model['threshold']) == policy(expected, model['threshold'])
        assert maximum < 1e-5
        results.append({'seed': model['seed'], 'max_probability_error': maximum, 'decisions_match': True})
    return results


def smoke(edge, health, probes, target, manifest):
    evidence = {'checks': {}, 'trials': [], 'calibrations': [], 'cpu_parity': []}
    observations = read_json(ARTIFACTS / 'observations.json')
    evidence['cpu_parity'] = parity(edge, observations, manifest)
    evidence['checks']['linux_export_parity'] = True
    chosen = read_json(ARTIFACTS / 'smoke-observations.json')['42']
    block = next(item for item in chosen if item['expected_action'] == 'block')
    allow = next(item for item in chosen if item['expected_action'] == 'allow')
    rtts, health_rtts = {}, {}
    for delay in SMOKE_DELAYS:
        calibration = edge.call('configure', seed=42, delay_ms=delay)
        evidence['calibrations'].append(calibration)
        assert calibration['trial_connection_warm_ok'], calibration
        rtts[delay] = sorted(calibration['rpc_rtt_ms'])[len(calibration['rpc_rtt_ms']) // 2]
        health_rtts[delay] = health.call('snapshot')['recent_rtt_median_ms']
        for index, observation in enumerate(chosen):
            for mode in ['local', 'central']:
                identifier = f'smoke-d{delay}-o{index}-{mode}'
                result = one_trial(edge, probes, {'trial_id': identifier, 'mode': mode}, observation['features'])
                assert result['status'] == f'ok_{observation["expected_action"]}', result
                assert result['action'] == observation['expected_action'], result
                evidence['trials'].append(result)
    assert rtts[10] > rtts[0] + 10 and rtts[50] > rtts[0] + 70, rtts
    assert rtts[100] > rtts[0] + 170 and rtts[250] > rtts[0] + 420, rtts
    assert rtts[250] < 1000 * RPC_TIMEOUT, ('250 ms must stay inside the 1 s trial timeout', rtts)
    assert health_rtts[250] is not None and health_rtts[250] < rtts[250] / 2, health_rtts
    evidence['checks']['netem_rpc_and_data_path_isolation'] = True
    evidence['checks']['real_drop_allow_health_and_reset'] = True
    # 500 ms one way: the policy RTT is above the 1 s trial timeout. Calibration must still succeed with its own
    # timeout while central trials fail open as classified timeouts; local trials are unaffected.
    slow = edge.call('configure', seed=42, delay_ms=SLOW_DELAY)
    evidence['calibrations'].append(slow)
    assert min(slow['rpc_rtt_ms']) > 900 * RPC_TIMEOUT, slow
    assert not slow['trial_connection_warm_ok'], slow
    timed_out = one_trial(edge, probes, {'trial_id': 'smoke-d500-central', 'mode': 'central'}, block['features'])
    assert timed_out['status'] == 'controller_failure' and timed_out['failure_kind'] == 'timeout', timed_out
    assert timed_out['drop_packets'] == 0 and timed_out['post_command_probe_delivered'] > 0, timed_out
    assert 'feature_to_firewall_command_ms' not in timed_out, timed_out
    local = one_trial(edge, probes, {'trial_id': 'smoke-d500-local', 'mode': 'local'}, block['features'])
    assert local['status'] == 'ok_block', local
    evidence['trials'] += [timed_out, local]
    evidence['checks']['calibration_survives_rtt_above_trial_timeout_and_timeouts_fail_open'] = True
    edge.call('configure', seed=42, delay_ms=0)
    for fault in ['outage', 'late', 'stale', 'enforcement']:
        result = one_trial(edge, probes, {'trial_id': f'smoke-fault-{fault}', 'mode': 'central'}, block['features'], fault=fault)
        expected = 'enforcement_failure' if fault == 'enforcement' else 'controller_failure'
        assert result['status'] == expected, result
        assert result['drop_packets'] == 0 and result['post_command_probe_delivered'] > 0, result
        assert 'feature_to_firewall_command_ms' not in result, result
        if fault == 'late':
            assert result['failure_kind'] == 'timeout', result
        evidence['trials'].append(result)
        follow = one_trial(edge, probes, {'trial_id': f'smoke-after-{fault}', 'mode': 'central'}, allow['features'])
        assert follow['status'] == 'ok_allow', follow
        evidence['trials'].append(follow)
    evidence['checks']['controller_outage_timeout_stale_and_enforcement_failure'] = True
    tiny = [{'trial_id': 'a-local', 'pair_id': 'a'}, {'trial_id': 'a-central', 'pair_id': 'a'},
            {'trial_id': 'b-local', 'pair_id': 'b'}, {'trial_id': 'b-central', 'pair_id': 'b'}]
    attempts = [{'trial_id': 'a-local', 'terminal': True, 'status': 'ok_allow'},
                {'trial_id': 'a-central', 'terminal': True, 'status': 'controller_failure'},
                {'trial_id': 'b-local', 'terminal': True, 'status': 'ok_block'},
                {'trial_id': 'b-central', 'terminal': False, 'status': 'started'}]
    recovery = target / 'recovery-fixture.jsonl'
    for attempt in attempts:
        append_json(recovery, attempt)
    recovered = [json.loads(line) for line in recovery.read_text().splitlines()]
    done, partial = completed_pairs(tiny, recovered)
    assert done == {'a'} and partial == {'b'}, (done, partial)
    evidence['checks']['append_only_recovery_preserves_failures_and_pairs'] = True
    evidence['rpc_median_ms'] = rtts
    evidence['health_recent_median_ms'] = health_rtts
    evidence['passed'] = True
    write_json(target / 'smoke.json', evidence)
    print(json.dumps({'smoke_passed': True, 'checks': evidence['checks'], 'rpc_median_ms': rtts}, indent=2), flush=True)


def rate_smoke(edge, health, probes, target, manifest):
    """Separate gate for the flow-rate profile: counting rule, rate setting, and packet accounting."""
    evidence = {'checks': {}, 'trials': [], 'achieved_rate_pps': {}}
    observations = read_json(ARTIFACTS / 'observations.json')
    evidence['cpu_parity'] = parity(edge, observations, manifest)
    chosen = read_json(ARTIFACTS / 'smoke-observations.json')['42']
    for rate in manifest['rates_pps']:
        probes.set_rate(rate)
        calibration = edge.call('configure', seed=42, delay_ms=0, count_rule=True)
        assert calibration['count_rule'], calibration
        achieved = []
        for index, observation in enumerate(chosen):
            for mode in ['local', 'central']:
                identifier = f'rate-smoke-r{rate}-o{index}-{mode}'
                result = one_trial(edge, probes, {'trial_id': identifier, 'mode': mode}, observation['features'])
                assert result['status'] == f'ok_{observation["expected_action"]}', result
                arrived, passed = result['chain_arrived_packets'], result['passed_in_counter_interval_packets']
                assert arrived is not None and arrived > 0 and passed >= 0, result
                assert passed == arrived - result['drop_packets'], result
                if observation['expected_action'] == 'block':
                    assert result['drop_packets'] > 0 and arrived >= result['drop_packets'], result
                else:
                    assert result['drop_packets'] == 0 and passed == arrived, result
                achieved.append(result['post_probe_rate_pps_achieved'])
                evidence['trials'].append(result)
        evidence['achieved_rate_pps'][str(rate)] = {'target': rate, 'median_achieved': sorted(achieved)[len(achieved) // 2]}
    evidence['checks']['count_rule_arrived_dropped_passed_accounting'] = True
    edge.call('configure', seed=42, delay_ms=0, count_rule=False)
    evidence['passed'] = True
    write_json(target / 'smoke.json', evidence)
    print(json.dumps({'rate_smoke_passed': True, 'achieved_rate_pps': evidence['achieved_rate_pps']}, indent=2), flush=True)


def full_run(edge, health, probes, target, manifest, profile):
    ledger_name = 'ledger-rate.jsonl' if profile == 'rate' else 'ledger.jsonl'
    observations = read_json(ARTIFACTS / 'observations.json')
    ledger = [json.loads(line) for line in (ARTIFACTS / ledger_name).read_text().splitlines()]
    journal = target / 'attempts.jsonl'
    attempts = [json.loads(line) for line in journal.read_text().splitlines()] if journal.exists() else []
    completed, partial = completed_pairs(ledger, attempts)
    segment = uuid.uuid4().hex[:12]
    append_json(target / 'segments.jsonl', {'segment': segment, 'started_utc': time.time(),
                'completed_pairs_at_start': len(completed), 'partial_pairs_repeated': sorted(partial)})
    current_block = None
    terminal_count = len(completed) * 2
    for row in ledger:
        if row['pair_id'] in completed:
            continue
        if (target / 'STOP').exists():
            write_json(target / 'status.json', {'state': 'stopped', 'terminal_trials': terminal_count, 'assigned_trials': len(ledger)})
            return
        if row['block_id'] != current_block:
            current_block = row['block_id']
            probes.set_rate(row.get('probe_rate_pps', BASE_PROBE_RATE_PPS))
            calibration = edge.call('configure', seed=row['seed'], delay_ms=row['delay_ms'], count_rule=profile == 'rate')
            append_json(target / 'calibrations.jsonl', {'segment': segment, 'block_id': current_block,
                        'edge': calibration, 'health': health.call('snapshot')})
        observation = observations[row['observation_index']]
        start = {**row, 'segment': segment, 'attempt_id': uuid.uuid4().hex,
                 'label': observation['label'], 'attack_type': observation['attack_type'],
                 'test_index': observation['test_index'], 'processed_row_id': observation['processed_row_id'],
                 'feature_hash_u64': observation['feature_hash_u64']}
        append_json(journal, {**start, 'terminal': False, 'status': 'started'})
        result = one_trial(edge, probes, row, observation['features'])
        record = {**start, **{key: value for key, value in result.items() if key != 'id'}, 'terminal': True}
        append_json(journal, record)
        terminal_count += 1
        if terminal_count % 20 == 0:
            write_json(target / 'status.json', {'state': 'running', 'terminal_trials': terminal_count,
                       'assigned_trials': len(ledger), 'block': current_block, 'last_status': record['status']})
            print(f'{terminal_count}/{len(ledger)} trials; {current_block}; last={record["status"]}', flush=True)
    write_json(target / 'status.json', {'state': 'completed', 'terminal_trials': terminal_count, 'assigned_trials': len(ledger)})
    print('Full 2b matrix completed.', flush=True)


def runner(profile, name):
    manifest = validate_artifacts(profile)
    target = RESULTS / name
    target.mkdir(parents=True, exist_ok=True)
    edge = RPC(EDGE, API_PORT, timeout=EDGE_API_TIMEOUT)
    health = RPC(HEALTH, HEALTH_PORT, timeout=2)
    wait_ready(edge)
    wait_ready(health)
    probes = Probes(paced=profile in ['rate-smoke', 'rate'])
    try:
        if profile == 'smoke':
            smoke(edge, health, probes, target, manifest)
        elif profile == 'rate-smoke':
            rate_smoke(edge, health, probes, target, manifest)
        else:
            full_run(edge, health, probes, target, manifest, profile)
    except Exception as error:
        write_json(target / 'status.json', {'state': 'failed', 'error': repr(error)})
        raise
    finally:
        try:
            edge.call('reset')
        finally:
            probes.stopped.set()
            edge.close()
            health.close()


if __name__ == '__main__':
    if sys.argv[1] == 'preflight':
        preflight()
    elif sys.argv[1] in ['edge', 'controller', 'health']:
        serve(sys.argv[1])
    elif sys.argv[1] == 'runner' and sys.argv[2] in PROFILES:
        runner(sys.argv[2], sys.argv[3])
    else:
        raise SystemExit(f'Usage: lab_2b.py preflight | edge | controller | health | runner {{{"|".join(PROFILES)}}} <run-name>')
