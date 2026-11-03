"""Control safety: no real network or hardware is used."""
import unittest
from unittest.mock import Mock, patch

import requests

from scripts.set_original_camera_quality import BASE, on_robot_network, set_quality


def response(quality=10, **changes):
    result = Mock(status_code=200, content=b'{}')
    result.json.return_value = dict(framesize=6, pixformat=4, xclk=20,
                                   quality=quality, **changes)
    result.__enter__ = Mock(return_value=result)
    result.__exit__ = Mock(return_value=False)
    return result


class QualityControlTests(unittest.TestCase):
    @patch('scripts.set_original_camera_quality.subprocess.run')
    def test_direct_route_accepts_mac_gateway_but_rejects_home_or_tunnel(self, run):
        for own, interface, gateway, destination, flags, expected in [
                ('192.168.4.2', 'en0', 'aa:bb:cc:dd:ee:ff', '192.168.4.1',
                 '<UP,HOST,DONE,LLINFO>', True),
                ('192.168.68.73', 'en0', '192.168.68.1', 'default', '<UP,GATEWAY>', False),
                ('192.168.4.2', 'utun0', '', '192.168.4', '<UP>', False),
                ('192.168.4.2', 'en0', '192.168.68.1', 'default', '<UP,GATEWAY>', False)]:
            with self.subTest(own=own, interface=interface, gateway=gateway):
                route = f'destination: {destination}\ninterface: {interface}\ngateway: {gateway}\nflags: {flags}\n'
                run.side_effect = [Mock(stdout=own), Mock(stdout=route)]
                self.assertEqual(on_robot_network(), expected)

    def test_wrong_network_sends_nothing(self):
        session = Mock()
        self.assertFalse(set_quality(session, lambda: False)['verified'])
        session.get.assert_not_called()

    def test_requires_expected_geometry_and_integer_status(self):
        for field, value in [('framesize', 8), ('pixformat', 2), ('xclk', 10),
                             ('quality', 30), ('framesize', True)]:
            with self.subTest(field=field, value=value):
                status = response()
                status.json.return_value[field] = value
                session = Mock()
                session.get.return_value = status
                report = set_quality(session, lambda: True)
                self.assertFalse(report['verified'])
                self.assertFalse(report['control_attempted'])
                self.assertEqual(session.get.call_count, 1)

    def test_one_control_and_verified_readback(self):
        session = Mock()
        session.get.side_effect = [response(), response(), response(20)]
        report = set_quality(session, lambda: True)
        self.assertTrue(report['verified'])
        self.assertEqual([call.args[0] for call in session.get.call_args_list],
                         [BASE + '/status', BASE + '/control?var=quality&val=20', BASE + '/status'])
        self.assertEqual(report['before']['quality'], 10)
        self.assertEqual(report['after']['quality'], 20)
        for call in session.get.call_args_list:
            self.assertFalse(call.kwargs['allow_redirects'])
            self.assertEqual(call.kwargs['timeout'], (2, 4))

    def test_network_change_before_control_blocks_mutation(self):
        session = Mock()
        session.get.return_value = response()
        report = set_quality(session, Mock(side_effect=[True, False]))
        self.assertFalse(report['verified'])
        self.assertFalse(report['control_attempted'])
        self.assertEqual(session.get.call_count, 1)

    def test_timeout_after_control_reads_back_without_retrying_control(self):
        session = Mock()
        session.get.side_effect = [response(), requests.Timeout(), response(20)]
        report = set_quality(session, lambda: True)
        self.assertTrue(report['verified'])
        self.assertEqual(session.get.call_count, 3)

    def test_failed_readback_never_claims_success(self):
        session = Mock()
        session.get.side_effect = [response(), response(), response()]
        self.assertFalse(set_quality(session, lambda: True)['verified'])

    def test_rejects_redirect_before_any_control(self):
        session = Mock()
        redirected = response()
        redirected.status_code = 302
        session.get.return_value = redirected
        self.assertFalse(set_quality(session, lambda: True)['verified'])
        self.assertEqual(session.get.call_count, 1)

    def test_already_set_only_verifies_and_restore_is_supported(self):
        for old, target, count in [(20, 20, 2), (20, 10, 3)]:
            with self.subTest(target=target):
                session = Mock()
                session.get.side_effect = [response(old), response(target), response(target)]
                report = set_quality(session, lambda: True, target)
                self.assertTrue(report['verified'])
                self.assertEqual(session.get.call_count, count)


if __name__ == '__main__':
    unittest.main()
