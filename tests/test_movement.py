"""Generated traces and fake acknowledgements only; no motor or serial access."""
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch
from types import SimpleNamespace
from flask import Flask, g, jsonify, request
from requests.exceptions import Timeout
from features.movement import MovementControl, validate_trace
from features.missions import Missions, MissionError
from features.telemetry import Telemetry, validate
from features.routes import register


def trace(**changes):
    return dict({'trace_id':'fixture-route-1','source':'uno_fixture','command_id':None,
        'sequence':1,'sample_age_ms':100,'state':'stopped','current_move':'S',
        'trace_complete':True,'return_ready':True,'returned_steps':0,
        'segments':[{'direction':'F','duration_ms':1200},{'direction':'L','duration_ms':450}]}, **changes)


class MovementTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        @contextmanager
        def database():
            db = sqlite3.connect(str(Path(temp.name)/'movement.db'))
            try:
                with db: yield db
            finally: db.close()
        self.http = MagicMock()
        self.telemetry = Telemetry({'movement':'http://fixture/trace','robot':'http://fixture/robot'}, self.http)
        self.telemetry.readings['movement'] = {**validate_trace(trace()), 'updated_at':time.time()}
        self.telemetry.readings['robot'] = {'state':'idle','navigation_ready':True,'mission_id':None,'updated_at':time.time()}
        self.missions = Missions(database, self.telemetry, self.http, 'http://fixture/missions')
        self.control = MovementControl(self.missions, self.telemetry, self.http, 'http://fixture/movement')
        self.missions.external_motion_busy = lambda: self.control.busy
        def ack(*args, **kwargs):
            data=kwargs['json']; response=MagicMock()
            response.json.return_value={**data,'acknowledged':True,'state':'stopped' if data['action']=='stop' else 'returning'}
            return response
        self.http.post.side_effect=ack

    def payload(self):
        return {'trace_id':'fixture-route-1','segment_count':2,'total_duration_ms':1650}

    def test_trace_has_commands_but_no_invented_position(self):
        data=validate('movement',trace(latitude=10,longitude=20,x=7,y=8))
        self.assertEqual(data['total_duration_ms'],1650)
        self.assertFalse(data['position_measured'])
        self.assertTrue(data['return_ready'])
        self.assertFalse(set(('latitude','longitude','x','y')) & set(data))

    def test_invalid_trace_and_limits(self):
        for changes in ({'segments':None},{'segments':[{'direction':'S','duration_ms':1}]},
                {'segments':[{'direction':'F','duration_ms':True}]},
                {'segments':[{'direction':'F','duration_ms':60001}]},
                {'segments':[{'direction':'F','duration_ms':1}]*81},
                {'segments':[{'direction':'F','duration_ms':60000}]*11},
                {'sample_age_ms':5000},{'sample_age_ms':float('nan')},
                {'sequence':True},{'trace_complete':1},{'return_ready':None},
                {'current_move':'X'},{'returned_steps':3},{'source':'<img>'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError): validate_trace(trace(**changes))

    def test_return_readiness_requires_complete_stopped_nonempty_trace(self):
        for changes in ({'trace_complete':False},{'current_move':'F'}, {'state':'recording'}, {'segments':[]}):
            self.assertFalse(validate_trace(trace(**changes))['return_ready'])

    def test_stale_simulated_unconfigured_or_active_mission_cannot_start_return(self):
        self.telemetry.readings['movement']['updated_at']-=10
        self.assertFalse(self.control.status('a')['can_return'])
        self.telemetry.readings['movement']['updated_at']=time.time()
        self.telemetry.readings['movement']['simulated']=True
        self.assertFalse(self.control.status('a')['can_return'])
        self.telemetry.readings['movement']['simulated']=False
        self.control.command_url=''
        with self.assertRaises(MissionError): self.control.start('a',self.payload())
        self.http.post.assert_not_called()
        self.control.command_url='http://fixture/movement'
        with self.missions.database() as db:
            db.execute('INSERT INTO missions VALUES (?,?,?,?,?,?)',('m','b','searching',time.time(),None,'Test'))
        with self.assertRaises(MissionError): self.control.start('a',self.payload())
        self.http.post.assert_not_called()

    def test_changed_trace_cannot_issue_command(self):
        for changes in ({'trace_id':'other'},{'segment_count':1},{'total_duration_ms':10}):
            with self.assertRaises(MissionError): self.control.start('a',{**self.payload(),**changes})
        self.http.post.assert_not_called()

    def test_matching_return_ack_owner_heartbeat_stop_and_no_double_start(self):
        data=self.control.start('a',self.payload())
        command_id=data['command_id']
        self.assertEqual(data['return_state'],'returning')
        self.assertTrue(data['can_stop']); self.assertFalse(data['lease_required'])
        self.assertFalse(self.missions.status('a')['can_start'])
        with self.assertRaises(MissionError): self.control.start('a',self.payload())
        self.assertFalse(self.control.status('b')['can_stop'])
        with self.assertRaises(MissionError): self.control.action('b','stop',command_id)
        self.telemetry.readings['movement'].update(state='returning',command_id=command_id,return_ready=False)
        self.assertTrue(self.control.action('a','heartbeat',command_id)['lease_required'])
        stopped=self.control.action('a','stop',command_id)
        self.assertFalse(stopped['can_stop'])
        self.assertFalse(self.control.busy)

    def test_timeout_is_persistently_uncertain_and_never_retried_automatically(self):
        self.http.post.side_effect=Timeout('private endpoint')
        with self.assertRaises(MissionError) as error: self.control.start('a',self.payload())
        self.assertNotIn('private',str(error.exception))
        self.assertEqual(self.control.status('a')['return_state'],'command_uncertain')
        restored=MovementControl(self.missions,self.telemetry,self.http,'http://fixture/movement')
        self.assertEqual(restored.status('a')['return_state'],'command_uncertain')
        self.http.post.assert_called_once()
        self.assertFalse(restored.status('a')['lease_required'])

    def test_stale_replay_telemetry_cannot_renew_motion_lease(self):
        data=self.control.start('a',self.payload())
        self.telemetry.readings['movement'].update(state='returning',command_id=data['command_id'],updated_at=time.time()-10)
        self.assertFalse(self.control.status('a')['lease_required'])
        with self.assertRaises(MissionError): self.control.action('a','heartbeat',data['command_id'])
        self.assertEqual(self.control.status('a')['return_state'],'command_uncertain')
        self.assertEqual(self.http.post.call_count,1)

    def test_mismatched_ack_cannot_report_success(self):
        self.http.post.side_effect=None
        self.http.post.return_value.json.return_value={'acknowledged':True,'state':'returning','command_id':'wrong','trace_id':'fixture-route-1'}
        with self.assertRaises(MissionError): self.control.start('a',self.payload())
        self.assertEqual(self.control.status('a')['return_state'],'command_uncertain')

    def test_completion_requires_matching_trace_and_command_never_at_base(self):
        data=self.control.start('a',self.payload())
        self.telemetry.readings['movement'].update(state='replay_complete',return_ready=False,command_id='other')
        self.assertTrue(self.control.busy)
        self.control.status('a'); self.assertTrue(self.control.busy)
        self.telemetry.readings['movement']['command_id']=data['command_id']
        result=self.control.status('a')
        self.assertFalse(self.control.busy)
        self.assertEqual(result['state'],'replay_complete')
        self.assertNotIn('at_base',str(result))

    def test_movement_source_age_includes_transport_and_same_sequence_never_refreshes(self):
        self.http.get.return_value.json.return_value=trace(sample_age_ms=500)
        with patch('features.telemetry.time.time',return_value=100), patch('features.telemetry.time.monotonic',side_effect=[0,.2]):
            self.telemetry.poll('movement'); first=self.telemetry.get('movement')
        self.assertAlmostEqual(first['updated_at'],99.3)
        self.http.get.return_value.json.return_value=trace(sample_age_ms=0)
        with patch('features.telemetry.time.time',return_value=103), patch('features.telemetry.time.monotonic',side_effect=[0,.01]):
            self.telemetry.poll('movement'); self.assertEqual(self.telemetry.get('movement')['updated_at'],first['updated_at'])
        with patch('features.telemetry.time.time',return_value=105): self.assertFalse(self.telemetry.get('movement')['fresh'])

    def test_routes_require_authentication_and_return_no_store_status(self):
        app=Flask(__name__)
        def auth(fn):
            @wraps(fn)
            def wrapped(*args,**kwargs):
                if request.headers.get('Authorization')!='Bearer fixture': return jsonify(error='Sign in'),401
                g.user=SimpleNamespace(id='a'); return fn(*args,**kwargs)
            return wrapped
        register(app,auth,self.missions,self.telemetry,lambda:{},lambda:[],lambda:{},movement=self.control)
        client=app.test_client(); headers={'Authorization':'Bearer fixture'}
        for method,path in (('get','/api/movement-data'),('post','/api/return_to_base'),('post','/api/movement/stop'),('post','/api/movement/heartbeat')):
            self.assertEqual(getattr(client,method)(path).status_code,401)
        response=client.get('/api/movement-data',headers=headers)
        self.assertEqual(response.headers['Cache-Control'],'no-store')
        self.assertEqual(client.post('/api/return_to_base',headers=headers,json=self.payload()).status_code,200)
        self.assertEqual(client.post('/api/movement/bad',headers=headers,json={}).status_code,400)


if __name__=='__main__': unittest.main()
