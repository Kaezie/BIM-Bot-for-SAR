"""Bounded internal capture records cache history without starting devices."""
import json
from pathlib import Path
import tempfile
import threading
import unittest

from features.system_diagnostics import DashboardCheck


class DashboardCheckTests(unittest.TestCase):
    def test_capture_has_one_job_and_saves_history_after_the_page_leaves(self):
        entered, release = threading.Event(), threading.Event()
        def snapshot():
            entered.set(); release.wait(1)
            return {'checked_at': '2026-10-28T00:00:00+00:00',
                    'network': {'robot_subnet': True},
                    'cameras': {name: {'viewers': 1, 'connected': True, 'source_errors': 2}
                                for name in ('main', 'nightvision')},
                    'sensor': {'fresh': True}, 'thermal': {'fresh': True}}
        with tempfile.TemporaryDirectory() as folder:
            check = DashboardCheck(folder, snapshot, duration=.02)
            self.assertTrue(check.start())
            self.assertTrue(entered.wait(1))
            self.assertFalse(check.start())
            release.set(); check.thread.join(timeout=2)
            state = check.status()
            self.assertTrue(state['saved'])
            self.assertFalse(state['running'])
            report = json.loads((Path(folder)/'diagnostics/normal_dashboard_check.json').read_text())
            self.assertGreaterEqual(len(report['samples']), 1)
            self.assertEqual(report['summary']['main']['source_errors_during_check'], 0)
            self.assertEqual(report['summary']['main']['fresh_active_samples'], len(report['samples']))
            self.assertEqual(report['summary']['thermal_fresh_samples'], len(report['samples']))
