"""Address changes must never select this Mac, the original AP or unknown firmware."""
import json
import unittest
from unittest.mock import MagicMock, patch

from features.robot_connection import SpareDiscovery
from features.telemetry import Telemetry
from requests import Response


class SpareDiscoveryTests(unittest.TestCase):
    def make(self, own='192.168.4.2', camera='http://192.168.4.2:81/stream',
             thermal='http://192.168.4.2/thermal'):
        network = MagicMock(return_value={'ipv4': own, 'robot_subnet': own.startswith('192.168.4.')})
        callback = MagicMock()
        discovery = SpareDiscovery(camera, thermal, callback, network=network)
        return discovery, callback

    def test_mac_at_old_spare_address_discovers_only_identity_verified_neighbour(self):
        discovery, callback = self.make()
        with patch.object(discovery, '_identify', side_effect=lambda host: host == '192.168.4.3') as probe:
            discovery.check()
        targets = {call.args[0] for call in probe.call_args_list}
        self.assertNotIn('192.168.4.1', targets)
        self.assertNotIn('192.168.4.2', targets)
        callback.assert_called_once_with('192.168.4.3', True, True)
        self.assertEqual(discovery.status()['state'], 'verified')

    def test_home_network_and_custom_disabled_targets_are_never_scanned(self):
        for own, camera, thermal in [('192.168.68.73', 'http://192.168.4.2:81/stream', ''),
                                     ('192.168.4.3', '', ''),
                                     ('192.168.4.3', 'http://custom:81/stream', 'http://custom/thermal')]:
            discovery, callback = self.make(own, camera, thermal)
            with patch.object(discovery, '_identify') as probe:
                discovery.check()
            probe.assert_not_called(); callback.assert_not_called()

    def test_ambiguous_identity_or_network_switch_cannot_change_targets(self):
        discovery, callback = self.make()
        with patch.object(discovery, '_identify', return_value=True):
            discovery.check()
        callback.assert_not_called()
        self.assertEqual(discovery.status()['state'], 'ambiguous')
        discovery, callback = self.make()
        discovery.network.side_effect = [{'ipv4': '192.168.4.2', 'robot_subnet': True},
                                         {'ipv4': '192.168.68.73', 'robot_subnet': False}]
        with patch.object(discovery, '_identify', side_effect=lambda host: host == '192.168.4.3'):
            discovery.check()
        callback.assert_not_called()
        self.assertEqual(discovery.status()['state'], 'network_changed')

    def test_matching_known_host_avoids_repeated_neighbourhood_search_and_disabled_thermal(self):
        discovery, callback = self.make(own='192.168.4.3', thermal='')
        with patch.object(discovery, '_identify', return_value=True) as probe:
            discovery.check(); discovery.check()
        self.assertEqual(probe.call_count, 2)
        self.assertTrue(all(call.args == ('192.168.4.2',) for call in probe.call_args_list))
        callback.assert_called_with('192.168.4.2', True, False)

    def test_brief_shared_outage_retries_known_spare_without_neighbourhood_scan(self):
        discovery, callback = self.make(own='192.168.4.3')
        with patch.object(discovery, '_identify', return_value=True):
            discovery.check()
        callback.reset_mock()
        with patch.object(discovery, '_identify', return_value=False) as probe:
            discovery.check(); discovery.check()
        self.assertEqual([call.args for call in probe.call_args_list], [('192.168.4.2',)] * 2)
        callback.assert_not_called()
        self.assertEqual(discovery.status()['state'], 'retrying_known')

    def test_identity_requires_exact_firmware_and_bounded_nonredirected_body(self):
        discovery, _ = self.make()
        factory = discovery.session_factory = MagicMock()
        session = factory.return_value.__enter__.return_value
        response = session.get.return_value.__enter__.return_value
        response.status_code = 200
        for payload, expected in [(b'{"firmware":"original"}', False),
                                  (b'{"firmware":"bimbot-nightvision/2"}', True),
                                  (b' ' * 4097, False)]:
            response.iter_content.return_value = [payload]
            self.assertEqual(discovery._identify('192.168.4.3'), expected)
        self.assertFalse(session.trust_env)
        self.assertFalse(session.get.call_args.kwargs['allow_redirects'])

    def test_thermal_address_change_discards_inflight_old_success_and_error(self):
        http = MagicMock()
        telemetry = Telemetry({'thermal': 'http://old/thermal'}, http)
        for failed in (False, True):
            telemetry.set_url('thermal', 'http://old/thermal')
            def get(*_args, **_kwargs):
                telemetry.set_url('thermal', 'http://new/thermal')
                if failed:
                    raise TimeoutError()
                result = Response(); result.status_code = 200
                result._content = json.dumps({'grid': [[26.] * 32 for _ in range(24)]}).encode()
                return result
            http.get.side_effect = get
            telemetry.poll('thermal')
            self.assertFalse(telemetry.get('thermal')['fresh'])
            self.assertNotIn('thermal', telemetry.readings)
            self.assertNotIn('thermal', telemetry.errors)

    def test_existing_identity_request_caches_only_public_firmware_profile(self):
        discovery, callback = self.make(own='192.168.4.6', thermal='')
        factory = discovery.session_factory = MagicMock()
        session = factory.return_value.__enter__.return_value
        response = session.get.return_value.__enter__.return_value
        response.status_code = 200
        response.iter_content.return_value = [json.dumps({
            'firmware': 'bimbot-nightvision/2', 'startup_profile': 'retry/2',
            'stream_profile': 'fresh/2', 'stream_target_fps': 8, 'camera_ready': True,
            'password': 'must-not-be-retained', 'other': {'token': 'discard'}}).encode()]
        discovery.check()
        profile = discovery.status()['firmware_profile']
        self.assertEqual(set(profile), {'firmware', 'checked_at', 'startup_profile',
                                        'stream_profile', 'stream_target_fps', 'camera_ready'})
        self.assertEqual(profile['stream_target_fps'], 8)
        self.assertEqual(profile['stream_profile'], 'fresh/2')
        self.assertGreater(profile['checked_at'], 0)
        self.assertEqual(session.get.call_count, 1, 'Do not add requests for firmware diagnostics.')
        callback.assert_called_once_with('192.168.4.2', True, False)

    def test_identity_diagnostics_reject_malformed_setting_values(self):
        discovery, _ = self.make(own='192.168.4.6', thermal='')
        factory = discovery.session_factory = MagicMock()
        response = factory.return_value.__enter__.return_value.get.return_value.__enter__.return_value
        response.status_code = 200
        response.iter_content.return_value = [json.dumps({
            'firmware': 'bimbot-nightvision/2', 'startup_profile': 'private arbitrary text',
            'stream_profile': {'unexpected': 'object'}, 'stream_target_fps': True,
            'camera_ready': 'true'}).encode()]
        discovery.check()
        self.assertEqual(set(discovery.status()['firmware_profile']), {'firmware', 'checked_at'})
