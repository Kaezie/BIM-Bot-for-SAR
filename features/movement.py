"""Recorded motor commands, never GPS or measured displacement.

The bridge is opt-in. It must implement a short controller lease, matching
command acknowledgements and verified motion interlocks before enabling return.
"""
import math
import time
from uuid import uuid4
from .missions import MissionError


def integer(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f'Invalid {name}.')
    return value


def identifier(value, name, optional=False):
    if optional and value is None:
        return None
    if not isinstance(value, str) or not 1 <= len(value) <= 80 or not all(c.isascii() and (c.isalnum() or c in '_-.') for c in value):
        raise ValueError(f'Invalid {name}.')
    return value


def validate_trace(data):
    state = data.get('state')
    if state not in ('idle', 'recording', 'stopped', 'returning', 'replay_complete', 'cancelled', 'fault'):
        raise ValueError('Unsupported movement state.')
    age = data.get('sample_age_ms')
    if isinstance(age, bool) or not isinstance(age, (int, float)) or not math.isfinite(age) or not 0 <= age < 5000:
        raise ValueError('Movement sample is invalid or stale.')
    segments = data.get('segments')
    if not isinstance(segments, list) or len(segments) > 80:
        raise ValueError('Movement trace exceeds Uno trace capacity.')
    moves = []
    for item in segments:
        if not isinstance(item, dict) or item.get('direction') not in ('F', 'B', 'L', 'R'):
            raise ValueError('Invalid movement segment.')
        moves.append({'direction': item['direction'], 'duration_ms': integer(item.get('duration_ms'), 'duration', 1, 60000)})
    total = sum(item['duration_ms'] for item in moves)
    if total > 600000:
        raise ValueError('Movement trace exceeds ten minutes.')
    current = data.get('current_move', 'S')
    if current not in ('F', 'B', 'L', 'R', 'S'):
        raise ValueError('Invalid current movement.')
    for key in ('trace_complete', 'return_ready'):
        if not isinstance(data.get(key), bool):
            raise ValueError(f'{key} must be explicit.')
    complete = data['trace_complete']
    return {
        'trace_id': identifier(data.get('trace_id'), 'trace_id'),
        'source': identifier(data.get('source'), 'source'),
        'command_id': identifier(data.get('command_id'), 'command_id', optional=True),
        'sequence': integer(data.get('sequence'), 'sequence', 0, 2**53-1),
        'sample_age_ms': age, 'state': state, 'segments': moves,
        'total_duration_ms': total, 'current_move': current,
        'active_duration_ms': integer(data.get('active_duration_ms', 0), 'active duration', 0, 60000),
        'returned_steps': integer(data.get('returned_steps', 0), 'returned steps', 0, len(moves)),
        'trace_complete': complete,
        'return_ready': bool(data['return_ready'] and complete and moves and current == 'S' and state == 'stopped'),
        'position_measured': False,
        **({'storage_available':data['storage_available']} if isinstance(data.get('storage_available'),bool) else {}),
    }


