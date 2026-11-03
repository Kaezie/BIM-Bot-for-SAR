"""Mocked safety and verification checks for the read-only thermal diagnostic."""
from contextlib import ExitStack
import ast
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from requests import Response
from requests.exceptions import Timeout

from scripts import check_thermal_sensor as checker


def payload(sequence_number=1, **overrides):
    data = {'sensor': 'MLX90640', 'fresh': True, 'frame_age_ms': 100,
            'sequence': sequence_number, 'grid': [[26.0] * 32 for _ in range(24)]}
    data.update(overrides)
    return data


class ThermalCheckTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.network = self.stack.enter_context(patch.object(checker, 'robot_ip', return_value='192.168.4.4'))
        self.direct = self.stack.enter_context(patch.object(checker, 'fetch_json'))
        self.session = checker.requests.Session()
        self.addCleanup(self.session.close)
        self.real_get = self.session.get
        self.production = self.stack.enter_context(patch.object(self.session, 'get'))
        self.closed = self.stack.enter_context(patch.object(self.session, 'close', wraps=self.session.close))
        self.session_factory = self.stack.enter_context(patch.object(checker.requests, 'Session', return_value=self.session))
        self.now = 0.0
        self.stack.enter_context(patch.object(checker.time, 'monotonic', side_effect=lambda: self.now))
        self.stack.enter_context(patch.object(checker.time, 'sleep', side_effect=self.advance))
        self.stack.enter_context(patch('builtins.print'))

    def advance(self, seconds):
        self.now += seconds

    def production_payload(self, data=None):
        response = Response()
        response.status_code = 200
        response._content = json.dumps(data if data is not None else payload(100)).encode()
        self.production.return_value = response

    def run_main(self):
        self.stack.enter_context(patch.object(checker.sys, 'argv', ['check_thermal_sensor.py']))
        save = self.stack.enter_context(patch.object(checker, 'save'))
        identify = self.stack.enter_context(patch.object(checker, 'identify'))
        check = self.stack.enter_context(patch.object(checker, 'check'))
        pool = self.stack.enter_context(patch.object(checker, 'ThreadPoolExecutor'))
        pool.return_value.__enter__.return_value.map.side_effect = lambda function, hosts: map(function, hosts)
        return save, identify, check

    def test_off_network_refuses_without_any_probe(self):
        save, identify, check = self.run_main()
        self.network.return_value = None
        self.assertEqual(checker.main(), 2)
        identify.assert_not_called()
        check.assert_not_called()
        self.direct.assert_not_called()
        self.production.assert_not_called()
        self.assertEqual(save.call_args.args[0]['phase'], 'robot_network_not_observed')

    def test_discovery_excludes_mac_and_original_camera(self):
        save, identify, check = self.run_main()
        self.network.return_value = '192.168.4.2'
        identify.side_effect = lambda host: {'host': host, 'matching_identity': host == '192.168.4.3'}
        check.return_value = {'phase': 'verified', 'configured': False}
        self.assertEqual(checker.main(), 0)
        hosts = [call.args[0] for call in identify.call_args_list]
        self.assertNotIn('192.168.4.1', hosts)
        self.assertNotIn('192.168.4.2', hosts)
        check.assert_called_once_with('192.168.4.3', 30, 'en0')
        self.assertFalse(save.call_args.args[0]['configured'])

    def test_ambiguous_or_missing_spare_identity_never_checks_sensor(self):
        save, identify, check = self.run_main()
        for matching_hosts, expected in (
                ((), 'spare_not_identified'),
                (('192.168.4.2', '192.168.4.3'), 'multiple_spares_found')):
            with self.subTest(phase=expected):
                identify.side_effect = lambda host: {'host': host, 'matching_identity': host in matching_hosts}
                self.assertEqual(checker.main(), 2)
                self.assertEqual(save.call_args.args[0]['phase'], expected)
                check.assert_not_called()

    def test_network_change_during_discovery_invalidates_result(self):
        save, identify, check = self.run_main()
        identify.side_effect = lambda host: {'host': host, 'matching_identity': host == '192.168.4.2'}
        self.network.side_effect = ['192.168.4.4', '192.168.4.5']
        self.assertEqual(checker.main(), 1)
        check.assert_not_called()
        self.assertEqual(save.call_args.args[0]['phase'], 'robot_network_changed')

    def test_identification_requires_exact_firmware_and_discards_private_fields(self):
        for firmware, expected in (('other-device', False), (checker.FIRMWARE, True)):
            with self.subTest(firmware=firmware):
                self.direct.return_value = {'firmware': firmware, 'camera_ready': True,
                                            'thermal': {'enabled': True, 'fresh': True},
                                            'private': 'SYNTHETIC_SECRET'}
                result = checker.identify('192.168.4.2')
                self.assertEqual(result['matching_identity'], expected)
                self.assertNotIn('SYNTHETIC_SECRET', json.dumps(result))

    def test_known_thermal_diagnostics_require_verified_firmware(self):
        states = ('disabled', 'waiting_for_camera', 'initializing', 'task_unavailable',
                  'sensor_unavailable', 'frame_unavailable', 'invalid_frame', 'ready', 'cache_busy')
        for state in states:
            with self.subTest(state=state):
                self.direct.return_value = {
                    'firmware': checker.FIRMWARE, 'camera_ready': True,
                    'thermal': {'enabled': True, 'fresh': False, 'state': state,
                                'frame_age_ms': 6000.5, 'sequence': 42,
                                'private': 'SYNTHETIC_SECRET'},
                }
                result = checker.identify('192.168.4.2')
                self.assertEqual(result['thermal_state'], state)
                self.assertEqual(result['thermal_frame_age_ms'], 6000.5)
                self.assertEqual(result['thermal_sequence'], 42)
                self.assertTrue(result['camera_ready'])
                self.assertTrue(result['thermal_enabled'])
                self.assertFalse(result['thermal_fresh'])
                self.assertNotIn('SYNTHETIC_SECRET', json.dumps(result))

        self.direct.return_value['firmware'] = 'other-device'
        result = checker.identify('192.168.4.2')
        self.assertFalse(result['matching_identity'])
        self.assertTrue(result['camera_ready'])
        self.assertTrue(result['thermal_enabled'])
        for key in ('thermal_state', 'thermal_frame_age_ms', 'thermal_sequence'):
            self.assertNotIn(key, result)

    def test_invalid_thermal_status_metadata_is_omitted_without_hiding_identity(self):
        cases = {
            'state': ('SYNTHETIC_SECRET', '', None, True, 1, [], {}),
            'frame_age_ms': ('SYNTHETIC_SECRET', None, True, -1, float('nan'),
                             float('inf'), -float('inf'), [], {}),
            'sequence': ('SYNTHETIC_SECRET', None, True, -1, 1.0, float('nan'),
                         float('inf'), [], {}),
        }
        names = {'state': 'thermal_state', 'frame_age_ms': 'thermal_frame_age_ms',
                 'sequence': 'thermal_sequence'}
        for field, invalid_values in cases.items():
            for invalid in invalid_values:
                with self.subTest(field=field, invalid=repr(invalid)):
                    self.direct.return_value = {
                        'firmware': checker.FIRMWARE, 'camera_ready': True,
                        'thermal': {'enabled': True, 'fresh': True, 'state': 'ready',
                                    'frame_age_ms': 100, 'sequence': 1, field: invalid},
                    }
                    result = checker.identify('192.168.4.2')
                    self.assertTrue(result['matching_identity'])
                    self.assertNotIn(names[field], result)
                    self.assertTrue(result['camera_ready'])
                    self.assertTrue(result['thermal_enabled'])
                    self.assertTrue(result['thermal_fresh'])
                    self.assertNotIn('SYNTHETIC_SECRET', json.dumps(result, allow_nan=False))

    def test_thermal_status_metadata_handles_zero_and_missing_payloads(self):
        for age in (0, 100, 4999, 5000, 6000.5):
            with self.subTest(age=age):
                self.direct.return_value = {'firmware': checker.FIRMWARE,
                                            'thermal': {'frame_age_ms': age, 'sequence': 0}}
                result = checker.identify('192.168.4.2')
                self.assertEqual(result['thermal_frame_age_ms'], age)
                self.assertEqual(result['thermal_sequence'], 0)
        for thermal in (None, [], 'SYNTHETIC_SECRET', {}):
            with self.subTest(thermal=repr(thermal)):
                self.direct.return_value = {'firmware': checker.FIRMWARE, 'thermal': thermal}
                result = checker.identify('192.168.4.2')
                self.assertTrue(result['matching_identity'])
                for key in ('thermal_state', 'thermal_frame_age_ms', 'thermal_sequence'):
                    self.assertNotIn(key, result)
                self.assertNotIn('SYNTHETIC_SECRET', json.dumps(result))

    def test_two_advancing_real_frames_and_production_freshness_verify(self):
        self.direct.side_effect = [payload(10), payload(11)]
        self.production_payload()
        result = checker.check('192.168.4.2', 4, 'en0')
        self.assertEqual(result['phase'], 'verified')
        self.assertEqual([frame['sequence'] for frame in result['frames']], [10, 11])
        self.assertTrue(result['production']['fresh'])
        self.assertFalse(result['configured'])

    def test_direct_production_transport_avoids_proxy_and_netrc_and_closes(self):
        self.direct.side_effect = [payload(10), payload(11)]
        response = Response()
        response.status_code = 200
        response._content = json.dumps(payload(100)).encode()
        # Exercise real request preparation, stopping before any socket is opened.
        with patch.object(self.session, 'get', side_effect=self.real_get), \
                patch.object(self.session, 'send', return_value=response) as send, \
                patch('requests.sessions.get_environ_proxies', side_effect=AssertionError('Proxy lookup prohibited.')) as proxies, \
                patch('requests.sessions.get_netrc_auth', side_effect=AssertionError('Credential lookup prohibited.')) as netrc:
            result = checker.check('192.168.4.2', 4, 'en0')
        self.assertEqual(result['phase'], 'verified')
        self.assertFalse(self.session.trust_env)
        self.session_factory.assert_called_once_with()
        self.closed.assert_called_once_with()
        proxies.assert_not_called()
        netrc.assert_not_called()
        self.assertEqual(send.call_count, 2)
        for call in send.call_args_list:
            self.assertEqual(call.kwargs['proxies'], {})

    def test_production_session_closes_on_network_change_and_deadline(self):
        for addresses in ((None,), ('192.168.4.2',),
                          ('192.168.4.4', None),
                          ('192.168.4.4', '192.168.4.4', '192.168.4.5')):
            with self.subTest(addresses=addresses):
                self.now = 0
                self.closed.reset_mock()
                self.network.side_effect = addresses
                self.direct.return_value = payload(10)
                self.production_payload()
                result = checker.check('192.168.4.2', 4, 'en0')
                self.assertEqual(result['phase'], 'robot_network_changed')
                self.closed.assert_called_once_with()
                self.assertFalse(self.session.trust_env)
        self.now = 0
        self.closed.reset_mock()
        self.network.side_effect = None
        self.network.return_value = '192.168.4.4'
        result = checker.check('192.168.4.2', 4, 'en0')
        self.assertEqual(result['phase'], 'sensor_not_verified')
        self.closed.assert_called_once_with()

    def test_dashboard_telemetry_uses_its_dedicated_direct_session(self):
        # Execute only transport wiring from source; importing the app would load
        # private settings and models, which are unnecessary for this check.
        source = ast.parse((Path(checker.ROOT) / 'app.py').read_text())
        names = {'telemetry_http', 'telemetry'}
        statements = [node for node in source.body if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id in names
            or isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name)
            and target.value.id == 'telemetry_http' for target in node.targets)]
        transport = MagicMock()
        constructor = MagicMock()
        namespace = {'requests': SimpleNamespace(Session=lambda: transport), 'Telemetry': constructor,
                     'os': SimpleNamespace(environ={'THERMAL_DATA_URL': 'http://192.168.4.2/thermal'})}
        exec(compile(ast.Module(body=statements, type_ignores=[]), 'app-transport-only', 'exec'), namespace)
        self.assertIs(transport.trust_env, False)
        urls, http = constructor.call_args.args
        self.assertEqual(urls['thermal'], 'http://192.168.4.2/thermal')
        self.assertIs(http, transport)

    def test_static_frames_never_verify(self):
        self.direct.return_value = payload(10)
        self.production_payload()
        result = checker.check('192.168.4.2', 4, 'en0')
        self.assertEqual(result['phase'], 'sensor_not_verified')
        self.assertEqual(len(result['frames']), 1)

    def test_invalid_or_simulated_direct_frames_never_verify(self):
        cases = ({'fresh': False}, {'fresh': 1}, {'simulated': True},
                 {'simulated': 1}, {'simulated': 'true'}, {'frame_age_ms': 5000},
                 {'grid': [[26.0] * 31 for _ in range(24)]}, {'sequence': None})
        for invalid in cases:
            with self.subTest(invalid=list(invalid)):
                self.now = 0
                self.direct.return_value = payload(10, **invalid)
                self.production_payload()
                result = checker.check('192.168.4.2', 4, 'en0')
                self.assertEqual(result['phase'], 'sensor_not_verified')
                self.assertEqual(result['frames'], [])
                self.assertEqual(result['direct_error']['error_code'], 'invalid_payload')

    def test_production_failure_or_simulation_prevents_verification(self):
        for simulated in (False, True):
            with self.subTest(simulated=simulated):
                self.now = 0
                self.direct.side_effect = [payload(10), payload(11)]
                if simulated:
                    self.production.side_effect = None
                    self.production_payload(payload(100, simulated=True))
                else:
                    self.production.side_effect = Timeout('SYNTHETIC_SECRET')
                result = checker.check('192.168.4.2', 4, 'en0')
                self.assertEqual(result['phase'], 'production_telemetry_not_fresh')
                self.assertNotIn('SYNTHETIC_SECRET', json.dumps(result))

    def test_network_change_during_read_invalidates_result(self):
        for changed in (None, '192.168.4.5', '192.168.4.2'):
            with self.subTest(changed=changed):
                self.now = 0
                self.network.side_effect = ['192.168.4.4', '192.168.4.4', changed]
                self.direct.return_value = payload(10)
                self.production_payload()
                result = checker.check('192.168.4.2', 4, 'en0')
                self.assertEqual(result['phase'], 'robot_network_changed')


if __name__ == '__main__':
    unittest.main()
