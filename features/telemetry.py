"""Validate documented firmware JSON contracts before publishing readings."""
import math
import threading
import time
from copy import deepcopy

from requests.exceptions import HTTPError, RequestException, Timeout
from .monitoring_profile import PROFILE


THERMAL_MAX_FRAME_AGE_MS = 5000
POSITION_MAX_SAMPLE_AGE_MS = 5000


def numeric(value, name, low=None, high=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'{name} must be a finite number.')
    if (low is not None and value < low) or (high is not None and value > high):
        raise ValueError(f'{name} is outside its allowed range.')
    return float(value)


def validate(kind, data):
    if not isinstance(data, dict):
        raise ValueError('Telemetry must be a JSON object.')
    if kind == 'movement':
        from .movement import validate_trace
        return validate_trace(data)
    if kind == 'thermal':
        metadata = {}
        if 'fresh' in data and data['fresh'] is not True:
            raise ValueError('Thermal sensor must report a fresh frame.')
        if 'frame_age_ms' in data:
            age = numeric(data['frame_age_ms'], 'frame_age_ms', 0)
            if age >= THERMAL_MAX_FRAME_AGE_MS:
                raise ValueError('Thermal frame is stale.')
            metadata['frame_age_ms'] = age
        if 'sequence' in data:
            sequence = data['sequence']
            if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
                raise ValueError('Thermal sequence must be a nonnegative integer.')
            metadata['sequence'] = sequence
        grid = data.get('grid')
        if not isinstance(grid, list) or len(grid) != 24 or any(not isinstance(row, list) or len(row) != 32 for row in grid):
            raise ValueError('MLX90640 grid must contain 24 rows of 32 temperatures.')
        grid = [[numeric(v, 'pixel', -40, 300) for v in row] for row in grid]
        return {'grid': grid, 'min_temp': min(map(min, grid)), 'max_temp': max(map(max, grid)), **metadata}
    if kind == 'sound':
        label = data.get('classification', 'unknown')
        if label not in ('unknown', 'voice_detected', 'tapping_detected', 'ambient'):
            raise ValueError('Unsupported sound classification.')
        return {'db_level': numeric(data.get('db_level'), 'db_level', 0, 160),
                'classification': label, 'confidence': numeric(data.get('confidence', 0), 'confidence', 0, 1)}
    if kind == 'position':
        # A robot observation position, never a YOLO-derived survivor coordinate.
        frame = data.get('frame')
        source = data.get('source')
        if frame not in ('local_meters', 'wgs84') or not isinstance(source, str) or not 1 <= len(source.strip()) <= 80:
            raise ValueError('Position requires a supported frame and a source.')
        values = {'frame': frame, 'source': source.strip()}
        if frame == 'wgs84':
            if not isinstance(data.get('fix_valid'), bool):
                raise ValueError('Global position requires an explicit fix_valid boolean.')
            values['fix_valid'] = data['fix_valid']
            if 'satellites' in data:
                satellites = data['satellites']
                if isinstance(satellites, bool) or not isinstance(satellites, int) or not 0 <= satellites <= 255:
                    raise ValueError('Satellite count must be a nonnegative integer.')
                values['satellites'] = satellites
            if not data['fix_valid']:
                # A healthy receiver without a fix must erase earlier coordinates.
                return values
            if 'horizontal_accuracy_m' in data:
                values['horizontal_accuracy_m'] = numeric(data['horizontal_accuracy_m'], 'horizontal_accuracy_m', 0)
        if frame == 'wgs84' or 'sample_age_ms' in data or 'sequence' in data:
            age = numeric(data.get('sample_age_ms'), 'sample_age_ms', 0)
            sequence = data.get('sequence')
            if age >= POSITION_MAX_SAMPLE_AGE_MS:
                raise ValueError('Position sample is stale.')
            if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
                raise ValueError('Position sequence must be a nonnegative integer.')
            values.update(sample_age_ms=age, sequence=sequence)
        if frame == 'local_meters':
            values.update(x=numeric(data.get('x'), 'x'), y=numeric(data.get('y'), 'y'))
        else:
            values.update(latitude=numeric(data.get('latitude'), 'latitude', -90, 90),
                          longitude=numeric(data.get('longitude'), 'longitude', -180, 180))
        return values
    if kind == 'robot':
        state = data.get('state')
        if state not in ('idle', 'searching', 'stopped', 'completed', 'fault'):
            raise ValueError('Unsupported robot state.')
        return {'state': state, 'navigation_ready': data.get('navigation_ready') is True,
                'mission_id': data.get('mission_id')}
    raise ValueError('Unknown telemetry kind.')


