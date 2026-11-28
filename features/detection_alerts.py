"""Main-camera observation alerts and optional Uno slowdowns."""
from threading import Lock
from time import time
from urllib.parse import urlsplit
from uuid import uuid4


LIVE_SECONDS = 2
HOLD_SECONDS = 6


def observation_cue(person):
    lying = person['posture'] == 'fallen' if 'posture' in person else person.get('pose') == 'lying'
    still = person.get('motion_observed') is False
    if lying and still:
        return 'Lying posture and little image motion. Check responsiveness and visible obstructions.'
    if lying:
        return 'Lying posture observed. Check the live view.'
    if still:
        return 'Little image motion observed. Verify the person’s condition.'
    return None


class DetectionAlerts:
    def __init__(self):
        self.lock = Lock()
        self.last_at = None
        self.latest = None
        self.candidate = 0
        self.incident = 0
        self.clear_at = None
        self.event = None
        self.light_at = None
        self.light_candidate = self.light_since = None

    def observe_light(self, at, dark):
        with self.lock:
            if self.light_at is not None and at <= self.light_at:
                return
            candidate = 'dark' if dark else 'bright'
            if candidate != self.light_candidate or self.light_at is None or at - self.light_at > 1.5:
                self.light_candidate, self.light_since = candidate, at
            self.light_at = at

    def observe(self, people, at):
        with self.lock:
            if self.last_at is not None and at <= self.last_at:
                return None
            consecutive = self.last_at is not None and at - self.last_at <= 1.5
            self.last_at = at
            count = len(people)
            if count:
                self.clear_at = None
                cues = list(dict.fromkeys(cue for person in people if (cue := observation_cue(person))))
                self.latest = {'count': count, 'seen_at': at, 'cues': cues}
            else:
                if self.clear_at is None or not consecutive:
                    self.clear_at = at
                if at - self.clear_at >= LIVE_SECONDS:
                    self.incident = 0
                    self.event = None
            new_event = count > self.incident and count == self.candidate and consecutive
            self.candidate = count
            if new_event:
                self.incident = count
                self.event = (at, min(4, count))
                return self.latest
            return None

    def snapshot(self, at):
        with self.lock:
            recent = dict(self.latest) if self.latest and 0 <= at - self.latest['seen_at'] < HOLD_SECONDS else None
            duration = 1 if self.light_candidate == 'dark' else 2
            light = (self.light_candidate if self.light_at is not None and 0 <= at - self.light_at < LIVE_SECONDS
                     and self.light_at - self.light_since >= duration else None)
            return {'recent_observation': recent, 'low_light': light == 'dark', 'light_state': light}

    def event_at(self, at):
        with self.lock:
            if self.event and 0 <= at-self.event[0] < LIVE_SECONDS and self.candidate:
                return self.event
            return None

    def source_lost(self, *, clear_light=True):
        with self.lock:
            self.event = None
            self.candidate = 0
            if clear_light:
                self.light_at = self.light_candidate = self.light_since = None


class DetectionSlowdown:
    """Send one slowdown request per confirmed increase. The Uno owns the timer."""
    def __init__(self, url, key, http, alerts, clock=time):
        try:
            parts = urlsplit(url)
        except ValueError:
            parts = urlsplit('')
        self.configured = bool(key and parts.scheme == 'http' and parts.hostname in {'127.0.0.1', 'localhost'}
                               and parts.path == '/command' and not (parts.query or parts.fragment or parts.username))
        self.url, self.key, self.http, self.alerts, self.clock = url, key, http, alerts, clock
        self.handled_at = None
        self.active = None
        self.status = 'ready' if self.configured else 'disabled'

    def send(self, trace, identifier, count):
        payload = {'action': 'observation_slowdown', 'trace_id': trace, 'command_id': identifier, 'count': count}
        try:
            response = self.http.post(self.url, json=payload, headers={'X-Robot-Key': self.key},
                                      timeout=(.3, 2.2), allow_redirects=False)
            response.raise_for_status()
            ack = response.json()
            return (ack.get('acknowledged') is True and ack.get('command_id') == identifier and
                    ack.get('trace_id') == trace and ack.get('state') == 'recording')
        except (OSError, ValueError, AttributeError):
            return False

    def tick(self, trace, live):
        if not self.configured:
            return
        now = self.clock()
        event = self.alerts.event_at(now)
        fresh = (trace.get('fresh') and trace.get('source') == 'uno_usb_serial' and
                 trace.get('sample_age_ms', 9999) < 2000 and trace.get('trace_id'))
        if not (live and fresh):
            if event:
                self.handled_at = event[0]
            if self.active:
                self.status = 'unconfirmed'
                self.active = None
            return
        trace_id = trace['trace_id']
        forward = trace.get('state') == 'recording' and trace.get('current_move') == 'F'
        if self.active and (self.active['trace'] != trace_id or not forward or now >= self.active['until']):
            self.active = None
            self.status = 'ready'
        if not event or self.handled_at == event[0]:
            return
        self.handled_at, count = event
        if not forward or (self.active and count <= self.active['count']):
            return
        identifier = self.active['id'] if self.active else uuid4().hex
        if self.send(trace_id, identifier, count):
            self.active = {'id': identifier, 'trace': trace_id, 'count': count,
                           'until': self.clock() + 3 * count}
            self.status = 'slowing'
        else:
            self.active = None
            self.status = 'unconfirmed'
