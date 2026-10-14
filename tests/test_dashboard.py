"""Hardware-free checks for history, freshness, and recording authorization."""
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]

class DashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.storage = MagicMock()
        fake_client = MagicMock()
        fake_client.storage.from_.return_value = cls.storage
        fake_model = MagicMock()
        fake_model.names = {14: 'person'}
        modules = {'cv2': MagicMock(), 'ultralytics': types.SimpleNamespace(YOLO=MagicMock(return_value=fake_model)),
                   'supabase': types.SimpleNamespace(create_client=lambda *args: fake_client), 'dotenv': MagicMock()}
        env = {'SUPABASE_URL':'https://example.supabase.co','SUPABASE_ANON_KEY':'test','SUPABASE_SERVICE_ROLE_KEY':'test'}
        spec = importlib.util.spec_from_file_location('bimbot_test_app', ROOT / 'app.py')
        cls.module = importlib.util.module_from_spec(spec)
        # Ensure importing the application creates its test database outside the repository.
        real_connect = __import__('sqlite3').connect
        with patch.dict(sys.modules, modules), patch.dict(os.environ, env), patch('sqlite3.connect', side_effect=lambda *a, **kw: real_connect(str(Path(cls.temp.name)/'history.sqlite3'), **kw)):
            spec.loader.exec_module(cls.module)
        cls.module.HISTORY_DB = str(Path(cls.temp.name)/'history.sqlite3')
        cls.module._verify_token = lambda token: types.SimpleNamespace(id='operator-a') if token=='valid' else None
        cls.client = cls.module.app.test_client()
        cls.headers = {'Authorization':'Bearer valid'}

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def setUp(self): self.storage.reset_mock()

    def test_routes_require_auth(self):
        for route in ['/api/history','/api/recordings','/api/recordings/link','/api/device-status','/api/mission','/api/survivor-events','/api/situational-report','/api/thermal']:
            self.assertEqual(self.client.get(route).status_code,401)

    def test_pages_share_safe_json_config_and_load_external_scripts_in_order(self):
        from html.parser import HTMLParser

        class Scripts(HTMLParser):
            def __init__(self):
                super().__init__()
                self.scripts = []
                self.current = None

            def handle_starttag(self, tag, attrs):
                if tag == 'script':
                    self.current = {'attrs': dict(attrs), 'text': ''}
                    self.scripts.append(self.current)

            def handle_data(self, data):
                if self.current is not None:
                    self.current['text'] += data

            def handle_endtag(self, tag):
                if tag == 'script':
                    self.current = None

        # The configuration must remain data, even with HTML-sensitive values.
        url = 'https://example.test/</script><script>alert(1)</script>'
        with patch.object(self.module, 'SUPABASE_URL', url):
            for route, page in [('/', 'dashboard'), ('/login', 'login')]:
                response = self.client.get(route)
                self.assertEqual(response.status_code, 200)
                parser = Scripts()
                parser.feed(response.get_data(as_text=True))
                config, sdk, auth, behavior = parser.scripts
                self.assertEqual(config['attrs']['type'], 'application/json')
                self.assertEqual(config['attrs']['id'], 'bim-config')
                self.assertEqual(json.loads(config['text']), {'url': url, 'key': 'test'})
                self.assertIn('@supabase/supabase-js@2', sdk['attrs']['src'])
                self.assertEqual(auth['attrs']['src'], '/static/js/auth.js')
                self.assertEqual(behavior['attrs']['src'], f'/static/js/{page}.js')
                for script in [sdk, auth, behavior]:
                    self.assertIn('defer', script['attrs'])
                    self.assertFalse(script['text'].strip())
                for asset in ['css/common.css', 'js/auth.js', f'css/{page}.css', f'js/{page}.js']:
                    with self.client.get(f'/static/{asset}') as asset_response:
                        self.assertEqual(asset_response.status_code, 200)

    def test_sar_camera_pipeline_supplies_classifications_to_ui(self):
        camera = MagicMock()
        frame = types.SimpleNamespace(shape=(480, 640, 3))
        camera.read.return_value = (True, frame)
        detector = MagicMock()
        box = MagicMock()
        box.xyxy[0].tolist.return_value = [10, 20, 100, 250]
        box.conf = .94
        result = MagicMock()
        result.boxes = [box]
        detector.return_value = [result]
        pose = MagicMock()
        pose.return_value[0].keypoints = None
        encoder = MagicMock()
        encoder.tobytes.return_value = b'jpeg-test'
        with patch.object(self.module.cv2, 'VideoCapture', return_value=camera), patch.object(self.module.cv2, 'imencode', return_value=(True, encoder)), patch.multiple(self.module, detection_model=detector, pose_model=pose, cap=None, frame_count=0, prev_frame=None, last_results=None):
            stream = self.module.generate_frames()
            for _ in range(3):
                self.assertIn(b'jpeg-test', next(stream))
            stream.close()
        detector.assert_called_once_with(frame, classes=[14], conf=.25)
        pose.assert_called_once_with(frame, conf=.25)
        response = self.client.get('/api/survivors', headers=self.headers).get_json()
        self.assertTrue(response['available'])
        self.assertEqual(response['survivors_found'], 1)
        self.assertEqual(response['detections'][0]['age'], 'Adult')
        self.assertEqual(response['detections'][0]['consciousness'], 'Unconscious/Unresponsive')
        self.assertEqual(response['detections'][0]['thermal_alive'], 'No thermal camera')

    def test_sar_sensor_rules_supply_ui_and_history(self):
        response = MagicMock(status_code=200)
        response.json.return_value = {'temp_c': 36, 'humidity': 72}
        with patch.object(self.module.requests, 'get', return_value=response), patch.object(self.module.time, 'sleep', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.module.wifi_sensor_listener()
        data = self.client.get('/api/sensor-data', headers=self.headers).get_json()
        expected = self.module.calculate_risk(36, 72)
        self.assertTrue(data['fresh'])
        self.assertEqual(data['risk_level'], expected[0])
        self.assertEqual(data['confidence'], expected[2])
        self.assertEqual(data['method'], 'threshold')
        history = self.client.get('/api/history', headers=self.headers).get_json()
        self.assertTrue(any(sample['temperature'] == 36 for sample in history['samples']))

    def test_new_mission_routes_reject_unauthenticated_commands(self):
        self.assertEqual(self.client.post('/api/mission/start', json={'area_label':'Area'}).status_code, 401)
        self.assertEqual(self.client.post('/api/mission/stop').status_code, 401)
        self.assertEqual(self.client.post('/api/survivor-events/id/review', json={'verification':'confirmed'}).status_code, 401)
        self.assertEqual(self.client.get('/api/situational-report', headers=self.headers).status_code, 200)

    def test_library_is_scoped_to_verified_user(self):
        self.storage.list.return_value = [{'id':'clip','name':'clip.webm','metadata':{'size':12},'created_at':'2026-09-30'}]
        data=self.client.get('/api/recordings',headers=self.headers).get_json()
        self.assertEqual(data['recordings'][0]['name'],'clip.webm')
        self.assertEqual(self.storage.list.call_args.args[0],'operator-a')

    def test_links_cannot_access_another_user_folder(self):
        response=self.client.get('/api/recordings/link?name=operator-b/clip.webm',headers=self.headers)
        self.assertEqual(response.status_code,400)
        self.storage.create_signed_url.assert_not_called()
        self.storage.create_signed_url.return_value={'signedURL':'https://example.test/clip'}
        self.client.get('/api/recordings/link?name=clip.webm',headers=self.headers)
        self.storage.create_signed_url.assert_called_once_with('operator-a/clip.webm',3600)

    def test_upload_rejects_path_traversal_and_scopes_clip(self):
        response=self.client.post('/api/upload-to-storage',headers=self.headers,data={'filename':'../clip.webm','video':(io.BytesIO(b'video'),'clip.webm')})
        self.assertEqual(response.status_code,400)
        self.storage.upload.assert_not_called()
        self.storage.create_signed_url.return_value={'signedURL':'https://example.test/clip'}
        response=self.client.post('/api/upload-to-storage',headers=self.headers,data={'filename':'clip.webm','video':(io.BytesIO(b'video'),'clip.webm')})
        self.assertTrue(response.get_json()['success'])
        self.assertEqual(self.storage.upload.call_args.args[0],'operator-a/clip.webm')

    def test_stale_reading_is_not_live(self):
        self.module.latest_sensor_data['updated_at']=time.time()-20
        self.assertFalse(self.client.get('/api/sensor-data',headers=self.headers).get_json()['fresh'])
        self.module.latest_sensor_data['updated_at']=time.time()
        self.assertTrue(self.client.get('/api/sensor-data',headers=self.headers).get_json()['fresh'])

    def test_no_camera_results_are_unavailable(self):
        with patch.object(self.module, 'last_detection_at', None):
            self.assertFalse(self.client.get('/api/survivors',headers=self.headers).get_json()['available'])
        self.assertFalse(self.client.get('/api/device-status',headers=self.headers).get_json()['nightvision'])

    def test_history_persists_and_excludes_old_chart_samples(self):
        import sqlite3
        self.module.add_alert('detection','Possible survivor')
        now=time.time()
        with self.module.history_database() as db:
            db.execute('INSERT INTO samples VALUES (?, 30, 70, 35)',(now,))
            db.execute('INSERT INTO samples VALUES (?, 30, 70, 35)',(now-7200,))
        self.module.init_history()
        data=self.client.get('/api/history',headers=self.headers).get_json()
        self.assertEqual(data['alerts'][0]['message'],'Possible survivor')
        self.assertEqual(len(data['samples']),1)

if __name__=='__main__': unittest.main()
