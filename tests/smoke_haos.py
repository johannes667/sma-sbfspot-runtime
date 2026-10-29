"""Container integration test with simulated inverter and local MQTT test broker.

Run only in a disposable add-on container; replaces its SBFspot executable.
See tests/README.md. No real Bluetooth hardware or external broker required.
"""
import json
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import os
if os.environ.get('RUN_HAOS_SMOKE_TEST') != '1':
    raise SystemExit('Use a disposable container with RUN_HAOS_SMOKE_TEST=1; see tests/README.md')
messages = []
connections = []
listener = socket.socket()
listener.bind(('127.0.0.1', 18883))
listener.listen()
def broker():
    conn, _ = listener.accept()
    connections.append(conn)
    with conn:
        def read(n):
            result = b''
            while len(result) < n:
                part = conn.recv(n-len(result))
                if not part:
                    raise EOFError
                result += part
            return result
        try:
            while True:
                header = read(1)[0]
                size, multiplier = 0, 1
                while True:
                    value = read(1)[0]
                    size += (value & 127) * multiplier
                    multiplier *= 128
                    if not value & 128:
                        break
                packet = read(size)
                kind = header >> 4
                if kind == 1:
                    conn.sendall(b'\x20\x02\x00\x00')
                elif kind == 8:
                    conn.sendall(b'\x90\x03' + packet[:2] + b'\x01')
                elif kind == 3:
                    length = int.from_bytes(packet[:2], 'big')
                    topic = packet[2:2+length].decode()
                    offset = 2+length
                    qos = (header >> 1) & 3
                    if qos:
                        packet_id = packet[offset:offset+2]
                        offset += 2
                    messages.append((topic, packet[offset:].decode()))
                    if qos == 1:
                        conn.sendall(b'\x40\x02' + packet_id)
                elif kind == 12:
                    conn.sendall(b'\xd0\x00')
                elif kind == 14:
                    break
        except EOFError:
            pass
Path('/data').mkdir(exist_ok=True)
Path('/data/options.json').write_text(json.dumps({
    'inverter_bluetooth_address': '00:80:25:01:02:03',
    'local_bluetooth_address': '', 'inverter_password': '0000',
    'timezone': 'Europe/Berlin', 'poll_seconds': 10,
    'mqtt_host': '127.0.0.1', 'mqtt_port': 18883, 'mqtt_tls': False,
    'mqtt_username': '', 'mqtt_password': '', 'mqtt_base_topic': 'sma/sbfspot',
    'discovery': True, 'discovery_prefix': 'homeassistant',
    'device_id': 'sma_sbfspot_amann', 'device_name': 'SMA Test',
    'retry_seconds': 1, 'stale_after_seconds': 30, 'log_level': 'debug',
    'source': 'webbox', 'webbox_diagnostics': True, 'webbox_host': 'invalid/host'}))
Path('/usr/local/bin/SBFspot').write_text('''#!/usr/bin/python3
from pathlib import Path
import sys
import time
p = Path('/tmp/runs')
n = int(p.read_text())+1 if p.exists() else 1
p.write_text(str(n))
if n == 1:
    time.sleep(1.5)
if n == 2 or Path('/tmp/fail').exists():
    print('bthConnect() returned -1')
    print('INFO: Done.')
    sys.exit(1)
print('SPOT_PACTOT: %s (W)' % (100 if n < 4 else 101))
if n < 4:
    print('SPOT_PAC1: 100 (W)')
else:
    print('getSpotGridFrequency returned an error: -1')
print('BT Signal=78.5%')
print('INFO: Done.')
sys.exit(0 if n < 4 else 1)
''')
threading.Thread(target=broker, daemon=True).start()
proc = subprocess.Popen([sys.executable, '-I', '-u', '-B', '/app/bridge.py'])
def await_condition(condition, timeout):
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        if condition():
            return
        assert proc.poll() is None, 'Bridge stopped unexpectedly'
        time.sleep(.2)
    raise AssertionError('Timeout; messages: ' + repr(messages))

try:
    await_condition(lambda: ('sma/sbfspot/power_w', '101') in messages, 35)
    assert int(Path('/tmp/runs').read_text()) == 4
    discovery = dict(messages)['homeassistant/sensor/sma_sbfspot_amann/power_w/config']
    assert json.loads(discovery)['unique_id'] == 'sma_sbfspot_amann_power_w'
    assert json.loads(discovery)['device']['identifiers'] == ['sma_sbfspot_amann']
    assert Path('/data/SBFspot.cfg').stat().st_mode & 0o777 == 0o600
    states = [v for t, v in messages if t == 'sma/sbfspot/power_w']
    assert states == ['100', '101'], states
    availability = [v for t, v in messages if t == 'sma/sbfspot/availability']
    assert availability == ['offline', 'online'], availability
    # Home Assistant birth must refresh MQTT without another Bluetooth query.
    topic = b'homeassistant/status'
    body = len(topic).to_bytes(2, 'big') + topic + b'online'
    connections[0].sendall(b'\x30' + bytes([len(body)]) + body)
    await_condition(lambda: sum(t == 'sma/sbfspot/power_w' for t, _ in messages) == 3, 5)
    assert int(Path('/tmp/runs').read_text()) == 4, 'HA birth triggered a Bluetooth query'
    availability = [v for t, v in messages if t == 'sma/sbfspot/availability']
    assert availability == ['offline', 'online', 'online'], availability
    # Missing phase expires on its own. Then complete outage expires power too.
    Path('/tmp/fail').touch()
    await_condition(lambda: messages and ('sma/sbfspot/status', 'stale') in messages, 35)
    phase = [v for t, v in messages if t == 'sma/sbfspot/pac1_w/availability']
    assert phase[-1] == 'offline', phase
    assert [v for t, v in messages if t == 'sma/sbfspot/pac1_w'] == ['100', '100']
    assert [v for t, v in messages if t == 'sma/sbfspot/power_w'] == ['100', '101', '101']
    assert [v for t, v in messages if t == 'sma/sbfspot/availability'][-1] == 'offline'
finally:
    proc.terminate()
    proc.wait(timeout=15)
assert proc.returncode == 0, proc.returncode
print('PASS: transient failure, immediate retry, no false zero/offline, partial exit, HA birth without query, independent expiry, graceful stop')
