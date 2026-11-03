"""Offline integration checks for evidence, model contracts and robot commands."""
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

from flask import Flask, g
from requests import Response
from requests.exceptions import ConnectionError as RequestsConnectionError, Timeout
from features.telemetry import Telemetry, validate
from features.missions import Missions, MissionError
from features.routes import register


class FeatureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        @contextmanager
        def database():
            db = sqlite3.connect(str(Path(self.temp.name)/'features.db'))
            try:
                with db:
                    yield db
            finally:
                db.close()
        self.database = database
        self.http = MagicMock()
        self.telemetry = Telemetry({'robot': 'http://robot/status', 'thermal': 'http://robot/thermal'}, self.http)
        self.telemetry.readings['robot'] = {'state': 'idle', 'mission_id': None, 'navigation_ready': True, 'updated_at': time.time()}
        self.missions = Missions(database, self.telemetry, self.http, 'http://robot/command')
        def ack(*args, **kwargs):
            payload = kwargs['json']
            response = MagicMock()
            response.json.return_value = {'acknowledged': True, 'mission_id': payload['mission_id'], 'state': 'stopped' if payload['action']=='stop' else 'searching'}
            return response
        self.http.post.side_effect = ack



    def test_thermal_validation_and_stale_cache(self):
        grid = [[25.0]*32 for _ in range(24)]
        data=validate('thermal', {'grid':grid})
        self.assertEqual(data['max_temp'],25)
        with self.assertRaises(ValueError): validate('thermal',{'grid':[[25]*31]*24})
        grid[0][0]=float('nan')
        with self.assertRaises(ValueError): validate('thermal',{'grid':grid})
        self.telemetry.readings['thermal']={'grid':[[25]*32]*24,'updated_at':time.time()-20}
        self.assertFalse(self.telemetry.get('thermal')['connected'])
        self.telemetry.readings['thermal']['updated_at']=time.time()
        self.http.get.side_effect=TimeoutError
        self.telemetry.poll('thermal')
        self.assertTrue(self.telemetry.get('thermal')['connected'])
        self.assertTrue(self.telemetry.get('thermal')['retrying'])

    def test_thermal_source_freshness_metadata_validation(self):
        grid = [[25.0] * 32 for _ in range(24)]
        for name, invalid_values in {
            'fresh': (False, None, 0, 1, 'true'),
            'frame_age_ms': (True, None, '100', -1, float('nan'), float('inf'), 5000, 6000),
            'sequence': (True, None, '1', -1, 1.5, float('nan')),
        }.items():
            for value in invalid_values:
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    validate('thermal', {'grid': grid, name: value})
        validated = validate('thermal', {'grid': grid, 'fresh': True,
                                         'frame_age_ms': 4999, 'sequence': 0})
        self.assertEqual(validated['frame_age_ms'], 4999)
        self.assertEqual(validated['sequence'], 0)

    def test_thermal_poll_retains_acquisition_age_and_expires_at_source_limit(self):
        payload = {'grid': [[25.0] * 32 for _ in range(24)], 'fresh': True,
                   'frame_age_ms': 500, 'sequence': 4}
        self.http.get.return_value.json.return_value = payload
        with patch('features.telemetry.time.time', return_value=100), \
                patch('features.telemetry.time.monotonic', return_value=0):
            self.telemetry.poll('thermal')
            first = self.telemetry.get('thermal')
        self.assertTrue(first['connected'])
        self.assertEqual(first['updated_at'], 99.5)

        # The second response is the same sample, now two seconds older.
        payload['frame_age_ms'] = 2500
        with patch('features.telemetry.time.time', return_value=102), \
                patch('features.telemetry.time.monotonic', return_value=0):
            self.telemetry.poll('thermal')
            self.assertEqual(self.telemetry.get('thermal')['updated_at'], 99.5)

        with patch('features.telemetry.time.time', return_value=104.5):
            self.assertFalse(self.telemetry.get('thermal')['connected'])

        # A reboot can reset the sequence without blocking a new fresh frame.
        payload.update(frame_age_ms=100, sequence=0)
        with patch('features.telemetry.time.time', return_value=105), \
                patch('features.telemetry.time.monotonic', return_value=0):
            self.telemetry.poll('thermal')
            recovered = self.telemetry.get('thermal')
        self.assertTrue(recovered['connected'])
        self.assertEqual(recovered['updated_at'], 104.9)

    def test_thermal_http_failure_invalidates_cache_and_recovers(self):
        payload = {'grid': [[25.0] * 32 for _ in range(24)],
                   'fresh': True, 'frame_age_ms': 100, 'sequence': 1}
        response = Response()
        response.status_code = 200
        response._content = json.dumps(payload).encode()
        self.http.get.return_value = response
        self.telemetry.poll('thermal')
        self.assertTrue(self.telemetry.get('thermal')['connected'])
        response.status_code = 503
        response._content = b'{"fresh":false,"error":"sensor unavailable"}'
        self.telemetry.poll('thermal')
        self.assertFalse(self.telemetry.get('thermal')['fresh'])
        response.status_code = 200
        payload['sequence'] = 2
        response._content = json.dumps(payload).encode()
        self.telemetry.poll('thermal')
        self.assertTrue(self.telemetry.get('thermal')['fresh'])
        self.assertNotIn('thermal', self.telemetry.errors)

    def test_thermal_sensor_failure_or_stale_frame_invalidates_last_good_reading(self):
        good = {'grid': [[25.0] * 32 for _ in range(24)], 'fresh': True,
                'frame_age_ms': 100, 'sequence': 1}
        for invalid in ({'fresh': False}, {'frame_age_ms': 5000}):
            with self.subTest(invalid=invalid):
                self.http.get.return_value.json.return_value = good
                self.telemetry.poll('thermal')
                self.assertTrue(self.telemetry.get('thermal')['fresh'])
                self.http.get.return_value.json.return_value = {**good, **invalid}
                self.telemetry.poll('thermal')
                self.assertFalse(self.telemetry.get('thermal')['fresh'])

    def test_telemetry_failure_categories_never_publish_exception_details(self):
        secret = 'SYNTHETIC_SECRET_DO_NOT_PUBLISH'
        cases = (
            (Timeout(secret), 'timeout'),
            (TimeoutError(secret), 'timeout'),
            (RequestsConnectionError(secret), 'transport_error'),
            (OSError(secret), 'transport_error'),
            (RuntimeError(secret), 'unavailable'),
        )
        for error, expected in cases:
            with self.subTest(category=expected, exception=type(error).__name__):
                self.http.get.side_effect = error
                self.telemetry.poll('thermal')
                reading = self.telemetry.get('thermal')
                self.assertEqual(reading['error_code'], expected)
                self.assertFalse(reading['connected'])
                self.assertFalse(reading['fresh'])
                self.assertNotIn('http_status', reading)
                self.assertNotIn(secret, json.dumps(reading))
                self.assertEqual(reading['message'],
                                 'Telemetry unavailable or invalid; check firmware and connection.')

    def test_telemetry_http_and_payload_diagnostics_clear_on_recovery(self):
        secret = 'SYNTHETIC_SECRET_DO_NOT_PUBLISH'
        response = Response()
        response.status_code = 503
        response.reason = secret
        response.url = f'http://user:{secret}@robot/thermal?token={secret}'
        response._content = json.dumps({'error': secret}).encode()
        self.http.get.return_value = response
        self.telemetry.poll('thermal')
        reading = self.telemetry.get('thermal')
        self.assertEqual(reading['error_code'], 'http_error')
        self.assertEqual(reading['http_status'], 503)
        self.assertNotIn(secret, json.dumps(reading))

        response.status_code = 200
        response._content = ('invalid json ' + secret).encode()
        self.telemetry.poll('thermal')
        reading = self.telemetry.get('thermal')
        self.assertEqual(reading['error_code'], 'invalid_payload')
        self.assertEqual(reading['http_status'], 200)
        self.assertNotIn(secret, json.dumps(reading))

        response._content = json.dumps({'grid': [[secret]]}).encode()
        self.telemetry.poll('thermal')
        self.assertEqual(self.telemetry.get('thermal')['error_code'], 'invalid_payload')
        self.assertNotIn(secret, json.dumps(self.telemetry.get('thermal')))

        response._content = json.dumps({
            'grid': [[25.0] * 32 for _ in range(24)], 'fresh': True,
            'frame_age_ms': 100, 'sequence': 2}).encode()
        self.telemetry.poll('thermal')
        reading = self.telemetry.get('thermal')
        self.assertTrue(reading['connected'])
        self.assertNotIn('error_code', reading)
        self.assertNotIn('http_status', reading)
        self.assertNotIn('thermal', self.telemetry.diagnostics)
        self.assertEqual(reading['message'], 'Live telemetry.')

    def test_thermal_legacy_grid_keeps_existing_ttl_and_rejects_future_timestamps(self):
        self.http.get.return_value.json.return_value = {
            'grid': [[25.0] * 32 for _ in range(24)], 'simulated': True}
        with patch('features.telemetry.time.time', return_value=100):
            self.telemetry.poll('thermal')
        with patch('features.telemetry.time.time', return_value=106):
            reading = self.telemetry.get('thermal')
            self.assertTrue(reading['fresh'])
            self.assertTrue(reading['simulated'])
        for now in (99, 110):
            with self.subTest(now=now), patch('features.telemetry.time.time', return_value=now):
                self.assertFalse(self.telemetry.get('thermal')['fresh'])

    def test_audio_and_position_validation(self):
        with self.assertRaises(ValueError): validate('sound', {'db_level':-1})
        with self.assertRaises(ValueError): validate('sound', {'db_level':40,'classification':'survivor_confirmed'})
        self.assertEqual(validate('position', {'frame':'local_meters','source':'encoders','x':1,'y':2})['x'],1)
        with self.assertRaises(ValueError): validate('position', {'frame':'wgs84','source':'gps','latitude':100,'longitude':1})

    def test_start_stop_and_operator_ownership(self):
        status=self.missions.start('a','Test corridor')
        self.assertEqual(status['mission']['state'],'searching')
        with self.assertRaises(MissionError): self.missions.start('b','Other area')
        with self.assertRaises(MissionError) as error: self.missions.stop('b')
        self.assertEqual(error.exception.status,403)
        self.assertEqual(self.missions.stop('a')['mission']['state'],'stopped')

    def test_missing_or_stale_navigation_blocks_motion(self):
        self.telemetry.readings['robot']['updated_at']=time.time()-20
        with self.assertRaises(MissionError): self.missions.start('a','Area')
        self.http.post.assert_not_called()

    def test_ack_loss_persists_uncertainty_and_allows_stop(self):
        self.http.post.side_effect=TimeoutError
        with self.assertRaises(MissionError): self.missions.start('a','Area')
        self.assertEqual(self.missions.active()['state'],'command_uncertain')
        self.assertFalse(self.missions.status('b')['can_start'])

    def test_wrong_ack_is_not_success(self):
        self.http.post.side_effect=None
        self.http.post.return_value.json.return_value={'acknowledged':True,'mission_id':'wrong','state':'searching'}
        with self.assertRaises(MissionError): self.missions.start('a','Area')
        self.assertEqual(self.missions.active()['state'],'command_uncertain')

    def test_restart_and_robot_completion(self):
        status=self.missions.start('a','Area')
        restarted=Missions(self.database,self.telemetry,self.http,'http://robot/command')
        self.assertEqual(restarted.active()['state'],'command_uncertain')
        self.telemetry.readings['robot'].update(state='completed',mission_id=status['mission']['id'])
        restarted.reconcile()
        self.assertIsNone(restarted.active())
        self.assertEqual(restarted.status('a')['mission']['state'],'completed')

    def test_heartbeat_failure_marks_uncertainty(self):
        self.missions.start('a','Area')
        self.http.post.side_effect=TimeoutError
        self.missions.heartbeat()
        self.assertEqual(self.missions.active()['state'],'command_uncertain')

    def test_receiver_without_fix_is_not_recorded_as_observation_position(self):
        self.missions.start('a','Generated test area')
        self.telemetry.readings['position'] = {
            'frame':'wgs84','source':'fixture-gps','fix_valid':False,
            'updated_at':time.time(),'satellites':2}
        self.missions.observe([{'confidence':.8,'bbox_xyxy':[0,0,10,20]}],{})
        evidence=self.missions.events('a')[0]['evidence']
        self.assertIsNone(evidence['observation_position'])
        self.assertIn('Survivor coordinates are not estimated',evidence['location_note'])

    def test_evidence_context_cooldown_review_and_persistence(self):
        self.missions.start('a','Hallway')
        detections=[{'confidence':.8,'bbox_xyxy':[0,0,10,20]}]
        environment={'updated_at':time.time()-20,'danger_level':'Danger'}
        self.missions.observe(detections,environment)
        self.missions.observe(detections,environment)
        events=self.missions.events('a')
        self.assertEqual(len(events),1)
        event=events[0]
        self.assertEqual(event['evidence']['area_label'],'Hallway')
        self.assertIsNone(event['evidence']['environment'])
        self.assertIsNone(event['evidence']['observation_position'])
        self.assertEqual(event['evidence']['assessment']['consciousness'],'unknown')
        self.assertEqual(self.missions.events('b'),[])
        with self.assertRaises(MissionError): self.missions.review('b',event['id'],{'verification':'confirmed'})
        self.missions.review('a',event['id'],{'verification':'confirmed','assessment':{'age_group':'adult'}})
        self.assertEqual(self.missions.events('a')[0]['review']['assessment']['age_group'],'adult')
        with self.assertRaises(MissionError): self.missions.review('a',event['id'],{'verification':'confirmed','assessment':{'injury':'guessed'}})
        restarted=Missions(self.database,self.telemetry,self.http)
        self.assertEqual(restarted.events('a')[0]['reviewed_by'],'a')



    def test_simulator_obeys_ack_and_lease_contract(self):
        import importlib.util
        path=Path(__file__).resolve().parents[1]/'scripts'/'simulate_robot.py'
        spec=importlib.util.spec_from_file_location('robot_simulator_test',path)
        simulator=importlib.util.module_from_spec(spec); spec.loader.exec_module(simulator)
        client=simulator.app.test_client()
        self.assertTrue(client.get('/robot').get_json()['simulated'])
        payload={'action':'start','mission_id':'test-mission'}
        self.assertEqual(client.post('/command',json=payload).get_json()['state'],'searching')
        simulator.lease_at=time.monotonic()-9
        self.assertEqual(client.get('/robot').get_json()['state'],'fault')
        self.assertEqual(client.post('/command',json={'action':'heartbeat','mission_id':'test-mission'}).status_code,409)
        self.assertEqual(client.post('/command',json={'action':'stop','mission_id':'test-mission'}).get_json()['state'],'stopped')

    def test_new_routes_enforce_auth_and_json(self):
        from functools import wraps
        from flask import request, jsonify
        app=Flask(__name__)
        def auth(fn):
            @wraps(fn)
            def wrapped(*a,**kw):
                if request.headers.get('Authorization')!='Bearer valid': return jsonify(error='Unauthorized'),401
                g.user=type('User',(),{'id':'a'})()
                return fn(*a,**kw)
            return wrapped
        register(app,auth,self.missions,self.telemetry,lambda:{},lambda:{},lambda:{})
        client=app.test_client(); headers={'Authorization':'Bearer valid'}
        for route in ['/api/mission','/api/survivor-events','/api/situational-report']:
            self.assertEqual(client.get(route).status_code,401)
        self.assertEqual(client.post('/api/mission/start').status_code,401)
        self.assertEqual(client.post('/api/mission/start',headers=headers,json=[]).status_code,400)
        self.assertEqual(client.post('/api/mission/start',headers=headers,json={'area_label':'Area'}).status_code,200)
        self.assertEqual(client.get('/api/situational-report',headers=headers).status_code,200)
        self.assertEqual(client.post('/api/survivor-events/unknown/review',headers=headers,json={}).status_code,400)


if __name__ == '__main__': unittest.main()
