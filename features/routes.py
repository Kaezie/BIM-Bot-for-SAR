"""Register new APIs behind the application's existing verified-user auth."""
import time
from flask import g, jsonify, request
from .missions import MissionError


def register(app, auth, missions, telemetry, environment, detections, vision_status, movement=None):
    @app.errorhandler(MissionError)
    def mission_error(error):
        return jsonify({'error': str(error)}), error.status

    @app.get('/api/position-data')
    @auth
    def position_data():
        response = jsonify(telemetry.get('position'))
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.get('/api/movement-data')
    @auth
    def movement_data():
        response = jsonify(movement.status(str(g.user.id)) if movement else telemetry.get('movement'))
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.post('/api/return_to_base')
    @auth
    def return_to_base():
        if movement is None:
            return jsonify({'error': 'Movement bridge is not configured.'}), 503
        return jsonify(movement.start(str(g.user.id), request.get_json(silent=True)))

    @app.post('/api/movement/<action>')
    @auth
    def movement_action(action):
        payload = request.get_json(silent=True)
        if movement is None:
            return jsonify({'error': 'Movement bridge is not configured.'}), 503
        if action not in ('stop', 'heartbeat') or not isinstance(payload, dict):
            return jsonify({'error': 'Expected a Stop or heartbeat with command_id.'}), 400
        return jsonify(movement.action(str(g.user.id), action, payload.get('command_id')))

    @app.get('/api/mission')
    @auth
    def mission_status():
        return jsonify(missions.status(str(g.user.id)))

    @app.post('/api/mission/<action>')
    @auth
    def mission_action(action):
        if action not in ('start', 'stop'):
            return jsonify({'error': 'Unknown mission action.'}), 400
        if action == 'start':
            payload = request.get_json(silent=True)
            if not isinstance(payload, dict):
                return jsonify({'error': 'Start requires a JSON observation area label.'}), 400
            return jsonify(missions.start(str(g.user.id), payload.get('area_label', '')))
        return jsonify(missions.stop(str(g.user.id)))

    @app.get('/api/survivor-events')
    @auth
    def survivor_events():
        return jsonify({'events': missions.events(str(g.user.id))})

    @app.post('/api/survivor-events/<event_id>/review')
    @auth
    def review_survivor(event_id):
        return jsonify({'review': missions.review(str(g.user.id), event_id, request.get_json(silent=True))})

    @app.get('/api/situational-report')
    @auth
    def situational_report():
        data = dict(environment())
        fresh = bool(data.get('updated_at') and time.time()-data['updated_at'] < 10)
        return jsonify({'generated_at': time.time(), 'mission': missions.status(str(g.user.id)),
                        'environment': {**data, 'fresh': fresh}, 'survivors': detections(),
                        'position': telemetry.get('position'), 'movement': telemetry.get('movement'), 'thermal': telemetry.get('thermal'),
                        'sound': telemetry.get('sound'), 'vision': vision_status(),
                        'events': missions.events(str(g.user.id)), 'requires_human_verification': True})