class Telemetry:
    def __init__(self, urls, http, ttl=10):
        self.urls, self.http, self.ttl = urls, http, ttl
        self.lock = threading.Lock()
        self.readings = {}
        self.errors = {}
        self.diagnostics = {}
        self.revisions = {}

    def set_url(self, kind, url):
        """Reject an old address's in-flight reply after DHCP rediscovery."""
        with self.lock:
            if self.urls.get(kind) == url:
                return False
            self.urls[kind] = url
            self.revisions[kind] = self.revisions.get(kind, 0) + 1
            for cache in (self.readings, self.errors, self.diagnostics):
                cache.pop(kind, None)
        return True

    def poll(self, kind):
        with self.lock:
            url, revision = self.urls.get(kind), self.revisions.get(kind, 0)
        if not url:
            return
        response = None
        try:
            transport_started = time.monotonic() if kind in ('thermal', 'position', 'movement') else None
            response = self.http.get(url, timeout=3)
            received_at = time.time()
            transport_ms = ((time.monotonic() - transport_started) * 1000
                            if transport_started is not None else None)
            response.raise_for_status()
            data = response.json()
            value = validate(kind, data)
            value['simulated'] = data.get('simulated') is True
            sample_age = value.get('sample_age_ms', 0) if kind in ('position', 'movement') else value.get('frame_age_ms', 0)
            updated_at = received_at - sample_age / 1000
            if kind in ('thermal', 'position', 'movement'):
                if not math.isfinite(transport_ms) or transport_ms < 0:
                    raise ValueError('Invalid telemetry transport duration.')
                value['transport_ms'] = transport_ms
                if 'frame_age_ms' in value or 'sample_age_ms' in value:
                    # The firmware measures age before sending the body. Count
                    # the full request conservatively; monotonic duration also
                    # survives a wall-clock adjustment during that request.
                    updated_at -= transport_ms / 1000
            with self.lock:
                if revision != self.revisions.get(kind, 0):
                    return
                previous = self.readings.get(kind, {})
                timed_sample = ((kind == 'thermal' and 'frame_age_ms' in value) or
                                (kind in ('position', 'movement') and 'sample_age_ms' in value and
                                 previous.get('source') == value.get('source') and
                                 previous.get('frame') == value.get('frame') and
                                 previous.get('trace_id') == value.get('trace_id')))
                if (timed_sample and 'sequence' in value
                        and previous.get('sequence') == value['sequence']
                        and isinstance(previous.get('updated_at'), (int, float))
                        and math.isfinite(previous['updated_at'])):
                    # A repeated frame cannot become younger because a later
                    # HTTP exchange had a different delay.
                    updated_at = min(updated_at, previous['updated_at'])
                self.readings[kind] = {**value, 'updated_at': updated_at}
                self.errors.pop(kind, None)
                self.diagnostics.pop(kind, None)
        except Exception as error:
            # Exception messages can contain credentials, URLs or response bodies.
            # Publish only a fixed category and a validated numeric HTTP status.
            if isinstance(error, (Timeout, TimeoutError)):
                code = 'timeout'
            elif isinstance(error, HTTPError):
                code = 'http_error'
                if response is None:
                    response = error.response
            elif isinstance(error, ValueError):
                code = 'invalid_payload'
            elif isinstance(error, (RequestException, OSError)):
                code = 'transport_error'
            else:
                code = 'unavailable'
            details = {'error_code': code}
            status = getattr(response, 'status_code', None)
            if isinstance(status, int) and not isinstance(status, bool) and 100 <= status <= 599:
                details['http_status'] = status
            with self.lock:
                if revision != self.revisions.get(kind, 0):
                    return
                self.errors[kind] = 'Telemetry unavailable or invalid; check firmware and connection.'
                self.diagnostics[kind] = details

    def get(self, kind):
        with self.lock:
            value = deepcopy(self.readings.get(kind, {}))
            error = self.errors.get(kind)
            details = self.diagnostics.get(kind, {}).copy()
        ttl = self.ttl
        if kind == 'thermal' and 'frame_age_ms' in value:
            ttl = min(ttl, THERMAL_MAX_FRAME_AGE_MS / 1000)
        if kind in ('position', 'movement') and 'sample_age_ms' in value:
            ttl = min(ttl, POSITION_MAX_SAMPLE_AGE_MS / 1000)
        # A brief transport failure does not make a still-recent, validated
        # acquisition disappear. Its original expiry is never extended.
        retrying = bool(error and kind == 'thermal' and
                        details.get('error_code') in ('timeout', 'transport_error'))
        connected = bool(value and 0 <= time.time() - value['updated_at'] < ttl and (not error or retrying))
        no_fix = kind == 'position' and value.get('fix_valid') is False
        fresh = connected and not no_fix
        return {**value, **details, 'configured': bool(self.urls.get(kind)), 'connected': connected, 'fresh': fresh,
                'retrying': retrying,
                'message': 'Retrying thermal connection; showing the last recent sensor frame.' if retrying and fresh else error or ('Receiver connected; waiting for a valid GPS fix.' if connected and no_fix else
                                    'Live telemetry.' if fresh else 'Waiting for fresh telemetry.' if self.urls.get(kind) else 'Hardware endpoint not configured.')}

    def run(self, kind):
        # Limit Wi-Fi grid reads independently of firmware acquisition. There
        # is one request at a time and no catch-up burst after a slow exchange.
        interval = 0.1 if kind == 'thermal' else .5 if kind == 'movement' else 2
        while True:
            started = time.monotonic()
            self.poll(kind)
            pause = max(interval, PROFILE['thermal_poll_seconds'] - (time.monotonic() - started)) if kind == 'thermal' else interval
            time.sleep(pause)

    def start(self):
        for kind, url in self.urls.items():
            if url:
                threading.Thread(target=self.run, args=(kind,), daemon=True).start()
