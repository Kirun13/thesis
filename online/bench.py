"""Real routed MQTT episodes: kernel capture -> causal windows -> model -> DROP."""
import collections
import hashlib
import json
import os
import queue
import resource
import socket
import socketserver
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, '/app')
from lab import RPC, command, interface_to, netem
from features import FEATURES, WINDOW_SECONDS, decode, vector
from mqtt import connect, publish, receive, subscribe

PORT = 18500
POLICY_PORT = 18600
BROKER = '172.30.96.3'
GATEWAY = '172.30.95.2'
SOURCES = ['172.30.95.10', '172.30.95.11', '172.30.95.12']
CONTROLLER = '172.30.97.3'
ROOT = Path('/results')
ARTIFACTS = Path('/artifacts')
CHAIN = 'THESIS_ONLINE'


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, allow_nan=False), encoding='utf-8')


def cpu():
    r = resource.getrusage(resource.RUSAGE_SELF)
    return r.ru_utime + r.ru_stime


class App:
    def __init__(self, role, source_index=None):
        self.role, self.index = role, source_index
        self.running = False
        self.lock = threading.Lock()
        self.epoch = 0
        self.broker_process = None
        self.connections = []
        self.threads = []
        self.firewall_lock = threading.Lock()
        if role == 'source':
            command(['ip', 'route', 'replace', '172.30.96.0/24', 'via', '172.30.95.2'])
        if role == 'broker':
            command(['ip', 'route', 'replace', '172.30.95.0/24', 'via', '172.30.96.2'])
        if role == 'edge':
            import torch
            self.torch = torch
            torch.set_num_threads(1)
            torch.set_num_interop_threads(1)
            self.ingress = interface_to(SOURCES[0])
            self.egress = interface_to(BROKER)
            # Docker bridge isolation rejects foreign-subnet routed frames before
            # container ingress. Use explicit gateway DNAT/SNAT inside edge only.
            # The FORWARD policy still matches the original source before SNAT.
            for table, chain, spec in [
                ('nat', 'PREROUTING', ['-d', GATEWAY, '-p', 'tcp', '--dport', '1883', '-j', 'DNAT', '--to-destination', BROKER + ':1883']),
                ('nat', 'POSTROUTING', ['-o', self.egress, '-d', BROKER, '-p', 'tcp', '--dport', '1883', '-j', 'SNAT', '--to-source', '172.30.96.2'])]:
                if command(['iptables', '-t', table, '-C', chain, *spec], check=False).returncode:
                    command(['iptables', '-t', table, '-A', chain, *spec])
            command(['iptables', '-N', CHAIN], check=False)
            jump = ['FORWARD', '-i', self.ingress, '-o', self.egress, '-p', 'tcp', '--dport', '1883', '-j', CHAIN]
            if command(['iptables', '-C', *jump], check=False).returncode:
                command(['iptables', '-I', *jump])
            command(['iptables', '-F', CHAIN])
            self.controller = RPC(CONTROLLER, POLICY_PORT, timeout=1)
            self.model = None

    def stop(self):
        self.running = False
        self.epoch += 1
        for connection in self.connections:
            try:
                connection.close()
            except OSError:
                pass
        self.connections = []
        for thread in self.threads:
            thread.join(timeout=2)
        self.threads = []
        if self.role == 'edge':
            command(['iptables', '-F', CHAIN])
        if self.role == 'broker' and self.broker_process:
            self.broker_process.terminate()
            self.broker_process.wait(timeout=2)
            self.broker_process = None
            self.broker_log.close()

    def source_loop(self, config):
        index, sequence, sock = self.index, 0, None
        start = config['start_ns']
        duration = config['duration']
        offered, relative, sequence = [], 0.0, 0
        while relative < duration:
            attack = index == config['attacker'] and config['attack_start'] <= relative < config['attack_end']
            burst = (int(relative * 2) + index + config['traffic_seed']) % 7 == 0
            rate = config['attack_rate'] if attack else (config['benign_burst_rate'] if burst else config['benign_rate'])
            offered.append([sequence, start + int(relative * 1e9), 'A' if attack else 'B'])
            relative += 1 / rate
            sequence += 1
        write(self.path / f'source-{index}-offered.json', offered)
        records, errors = [], 0
        attempts, skipped = 0, 0
        for sequence, planned, tag in offered:
            if not self.running:
                break
            now = time.monotonic_ns()
            if now < planned:
                time.sleep((planned - now) / 1e9)
            if time.monotonic_ns() - planned > 50_000_000:
                skipped += 1
                continue
            attempts += 1
            try:
                if sock is None:
                    sock = connect(GATEWAY, f'device-{config["traffic_seed"]}-{index}-{sequence}')
                    sock.settimeout(0.3)
                    self.connections.append(sock)
                stamp = time.monotonic_ns()
                payload = f'{config["episode_id"]}|{index}|{sequence:08d}|{stamp:020d}|{tag}|'.encode()
                payload = payload.ljust(config['payload_bytes'], b'x')
                publish(sock, payload)
                records.append([sequence, stamp, tag])
            except (OSError, RuntimeError) as error:
                errors += 1
                if sock:
                    sock.close()
                sock = None
        if sock:
            sock.close()
        write(self.path / f'source-{index}.json', {'source': SOURCES[index], 'records': records,
              'errors': errors, 'attempted': attempts, 'scheduled': len(offered), 'skipped_late': skipped,
              'clock_namespace': os.readlink('/proc/self/ns/time')})

    def subscriber(self, config):
        records = []
        sock = connect('127.0.0.1', f'observer-{config["traffic_seed"]}')
        sock.settimeout(0.2)
        self.connections.append(sock)
        subscribe(sock)
        self.subscriber_ready.set()
        while self.running:
            try:
                kind, body = receive(sock)
                if kind >> 4 != 3:
                    continue
                topic_length = struct.unpack_from('!H', body)[0]
                payload = body[2 + topic_length:]
                parts = payload.decode().split('|')
                if parts[0] != config['episode_id']:
                    continue
                records.append([int(parts[1]), int(parts[2]), int(parts[3]), time.monotonic_ns(), parts[4]])
            except socket.timeout:
                continue
            except (OSError, ValueError, ConnectionError):
                break
        write(self.path / 'subscriber.json', {'records': records, 'clock_namespace': os.readlink('/proc/self/ns/time')})

    def capture(self, direction, interface, config, ready):
        sock = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(3))
        sock.bind((interface, 0))
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
        sock.setsockopt(socket.SOL_SOCKET, 35, 1)  # Linux SO_TIMESTAMPNS / SCM_TIMESTAMPNS.
        sock.settimeout(0.05)
        start_mono = time.monotonic_ns()
        real = time.time_ns()
        end_mono = time.monotonic_ns()
        offset = real - (start_mono + end_mono) // 2
        events = []
        pcap = (self.path / f'{direction}.pcap').open('wb')
        pcap.write(struct.pack('<IHHIIII', 0xa1b23c4d, 2, 4, 0, 0, 65535, 1))
        ready.set()
        while self.running:
            try:
                frame, ancillary, _, _ = sock.recvmsg(65535, 256)
            except socket.timeout:
                continue
            packet = decode(frame)
            if not packet or packet['dport'] != 1883:
                continue
            if direction == 'ingress' and (packet['source'] not in SOURCES or packet['destination'] != GATEWAY):
                continue
            if direction == 'egress' and packet['destination'] != BROKER:
                continue
            real_stamp = None
            for level, kind, raw in ancillary:
                if level == socket.SOL_SOCKET and kind == 35:
                    sec, ns = struct.unpack('qq', raw[:16])
                    real_stamp = sec * 1_000_000_000 + ns
            if real_stamp is None:
                raise RuntimeError('Kernel packet timestamp unavailable; no arrival-time fallback permitted.')
            stamp = real_stamp - offset
            pcap.write(struct.pack('<IIII', real_stamp // 1_000_000_000, real_stamp % 1_000_000_000, len(frame), len(frame)))
            pcap.write(frame)
            packet['timestamp_ns'] = stamp
            packet.pop('payload')
            events.append(packet)
            if direction == 'ingress' and stamp >= config['start_ns']:
                window = int((stamp - config['start_ns']) // int(WINDOW_SECONDS * 1e9))
                with self.lock:
                    if window <= self.flushed_window:
                        self.late_packets += 1
                    else:
                        self.buckets.setdefault((window, packet['source']), []).append(packet)
        stats = struct.unpack('II', sock.getsockopt(263, 6, 8))  # PACKET_STATISTICS
        sock.close()
        pcap.close()
        write(self.path / f'{direction}-events.json', {'packets': events, 'kernel_received': stats[0], 'kernel_drops': stats[1],
              'realtime_minus_monotonic_ns': offset, 'offset_uncertainty_ns': end_mono - start_mono,
              'clock_namespace': os.readlink('/proc/self/ns/time')})

    def windows(self, config):
        step = int(WINDOW_SECONDS * 1e9)
        while self.running:
            now = time.monotonic_ns()
            if now >= config['start_ns'] and not self.cpu_measure_started:
                self.cpu_measure_start = cpu()
                self.cpu_measure_started = True
            closed = int((now - config['start_ns'] - 20_000_000) // step) - 1
            with self.lock:
                ready = [(key, self.buckets.pop(key)) for key in sorted(self.buckets) if key[0] <= closed]
                self.flushed_window = max(self.flushed_window, closed)
            for (window, source), packets in ready:
                packets.sort(key=lambda p: p['timestamp_ns'])
                row = {'window': window, 'source': source, 'features': vector(packets),
                       'packet_count': len(packets), 'attack_tagged_packets': sum(p['attack_tag'] for p in packets),
                       'window_start_ns': config['start_ns'] + window * step,
                       'window_end_ns': config['start_ns'] + (window + 1) * step,
                       'ready_ns': time.monotonic_ns()}
                self.feature_rows.append(row)
                if self.model is not None:
                    self.jobs.put((self.epoch, row))
            if ready:
                self.rss_samples.append({'timestamp_ns': time.monotonic_ns(),
                    'rss_kb': int(Path('/proc/self/statm').read_text().split()[1]) * os.sysconf('SC_PAGE_SIZE') // 1024})
            time.sleep(0.003)

    def detector(self, config):
        torch = self.torch
        while self.running or not self.jobs.empty():
            try:
                epoch, row = self.jobs.get(timeout=0.1)
            except queue.Empty:
                continue
            if not self.running or epoch != self.epoch:
                continue
            begin = time.monotonic_ns()
            with torch.inference_mode():
                x = torch.tensor([row['features']], dtype=torch.float32)
                score = torch.sigmoid(self.model((x - self.means) / self.scales)).item()
            decision = {'source': row['source'], 'window': row['window'], 'ready_ns': row['ready_ns'],
                        'inference_start_ns': begin, 'score': score, 'decision_ns': time.monotonic_ns(),
                        'flagged': score >= self.threshold, 'mode': config['mode'], 'status': 'allow'}
            if score >= self.threshold and config['mode'] != 'none':
                if time.monotonic_ns() < self.blocked_until.get(row['source'], 0):
                    decision['status'] = 'already_blocked'
                else:
                    try:
                        if config['mode'] == 'central':
                            reply = self.controller.call('policy', score=score, threshold=self.threshold,
                                      request_id=f'{config["episode_id"]}-{row["window"]}-{row["source"]}')
                            if reply['action'] != 'block':
                                raise RuntimeError('Controller policy disagreement')
                        if self.running and epoch == self.epoch:
                            with self.firewall_lock:
                                if row['source'] in self.blocked_until:
                                    self.rule_events.append({'event': 'replace_expired', 'source': row['source'],
                                        'timestamp_ns': time.monotonic_ns(), 'counters': command(['iptables', '-nvxL', CHAIN]).stdout})
                                    command(['iptables', '-D', CHAIN, '-s', row['source'], '-j', 'DROP'], check=False)
                                command(['iptables', '-A', CHAIN, '-s', row['source'], '-j', 'DROP'])
                                ended = time.monotonic_ns()
                                self.blocked_until[row['source']] = ended + int(config['block_ttl'] * 1e9)
                            decision.update(status='blocked', command_end_ns=ended,
                                            feature_to_command_ms=(ended - row['ready_ns']) / 1e6)
                    except Exception as error:
                        decision.update(status='response_failure', error=repr(error))
            self.decisions.append(decision)

    def expiry(self):
        while self.running:
            now = time.monotonic_ns()
            for source, deadline in list(self.blocked_until.items()):
                if now >= deadline:
                    with self.firewall_lock:
                        if self.blocked_until.get(source) != deadline:
                            continue
                        self.rule_events.append({'event': 'expiry', 'source': source, 'timestamp_ns': time.monotonic_ns(),
                            'counters': command(['iptables', '-nvxL', CHAIN]).stdout})
                        command(['iptables', '-D', CHAIN, '-s', source, '-j', 'DROP'], check=False)
                        self.blocked_until.pop(source, None)
            time.sleep(0.01)

    def start(self, config):
        self.stop()
        self.config = config
        self.path = ROOT / config['relative_path']
        self.path.mkdir(parents=True, exist_ok=True)
        self.running = True
        self.cpu_start = cpu()
        self.started = time.monotonic_ns()
        if self.role == 'source':
            threads = [(self.source_loop, (config,))]
        elif self.role == 'broker':
            conf = self.path / 'mosquitto.conf'
            conf.write_text('user root\nlistener 1883 0.0.0.0\nallow_anonymous true\npersistence false\nmax_queued_messages 1000\n', encoding='utf-8')
            self.broker_log = (self.path / 'broker.log').open('w')
            self.broker_process = subprocess.Popen(['mosquitto', '-c', str(conf)], stdout=self.broker_log, stderr=self.broker_log)
            deadline = time.monotonic() + 2
            while True:
                try:
                    s = socket.create_connection(('127.0.0.1', 1883), timeout=0.1)
                    s.close()
                    break
                except OSError:
                    if time.monotonic() > deadline:
                        raise
                    time.sleep(0.02)
            self.subscriber_ready = threading.Event()
            thread = threading.Thread(target=self.subscriber, args=(config,), daemon=True)
            self.threads = [thread]
            thread.start()
            if not self.subscriber_ready.wait(2):
                raise RuntimeError('Subscriber not ready')
            return {'started': True}
        elif self.role == 'edge':
            self.buckets, self.feature_rows, self.decisions, self.blocked_until, self.rule_events = {}, [], [], {}, []
            self.flushed_window, self.late_packets = -1, 0
            self.jobs = queue.Queue()
            self.rss_samples = []
            self.cpu_measure_started = False
            self.cpu_measure_start = cpu()
            self.model = None
            if config.get('model_id'):
                manifest = json.loads((ARTIFACTS / 'models.json').read_text())
                info = next(m for m in manifest['models'] if m['id'] == config['model_id'])
                self.model = self.torch.jit.load(str(ARTIFACTS / info['file'])).eval()
                self.threshold = info['threshold']
                self.means = self.torch.tensor(manifest['means'])
                self.scales = self.torch.tensor(manifest['scales'])
                with self.torch.inference_mode():
                    for _ in range(20):
                        self.model(self.torch.zeros((1, len(FEATURES))))
            r1, r2 = threading.Event(), threading.Event()
            threads = [(self.capture, ('ingress', self.ingress, config, r1)),
                       (self.capture, ('egress', self.egress, config, r2)),
                       (self.windows, (config,)), (self.expiry, ())]
            if self.model is not None:
                threads.append((self.detector, (config,)))
            for function, args in threads:
                t = threading.Thread(target=function, args=args, daemon=True)
                self.threads.append(t)
                t.start()
            if not r1.wait(2) or not r2.wait(2):
                raise RuntimeError('Capture not ready')
            return {'started': True, 'interfaces': [self.ingress, self.egress]}
        else:
            return {'started': True}
        for function, args in threads:
            t = threading.Thread(target=function, args=args, daemon=True)
            self.threads.append(t)
            t.start()
        return {'started': True}

    def dispatch(self, request):
        op = request['op']
        if op == 'ping':
            return {'role': self.role, 'clock_namespace': os.readlink('/proc/self/ns/time'),
                    'clock_offsets': Path('/proc/self/timens_offsets').read_text(),
                    'kernel_boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
        if op == 'start':
            return self.start(request['config'])
        if op == 'configure' and self.role in ['edge', 'controller']:
            peer = CONTROLLER if self.role == 'edge' else '172.30.97.2'
            self.controller.close() if self.role == 'edge' else None
            result = {'netem': netem(peer, request['delay_ms'])}
            if self.role == 'edge':
                for _ in range(2):
                    self.controller.call('policy', score=0.0, threshold=1.0)
                rtts = []
                for _ in range(4):
                    began = time.monotonic_ns()
                    self.controller.call('policy', score=0.0, threshold=1.0)
                    rtts.append((time.monotonic_ns() - began) / 1e6)
                result['rpc_rtt_ms'] = rtts
            return result
        if op == 'outage' and self.role == 'edge':
            interface = interface_to(CONTROLLER)
            command(['tc', 'qdisc', 'replace', 'dev', interface, 'root', 'netem', 'loss', '100%'])
            return {'outage': True}
        if op == 'policy' and self.role == 'controller':
            return {'action': 'block' if request['score'] >= request['threshold'] else 'allow'}
        if op == 'stop':
            if not self.running:
                return {'stopped': True, 'already_stopped': True}
            if self.role == 'edge':
                cpu_end, measurement_end = cpu(), time.monotonic_ns()
                counters = command(['iptables', '-nvxL', CHAIN]).stdout
                self.rule_events.append({'event': 'stop', 'timestamp_ns': time.monotonic_ns(), 'counters': counters})
            else:
                counters = None
            self.stop()
            if self.role == 'edge':
                write(self.path / 'windows.json', self.feature_rows)
                write(self.path / 'decisions.json', self.decisions)
                write(self.path / 'rule-events.json', self.rule_events)
                write(self.path / 'edge-resources.json', {'cpu_seconds': cpu() - self.cpu_start,
                      'active_cpu_seconds': cpu_end - self.cpu_measure_start,
                      'active_wall_seconds': (measurement_end - self.config['start_ns']) / 1e9,
                      'sampled_peak_rss_kb': max((sample['rss_kb'] for sample in self.rss_samples), default=0),
                      'wall_seconds': (time.monotonic_ns() - self.started) / 1e9,
                      'peak_rss_kb': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                      'late_packets': self.late_packets, 'final_counters': counters,
                      'clock_namespace': os.readlink('/proc/self/ns/time')})
            return {'stopped': True}
        raise ValueError(op)


def serve(app, port):
    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            self.request.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            while raw := self.rfile.readline():
                request = json.loads(raw)
                try:
                    payload = app.dispatch(request)
                    reply = {'id': request['id'], **payload}
                except Exception as error:
                    reply = {'id': request['id'], 'rpc_error': repr(error)}
                try:
                    self.wfile.write((json.dumps(reply) + '\n').encode())
                    self.wfile.flush()
                except OSError:
                    break
    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True
    Server(('0.0.0.0', port), Handler).serve_forever()


if __name__ == '__main__':
    role = sys.argv[1]
    app = App(role, int(sys.argv[2]) if role == 'source' else None)
    if role == 'controller':
        threading.Thread(target=serve, args=(app, POLICY_PORT), daemon=True).start()
    print(f'{role} ready', flush=True)
    serve(app, PORT)
