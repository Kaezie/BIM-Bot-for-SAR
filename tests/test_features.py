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
        self.assertFalse(self.telemetry.get('thermal')['connected'])

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
