"""Explicit local-only firmware-contract simulator. Does not control any motors.

Run: python scripts/simulate_robot.py (port 5052)
See docs/FEATURE_INTEGRATION.md for opt-in application configuration.
"""
import threading
import time
from flask import Flask, jsonify, request

app = Flask(__name__)
lock = threading.Lock()
state, mission_id, lease_at = 'idle', None, 0


def expire():
    global state
    if state == 'searching' and time.monotonic()-lease_at > 8:
        state = 'fault'


@app.get('/robot')
def robot():
    with lock:
        expire()
        return jsonify(state=state, mission_id=mission_id, navigation_ready=state != 'searching', simulated=True)


@app.post('/command')
def command():
    global state, mission_id, lease_at
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or data.get('action') not in ('start', 'stop', 'heartbeat') or not isinstance(data.get('mission_id'), str):
        return jsonify(error='Invalid command'), 400
    with lock:
        expire()
        action, incoming = data['action'], data['mission_id']
        if action == 'start':
            if state == 'searching' and mission_id != incoming:
                return jsonify(error='Robot busy'), 409
            state, mission_id, lease_at = 'searching', incoming, time.monotonic()
        elif action == 'stop':
            state, mission_id = 'stopped', incoming
        elif incoming == mission_id and state == 'searching':
            lease_at = time.monotonic()
        else:
            return jsonify(error='No matching active mission'), 409
        return jsonify(acknowledged=True, mission_id=mission_id, state=state, simulated=True)


@app.get('/thermal')
def thermal():
    return jsonify(grid=[[24.0 + (7 if 10 <= x < 16 and 8 <= y < 16 else 0) for x in range(32)] for y in range(24)], simulated=True)


@app.get('/sound')
def sound():
    return jsonify(db_level=35.0, classification='ambient', confidence=0.0, simulated=True)


if __name__ == '__main__':
    print('SIMULATION ONLY: no hardware or survivor detection is connected.')
    app.run(host='127.0.0.1', port=5052, debug=False)
