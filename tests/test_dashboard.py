"""Hardware-free checks for history, freshness, and recording authorization."""
import importlib.util
from contextlib import contextmanager, ExitStack
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

# Load C extensions before temporarily replacing sys.modules for app import.
# Restoring a snapshot must not discard a newly loaded NumPy/OpenCV module.
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]

class DashboardTests(unittest.TestCase):
    viewer_id = '7e296a38-26a8-41c1-90c8-ec6908c68d33'
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
        env = {'SUPABASE_URL':'https://example.supabase.co','SUPABASE_ANON_KEY':'test','SUPABASE_SERVICE_ROLE_KEY':'test',
               'HISTORY_DB':str(Path(cls.temp.name)/'history.sqlite3'),
               'LOCAL_DATA_DIR':str(Path(cls.temp.name)/'local_data')}
        spec = importlib.util.spec_from_file_location('bimbot_test_app', ROOT / 'app.py')
        cls.module = importlib.util.module_from_spec(spec)
        # Ensure importing the application creates its test database outside the repository.
        with patch.dict(sys.modules, modules), patch.dict(os.environ, env):
            spec.loader.exec_module(cls.module)
        cls.module.HISTORY_DB = str(Path(cls.temp.name)/'history.sqlite3')
        cls.google_user = types.SimpleNamespace(id='operator-a', email='operator@example.test', app_metadata={'providers':['google']})
        cls.module._verify_token = lambda token: cls.google_user if token=='valid' else None
        cls.client = cls.module.app.test_client()
        cls.headers = {'Authorization':'Bearer valid'}

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def setUp(self):
        self.storage.reset_mock()
        self.module.sensor_health.update(error_code=None, last_attempt_at=None)

    @contextmanager
    def pipeline_inputs(self, **values):
        # Exercise the extracted shared analyzer while isolating its per-camera
        # temporal state. Models and optional thermal I/O remain app adapters.
        state = self.module.main_analysis
        state_names = {'prev_frame', 'motion_generation', 'person_tracker',
                       'stationary_timers', 'survivor_observations'}
        state_values = {name: value for name, value in values.items() if name in state_names}
        app_values = {name: value for name, value in values.items() if name not in state_names}
        if 'cv2' in app_values:
            state_values['cv'] = app_values['cv2']
        with ExitStack() as stack:
            stack.enter_context(patch.multiple(self.module, **app_values))
            stack.enter_context(patch.multiple(state, **state_values))
            yield

    def test_routes_require_auth(self):
        self.assertEqual(self.client.get('/api/sound-model').status_code, 401)
        self.assertEqual(self.client.post('/api/sound-classify', data=b'').status_code, 401)
        self.assertEqual(self.client.get('/api/position-data').status_code,401)
        for route in ['/api/history','/api/recordings','/api/local-recordings','/api/recordings/link','/api/device-status','/api/nightvision','/api/nightvision/light','/nightvision_feed','/api/camera-frame/main','/api/camera-frame/nightvision','/api/mission','/api/survivor-events','/api/situational-report','/api/thermal']:
            self.assertEqual(self.client.get(route).status_code,401)
        self.assertEqual(self.client.post('/api/local-recordings').status_code,401)
        self.assertEqual(self.client.post('/api/local-recordings/sync').status_code,401)
        self.assertEqual(self.client.post('/api/nightvision/light',json={'enabled':True}).status_code,401)

    def test_current_image_auth_rejects_url_credentials_before_touching_either_camera(self):
        with patch.object(self.module.main_camera, 'snapshot') as main, \
             patch.object(self.module.nightvision, 'snapshot') as night, \
             patch.object(self.module, '_verify_token') as verify:
            for source in ('main', 'nightvision'):
                response = self.client.get(f'/api/camera-frame/{source}')
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.headers['Cache-Control'], 'no-store')
                response = self.client.get(f'/api/camera-frame/{source}?access_token=valid',
                                           headers={'X-Camera-Viewer': self.viewer_id})
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.headers['Cache-Control'], 'no-store')
            main.assert_not_called()
            night.assert_not_called()
            verify.assert_not_called()

    def test_current_image_returns_atomic_metadata_and_scopes_viewer_to_source_and_owner(self):
        frame = {'state': 'frame', 'jpeg': b'generated-jpeg', 'sequence': 42,
                 'generation': 3, 'received_at': 123.5, 'age_ms': 12.75}
        headers = {**self.headers, 'X-Camera-Viewer': self.viewer_id,
                   'X-Camera-Sequence': '39', 'X-Camera-Generation': '3'}
        with patch.object(self.module.main_camera, 'snapshot', return_value=frame) as main, \
             patch.object(self.module.nightvision, 'snapshot', return_value=frame) as night:
            for source, command in [('main', main), ('nightvision', night)]:
                response = self.client.get(f'/api/camera-frame/{source}', headers=headers)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.mimetype, 'image/jpeg')
                self.assertEqual(response.data, frame['jpeg'])
                self.assertEqual(response.headers['X-Camera-Sequence'], '42')
                self.assertEqual(response.headers['X-Camera-Generation'], '3')
                self.assertEqual(float(response.headers['X-Camera-Received-At']), 123.5)
                self.assertEqual(float(response.headers['X-Camera-Age-Ms']), 12.75)
                self.assertEqual(response.headers['Cache-Control'], 'no-store')
                command.assert_called_once_with(('operator-a', self.viewer_id), sequence=39, generation=3)
        other = types.SimpleNamespace(id='operator-b', app_metadata={'providers': ['google']})
        with patch.object(self.module, '_verify_token', return_value=other), \
             patch.object(self.module.main_camera, 'snapshot', return_value={'state': 'pending'}) as main:
            response = self.client.get('/api/camera-frame/main', headers=headers)
            self.assertEqual(response.status_code, 204)
            main.assert_called_once_with(('operator-b', self.viewer_id), sequence=39, generation=3)

    def test_current_image_validation_never_starts_hardware(self):
        valid = {**self.headers, 'X-Camera-Viewer': self.viewer_id}
        invalid = [
            ({**valid, 'X-Camera-Viewer': ''}, 400),
            ({**valid, 'X-Camera-Viewer': 'not-a-uuid'}, 400),
            ({**valid, 'X-Camera-Sequence': '-2'}, 400),
            ({**valid, 'X-Camera-Sequence': '9223372036854775808'}, 400),
            ({**valid, 'X-Camera-Generation': 'invalid'}, 400),
            ({**valid, 'X-Camera-Generation': '9' * 100}, 400),
        ]
        with patch.object(self.module.main_camera, 'snapshot') as main, \
             patch.object(self.module.nightvision, 'snapshot') as night:
            for headers, expected in invalid:
                response = self.client.get('/api/camera-frame/main', headers=headers)
                self.assertEqual(response.status_code, expected)
                self.assertEqual(response.headers['Cache-Control'], 'no-store')
            response = self.client.get('/api/camera-frame/unrecognized', headers=valid)
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
            main.assert_not_called()
            night.assert_not_called()

    def test_current_image_pending_failed_and_busy_responses_are_uncached(self):
        headers = {**self.headers, 'X-Camera-Viewer': self.viewer_id}
        for state, expected in [('pending', 204), ('unavailable', 503), ('busy', 429)]:
            snapshot = {'state': state, 'message': 'No current image.'}
            with self.subTest(state=state), patch.object(self.module.main_camera, 'snapshot', return_value=snapshot):
                response = self.client.get('/api/camera-frame/main', headers=headers)
                self.assertEqual(response.status_code, expected)
                self.assertEqual(response.headers['Cache-Control'], 'no-store')
                self.assertNotIn('X-Camera-Sequence', response.headers)
                if state == 'pending':
                    self.assertEqual(response.data, b'')
                elif state == 'busy':
                    self.assertEqual(response.headers['Retry-After'], '1')

    def test_optional_capture_includes_failed_startup_once_after_auth_validation_and_robot_join(self):
        headers = {**self.headers, 'X-Camera-Viewer': self.viewer_id}
        order = []
        def pending(*_args, **_kwargs):
            order.append('camera-request')
            return {'state': 'pending'}
        with patch.object(self.module, '_capture_enabled', True), \
             patch.object(self.module, '_capture_started', False), \
             patch.object(self.module, 'robot_network', return_value={'robot_subnet': False}) as network, \
             patch.object(self.module.dashboard_check, 'start', side_effect=lambda: order.append('record')) as start, \
             patch.object(self.module.main_camera, 'snapshot', side_effect=pending) as main, \
             patch.object(self.module.nightvision, 'snapshot', return_value={'state': 'unavailable', 'message': 'No image.'}), \
             patch.object(self.module.main_camera, 'close_snapshot'):
            for path, request_headers, expected in [
                ('/api/camera-frame/main', {'X-Camera-Viewer': self.viewer_id}, 401),
                ('/api/camera-frame/main?access_token=valid', headers, 400),
                ('/api/camera-frame/main', self.headers, 400),
                ('/api/camera-frame/unknown', headers, 404),
            ]:
                self.assertEqual(self.client.get(path, headers=request_headers).status_code, expected)
            self.assertEqual(self.client.delete('/api/camera-frame/main', headers=headers).status_code, 204)
            network.assert_not_called()
            start.assert_not_called()
            main.assert_not_called()
            self.assertEqual(self.client.get('/api/camera-frame/main', headers=headers).status_code, 204)
            start.assert_not_called()
            order.clear()
            network.return_value = {'robot_subnet': True}
            self.assertEqual(self.client.get('/api/camera-frame/main', headers=headers).status_code, 204)
            self.assertEqual(order, ['record', 'camera-request'])
            self.assertEqual(self.client.get('/api/camera-frame/nightvision', headers=headers).status_code, 503)
            start.assert_called_once()
            self.assertEqual(network.call_count, 2, 'After starting, frame requests must not repeat network probes')

    def test_optional_capture_is_disabled_by_default_and_diagnostic_failure_does_not_block_video(self):
        headers = {**self.headers, 'X-Camera-Viewer': self.viewer_id}
        with patch.object(self.module, '_capture_started', False), \
             patch.object(self.module, 'robot_network', side_effect=OSError('diagnostic unavailable')) as network, \
             patch.object(self.module.dashboard_check, 'start') as start, \
             patch.object(self.module.main_camera, 'snapshot', return_value={'state': 'pending'}):
            with patch.object(self.module, '_capture_enabled', False):
                self.assertEqual(self.client.get('/api/camera-frame/main', headers=headers).status_code, 204)
                network.assert_not_called()
            with patch.object(self.module, '_capture_enabled', True):
                self.assertEqual(self.client.get('/api/camera-frame/main', headers=headers).status_code, 204)
                network.assert_called_once()
            start.assert_not_called()

    def test_current_image_delete_requires_same_origin_and_releases_only_the_signed_in_owner(self):
        client = self.module.app.test_client()
        token, _ = self.module.offline_sessions.create(self.google_user)
        client.set_cookie('bimbot_local_session', token)
        headers = {'X-Camera-Viewer': self.viewer_id.upper()}
        with patch.object(self.module.main_camera, 'close_snapshot') as close:
            for origin in (None, 'https://untrusted.example'):
                request_headers = dict(headers)
                if origin:
                    request_headers['Origin'] = origin
                response = client.delete('/api/camera-frame/main', headers=request_headers)
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.headers['Cache-Control'], 'no-store')
            close.assert_not_called()
            response = client.delete('/api/camera-frame/main', headers={**headers, 'Origin': 'http://localhost'})
            self.assertEqual(response.status_code, 204)
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
            close.assert_called_once_with(('operator-a', self.viewer_id), asynchronous=True)

    def test_current_image_rechecks_session_expiry_and_revocation_after_wait(self):
        for expires in (False, True):
            with self.subTest(expires=expires):
                client = self.module.app.test_client()
                token, identity = self.module.offline_sessions.create(self.google_user)
                client.set_cookie('bimbot_local_session', token)
                now = time.time()
                with patch.object(self.module.time, 'time', return_value=now) as clock:
                    def after_wait(*_args, **_kwargs):
                        if expires:
                            clock.return_value = identity['expires_at'] + 1
                        else:
                            self.module.offline_sessions.revoke(token)
                        return {'state': 'frame', 'jpeg': b'private-frame', 'sequence': 1,
                                'generation': 0, 'received_at': now, 'age_ms': 0}
                    with patch.object(self.module.main_camera, 'snapshot', side_effect=after_wait), \
                         patch.object(self.module.main_camera, 'close_snapshot') as close:
                        response = client.get('/api/camera-frame/main', headers={'X-Camera-Viewer': self.viewer_id})
                        self.assertEqual(response.status_code, 401)
                        self.assertNotIn(b'private-frame', response.data)
                        self.assertEqual(response.headers['Cache-Control'], 'no-store')
                        close.assert_called_once_with(('operator-a', self.viewer_id), asynchronous=True)

    def test_light_route_requires_same_origin_with_a_local_cookie(self):
        client = self.module.app.test_client()
        token, _ = self.module.offline_sessions.create(self.google_user)
        client.set_cookie('bimbot_local_session', token)
        with patch.object(self.module.nightvision_illumination, 'set_enabled',
                          return_value=({'supported':True}, 200)) as command:
            self.assertEqual(client.post('/api/nightvision/light',json={'enabled':True}).status_code,403)
            self.assertEqual(client.post('/api/nightvision/light',json={'enabled':True},
                                         headers={'Origin':'https://untrusted.example'}).status_code,403)
            command.assert_not_called()
            self.assertEqual(client.post('/api/nightvision/light',json={'enabled':True},
                                         headers={'Origin':'http://localhost'}).status_code,200)
            command.assert_called_once_with(True)

    def test_google_only_policy_and_signup_redirect(self):
        email_user = types.SimpleNamespace(id='password-user', app_metadata={'provider':'email'})
        with patch.object(self.module, '_verify_token', return_value=email_user):
            self.assertEqual(self.client.get('/api/history', headers=self.headers).status_code,403)
        self.assertEqual(self.client.get('/signup').status_code,302)
        self.assertEqual(self.client.get('/signup').headers['Location'],'/login')

    def test_google_device_session_records_and_downloads_without_cloud(self):
        client = self.module.app.test_client()
        origin = {'Origin':'http://localhost'}
        with patch.object(self.module.supabase_auth_client.auth, 'get_user', return_value=types.SimpleNamespace(user=self.google_user)) as verify:
            response = client.post('/api/local-session', headers={**origin, **self.headers})
            self.assertEqual(response.status_code,200)
            self.assertIsNone(response.json['session']['access_token'])
            verify.assert_called_once_with('valid')
        mp4 = b'\x00\x00\x00\x18ftypisom\x00\x00\x00\x00isommp42' + b'\x00\x00\x00\x08mdat'
        with patch.object(self.module.supabase_auth_client.auth, 'get_user', side_effect=ConnectionError('offline')) as verify:
            self.assertEqual(client.get('/api/history').status_code,200)
            # Cookie mutations need browser proof of same-origin intent.
            self.assertEqual(client.post('/api/local-recordings/sync').status_code,403)
            saved = client.post('/api/local-recordings', headers=origin, data={
                'filename':'offline-integration.mp4','source':'nightvision',
                'video':(io.BytesIO(mp4),'offline-integration.mp4','video/mp4')})
            self.assertEqual(saved.status_code,201,saved.json)
            self.assertEqual(saved.json['recording']['sync_state'],'pending')
            with client.get(saved.json['recording']['download_url']) as download:
                self.assertEqual(download.status_code,200)
                self.assertEqual(download.data,mp4)
            listed = client.get('/api/local-recordings').json
            self.assertTrue(any(row['id']==saved.json['recording']['id'] for row in listed['recordings']))
            self.storage.upload.assert_not_called()
            verify.assert_not_called()
        self.assertEqual(client.delete('/api/local-session',headers=origin).status_code,200)
        self.assertEqual(client.get('/api/local-recordings').status_code,401)

    def test_existing_camera_stream_closes_after_local_signout_or_expiry(self):
        for route, expires in [('/video_feed',False),('/nightvision_feed',True)]:
            client = self.module.app.test_client()
            token, _ = self.module.offline_sessions.create(self.google_user)
            client.set_cookie('bimbot_local_session',token)
            closed=[]
            now=time.time()
            with patch.object(self.module.time, 'time', return_value=now) as clock:
                def frames():
                    try:
                        yield b'first'
                        if expires:
                            clock.return_value=now+43201
                        else:
                            self.module.offline_sessions.revoke(token)
                            clock.return_value=now+3
                        yield b'second'
                    finally:
                        closed.append(True)
                with patch.object(self.module, 'generate_frames', frames), patch.object(self.module.nightvision, 'frames', frames), patch.object(self.module.nightvision, 'url', 'http://camera/stream'):
                    response=client.get(route, buffered=False)
                    self.assertEqual(response.status_code,200)
                    self.assertEqual(b''.join(response.response),b'first')
                    response.close()
                    self.assertEqual(closed,[True])

    def test_pages_share_safe_json_config_and_local_scripts_in_order(self):
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
                config, profile, auth, *scripts = parser.scripts
                self.assertEqual(profile['attrs']['type'], 'application/json')
                self.assertEqual(profile['attrs']['id'], 'bim-monitoring-profile')
                self.assertEqual(json.loads(profile['text'])['name'], 'conservative-2')
                if page == 'dashboard':
                    player, local_audio, headset_audio, movement, behavior = scripts
                    self.assertEqual(player['attrs']['src'], '/static/js/live_camera_player.js')
                    self.assertIn('defer', player['attrs'])
                    self.assertFalse(player['text'].strip())
                    self.assertEqual(local_audio['attrs']['src'], '/static/js/laptop_sound.js')
                    self.assertIn('defer', local_audio['attrs'])
                    self.assertFalse(local_audio['text'].strip())
                    self.assertEqual(headset_audio['attrs']['src'], '/static/js/headset_audio.js')
                    self.assertIn('defer', headset_audio['attrs'])
                    self.assertFalse(headset_audio['text'].strip())
                    self.assertEqual(movement['attrs']['src'], '/static/js/movement.js')
                    self.assertIn('defer', movement['attrs'])
                    self.assertFalse(movement['text'].strip())
                else:
                    behavior, = scripts
                self.assertEqual(config['attrs']['type'], 'application/json')
                self.assertEqual(config['attrs']['id'], 'bim-config')
                self.assertEqual(json.loads(config['text']), {'url': url, 'key': 'test'})
                self.assertEqual(auth['attrs']['src'], '/static/js/auth.js')
                self.assertEqual(behavior['attrs']['src'], f'/static/js/{page}.js')
                for script in [auth, behavior]:
                    self.assertIn('defer', script['attrs'])
                    self.assertFalse(script['text'].strip())
                for asset in ['css/common.css', 'js/auth.js', f'css/{page}.css', f'js/{page}.js']:
                    with self.client.get(f'/static/{asset}') as asset_response:
                        self.assertEqual(asset_response.status_code, 200)

    def test_sar_camera_pipeline_supplies_classifications_to_ui(self):
        frame = types.SimpleNamespace(shape=(480, 640, 3))
        detector = MagicMock()
        box = MagicMock()
        box.xyxy[0].tolist.return_value = [10, 20, 100, 250]
        box.conf = .94
        result = MagicMock()
        result.boxes = [box]
        detector.return_value = [result]
        pose = MagicMock()
        pose.return_value[0].keypoints = None
        # Classification contracts are independent of the asynchronous video
        # cadence. The shared reader/slow-inference lifecycle is tested separately.
        with self.pipeline_inputs(detection_model=detector, pose_model=pose, prev_frame=None):
            detections = self.module.analyze_main_frame(frame)
            deferred = self.module.accept_main_result(detections, time.time())
            deferred()
        detector.assert_called_once_with(frame, classes=[14], conf=.25)
        pose.assert_called_once_with(frame, conf=.25)
        response = self.client.get('/api/survivors', headers=self.headers).get_json()
        self.assertTrue(response['available'])
        self.assertEqual(response['survivors_found'], 1)
        self.assertEqual(response['detections'][0]['age'], 'Adult')
        self.assertEqual(response['detections'][0]['consciousness'], 'Unknown')
        self.assertIsNone(response['detections'][0]['motion_observed'])
        self.assertTrue(response['detections'][0]['track_id'])
        self.assertEqual(response['detections'][0]['thermal_alive'], 'No thermal camera')

    def test_heat_index_hot_reference_and_cool_screening(self):
        # NWS hot regression at90F/70% is about105.92F; cool values use the
        # screened simple expression instead of extrapolating that polynomial.
        hot = self.module.calculate_heat_index((90 - 32) * 5 / 9, 70)
        self.assertAlmostEqual(hot, (105.9220206 - 32) * 5 / 9, places=4)
        cool = self.module.calculate_heat_index((70 - 32) * 5 / 9, 50)
        self.assertAlmostEqual(cool, (69.525 - 32) * 5 / 9, places=5)

    def test_invalid_environment_values_do_not_become_zero_readings(self):
        for temperature, humidity in ((None, 50), (25, None), (True, 50),
                                      (float('nan'), 50), (25, float('inf')),
                                      (25, -1), (25, 101), (-41, 50), (86, 50)):
            with self.subTest(temperature=temperature, humidity=humidity), self.assertRaises(ValueError):
                self.module.calculate_heat_index(temperature, humidity)

    def test_risk_boundaries_and_scope(self):
        for temperature, heat_index, expected in ((34.99, 40.99, 'Low Risk'), (34, 41, 'Moderate Risk'),
                                                   (35, 20, 'Moderate Risk'), (34, 54, 'Severe Risk'), (41, 20, 'Severe Risk')):
            with patch.object(self.module, 'calculate_heat_index', return_value=heat_index):
                self.assertEqual(self.module.calculate_risk(temperature, 50)[0], expected)
        self.assertIn('other hazards are not assessed', self.module.calculate_risk(25, 50)[4])

    def test_missing_dht_field_never_refreshes_sensor_history(self):
        response = MagicMock(status_code=200);response.json.return_value = {'temp_c': 25}
        with patch.object(self.module.sensor_http, 'get', return_value=response), \
             patch.object(self.module, 'publish_sensor_reading') as publish, \
             patch.object(self.module.time, 'sleep', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):self.module.wifi_sensor_listener()
            publish.assert_not_called()

    def test_testing_guide_is_readable_without_starting_workers(self):
        with patch.object(self.module, 'start_workers') as workers:
            response = self.client.get('/testing')
            self.assertEqual(response.status_code, 200)
            self.assertIn('Movement is on hold', response.get_data(as_text=True))
            workers.assert_not_called()

    @staticmethod
    def generated_model_result(boxes, lying=None, confidence=1):
        import numpy as np
        rows = [types.SimpleNamespace(xyxy=np.array([box], dtype=float), conf=.94) for box in boxes]
        result = types.SimpleNamespace(boxes=rows, keypoints=None)
        if lying is not None:
            joints = []
            for box, is_lying in zip(boxes, lying):
                center = (box[0] + box[2]) / 2
                points = [[center, 30.] for _ in range(17)]
                points[15][1] = points[16][1] = 35. if is_lying else 100.
                joints.append(points)
            result.keypoints = types.SimpleNamespace(xy=np.array(joints), conf=np.full((len(boxes), 17), confidence))
        return [result]

    def test_main_pipeline_spatially_matches_reversed_pose_results(self):
        import cv2
        import numpy as np
        boxes = [(10, 10, 70, 110), (140, 10, 200, 110)]
        detector = MagicMock(return_value=self.generated_model_result(boxes))
        pose = MagicMock(return_value=self.generated_model_result(boxes[::-1], [False, True]))
        with self.pipeline_inputs(detection_model=detector, pose_model=pose, cv2=cv2,
                            get_thermal_frame=lambda: None, prev_frame=None, motion_generation=None,
                            person_tracker=self.module.PersonTracker(), stationary_timers={}):
            detections = self.module.analyze_main_frame(np.zeros((140, 240, 3), np.uint8))
        self.assertEqual([d['pose'] for d in detections], ['lying', 'upright'])
        self.assertTrue(all(d['pose_matched'] for d in detections))
        self.assertTrue(all(d['consciousness'] == 'Unknown' for d in detections))

    def test_main_pipeline_reorder_keeps_ids_and_independent_motion_and_timers(self):
        import cv2
        import numpy as np
        left, right = (10, 10, 70, 110), (140, 10, 200, 110)
        detector = MagicMock(side_effect=[self.generated_model_result([left, right]),
                                          self.generated_model_result([right, left]),
                                          self.generated_model_result([left])])
        pose = MagicMock(side_effect=[self.generated_model_result([left, right], [True, False]),
                                      self.generated_model_result([left, right], [True, False]),
                                      self.generated_model_result([left], [True])])
        base = np.zeros((140, 240, 3), np.uint8)
        changed = base.copy();changed[30:60, 20:50] = 255
        timers = {}
        with self.pipeline_inputs(detection_model=detector, pose_model=pose, cv2=cv2,
                            get_thermal_frame=lambda: None, prev_frame=None, motion_generation=None,
                            person_tracker=self.module.PersonTracker(), stationary_timers=timers):
            first = self.module.analyze_main_frame(base)
            second = self.module.analyze_main_frame(changed)
            self.assertEqual([d['track_id'] for d in second], [first[1]['track_id'], first[0]['track_id']])
            self.assertEqual([d['motion_observed'] for d in second], [False, True])
            self.assertIn(first[1]['track_id'], timers)
            self.assertNotIn(first[0]['track_id'], timers)
            self.module.analyze_main_frame(changed)
            self.assertNotIn(first[1]['track_id'], timers)

    def test_main_pipeline_missing_or_low_confidence_pose_stays_unknown(self):
        import cv2
        import numpy as np
        box = (10, 10, 70, 110)
        detector = MagicMock(return_value=self.generated_model_result([box]))
        for poses in (self.generated_model_result([(140, 10, 200, 110)], [True]),
                      self.generated_model_result([box], [True], confidence=.1)):
            with self.pipeline_inputs(detection_model=detector, pose_model=lambda *_a, **_k: poses,
                                cv2=cv2, get_thermal_frame=lambda: None, prev_frame=None,
                                motion_generation=None, person_tracker=self.module.PersonTracker(), stationary_timers={}):
                result = self.module.analyze_main_frame(np.zeros((140, 240, 3), np.uint8))[0]
            self.assertFalse(result['pose_matched'])
            self.assertEqual(result['pose'], 'unknown')
            self.assertEqual(result['injury'], 'Unknown')

    def test_main_pipeline_disconnect_discards_identity_and_immobility_state(self):
        import cv2
        import numpy as np
        box = (10, 10, 70, 110)
        model = MagicMock(return_value=self.generated_model_result([box], [True]))
        timers = {}
        with self.pipeline_inputs(detection_model=model, pose_model=model, cv2=cv2,
                            get_thermal_frame=lambda: None, prev_frame=None, motion_generation=None,
                            person_tracker=self.module.PersonTracker(), stationary_timers=timers):
            frame = np.zeros((140, 240, 3), np.uint8)
            before = self.module.analyze_main_frame(frame)[0]
            self.module.analyze_main_frame(frame)
            self.assertIn(before['track_id'], timers)
            self.module.clear_main_result()
            self.assertFalse(timers)
            after = self.module.analyze_main_frame(frame)[0]
            self.assertNotEqual(before['track_id'], after['track_id'])
            self.assertIsNone(after['motion_observed'])

    def test_main_pipeline_rejects_results_from_a_disconnected_generation(self):
        import cv2
        import numpy as np
        box = (10, 10, 70, 110)
        generation = self.module.main_camera.generation
        def detection(*_args, **_kwargs):
            self.module.main_camera.generation += 1
            return self.generated_model_result([box])
        tracker = self.module.PersonTracker()
        with patch.object(self.module.main_camera, 'generation', generation), \
             patch.object(self.module.main_camera, 'analysis_generation', generation), \
             self.pipeline_inputs(detection_model=detection,
                            pose_model=lambda *_a, **_k: self.generated_model_result([box], [True]),
                            cv2=cv2, get_thermal_frame=lambda: None, prev_frame=None,
                            motion_generation=None, person_tracker=tracker, stationary_timers={}):
            self.assertEqual(self.module.analyze_main_frame(np.zeros((140, 240, 3), np.uint8)), [])
            self.assertFalse(tracker.tracks)

    def test_main_pipeline_stale_source_discards_tracking_before_recovery(self):
        import cv2
        import numpy as np
        box = (10, 10, 70, 110)
        model = MagicMock(return_value=self.generated_model_result([box], [True]))
        tracker, timers = self.module.PersonTracker(), {}
        with patch.object(self.module.main_camera, 'analysis_received_at', None), \
             self.pipeline_inputs(detection_model=model, pose_model=model, cv2=cv2,
                            get_thermal_frame=lambda: None, prev_frame=None, motion_generation=None,
                            person_tracker=tracker, stationary_timers=timers):
            image = np.zeros((140, 240, 3), np.uint8)
            initial = self.module.analyze_main_frame(image)[0]
            self.module.analyze_main_frame(image)
            self.assertTrue(timers)
            self.module.main_camera.analysis_received_at = time.time() - 3
            self.assertEqual(self.module.analyze_main_frame(image), [])
            self.assertFalse(tracker.tracks)
            self.assertFalse(timers)
            self.module.main_camera.analysis_received_at = None
            recovered = self.module.analyze_main_frame(image)[0]
            self.assertNotEqual(initial['track_id'], recovered['track_id'])
            self.assertIsNone(recovered['motion_observed'])

    def test_temporal_gap_resets_the_retained_injury_timer(self):
        model = MagicMock(return_value=self.generated_model_result([(10, 10, 70, 110)], [True]))
        timers, clock = {}, [1.]
        observer = self.module.SurvivorObservations(clock=lambda: clock[0])
        with self.pipeline_inputs(detection_model=model, pose_model=model, cv2=cv2,
                            get_thermal_frame=lambda: None, prev_frame=None, motion_generation=None,
                            person_tracker=self.module.PersonTracker(), stationary_timers=timers,
                            survivor_observations=observer), patch.object(self.module.time, 'time', return_value=100) as wall:
            frame = np.zeros((140, 240, 3), np.uint8)
            self.module.analyze_main_frame(frame)
            clock[0] = 1.2
            initial = self.module.analyze_main_frame(frame)[0]
            self.assertEqual(timers[initial['track_id']], 100)
            clock[0], wall.return_value = 2.5, 140
            resumed = self.module.analyze_main_frame(frame)[0]
            self.assertEqual(resumed['immobility_seconds'], 0)
            self.assertEqual(timers[resumed['track_id']], 140)

    @contextmanager
    def night_inputs(self, detector, pose):
        night = self.module.nightvision
        night.person_analysis.reset()
        with patch.multiple(night, cv=cv2, detector=detector, pose_model=pose,
                            analysis_generation=None, analysis_received_at=None), \
             patch.object(night.person_analysis, 'cv', cv2):
            try:
                yield night
            finally:
                with night.condition:
                    night._clear_locked()

    def test_night_person_pipeline_has_same_details_and_separate_identity(self):
        boxes = [(10, 10, 70, 110), (140, 10, 200, 45)]
        detector = MagicMock(return_value=self.generated_model_result(boxes))
        pose = MagicMock(return_value=self.generated_model_result(boxes[::-1], [False, True]))
        with self.night_inputs(detector, pose) as night, \
             self.pipeline_inputs(detection_model=detector, pose_model=pose, cv2=cv2,
                                  get_thermal_frame=lambda: None, prev_frame=None, motion_generation=None,
                                  person_tracker=self.module.PersonTracker(), stationary_timers={}):
            image = np.zeros((140, 240, 3), np.uint8)
            main = self.module.analyze_main_frame(image)
            results = night._detect(image)
            self.assertEqual([item['age'] for item in results], ['Adult', 'Child'])
            self.assertEqual([item['pose'] for item in results], ['lying', 'upright'])
            self.assertTrue(all(item['source'] == 'nightvision' for item in results))
            self.assertTrue(all(item['age_years'] is None for item in results))
            self.assertTrue(all(item['consciousness'] == 'Unknown' for item in results))
            self.assertTrue(all(item['gesture_state'] == 'unknown' for item in results))
            self.assertTrue(all(item['thermal_alive'] == 'No thermal camera' for item in results))
            self.assertTrue(all(item['track_id'] != original['track_id'] for item, original in zip(results, main)))
            self.assertIsNot(night.person_analysis.stationary_timers, self.module.main_analysis.stationary_timers)

    def test_night_reset_clears_only_its_own_timers_and_main_result_is_unchanged(self):
        model = MagicMock(return_value=self.generated_model_result([(10, 10, 70, 110)], [True]))
        image = np.zeros((140, 240, 3), np.uint8)
        with self.night_inputs(model, model) as night, \
             self.pipeline_inputs(detection_model=model, pose_model=model, cv2=cv2,
                                  get_thermal_frame=lambda: None, prev_frame=None, motion_generation=None,
                                  person_tracker=self.module.PersonTracker(), stationary_timers={}):
            main = self.module.analyze_main_frame(image)
            self.module.analyze_main_frame(image)
            self.module.accept_main_result(main, time.time())
            first = night._detect(image)
            night._detect(image)
            self.assertTrue(night.person_analysis.stationary_timers)
            self.assertTrue(self.module.main_analysis.stationary_timers)
            with night.condition:
                night._clear_locked()
            self.assertFalse(night.person_analysis.stationary_timers)
            self.assertTrue(self.module.main_analysis.stationary_timers)
            self.assertEqual(self.module.latest_detections, main)
            resumed = night._detect(image)
            self.assertNotEqual(resumed[0]['track_id'], first[0]['track_id'])
            self.assertIsNone(resumed[0]['motion_observed'])
            self.assertEqual(self.client.get('/api/survivors', headers=self.headers).get_json()['survivors_found'], 1)

    def test_night_old_source_and_generation_cannot_retain_conditions(self):
        model = MagicMock(return_value=self.generated_model_result([(10, 10, 70, 110)], [True]))
        image = np.zeros((140, 240, 3), np.uint8)
        with self.night_inputs(model, model) as night, \
             patch.object(night, 'analysis_received_at', None), \
             patch.object(night, 'analysis_generation', night.generation):
            night._detect(image); night._detect(image)
            self.assertTrue(night.person_analysis.stationary_timers)
            night.analysis_received_at = time.time() - 3
            self.assertEqual(night._detect(image), [])
            self.assertFalse(night.person_analysis.stationary_timers)
            night.analysis_received_at = None
            night.generation += 1
            self.assertEqual(night._detect(image), [])
            self.assertFalse(night.person_analysis.person_tracker.tracks)

    def test_night_wave_is_temporal_and_lost_pose_resets_it(self):
        box = (10, 5, 110, 135)
        detector = MagicMock(return_value=self.generated_model_result([box]))
        pose_result = self.generated_model_result([box], [False])
        points = pose_result[0].keypoints.xy[0]
        points[5] = [40, 60]; points[6] = [80, 60]
        points[10] = [80, 95]
        pose = MagicMock(return_value=pose_result)
        clock = [1.]
        observer = self.module.SurvivorObservations(clock=lambda: clock[0])
        with self.night_inputs(detector, pose) as night, \
             patch.object(night.person_analysis, 'survivor_observations', observer):
            image = np.zeros((140, 240, 3), np.uint8)
            results = []
            for i, x in enumerate([40, 40, 65, 40, 65, 40, 65]):
                clock[0] = 1 + i * .2
                points[9] = [x, 20]
                results = night._detect(image)
            self.assertEqual(results[0]['gesture_state'], 'possible_wave')
            self.assertTrue(results[0]['gesture_requires_verification'])
            pose_result[0].keypoints = None
            clock[0] += .2
            self.assertEqual(night._detect(image)[0]['gesture_state'], 'unknown')

    def test_night_actual_pipeline_publishes_authenticated_details_and_clears_stale(self):
        model = MagicMock(return_value=self.generated_model_result([(10, 10, 70, 110)], [False]))
        with self.night_inputs(model, model) as night:
            jpeg = cv2.imencode('.jpg', np.zeros((140, 240, 3), np.uint8))[1].tobytes()
            night.publish(jpeg, infer=True)
            with night.condition:
                self.assertTrue(night.condition.wait_for(lambda: night.detected_at is not None, timeout=2))
            response = self.client.get('/api/nightvision', headers=self.headers).get_json()
            self.assertTrue(response['person_analysis_enabled'])
            self.assertEqual(response['detections'][0]['age'], 'Adult')
            self.assertIn('gesture', response['detections'][0])
            self.assertEqual(self.client.get('/api/nightvision').status_code, 401)
            with night.condition:
                night.detected_at = time.time() - 3
            stale = self.client.get('/api/nightvision', headers=self.headers).get_json()
            self.assertEqual(stale['detections'], [])
            self.assertFalse(stale['detections_available'])


    def test_sar_sensor_rules_supply_ui_and_history(self):
        response = MagicMock(status_code=200)
        response.json.return_value = {'temp_c': 36, 'humidity': 72}
        with patch.object(self.module.sensor_http, 'get', return_value=response), patch.object(self.module.time, 'sleep', side_effect=KeyboardInterrupt):
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

    def test_dht_timeout_recovers_without_a_camera_or_server_restart(self):
        response = MagicMock(status_code=200)
        response.json.return_value = {'temp_c': 28, 'humidity': 65}
        observed = []
        def sleep(_seconds):
            observed.append(self.client.get('/api/sensor-data', headers=self.headers).get_json())
            if len(observed) == 2:
                raise KeyboardInterrupt
        previous = {**self.module.latest_sensor_data, 'updated_at': time.time()}
        def publish():
            self.module.latest_sensor_data['updated_at'] = time.time()
        with patch.object(self.module, 'latest_sensor_data', previous), \
             patch.object(self.module, 'publish_sensor_reading', side_effect=publish), \
             patch.object(self.module.sensor_http, 'get', side_effect=[self.module.requests.Timeout(), response]) as get, \
             patch.object(self.module.time, 'sleep', side_effect=sleep), self.assertRaises(KeyboardInterrupt):
            self.module.wifi_sensor_listener()
        self.assertTrue(observed[0]['fresh'])
        self.assertTrue(observed[0]['retrying'])
        self.assertEqual(observed[0]['updated_at'], previous['updated_at'])
        self.assertEqual(observed[0]['error_code'], 'timeout')
        self.assertTrue(observed[1]['fresh'])
        self.assertEqual(observed[1]['temperature'], 28)
        self.assertIsNone(observed[1]['error_code'])
        self.assertFalse(self.module.sensor_http.trust_env)
        get.assert_called_with(self.module.SENSOR_URL, timeout=(1, 2), allow_redirects=False)
        response.close.assert_called_once()

    def test_internal_system_check_requires_auth_origin_and_never_starts_a_camera(self):
        self.assertEqual(self.client.post('/api/system-check').status_code, 401)
        self.assertEqual(self.client.post('/api/system-check', headers=self.headers).status_code, 403)
        with patch.dict(self.module.save_check.__globals__, robot_network=lambda: {'ipv4': '192.168.4.3', 'robot_subnet': True}), \
             patch.object(self.module.main_camera, 'snapshot') as main, \
             patch.object(self.module.nightvision, 'snapshot') as night:
            response = self.client.post('/api/system-check', headers={**self.headers, 'Origin': 'http://localhost'})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
            report = response.get_json()['report']
            self.assertTrue(report['network']['robot_subnet'])
            self.assertNotIn('detections', report['cameras']['main'])
            self.assertNotIn('grid', report['thermal'])
            saved = Path(self.module.LOCAL_DATA_DIR) / 'diagnostics/latest_system_check.json'
            self.assertEqual(json.loads(saved.read_text()), report)
            main.assert_not_called(); night.assert_not_called()

    def test_sensor_responses_are_not_cached(self):
        for route in ['/api/sensor-data', '/api/thermal-data']:
            self.assertEqual(self.client.get(route, headers=self.headers).headers['Cache-Control'], 'no-store')

    def test_recent_dht_retry_keeps_its_original_expiry(self):
        with patch.object(self.module, 'latest_sensor_data', {'updated_at': 100, 'temperature': 27}), \
             patch.dict(self.module.sensor_health, error_code='timeout'), \
             patch.object(self.module.time, 'time', return_value=101) as clock:
            recent = self.client.get('/api/sensor-data', headers=self.headers).get_json()
            self.assertTrue(recent['fresh'])
            self.assertTrue(recent['retrying'])
            self.assertEqual(recent['updated_at'], 100)
            clock.return_value = 110
            self.assertFalse(self.client.get('/api/sensor-data', headers=self.headers).get_json()['fresh'])

    def test_dashboard_recording_requires_auth_and_same_origin(self):
        self.assertEqual(self.client.get('/api/system-check/recording').status_code, 401)
        self.assertEqual(self.client.post('/api/system-check/recording', headers=self.headers).status_code, 403)
        with patch.object(self.module.dashboard_check, 'start', return_value=True) as start:
            result = self.client.post('/api/system-check/recording', headers={**self.headers, 'Origin':'http://localhost'})
            self.assertEqual(result.status_code, 202)
            start.assert_called_once()
        self.assertEqual(self.client.get('/api/system-check/recording', headers=self.headers).headers['Cache-Control'], 'no-store')

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

    def test_night_camera_status_does_not_open_hardware_and_unconfigured_feed_is_503(self):
        with patch.object(self.module.nightvision, 'url', None), patch.object(self.module.requests, 'get') as get:
            status = self.client.get('/api/nightvision', headers=self.headers)
            self.assertEqual(status.status_code, 200)
            self.assertFalse(status.get_json()['connected'])
            self.assertEqual(self.client.get('/nightvision_feed', headers=self.headers).status_code, 503)
            get.assert_not_called()

    def test_night_stream_response_closes_subscription(self):
        closed = []
        def frames():
            try:
                yield b'--frame\r\nContent-Type: image/jpeg\r\n\r\njpeg\r\n'
                yield b'second'
            finally:
                closed.append(True)
        with patch.object(self.module.nightvision, 'url', 'http://camera/stream'), patch.object(self.module.nightvision, 'frames', frames):
            response = self.client.get('/nightvision_feed', headers=self.headers, buffered=False)
            self.assertEqual(response.status_code, 200)
            self.assertIn('multipart/x-mixed-replace', response.content_type)
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
            response.close()
            self.assertEqual(closed, [True])

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
