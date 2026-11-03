"""Bounded, identity-checked control of the spare camera's white LED.

Control uses the firmware's separate port 80 server, so an open MJPEG request
on port 81 cannot occupy the HTTP task handling the light lease. No connection
is made at import time, and no control request is sent to the original camera.
"""
from ipaddress import ip_address, IPv4Address
import json
from urllib.parse import urlsplit

from flask import jsonify, request
import requests


FIRMWARE_ID = 'bimbot-nightvision/2'
LEASE_MS = 15000
WHITE_LED_BRIGHTNESS = 32
MAX_STATUS_BYTES = 4096


class IlluminationError(Exception):
    def __init__(self, code, message, status):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


class NightVisionIllumination:
    def __init__(self, camera_url, original_url, session_factory=None):
        self.camera_url, self.original_url = camera_url, original_url
        self.session_factory = session_factory or requests.Session

    def _target(self):
        if not self.camera_url:
            raise IlluminationError('not_configured', 'Spare camera is not configured.', 503)
        try:
            spare = urlsplit(self.camera_url)
            original = urlsplit(self.original_url)
            address = ip_address(spare.hostname or '')
            # Literal private IPv4 addresses avoid DNS aliases or rebinding to
            # the original board. Stream addresses are trusted server settings,
            # never accepted from a browser request.
            if (spare.scheme != 'http' or not isinstance(address, IPv4Address)
                    or not address.is_private or address.is_loopback
                    or address.is_link_local or address.is_unspecified
                    or address.is_multicast or address.is_reserved
                    or spare.port != 81 or spare.path != '/stream'
                    or spare.username is not None or spare.password is not None
                    or spare.query or spare.fragment
                    or original.hostname is None):
                raise ValueError('Unsafe camera setting')
            original_host = original.hostname.lower().rstrip('.')
            if original_host == spare.hostname.lower().rstrip('.'):
                raise ValueError('Original camera target')
            try:
                original_address = ip_address(original_host)
            except ValueError:
                original_address = None
            if original_address == address:
                raise ValueError('Original camera target')
            return f'http://{address}:80'
        except (TypeError, ValueError):
            raise IlluminationError(
                'invalid_target',
                'Light control requires a separate spare camera at a private IPv4 stream address on port 81.', 409)

    @staticmethod
    def _verified_status(payload):
        if (not isinstance(payload, dict) or payload.get('firmware') != FIRMWARE_ID
                or not isinstance(payload.get('capabilities'), list)
                or 'white_led' not in payload['capabilities']):
            raise IlluminationError(
                'unsupported_firmware',
                'Spare camera needs the updated white-light firmware. Video can still be used.', 409)
        light = payload.get('illumination')
        if (not isinstance(light, dict) or type(light.get('enabled')) is not bool
                or type(light.get('brightness')) is not int
                or light['brightness'] not in (0, WHITE_LED_BRIGHTNESS)
                or type(light.get('lease_ms')) is not int
                or light['lease_ms'] != LEASE_MS
                or light['enabled'] != (light['brightness'] > 0)):
            raise IlluminationError('invalid_response', 'Camera returned an invalid light status.', 502)
        return {key: light[key] for key in ('enabled', 'brightness', 'lease_ms')}

    def _read(self, session, method, url, **kwargs):
        with session.request(method, url, timeout=(1, 2), allow_redirects=False,
                             stream=True, **kwargs) as response:
            if response.status_code in (301, 302, 303, 307, 308, 404, 405):
                raise IlluminationError(
                    'unsupported_firmware',
                    'Spare camera needs the updated white-light firmware. Video can still be used.', 409)
            if response.status_code != 200:
                raise IlluminationError('unreachable', 'Spare camera light control is unavailable. Check its power and Wi-Fi.', 503)
            if response.headers.get('Content-Type', '').split(';')[0].strip().lower() != 'application/json':
                raise IlluminationError('invalid_response', 'Camera returned an invalid light status.', 502)
            body = bytearray()
            for chunk in response.iter_content(chunk_size=1024):
                body.extend(chunk)
                if len(body) > MAX_STATUS_BYTES:
                    raise IlluminationError('invalid_response', 'Camera returned an invalid light status.', 502)
            # Parse the bounded body ourselves: response.json() would read the
            # entire response and remove the upper limit above.
            return self._verified_status(json.loads(body.decode('utf-8')))

    def _perform(self, enabled=None):
        try:
            target = self._target()
            with self.session_factory() as session:
                # Do not send robot-network traffic through environment proxies
                # or load ambient .netrc credentials.
                session.trust_env = False
                light = self._read(session, 'GET', target + '/status')
                if enabled is not None:
                    light = self._read(session, 'POST', target + '/light',
                                       params={'enabled': '1' if enabled else '0'})
                    if light['enabled'] is not enabled:
                        raise IlluminationError('command_not_applied', 'Camera did not confirm the requested light setting.', 502)
            return {'supported': True, 'available': True, 'firmware': FIRMWARE_ID,
                    'illumination': light,
                    'message': 'White camera light on.' if light['enabled'] else 'White camera light off.'}, 200
        except IlluminationError as error:
            return {'supported': False, 'available': False, 'illumination': None,
                    'code': error.code, 'error': error.message, 'message': error.message}, error.status
        except requests.RequestException:
            message = 'Spare camera light control is unavailable. Check its power and Wi-Fi.'
            return {'supported': False, 'available': False, 'illumination': None,
                    'code': 'unreachable', 'error': message, 'message': message}, 503
        except (UnicodeError, ValueError, TypeError):
            message = 'Camera returned an invalid light status.'
            return {'supported': False, 'available': False, 'illumination': None,
                    'code': 'invalid_response', 'error': message, 'message': message}, 502

    def status(self):
        return self._perform()

    def set_enabled(self, enabled):
        if type(enabled) is not bool:
            raise ValueError('enabled must be a boolean')
        return self._perform(enabled)

    def register(self, app, require_auth):
        @app.route('/api/nightvision/light', methods=['GET', 'POST'])
        @require_auth
        def nightvision_light():
            if request.method == 'POST':
                data = request.get_json(silent=True)
                if (not isinstance(data, dict) or set(data) != {'enabled'}
                        or type(data['enabled']) is not bool):
                    return jsonify({'error': 'Provide enabled as a JSON boolean.'}), 400
                payload, status = self.set_enabled(data['enabled'])
            else:
                payload, status = self.status()
            response = jsonify(payload)
            response.headers['Cache-Control'] = 'no-store'
            return response, status
