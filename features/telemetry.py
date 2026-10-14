"""Validate documented firmware JSON contracts before publishing readings."""
import math
import threading
import time
from copy import deepcopy


def numeric(value, name, low=None, high=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'{name} must be a finite number.')
    if (low is not None and value < low) or (high is not None and value > high):
        raise ValueError(f'{name} is outside its allowed range.')
    return float(value)


def validate(kind, data):
    if not isinstance(data, dict):
        raise ValueError('Telemetry must be a JSON object.')
    if kind == 'thermal':
        grid = data.get('grid')
        if not isinstance(grid, list) or len(grid) != 24 or any(not isinstance(row, list) or len(row) != 32 for row in grid):
            raise ValueError('MLX90640 grid must contain 24 rows of 32 temperatures.')
        grid = [[numeric(v, 'pixel', -40, 300) for v in row] for row in grid]
        return {'grid': grid, 'min_temp': min(map(min, grid)), 'max_temp': max(map(max, grid))}
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
        if frame not in ('local_meters', 'wgs84') or not isinstance(source, str) or not 1 <= len(source) <= 80:
            raise ValueError('Position requires a supported frame and a source.')
        values = {'frame': frame, 'source': source}
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

    def poll(self, kind):
        if not self.urls.get(kind):
            return
        try:
            response = self.http.get(self.urls[kind], timeout=3)
            response.raise_for_status()
            data = response.json()
            value = validate(kind, data)
            value['simulated'] = data.get('simulated') is True
            with self.lock:
                self.readings[kind] = {**value, 'updated_at': time.time()}
                self.errors.pop(kind, None)
        except Exception:
            with self.lock:
                self.errors[kind] = 'Telemetry unavailable or invalid; check firmware and connection.'

    def get(self, kind):
        with self.lock:
            value = deepcopy(self.readings.get(kind, {}))
            error = self.errors.get(kind)
        fresh = bool(value and time.time() - value['updated_at'] < self.ttl and not error)
        return {**value, 'configured': bool(self.urls.get(kind)), 'connected': fresh, 'fresh': fresh,
                'message': error or ('Live telemetry.' if fresh else 'Waiting for fresh telemetry.' if self.urls.get(kind) else 'Hardware endpoint not configured.')}

    def run(self, kind):
        while True:
            self.poll(kind)
            time.sleep(2)

    def start(self):
        for kind, url in self.urls.items():
            if url:
                threading.Thread(target=self.run, args=(kind,), daemon=True).start()