class MovementControl:
    def __init__(self, missions, telemetry, http, command_url='', command_key=''):
        self.missions, self.telemetry, self.http = missions, telemetry, http
        self.command_url, self.command_key = command_url, command_key
        self.lock, self.database = missions.lock, missions.database
        with self.database() as db:
            db.execute('CREATE TABLE IF NOT EXISTS movement_returns (id TEXT PRIMARY KEY, owner TEXT NOT NULL, trace_id TEXT NOT NULL, state TEXT NOT NULL, started_at REAL NOT NULL)')
            db.execute("UPDATE movement_returns SET state='command_uncertain' WHERE state='returning'")

    def active(self):
        with self.database() as db:
            db.row_factory = __import__('sqlite3').Row
            row = db.execute("SELECT * FROM movement_returns WHERE state IN ('returning','command_uncertain') ORDER BY started_at DESC LIMIT 1").fetchone()
        return dict(row) if row else None

    @property
    def busy(self):
        return bool(self.active())

    def status(self, owner):
        with self.lock:
            trace = self.telemetry.get('movement')
            run = self.active()
            if (run and trace['fresh'] and trace.get('command_id') == run['id'] and trace.get('trace_id') == run['trace_id']
                    and trace.get('state') in ('replay_complete', 'stopped', 'cancelled', 'fault')):
                with self.database() as db:
                    db.execute('UPDATE movement_returns SET state=? WHERE id=?', (trace['state'], run['id']))
                run = None
            return {**trace, 'control_configured': bool(self.command_url),
                    'can_return': bool(self.command_url and trace['fresh'] and trace.get('return_ready') and not trace.get('simulated') and not run and not self.missions.active()),
                    'can_stop': bool(run and run['owner'] == owner),
                    'return_state': run['state'] if run else None,
                    'command_id': run['id'] if run and run['owner'] == owner else trace.get('command_id'),
                    'lease_required': bool(run and run['owner'] == owner and run['state'] == 'returning'
                                           and trace['fresh'] and trace.get('state') == 'returning'
                                           and trace.get('command_id') == run['id'])}

    def send(self, action, run):
        if not self.command_url:
            raise MissionError('Movement bridge is not configured.', 503)
        try:
            response = self.http.post(self.command_url, json={'action': action, 'command_id': run['id'], 'trace_id': run['trace_id']},
                                      headers={'X-Robot-Key': self.command_key} if self.command_key else {}, timeout=3)
            response.raise_for_status()
            ack = response.json()
            if (ack.get('acknowledged') is not True or ack.get('command_id') != run['id'] or ack.get('trace_id') != run['trace_id']
                    or ack.get('state') != ('stopped' if action == 'stop' else 'returning')):
                raise ValueError('Unmatched acknowledgement')
        except Exception as exc:
            with self.database() as db:
                db.execute("UPDATE movement_returns SET state='command_uncertain' WHERE id=?", (run['id'],))
            raise MissionError('Movement acknowledgement missing. Motion is uncertain; use Stop and verify the robot.', 502) from exc

    def start(self, owner, payload):
        with self.lock:
            status = self.status(owner)
            if not status['can_return']:
                raise MissionError('Return needs a fresh complete stopped trace, verified controller interlocks, a configured bridge, and no active mission or return.')
            if (not isinstance(payload, dict) or payload.get('trace_id') != status['trace_id']
                    or payload.get('segment_count') != len(status['segments']) or payload.get('total_duration_ms') != status['total_duration_ms']):
                raise MissionError('Recorded movement changed. Refresh and review it before returning.')
            run = {'id': uuid4().hex, 'owner': owner, 'trace_id': status['trace_id']}
            with self.database() as db:
                db.execute('INSERT INTO movement_returns VALUES (?,?,?,?,?)', (run['id'], owner, run['trace_id'], 'command_uncertain', time.time()))
            self.send('return', run)
            with self.database() as db:
                db.execute("UPDATE movement_returns SET state='returning' WHERE id=?", (run['id'],))
            return self.status(owner)

    def action(self, owner, action, command_id):
        with self.lock:
            run = self.active()
            if not run or run['owner'] != owner or run['id'] != command_id:
                raise MissionError('Only the return owner can control this active return.', 403)
            if action == 'heartbeat' and run['state'] != 'returning':
                raise MissionError('Return state is uncertain. Stop and verify the robot.')
            if action == 'heartbeat':
                trace = self.telemetry.get('movement')
                if (not trace['fresh'] or trace.get('state') != 'returning' or trace.get('command_id') != run['id'] or trace.get('trace_id') != run['trace_id']):
                    with self.database() as db:
                        db.execute("UPDATE movement_returns SET state='command_uncertain' WHERE id=?", (run['id'],))
                    raise MissionError('Fresh matching replay telemetry is unavailable. Stop and verify the robot.')
            self.send(action, run)
            if action == 'stop':
                with self.database() as db:
                    db.execute("UPDATE movement_returns SET state='stopped' WHERE id=?", (run['id'],))
            return self.status(owner)
