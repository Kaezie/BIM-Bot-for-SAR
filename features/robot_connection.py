"""Resolve the configured spare's DHCP address on the robot subnet only.

Only bounded GET /status requests are made. No stream, light or motor starts.
The original AP and this computer are excluded. Custom/disabled endpoints stay
under their explicit configuration; discovered addresses are runtime state.
"""
from concurrent.futures import ThreadPoolExecutor
from ipaddress import ip_address, ip_network
import json
import re
import threading
import time
from urllib.parse import urlsplit

import requests

from .system_diagnostics import robot_network


NETWORK = ip_network('192.168.4.0/24')
FIRMWARE = 'bimbot-nightvision/2'


def endpoint_host(url, port, path):
    try:
        value = urlsplit(url or '')
        address = ip_address(value.hostname or '')
        if (value.scheme == 'http' and address in NETWORK and 2 <= int(str(address).rsplit('.', 1)[1]) <= 254
                and (value.port or 80) == port and value.path == path
                and value.username is None and value.password is None and not value.query and not value.fragment):
            return str(address)
    except (ValueError, TypeError):
        pass
    return None


class SpareDiscovery:
    def __init__(self, camera_url, thermal_url, apply, network=robot_network,
                 session_factory=requests.Session):
        self.camera_host = endpoint_host(camera_url, 81, '/stream')
        self.thermal_host = endpoint_host(thermal_url, 80, '/thermal')
        self.apply, self.network, self.session_factory = apply, network, session_factory
        self.host = self.camera_host or self.thermal_host
        self.verified_own = None
        self.failed_checks = 0
        self.lock = threading.Lock()
        self.identity_profiles = {}
        self.state = {'enabled': bool(self.host), 'state': 'waiting_network' if self.host else 'disabled'}

    def status(self):
        with self.lock:
            return dict(self.state)

    def _state(self, state, **values):
        with self.lock:
            self.state.update(state=state, checked_at=time.time(), **values)

    def _identify(self, host):
        try:
            with self.session_factory() as session:
                session.trust_env = False
                with session.get(f'http://{host}/status', timeout=(.6, 1),
                                 stream=True, allow_redirects=False) as response:
                    if response.status_code != 200:
                        return False
                    body = bytearray()
                    for chunk in response.iter_content(chunk_size=1024):
                        body.extend(chunk)
                        if len(body) > 4096:
                            return False
                    value = json.loads(body)
                    if not isinstance(value, dict) or value.get('firmware') != FIRMWARE:
                        return False
                    # Retain only public firmware settings from the existing
                    # identity request. Diagnostics then capture the installed
                    # profile whenever the operator connects, without a timed
                    # observer or a second video stream.
                    profile = {'firmware': FIRMWARE, 'checked_at': time.time()}
                    for key, pattern in (('startup_profile', r'retry/[0-9]{1,3}'),
                                         ('stream_profile', r'fresh/[0-9]{1,3}')):
                        item = value.get(key)
                        if isinstance(item, str) and re.fullmatch(pattern, item):
                            profile[key] = item
                    fps = value.get('stream_target_fps')
                    if type(fps) is int and 1 <= fps <= 120:
                        profile['stream_target_fps'] = fps
                    if type(value.get('camera_ready')) is bool:
                        profile['camera_ready'] = value['camera_ready']
                    with self.lock:
                        self.identity_profiles[host] = profile
                    return True
        except (requests.RequestException, ValueError, TypeError, OSError):
            return False

    def check(self):
        if not self.host:
            return
        network = self.network()
        own = network.get('ipv4')
        try:
            on_robot = network.get('robot_subnet') is True and ip_address(own) in NETWORK
        except (ValueError, TypeError):
            on_robot = False
        if not on_robot:
            self._state('waiting_network', mac_ip=own)
            return
        # A known, still-identified address needs no neighbourhood search.
        self._state('checking', mac_ip=own)
        matched = self.host != own and self._identify(self.host)
        if matched:
            matching = [self.host]
        else:
            self.failed_checks += 1
            if self.host != own and self.verified_own == own and self.failed_checks < 3:
                # Do not turn a brief shared radio outage into repeated ARP/
                # status searches across the AP. Retry the verified host first.
                self._state('retrying_known', mac_ip=own)
                return
            hosts = [f'192.168.4.{n}' for n in range(2, 11) if f'192.168.4.{n}' not in (own, self.host)]
            self._state('searching', mac_ip=own)
            with ThreadPoolExecutor(max_workers=2) as pool:
                matching = [host for host, found in zip(hosts, pool.map(self._identify, hosts)) if found]
        if self.network() != network:
            self._state('network_changed', mac_ip=own)
            return
        if len(matching) != 1:
            self._state('not_found' if not matching else 'ambiguous', mac_ip=own)
            return
        host = matching[0]
        self.apply(host, bool(self.camera_host), bool(self.thermal_host))
        self.host = host
        self.verified_own, self.failed_checks = own, 0
        with self.lock:
            profile = dict(self.identity_profiles.get(host, {}))
        self._state('verified', mac_ip=own, spare_ip=host, firmware_profile=profile)

    def run(self):
        while True:
            try:
                self.check()
            except Exception:
                self._state('unavailable')
            time.sleep(5 if self.status()['state'] == 'waiting_network' else 20)

    def start(self):
        if self.host:
            threading.Thread(target=self.run, daemon=True).start()
