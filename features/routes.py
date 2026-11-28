"""Register new APIs behind the application's existing verified-user auth."""
import sqlite3
import time
from datetime import datetime, timezone
from flask import g, jsonify, request
from .missions import MissionError


EXCAVATION_DECISIONS = {
    'cleared': 'Clearance reported',
    'hold': 'Hold excavation',
    'danger': 'Extreme danger · Do not excavate',
}


def _report_excavation_assessment(assessment):
    if assessment is None:
        return None
    if not isinstance(assessment, dict) or set(assessment) != {'area', 'lead', 'decision', 'at'}:
        raise MissionError('Expected a recorded excavation decision with its area, rescue lead, and time.', 400)
    area, lead = assessment['area'], assessment['lead']
    if not all(isinstance(value, str) and 1 <= len(value.strip()) <= 120 for value in (area, lead)):
        raise MissionError('Enter an assessed area and rescue lead (1–120 characters each).', 400)
    decision = assessment['decision']
    if not isinstance(decision, str) or decision not in EXCAVATION_DECISIONS:
        raise MissionError('Choose a reported excavation decision.', 400)
    at = assessment['at']
    if type(at) not in (int, float) or not 0 <= at <= 253402300799:
        raise MissionError('The reported excavation time is invalid.', 400)
    return {'area': area.strip(), 'rescue_lead': lead.strip(), 'decision': decision,
            'decision_label': EXCAVATION_DECISIONS[decision],
            'recorded_at': datetime.fromtimestamp(at, timezone.utc).isoformat(timespec='milliseconds'),
            'source': 'operator_reported_rescue_lead_decision'}


def register(app, auth, missions, telemetry, environment, detections, vision_status, movement=None, evidence_store=None):
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

    def build_report(owner, excavation_assessment=None):
        data = dict(environment())
        fresh = bool(data.get('updated_at') and time.time()-data['updated_at'] < 10)
        return {'generated_at': time.time(), 'mission': missions.status(owner),
                        'environment': {**data, 'fresh': fresh}, 'survivors': detections(),
                        'position': telemetry.get('position'), 'movement': telemetry.get('movement'), 'thermal': telemetry.get('thermal'),
                        'sound': telemetry.get('sound'), 'vision': vision_status(),
                        'events': missions.events(owner), 'excavation_assessment': excavation_assessment,
                        'requires_human_verification': True}

    @app.get('/api/situational-report')
    @auth
    def situational_report():
        return jsonify(build_report(str(g.user.id)))

    if evidence_store is None:
        return

    @app.post('/api/mission-reports')
    @auth
    def save_mission_report():
        if request.content_length is not None and request.content_length > 4096:
            return jsonify(error='Expected a small report save request.'), 413
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(error='Expected a report save ID.'), 400
        assessment = _report_excavation_assessment(payload.get('excavation_assessment'))
        try:
            report = evidence_store.save_report(str(g.user.id), payload.get('save_id'),
                                                lambda owner: build_report(owner, assessment))
        except (OSError, sqlite3.Error, ValueError):
            return jsonify(error='Could not save the report on this laptop. Please retry.'), 500
        return jsonify(report=report), 201

    @app.get('/api/mission-reports')
    @auth
    def list_mission_reports():
        data = evidence_store.list(str(g.user.id), reports=True)
        response = jsonify(reports=data['recordings'], pending_count=data['pending_count'])
        response.headers['Cache-Control'] = 'private, no-store'
        return response

    @app.get('/api/mission-reports/<report_id>/file')
    @auth
    def download_mission_report(report_id):
        return evidence_store.download(str(g.user.id), report_id, reports=True)
