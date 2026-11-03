"""Internal, operator-triggered snapshots; no camera/device activation."""
from datetime import datetime, timezone
from ipaddress import ip_address, ip_network
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import threading
from .monitoring_profile import PROFILE


def robot_network():
    try:
        result = subprocess.run(['ipconfig', 'getifaddr', 'en0'], capture_output=True,
                                text=True, timeout=1)
        address = ip_address(result.stdout.strip())
        return {'ipv4': str(address) if address.version == 4 else None,
                'robot_subnet': address.version == 4 and address in ip_network('192.168.4.0/24')}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {'ipv4': None, 'robot_subnet': False}


def collect_check(cameras, sensor, sensor_health, thermal):
    now = time.time()
    camera_fields = ('connected', 'configured', 'updated_at', 'detected_at', 'received_fps',
                     'inference_ms', 'video_processing_ms', 'skipped_video_frames', 'analysis_error',
                     'source_errors', 'last_source_error_at', 'last_source_error_stage',
                     'last_source_error_code', 'received_bytes', 'received_chunks', 'received_frames',
                     'last_byte_at', 'last_frame_bytes', 'invalid_frames', 'last_invalid_frame_at')
    states = {}
    for name, camera in cameras.items():
        with camera.condition:
            status = camera.status()
            states[name] = {key: status.get(key) for key in camera_fields}
            states[name].update(viewers=camera.clients, generation=camera.generation,
                                detections_available=status.get('detections_available', False))
    sensor_age = now - sensor['updated_at'] if sensor.get('updated_at') else None
    report = {
        'monitoring_profile': dict(PROFILE),
        'checked_at': datetime.now(timezone.utc).isoformat(), 'network': robot_network(),
        'cameras': states,
        'sensor': {**{key: sensor.get(key) for key in ('temperature', 'humidity', 'updated_at')},
                   **sensor_health,
                   'fresh': sensor_age is not None and 0 <= sensor_age < 10 and sensor_health.get('error_code') in (None, 'timeout', 'transport_error'),
                   'retrying': sensor_health.get('error_code') in ('timeout', 'transport_error')},
        'thermal': {key: thermal.get(key) for key in ('configured', 'connected', 'fresh', 'sequence',
                   'frame_age_ms', 'transport_ms', 'updated_at', 'min_temp', 'max_temp', 'error_code', 'http_status')},
        'note': 'Current cached state only. No camera, microphone, motor or firmware action. No images, identities or credentials saved.',
    }
    return report


def write_report(root, filename, report):
    folder = Path(root) / 'diagnostics'
    folder.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=folder, suffix='.tmp', delete=False) as output:
            temporary = Path(output.name)
            json.dump(report, output, indent=2, allow_nan=False)
            output.write('\n')
        os.replace(temporary, folder / filename)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def save_check(root, cameras, sensor, sensor_health, thermal):
    report = collect_check(cameras, sensor, sensor_health, thermal)
    write_report(root, 'latest_system_check.json', report)
    return report


class DashboardCheck:
    """Bounded cached-state recording while the normal dashboard stays visible."""
    def __init__(self, root, snapshot, duration=60):
        self.root, self.snapshot, self.duration = root, snapshot, duration
        self.lock = threading.Lock()
        self.state = {'running': False, 'saved': False, 'samples': 0}
        self.thread = None

    def status(self):
        with self.lock:
            return dict(self.state)

    def start(self):
        with self.lock:
            if self.state['running']:
                return False
            self.state = {'running': True, 'saved': False, 'samples': 0,
                          'duration_seconds': self.duration,
                          'started_at': datetime.now(timezone.utc).isoformat()}
            self.thread = threading.Thread(target=self._record, daemon=True)
            self.thread.start()
        return True

    def _record(self):
        began = time.monotonic()
        records = []
        try:
            while True:
                records.append(self.snapshot())
                with self.lock:
                    self.state['samples'] = len(records)
                # Retain partial evidence if the operator returns early or the
                # application is interrupted during the reproduction.
                write_report(self.root, 'normal_dashboard_check.json', {
                    'running': True, 'started_at': records[0]['checked_at'],
                    'duration_seconds': time.monotonic()-began, 'samples': records,
                    'scope': 'Partial cached-state recording; no images, identities or credentials.'})
                remaining = self.duration - (time.monotonic() - began)
                if remaining <= 0:
                    break
                time.sleep(min(1, remaining))
            summary = {}
            relevant = [row for row in records if row.get('network', {}).get('robot_subnet') is True]
            summary['robot_subnet_samples'] = len(relevant)
            summary['other_or_unknown_network_samples'] = len(records)-len(relevant)
            for name in ('main', 'nightvision'):
                active = [row['cameras'][name] for row in relevant if row['cameras'][name].get('viewers', 0)]
                counts = [row['cameras'][name].get('source_errors', 0) for row in relevant] or [0]
                invalid = [row['cameras'][name].get('invalid_frames', 0) for row in relevant] or [0]
                summary[name] = {'active_samples': len(active),
                                 'fresh_active_samples': sum(row.get('connected', False) for row in active),
                                 'source_errors_during_check': max(counts) - min(counts),
                                 'invalid_frames_during_check': max(invalid)-min(invalid)}
            summary['dht_fresh_samples'] = sum(row['sensor']['fresh'] for row in relevant)
            summary['thermal_fresh_samples'] = sum(row['thermal'].get('fresh') is True for row in relevant)
            report = {'running': False, 'started_at': records[0]['checked_at'], 'duration_seconds': time.monotonic()-began,
                      'summary': summary, 'samples': records,
                      'scope': 'Cached normal-dashboard connection history; no device activation, images, identities or credentials. Freshness and FPS are laptop reception metrics, not optical latency.'}
            write_report(self.root, 'normal_dashboard_check.json', report)
            with self.lock:
                self.state.update(running=False, saved=True, summary=summary)
        except Exception:
            with self.lock:
                self.state.update(running=False, saved=False, error='Diagnostic recording failed.')
