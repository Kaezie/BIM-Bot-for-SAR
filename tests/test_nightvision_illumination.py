"""Hardware-free tests of identity checks, light acknowledgements and HTTP bounds."""
import json
import unittest
from unittest.mock import MagicMock

from flask import Flask
import requests

from features.nightvision_illumination import NightVisionIllumination, FIRMWARE_ID


def camera_status(enabled=False):
    return {'firmware': FIRMWARE_ID, 'capabilities': ['white_led'],
            'illumination': {'enabled': enabled, 'brightness': 32 if enabled else 0,
                             'lease_ms': 15000}}


def response(payload=None, status=200, content_type='application/json', body=None):
    result = MagicMock()
    result.__enter__.return_value = result
    result.status_code = status
    result.headers = {'Content-Type': content_type}
    result.iter_content.return_value = [body if body is not None else json.dumps(payload).encode()]
    return result


class NightVisionIlluminationTests(unittest.TestCase):
    def setUp(self):
        self.session = MagicMock()
        self.session.__enter__.return_value = self.session
        self.factory = MagicMock(return_value=self.session)
        self.light = NightVisionIllumination('http://192.168.4.2:81/stream',
                                            'http://192.168.4.1:81/stream', self.factory)

    def test_constructing_the_adapter_does_not_contact_a_camera(self):
        self.factory.assert_not_called()

    def test_status_uses_control_port_without_mutating_or_sending_proxy_credentials(self):
        self.session.request.return_value = response(camera_status())
        payload, status = self.light.status()
        self.assertEqual(status, 200)
        self.assertFalse(payload['illumination']['enabled'])
        self.assertTrue(payload['supported'])
        self.assertFalse(self.session.trust_env)
        self.session.request.assert_called_once_with(
            'GET', 'http://192.168.4.2:80/status', timeout=(1, 2), allow_redirects=False, stream=True)

    def test_enabling_first_checks_firmware_then_requires_the_actual_acknowledgement(self):
        self.session.request.side_effect = [response(camera_status()), response(camera_status(True))]
        payload, status = self.light.set_enabled(True)
        self.assertEqual(status, 200)
        self.assertEqual(payload['illumination'], {'enabled': True, 'brightness': 32, 'lease_ms': 15000})
        self.assertEqual(self.session.request.call_args_list[0].args,
                         ('GET', 'http://192.168.4.2:80/status'))
        self.session.request.assert_called_with(
            'POST', 'http://192.168.4.2:80/light', params={'enabled': '1'},
            timeout=(1, 2), allow_redirects=False, stream=True)

    def test_disabling_also_verifies_the_spare_and_uses_post(self):
        self.session.request.side_effect = [response(camera_status(True)), response(camera_status())]
        payload, status = self.light.set_enabled(False)
        self.assertEqual(status, 200)
        self.assertFalse(payload['illumination']['enabled'])
        self.assertEqual(self.session.request.call_args.kwargs['params'], {'enabled': '0'})

    def test_missing_spare_config_never_makes_a_request(self):
        self.light.camera_url = None
        payload, status = self.light.set_enabled(True)
        self.assertEqual((status, payload['code']), (503, 'not_configured'))
        self.factory.assert_not_called()

    def test_original_camera_or_unsafe_urls_never_receive_a_light_command(self):
        for url in ['http://192.168.4.1:81/stream', 'https://192.168.4.2:81/stream',
                    'http://127.0.0.1:81/stream', 'http://8.8.8.8:81/stream',
                    'http://camera.local:81/stream', 'http://192.168.4.2:80/stream',
                    'http://192.168.4.2:81/control', 'http://192.168.4.2:81/stream?enabled=1',
                    'http://192.168.4.2:81/stream#foo', 'http://user:secret@192.168.4.2:81/stream',
                    'http://169.254.1.1:81/stream', 'http://224.0.0.1:81/stream']:
            with self.subTest(url=url):
                self.light.camera_url = url
                payload, status = self.light.set_enabled(True)
                self.assertEqual((status, payload['code']), (409, 'invalid_target'))
        self.factory.assert_not_called()

    def test_a_camera_with_other_firmware_or_no_pwm_capability_is_not_controlled(self):
        for payload in [{}, {'firmware': 'original-camera', 'capabilities': ['white_led']},
                        {**camera_status(), 'capabilities': []},
                        {**camera_status(), 'capabilities': 'white_led'}]:
            with self.subTest(payload=payload):
                self.session.request.reset_mock()
                self.session.request.return_value = response(payload)
                result, status = self.light.set_enabled(True)
                self.assertEqual((status, result['code']), (409, 'unsupported_firmware'))
                self.assertEqual(self.session.request.call_count, 1)

    def test_old_firmware_and_redirects_do_not_trigger_a_post_or_follow_a_redirect(self):
        for code in (301, 302, 303, 307, 308, 404, 405):
            with self.subTest(code=code):
                self.session.request.reset_mock()
                self.session.request.return_value = response(status=code)
                payload, status = self.light.set_enabled(True)
                self.assertEqual((status, payload['code']), (409, 'unsupported_firmware'))
                self.assertEqual(self.session.request.call_count, 1)
                self.assertFalse(self.session.request.call_args.kwargs['allow_redirects'])

    def test_timeout_clears_confirmation_and_does_not_expose_exception_text(self):
        self.session.request.side_effect = requests.Timeout('private upstream details')
        payload, status = self.light.set_enabled(True)
        self.assertEqual((status, payload['code']), (503, 'unreachable'))
        self.assertIsNone(payload['illumination'])
        self.assertNotIn('private upstream details', json.dumps(payload))
        self.assertEqual(self.session.request.call_count, 1)

    def test_timeout_after_sending_command_never_reports_a_confirmed_light_state(self):
        self.session.request.side_effect = [response(camera_status()), requests.Timeout('no acknowledgement')]
        payload, status = self.light.set_enabled(True)
        self.assertEqual((status, payload['code']), (503, 'unreachable'))
        self.assertIsNone(payload['illumination'])
        self.assertEqual(self.session.request.call_count, 2)

    def test_invalid_json_content_type_and_oversized_payload_are_rejected(self):
        for candidate in [response(body=b'{invalid'), response(body=b'\xff'),
                          response(camera_status(), content_type='text/html'),
                          response(body=b' ' * 4097)]:
            with self.subTest(candidate=candidate):
                self.session.request.reset_mock()
                self.session.request.return_value = candidate
                payload, status = self.light.set_enabled(True)
                self.assertEqual((status, payload['code']), (502, 'invalid_response'))
                self.assertEqual(self.session.request.call_count, 1)

    def test_bad_light_schema_is_not_treated_as_an_on_confirmation(self):
        for fields in [{'enabled': 1}, {'brightness': True}, {'brightness': 255},
                       {'enabled': True, 'brightness': 0}, {'brightness': 32},
                       {'lease_ms': 15000.0}, {'lease_ms': 0}]:
            with self.subTest(fields=fields):
                value = camera_status()
                value['illumination'].update(fields)
                self.session.request.reset_mock()
                self.session.request.return_value = response(value)
                payload, status = self.light.set_enabled(True)
                self.assertEqual((status, payload['code']), (502, 'invalid_response'))
                self.assertIsNone(payload['illumination'])
                self.assertEqual(self.session.request.call_count, 1)

    def test_no_optimistic_on_if_camera_does_not_apply_command(self):
        self.session.request.side_effect = [response(camera_status()), response(camera_status())]
        payload, status = self.light.set_enabled(True)
        self.assertEqual((status, payload['code']), (502, 'command_not_applied'))
        self.assertIsNone(payload['illumination'])

    def test_command_response_must_also_match_verified_firmware(self):
        self.session.request.side_effect = [response(camera_status()), response({'enabled': True})]
        payload, status = self.light.set_enabled(True)
        self.assertEqual((status, payload['code']), (409, 'unsupported_firmware'))
        self.assertIsNone(payload['illumination'])

    def test_direct_calls_require_a_real_boolean(self):
        for value in (None, 'true', 'false', 0, 1, [], {}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.light.set_enabled(value)
        self.factory.assert_not_called()

    def test_route_rejects_malformed_commands_and_caches_no_light_state(self):
        # Actual Google/cookie authorization is covered by DashboardTests; this
        # isolated route test exercises input validation without a camera.
        app = Flask(__name__)
        self.light.register(app, lambda handler: handler)
        client = app.test_client()
        for payload in (None, [], {}, {'enabled': 1}, {'enabled': 'false'},
                        {'enabled': True, 'url': 'http://192.168.4.1'}):
            with self.subTest(payload=payload):
                self.assertEqual(client.post('/api/nightvision/light', json=payload).status_code, 400)
        self.factory.assert_not_called()
        self.session.request.return_value = response(camera_status())
        result = client.get('/api/nightvision/light')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.headers['Cache-Control'], 'no-store')


if __name__ == '__main__':
    unittest.main()
