"""Read-only live thermal check using the same Telemetry class as the dashboard.

Run while connected to ESP32_CAM. Optionally wait for that network first.
No firmware, light, motor, Wi-Fi, credentials or application settings are changed.
Output contains allowlisted diagnostics and frame summaries, never raw responses.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import ipaddress
import json
import math
from pathlib import Path
import subprocess
import sys
import time

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from features.telemetry import Telemetry, validate

ROBOT_NETWORK = ipaddress.ip_network('192.168.4.0/24')
FIRMWARE = 'bimbot-nightvision/2'
THERMAL_STATES = frozenset({
    'disabled', 'waiting_for_camera', 'initializing', 'task_unavailable',
    'sensor_unavailable', 'frame_unavailable', 'invalid_frame', 'ready', 'cache_busy',
})


def robot_ip(interface='en0'):
    try:
        result = subprocess.run(['ipconfig', 'getifaddr', interface],
                                capture_output=True, text=True, timeout=3)
        address = ipaddress.ip_address(result.stdout.strip())
        if address in ROBOT_NETWORK and str(address) not in ('192.168.4.0', '192.168.4.255'):
            return str(address)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    return None


def failure(error):
    if isinstance(error, (requests.exceptions.Timeout, TimeoutError)):
        code = 'timeout'
    elif isinstance(error, requests.exceptions.HTTPError):
        code = 'http_error'
    elif isinstance(error, ValueError):
        code = 'invalid_payload'
    elif isinstance(error, (requests.exceptions.RequestException, OSError)):
        code = 'transport_error'
    else:
        code = 'unavailable'
    details = {'error_code': code}
    status = getattr(getattr(error, 'response', None), 'status_code', None)
    if isinstance(status, int) and not isinstance(status, bool) and 100 <= status <= 599:
        details['http_status'] = status
    return details


def fetch_json(url):
    # Compare direct local HTTP with the dashboard's normal requests transport.
    with requests.Session() as session:
        session.trust_env = False
        with session.get(url, timeout=(1, 3), stream=True, allow_redirects=False) as response:
            response.raise_for_status()
            if response.status_code != 200:
                raise ValueError('Expected HTTP 200.')
            body = bytearray()
            for chunk in response.iter_content(chunk_size=4096):
                body.extend(chunk)
                if len(body) > 65536:
                    raise ValueError('Response exceeds the sensor contract.')
            payload = json.loads(body)
            if not isinstance(payload, dict):
                raise ValueError('Expected a JSON object.')
            return payload


def identify(host):
    try:
        data = fetch_json(f'http://{host}/status')
        thermal = data.get('thermal')
        thermal = thermal if isinstance(thermal, dict) else {}
        result = {'host': host, 'matching_identity': data.get('firmware') == FIRMWARE,
                  'camera_ready': data.get('camera_ready') is True,
                  'thermal_enabled': thermal.get('enabled') is True,
                  'thermal_fresh': thermal.get('fresh') is True}
        # Report only known firmware diagnostics, never arbitrary status text.
        if result['matching_identity']:
            state = thermal.get('state')
            if isinstance(state, str) and state in THERMAL_STATES:
                result['thermal_state'] = state
            age = thermal.get('frame_age_ms')
            if (isinstance(age, (int, float)) and not isinstance(age, bool) and age >= 0
                    and (isinstance(age, int) or math.isfinite(age))):
                result['thermal_frame_age_ms'] = age
            sequence = thermal.get('sequence')
            if isinstance(sequence, int) and not isinstance(sequence, bool) and sequence >= 0:
                result['thermal_sequence'] = sequence
        return result
    except Exception as error:
        return {'host': host, 'matching_identity': False, **failure(error)}


def frame_summary(payload):
    if payload.get('fresh') is not True or (
            'simulated' in payload and payload['simulated'] is not False):
        raise ValueError('A real fresh sensor frame is required.')
    value = validate('thermal', payload)
    if 'sequence' not in value or 'frame_age_ms' not in value:
        raise ValueError('Source sequence and acquisition age are required.')
    return {'sequence': value['sequence'], 'age_ms': value['frame_age_ms'],
            'rows': 24, 'columns': 32,
            'min_c': value['min_temp'], 'max_c': value['max_temp']}


def check(host, seconds, interface):
    url = f'http://{host}/thermal'
    # Match the dashboard's direct hardware transport and release it on every exit.
    with requests.Session() as session:
        session.trust_env = False
        telemetry = Telemetry({'thermal': url}, session)
        result = {'phase': 'sensor_not_verified', 'host': host, 'configured': False,
                  'frames': [], 'production': {}}
        own_ip = robot_ip(interface)
        if own_ip in (None, host):
            result['phase'] = 'robot_network_changed'
            return result
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if robot_ip(interface) != own_ip:
                result['phase'] = 'robot_network_changed'
                return result
            try:
                frame = frame_summary(fetch_json(url))
                frames = result['frames']
                if not frames or frame['sequence'] > frames[-1]['sequence']:
                    frames.append(frame)
                    result['frames'] = frames[-2:]
                result.pop('direct_error', None)
            except Exception as error:
                result['direct_error'] = failure(error)
            telemetry.poll('thermal')
            production = telemetry.get('thermal')
            result['production'] = {name: production[name] for name in (
                'connected', 'fresh', 'sequence', 'frame_age_ms', 'min_temp',
                'max_temp', 'simulated', 'error_code', 'http_status') if name in production}
            # A network switch during either read invalidates the comparison.
            if robot_ip(interface) != own_ip:
                result['phase'] = 'robot_network_changed'
                return result
            if len(result['frames']) == 2 and not result.get('direct_error'):
                result['phase'] = 'production_telemetry_not_fresh'
                if production['fresh'] and not production.get('simulated'):
                    result['phase'] = 'verified'
                    return result
            time.sleep(min(2, max(0, deadline - time.monotonic())))
        return result


def save(result, output):
    result['checked_at_utc'] = datetime.now(timezone.utc).isoformat()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix('.tmp')
    temporary.write_text(json.dumps(result, indent=2) + '\n')
    temporary.replace(output)
    print(json.dumps(result), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='192.168.4.2', help='Last-known spare address; identity is checked.')
    parser.add_argument('--interface', default='en0')
    parser.add_argument('--wait-network', type=int, choices=range(0, 301), default=0, metavar='0..300')
    parser.add_argument('--seconds', type=int, choices=range(10, 61), default=30, metavar='10..60')
    parser.add_argument('--output', type=Path, default=ROOT / 'local_data' / 'thermal_check.json')
    args = parser.parse_args()
    try:
        address = ipaddress.ip_address(args.host)
        if address not in ROBOT_NETWORK or address in (
                ROBOT_NETWORK.network_address, ROBOT_NETWORK.broadcast_address,
                ipaddress.ip_address('192.168.4.1')):
            raise ValueError
    except ValueError:
        parser.error('--host must be a spare address in 192.168.4.2–254.')
    print(json.dumps({'phase': 'waiting_for_robot_network', 'configured': False}), flush=True)
    deadline = time.monotonic() + args.wait_network
    own_ip = robot_ip(args.interface)
    while own_ip is None and time.monotonic() < deadline:
        time.sleep(min(1, max(0, deadline - time.monotonic())))
        own_ip = robot_ip(args.interface)
    if own_ip is None:
        save({'phase': 'robot_network_not_observed', 'configured': False}, args.output)
        return 2
    # Discover usual DHCP neighbours, always excluding the Mac and original AP.
    hosts = list(dict.fromkeys([args.host] + [f'192.168.4.{n}' for n in range(2, 11)]))
    hosts = [host for host in hosts if host != own_ip]
    with ThreadPoolExecutor(max_workers=len(hosts)) as pool:
        observations = list(pool.map(identify, hosts))
    if robot_ip(args.interface) != own_ip:
        save({'phase': 'robot_network_changed', 'configured': False,
              'mac_ip': own_ip, 'observations': observations}, args.output)
        return 1
    matching = [item for item in observations if item['matching_identity']]
    if len(matching) != 1:
        save({'phase': 'spare_not_identified' if not matching else 'multiple_spares_found',
              'configured': False, 'mac_ip': own_ip, 'observations': observations}, args.output)
        return 2
    result = check(matching[0]['host'], args.seconds, args.interface)
    result.update(mac_ip=own_ip, observations=observations)
    save(result, args.output)
    return 0 if result['phase'] == 'verified' else 1


if __name__ == '__main__':
    raise SystemExit(main())
