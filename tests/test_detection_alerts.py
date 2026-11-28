import unittest
from unittest.mock import Mock

from features.detection_alerts import DetectionAlerts, DetectionSlowdown


class DetectionAlertTests(unittest.TestCase):
    def setUp(self):
        self.alerts = DetectionAlerts()
        self.person = {'pose': 'lying', 'motion_observed': False}
        self.now = 100
        self.http = Mock()
        self.slowdown = DetectionSlowdown('http://127.0.0.1:5054/command', 'fixture', self.http, self.alerts, lambda: self.now)
        self.trace = {'trace_id': 'fixture-1', 'source': 'uno_usb_serial', 'fresh': True,
                      'sample_age_ms': 100, 'current_move': 'F', 'state': 'recording'}
        def ack(_url, *, json, **_kwargs):
            return Mock(**{'json.return_value': {'acknowledged': True, 'state': 'recording',
                                                'trace_id': json['trace_id'], 'command_id': json['command_id']}})
        self.http.post.side_effect = ack

    def observe_count(self, count):
        self.alerts.observe([self.person] * count, self.now - .5)
        return self.alerts.observe([self.person] * count, self.now)

    def test_new_group_is_confirmed_and_last_seen_expires(self):
        self.assertIsNone(self.alerts.observe([self.person], 99.5))
        alert = self.alerts.observe([self.person], 100)
        self.assertIn('visible obstructions', alert['cues'][0])
        self.alerts.observe([], 100.5)
        self.alerts.observe([self.person], 101)
        self.assertIsNone(self.alerts.observe([self.person], 101.5))
        self.assertEqual(self.alerts.snapshot(104)['recent_observation']['seen_at'], 101.5)
        self.assertIsNone(self.alerts.snapshot(108)['recent_observation'])

    def test_slowdown_scales_with_confirmed_group_and_sends_nothing_after_link_loss(self):
        self.observe_count(1)
        self.slowdown.tick(self.trace, True)
        first = self.http.post.call_args.kwargs['json']
        self.assertEqual((first['action'], first['count']), ('observation_slowdown', 1))
        self.assertEqual(self.slowdown.status, 'slowing')
        self.now += 1
        self.observe_count(2)
        self.slowdown.tick(self.trace, True)
        extension = self.http.post.call_args.kwargs['json']
        self.assertEqual(extension['command_id'], first['command_id'])
        self.assertEqual(extension['count'], 2)
        self.now += 1
        self.slowdown.tick(self.trace, False)
        self.now += 10
        self.slowdown.tick(self.trace, True)
        self.assertEqual(self.slowdown.status, 'unconfirmed')
        self.assertEqual(self.http.post.call_count, 2)

    def test_expiry_sends_no_resume_and_never_starts_a_stopped_robot(self):
        self.observe_count(2)
        self.slowdown.tick(self.trace, True)
        self.now += 5
        self.slowdown.tick(self.trace, True)
        self.assertEqual(self.slowdown.status, 'slowing')
        self.now += 1
        self.slowdown.tick(self.trace, True)
        self.assertEqual(self.slowdown.status, 'ready')
        self.trace.update(state='stopped', current_move='S')
        self.now += 1
        self.observe_count(3)
        self.slowdown.tick(self.trace, True)
        self.assertEqual(self.http.post.call_count, 1)

    def test_light_notice_requires_sustained_and_recent_dark_frames(self):
        self.alerts.observe_light(100,True)
        self.assertFalse(self.alerts.snapshot(100)['low_light'])
        self.alerts.observe_light(101,True)
        self.assertTrue(self.alerts.snapshot(101)['low_light'])
        self.assertFalse(self.alerts.snapshot(103)['low_light'])
        self.alerts.source_lost()
        self.assertFalse(self.alerts.snapshot(101)['low_light'])

    def test_brightness_recovery_requires_fresh_consecutive_light_frames(self):
        for at, dark in [(100, True), (101, True), (101.5, False), (102, True)]:
            self.alerts.observe_light(at, dark)
        self.assertIsNone(self.alerts.snapshot(102)['light_state'])
        for at in (102.5, 103.5, 104.5):
            self.alerts.observe_light(at, False)
        self.assertEqual(self.alerts.snapshot(104.5)['light_state'], 'bright')
        self.alerts.observe_light(107, True)
        self.assertIsNone(self.alerts.snapshot(107)['light_state'])
