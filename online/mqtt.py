"""Small MQTT 3.1.1 transport for isolated controlled workload episodes."""
import json
import socket
import struct


def text(value):
    value = value.encode() if isinstance(value, str) else value
    return struct.pack('!H', len(value)) + value


def packet(kind, body):
    n, length = len(body), bytearray()
    while True:
        digit = n % 128
        n //= 128
        length.append(digit | (128 if n else 0))
        if not n:
            return bytes([kind]) + bytes(length) + body


def exact(sock, n):
    result = bytearray()
    while len(result) < n:
        part = sock.recv(n - len(result))
        if not part:
            raise ConnectionError('MQTT peer closed')
        result.extend(part)
    return bytes(result)


def receive(sock):
    kind = exact(sock, 1)[0]
    length, multiplier = 0, 1
    for _ in range(4):
        digit = exact(sock, 1)[0]
        length += (digit & 127) * multiplier
        if not digit & 128:
            return kind, exact(sock, length)
        multiplier *= 128
    raise ValueError('Invalid MQTT remaining length')


def connect(host, identifier):
    sock = socket.create_connection((host, 1883), timeout=1)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    sock.sendall(packet(0x10, text('MQTT') + b'\x04\x02\x00\x3c' + text(identifier)))
    kind, body = receive(sock)
    if kind != 0x20 or body != b'\x00\x00':
        sock.close()
        raise RuntimeError(f'MQTT connect rejected: {kind}, {body!r}')
    return sock


def publish(sock, body):
    sock.sendall(packet(0x30, text('utility/readings') + body))


def subscribe(sock):
    sock.sendall(packet(0x82, b'\x00\x01' + text('utility/readings') + b'\x00'))
    kind, _ = receive(sock)
    if kind != 0x90:
        raise RuntimeError('MQTT subscribe rejected')
