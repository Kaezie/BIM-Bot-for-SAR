"""Software-only worker timing tests using synthetic sensor frames and clocks."""
import json
import math
import unittest
from unittest.mock import MagicMock, patch

from requests import Response

from features.telemetry import Telemetry


class StopWorker(BaseException):
    """Stop an infinite worker at a controlled test boundary."""


def response(sequence, age_ms):
    value = Response()
    value.status_code = 200
    value._content = json.dumps({'grid': [[26.0] * 32 for _ in range(24)],
                                 'sequence': sequence, 'frame_age_ms': age_ms,
                                 'fresh': True, 'simulated': False}).encode()
    return value


class TelemetryPollingTests(unittest.TestCase):
    def test_short_transport_failure_preserves_only_recent_thermal_acquisition(self):
        import requests
        http = MagicMock()
        http.get.return_value = response(7, 100)
        telemetry = Telemetry({'thermal':'http://synthetic/thermal'}, http)
        with patch('features.telemetry.time.time', return_value=100), \
             patch('features.telemetry.time.monotonic', return_value=10):
            telemetry.poll('thermal')
        http.get.side_effect = requests.Timeout()
        with patch('features.telemetry.time.time', return_value=101):
            telemetry.poll('thermal')
            reading = telemetry.get('thermal')
            self.assertTrue(reading['fresh'])
            self.assertTrue(reading['retrying'])
            self.assertEqual(reading['updated_at'], 99.9)
        with patch('features.telemetry.time.time', return_value=104.9):
            self.assertFalse(telemetry.get('thermal')['fresh'])

    def test_conservative_thermal_reader_samples_current_four_hz_source_once_per_second(self):
        clock = [100.2]
        http = MagicMock()
        telemetry = Telemetry({'thermal': 'http://synthetic/thermal'}, http)
        snapshots = []

        def get(*_args, **_kwargs):
            clock[0] += 0.05  # Synthetic local HTTP latency.
            sequence = math.floor(clock[0]*4)
            acquired_at = sequence/4
            return response(sequence, (clock[0] - acquired_at) * 1000)

        def sleep(seconds):
            snapshots.append((clock[0], telemetry.get('thermal')))
            if len(snapshots) == 5:
                raise StopWorker
            clock[0] += seconds

        http.get.side_effect = get
        with patch('features.telemetry.time.time', side_effect=lambda: clock[0]), \
                patch('features.telemetry.time.monotonic', side_effect=lambda: clock[0]), \
                patch('features.telemetry.time.sleep', side_effect=sleep), \
                self.assertRaises(StopWorker):
            telemetry.run('thermal')

        # Source acquisition stays at4Hz while the conservative Wi-Fi reader
        # samples the latest image at1Hz, without replaying skipped images.
        distinct = []
        for received_at, reading in snapshots:
            self.assertTrue(reading['fresh'])
            self.assertFalse(reading['simulated'])
            self.assertAlmostEqual(reading['updated_at'], reading['sequence']/4 - 0.05)
            if not distinct or reading['sequence'] != distinct[-1][1]['sequence']:
                distinct.append((received_at, reading))
        self.assertEqual([reading['sequence'] for _, reading in distinct], [401, 405, 409, 413, 417])
        self.assertTrue(all(received_at - reading['updated_at'] < 0.25
                            for received_at, reading in distinct))

    def test_slow_reads_finish_before_next_poll_without_catchup_bursts(self):
        for kind, minimum_gap in (('thermal', 0.1), ('sound', 2), ('position', 2), ('robot', 2)):
            with self.subTest(kind=kind):
                clock = [100.0]
                starts, finishes = [], []
                telemetry = Telemetry({kind: 'http://synthetic/telemetry'}, MagicMock())

                def poll(actual_kind):
                    self.assertEqual(actual_kind, kind)
                    self.assertEqual(len(starts), len(finishes))
                    starts.append(clock[0])
                    clock[0] += 1.25  # A request slower than thermal's target pause.
                    finishes.append(clock[0])

                def sleep(seconds):
                    if len(starts) == 3:
                        raise StopWorker
                    clock[0] += seconds

                with patch.object(telemetry, 'poll', side_effect=poll), \
                        patch('features.telemetry.time.monotonic', side_effect=lambda: clock[0]), \
                        patch('features.telemetry.time.sleep', side_effect=sleep), \
                        self.assertRaises(StopWorker):
                    telemetry.run(kind)
                self.assertEqual(len(starts), 3)
                for next_start, previous_finish in zip(starts[1:], finishes):
                    self.assertAlmostEqual(next_start - previous_finish, minimum_gap)

    def test_fast_repolling_does_not_rejuvenate_a_frozen_source_frame(self):
        clock = [100.1]
        captured_at = 100.0
        http = MagicMock()
        telemetry = Telemetry({'thermal': 'http://synthetic/thermal'}, http)
        snapshots = []
        http.get.side_effect = lambda *_args, **_kwargs: response(7, (clock[0] - captured_at) * 1000)

        def sleep(seconds):
            snapshots.append((clock[0], telemetry.get('thermal')))
            if len(snapshots) == 61:
                raise StopWorker
            clock[0] += seconds

        with patch('features.telemetry.time.time', side_effect=lambda: clock[0]), \
                patch('features.telemetry.time.monotonic', side_effect=lambda: clock[0]), \
                patch('features.telemetry.time.sleep', side_effect=sleep), \
                self.assertRaises(StopWorker):
            telemetry.run('thermal')

        for checked_at, reading in snapshots:
            self.assertEqual(reading['sequence'], 7)
            self.assertAlmostEqual(reading['updated_at'], captured_at)
            self.assertEqual(reading['fresh'], checked_at - captured_at < 5)
        self.assertFalse(snapshots[-1][1]['fresh'])
        self.assertEqual(snapshots[-1][1]['error_code'], 'invalid_payload')
        self.assertEqual(http.get.call_count, 61)

    def test_body_transfer_time_counts_toward_five_second_freshness(self):
        cases = ((4500, 0.499, True), (4500, 0.5, False),
                 (100, 1.5, True), (100, 5.0, False))
        for source_age_ms, transfer_seconds, fresh in cases:
            with self.subTest(source_age_ms=source_age_ms, transfer_seconds=transfer_seconds):
                http = MagicMock()
                http.get.return_value = response(7, source_age_ms)
                telemetry = Telemetry({'thermal': 'http://synthetic/thermal'}, http)
                with patch('features.telemetry.time.monotonic', side_effect=[10, 10 + transfer_seconds]), \
                        patch('features.telemetry.time.time', return_value=200):
                    telemetry.poll('thermal')
                    reading = telemetry.get('thermal')
                self.assertAlmostEqual(reading['transport_ms'], transfer_seconds * 1000)
                self.assertAlmostEqual(reading['updated_at'], 200 - source_age_ms / 1000 - transfer_seconds)
                self.assertEqual(reading['fresh'], fresh)

    def test_variable_transfer_cannot_rejuvenate_a_repeated_sequence(self):
        http = MagicMock()
        telemetry = Telemetry({'thermal': 'http://synthetic/thermal'}, http)
        snapshots = []
        # A slower first exchange and a faster second exchange can otherwise
        # move the same sequence's estimated capture time forward.
        cases = ((7, 200, 100.9, (10, 10.8)),
                 (7, 1400, 101.6, (20, 20.2)),
                 (0, 100, 102.1, (30, 30.1)))
        for sequence, age_ms, received_at, monotonic in cases:
            http.get.return_value = response(sequence, age_ms)
            with patch('features.telemetry.time.monotonic', side_effect=monotonic), \
                    patch('features.telemetry.time.time', return_value=received_at):
                telemetry.poll('thermal')
                snapshots.append(telemetry.get('thermal'))
        self.assertAlmostEqual(snapshots[0]['updated_at'], 99.9)
        self.assertAlmostEqual(snapshots[1]['updated_at'], snapshots[0]['updated_at'])
        self.assertAlmostEqual(snapshots[1]['transport_ms'], 200)
        self.assertEqual(snapshots[2]['sequence'], 0)
        self.assertGreater(snapshots[2]['updated_at'], snapshots[1]['updated_at'])
        self.assertTrue(snapshots[2]['fresh'])

    def test_transport_duration_uses_monotonic_time_across_wall_clock_changes(self):
        for received_at in (50, 1000):
            with self.subTest(received_at=received_at):
                http = MagicMock()
                http.get.return_value = response(1, 250)
                telemetry = Telemetry({'thermal': 'http://synthetic/thermal'}, http)
                with patch('features.telemetry.time.monotonic', side_effect=[10, 11.25]), \
                        patch('features.telemetry.time.time', return_value=received_at):
                    telemetry.poll('thermal')
                    reading = telemetry.get('thermal')
                self.assertEqual(reading['transport_ms'], 1250)
                self.assertEqual(reading['updated_at'], received_at - 1.5)
                self.assertTrue(reading['fresh'])

    def test_legacy_thermal_grid_retains_received_time_semantics(self):
        http = MagicMock()
        value = response(1, 100)
        value._content = json.dumps({'grid': [[26.0] * 32 for _ in range(24)]}).encode()
        http.get.return_value = value
        telemetry = Telemetry({'thermal': 'http://synthetic/thermal'}, http)
        with patch('features.telemetry.time.monotonic', side_effect=[10, 12]), \
                patch('features.telemetry.time.time', return_value=100):
            telemetry.poll('thermal')
            reading = telemetry.get('thermal')
        self.assertEqual(reading['updated_at'], 100)
        self.assertEqual(reading['transport_ms'], 2000)
        self.assertTrue(reading['fresh'])


if __name__ == '__main__':
    unittest.main()
