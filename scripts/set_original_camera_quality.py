"""One reversible JPEG-quality control on the isolated ORIGINAL camera.

No serial, flash, image capture, credential access or persistent config changes.
The dashboard should be stopped before running this operator diagnostic.
"""
import argparse
from datetime import datetime, timezone
from ipaddress import ip_address, ip_network
import json
from pathlib import Path
import subprocess
import time

import requests

BASE = 'http://192.168.4.1'
GEOMETRY = {'framesize': 6, 'pixformat': 4, 'xclk': 20}


class CheckFailed(Exception):
    pass


def on_robot_network():
    try:
        address = subprocess.run(['ipconfig', 'getifaddr', 'en0'],
                                 capture_output=True, text=True, timeout=2)
        own = ip_address(address.stdout.strip())
        route = subprocess.run(['route', '-n', 'get', '192.168.4.1'],
                               capture_output=True, text=True, timeout=2)
        fields = dict(line.strip().split(':', 1) for line in route.stdout.splitlines()
                      if ':' in line)
        flags = fields.get('flags', '').strip('<> ').split(',')
        direct = ('GATEWAY' not in flags and fields.get('destination', '').strip()
                  in ('192.168.4.1', '192.168.4', '192.168.4.0'))
        via_original = fields.get('gateway', '').strip() == '192.168.4.1'
        return (own in ip_network('192.168.4.0/24') and str(own) != '192.168.4.1'
                and fields.get('interface', '').strip() == 'en0'
                and (direct or via_original))
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return False


def set_quality(session, network_check, target=20):
    if type(target) is not int or target not in (10, 20):
        raise CheckFailed('Only quality 10 or 20 is permitted.')
    report = {'target': 'original_camera_192.168.4.1', 'requested_quality': target,
              'control_attempted': False, 'verified': False,
              'checked_at': datetime.now(timezone.utc).isoformat()}

    def get(path, control=False):
        if not network_check():
            raise CheckFailed('Robot subnet/direct route not verified; request blocked.')
        if control:
            report['control_attempted'] = True
        response = session.get(BASE + path, timeout=(2, 4), allow_redirects=False,
                               headers={'Connection': 'close', 'Cache-Control': 'no-cache'})
        return response

    def status():
        with get('/status') as response:
            if response.status_code != 200 or len(response.content) > 8192:
                raise CheckFailed('Status response not accepted.')
            raw = response.json()
            if not isinstance(raw, dict):
                raise CheckFailed('Status must be an object.')
            keys = (*GEOMETRY, 'quality')
            if any(type(raw.get(key)) is not int for key in keys):
                raise CheckFailed('Status settings missing or invalid.')
            values = {key: raw[key] for key in keys}
            if any(values[key] != value for key, value in GEOMETRY.items()):
                raise CheckFailed('Unexpected geometry/format/clock; no further control.')
            if values['quality'] not in (10, 20):
                raise CheckFailed('Unexpected quality; no further control.')
            return values

    try:
        report['before'] = status()
        if report['before']['quality'] != target:
            # Recheck route immediately before the sole mutation. Never retry it
            # blindly: a timeout can mean the device applied the setting already.
            if not network_check():
                raise CheckFailed('Network changed before control; request blocked.')
            try:
                with get(f'/control?var=quality&val={target}', control=True) as response:
                    report['control_http_status'] = response.status_code
                    if response.status_code != 200:
                        raise CheckFailed('Control HTTP response not accepted.')
            except requests.RequestException:
                report['control_response'] = 'transport_error_readback_required'
        report['after'] = status()
        if report['after']['quality'] != target:
            raise CheckFailed('Requested quality not confirmed by readback.')
        report['verified'] = True
    except (CheckFailed, requests.RequestException, ValueError):
        # Do not save exception text, response bodies or device startup strings.
        report['error'] = 'setting_not_verified'
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--quality', type=int, choices=(10, 20), default=20)
    parser.add_argument('--wait-seconds', type=int, default=900)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    if not 0 <= args.wait_seconds <= 1800:
        parser.error('wait-seconds must be between 0 and 1800')
    deadline = time.monotonic() + args.wait_seconds
    print('Waiting for the original camera network; no requests on other networks.', flush=True)
    while not on_robot_network():
        if time.monotonic() >= deadline:
            print('Robot network not observed; no camera setting changed.', flush=True)
            return 2
        time.sleep(2)
    with requests.Session() as session:
        session.trust_env = False
        report = set_quality(session, on_robot_network, args.quality)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report), flush=True)
    return 0 if report['verified'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
