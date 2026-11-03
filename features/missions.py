"""Single-robot mission commands and persistent, operator-owned evidence."""
import json
import threading
import time
from uuid import uuid4

FIELDS = {'age_group': ('unknown', 'adult', 'child'),
          'consciousness': ('unknown', 'conscious', 'unconscious'),
          'injury': ('unknown', 'injured', 'uninjured'),
          'entrapment': ('unknown', 'trapped', 'not_trapped')}


class MissionError(Exception):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


class Missions:
    def __init__(self, database, telemetry, http, command_url='', command_key=''):
        self.database, self.telemetry, self.http = database, telemetry, http
        self.command_url, self.command_key = command_url, command_key
        self.lock = threading.RLock()
        self.external_motion_busy = lambda: False
        self.last_event = 0
        self.last_count = 0
        with database() as db:
            db.execute('CREATE TABLE IF NOT EXISTS missions (id TEXT PRIMARY KEY, owner TEXT NOT NULL, state TEXT NOT NULL, started_at REAL NOT NULL, stopped_at REAL)')
            if 'area_label' not in {row[1] for row in db.execute('PRAGMA table_info(missions)')}:
                db.execute("ALTER TABLE missions ADD COLUMN area_label TEXT NOT NULL DEFAULT ''")
            db.execute('CREATE TABLE IF NOT EXISTS survivor_events (id TEXT PRIMARY KEY, mission_id TEXT NOT NULL, at REAL NOT NULL, evidence TEXT NOT NULL, review TEXT, reviewed_by TEXT, reviewed_at REAL)')
            # A server restart cannot establish whether motors have stopped.
            db.execute("UPDATE missions SET state='command_uncertain' WHERE state='searching'")

    def active(self):
        with self.database() as db:
            db.row_factory = __import__('sqlite3').Row
            row = db.execute("SELECT * FROM missions WHERE state IN ('searching','command_uncertain') ORDER BY started_at DESC LIMIT 1").fetchone()
            return dict(row) if row else None

    def status(self, owner):
        with self.database() as db:
            db.row_factory = __import__('sqlite3').Row
            row = db.execute('SELECT * FROM missions WHERE owner=? ORDER BY started_at DESC LIMIT 1', (owner,)).fetchone()
        robot = self.telemetry.get('robot')
        active = self.active()
        return {'mission': dict(row) if row else None, 'robot': robot,
                'can_start': bool(self.command_url and robot['fresh'] and robot['navigation_ready'] and robot['state'] in ('idle', 'stopped', 'completed') and not active and not self.external_motion_busy()),
                'robot_busy': bool(active and active['owner'] != owner),
                'control_configured': bool(self.command_url)}

    def command(self, action, mission_id):
        if not self.command_url:
            raise MissionError('Robot command endpoint is not configured.', 503)
        try:
            response = self.http.post(self.command_url, json={'action': action, 'mission_id': mission_id},
                                      headers={'X-Robot-Key': self.command_key} if self.command_key else {}, timeout=3)
            response.raise_for_status()
            ack = response.json()
            expected = 'stopped' if action == 'stop' else 'searching'
            if ack.get('mission_id') != mission_id or ack.get('state') != expected or ack.get('acknowledged') is not True:
                raise ValueError('Missing command acknowledgement')
        except Exception as exc:
            raise MissionError('Robot did not acknowledge the command. Motion state is uncertain; verify at the robot.', 502) from exc

    def start(self, owner, area_label=''):
        if not isinstance(area_label, str) or not 1 <= len(area_label.strip()) <= 120:
            raise MissionError('Enter an observation area label (1–120 characters).', 400)
        with self.lock:
            if not self.status(owner)['can_start']:
                raise MissionError('Start requires fresh, navigation-ready robot telemetry and no active mission.')
            mission_id = uuid4().hex
            with self.database() as db:
                db.execute('INSERT INTO missions (id, owner, state, started_at, area_label) VALUES (?, ?, ?, ?, ?)', (mission_id, owner, 'command_uncertain', time.time(), area_label.strip()))
            self.last_count = 0
            self.last_event = 0
            self.command('start', mission_id)
            with self.database() as db:
                db.execute("UPDATE missions SET state='searching' WHERE id=?", (mission_id,))
            return self.status(owner)

    def stop(self, owner):
        with self.lock:
            active = self.active()
            if not active:
                raise MissionError('There is no active mission to stop.')
            if active['owner'] != owner:
                raise MissionError('Only the mission owner can send dashboard mission commands.', 403)
            with self.database() as db:
                db.execute("UPDATE missions SET state='command_uncertain' WHERE id=?", (active['id'],))
            self.command('stop', active['id'])
            with self.database() as db:
                db.execute("UPDATE missions SET state='stopped', stopped_at=? WHERE id=?", (time.time(), active['id']))
            return self.status(owner)

    def heartbeat(self):
        with self.lock:
            active = self.active()
            if active and active['state'] == 'searching':
                try:
                    self.command('heartbeat', active['id'])
                except MissionError:
                    with self.database() as db:
                        db.execute("UPDATE missions SET state='command_uncertain' WHERE id=?", (active['id'],))

    def reconcile(self):
        with self.lock:
            active = self.active()
            robot = self.telemetry.get('robot')
            if active and robot['fresh'] and robot.get('mission_id') == active['id'] and robot['state'] in ('completed', 'stopped', 'fault'):
                with self.database() as db:
                    db.execute('UPDATE missions SET state=?, stopped_at=? WHERE id=?', (robot['state'], time.time(), active['id']))

    def observe(self, detections, environment):
        with self.lock:
            active = self.active()
            count = len(detections)
            if not active or active['state'] != 'searching':
                return
            if not count:
                self.last_count = 0
                return
            now = time.time()
            if count == self.last_count and now - self.last_event < 15:
                return
            position = self.telemetry.get('position')
            movement = self.telemetry.get('movement')
            fresh_environment = bool(environment.get('updated_at') and now - environment['updated_at'] < 10)
            evidence = {'detections': detections, 'environment': dict(environment) if fresh_environment else None,
                        'observation_position': position if position['fresh'] else None,
                        'observation_movement': movement if movement['fresh'] else None,
                        'area_label': active['area_label'],
                        'location_note': 'Operator-entered mission area; robot position if available. Survivor coordinates are not estimated.',
                        'assessment': {key: 'unknown' for key in FIELDS}, 'verification': 'pending'}
            with self.database() as db:
                db.execute('INSERT INTO survivor_events VALUES (?, ?, ?, ?, NULL, NULL, NULL)',
                           (uuid4().hex, active['id'], now, json.dumps(evidence, allow_nan=False)))
            self.last_event, self.last_count = now, count

    def events(self, owner):
        with self.database() as db:
            rows = db.execute('SELECT e.id,e.mission_id,e.at,e.evidence,e.review,e.reviewed_by,e.reviewed_at FROM survivor_events e JOIN missions m ON m.id=e.mission_id WHERE m.owner=? ORDER BY e.at DESC LIMIT 100', (owner,)).fetchall()
        return [{'id': r[0], 'mission_id': r[1], 'at': r[2], 'evidence': json.loads(r[3]),
                 'review': json.loads(r[4]) if r[4] else None, 'reviewed_by': r[5], 'reviewed_at': r[6]} for r in rows]

    def review(self, owner, event_id, data):
        if not isinstance(data, dict) or data.get('verification') not in ('confirmed', 'false_positive', 'uncertain'):
            raise MissionError('Review requires confirmed, false_positive, or uncertain verification.', 400)
        assessment = data.get('assessment', {})
        if not isinstance(assessment, dict) or any(k not in FIELDS or v not in FIELDS[k] for k, v in assessment.items()):
            raise MissionError('Invalid survivor assessment.', 400)
        notes = data.get('notes', '')
        if not isinstance(notes, str) or len(notes) > 2000:
            raise MissionError('Notes must contain at most 2000 characters.', 400)
        review = {'verification': data['verification'], 'assessment': {k: assessment.get(k, 'unknown') for k in FIELDS}, 'notes': notes}
        with self.lock, self.database() as db:
            owned = db.execute('SELECT e.id FROM survivor_events e JOIN missions m ON m.id=e.mission_id WHERE e.id=? AND m.owner=?', (event_id, owner)).fetchone()
            if not owned:
                raise MissionError('Detection record not found.', 404)
            db.execute('UPDATE survivor_events SET review=?, reviewed_by=?, reviewed_at=? WHERE id=?',
                       (json.dumps(review), owner, time.time(), event_id))
        return review
