"""Generated images and controlled slow models verify video concurrency."""
from email.parser import BytesParser
from email.policy import default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
import threading
import time
import unittest
from unittest.mock import MagicMock, patch
import cv2
import numpy as np
import requests
from features.live_camera import LiveCamera


def jpeg(value):
    ok, data = cv2.imencode('.jpg', np.full((24, 32, 3), value, dtype=np.uint8))
    assert ok
    return data.tobytes()


class LiveCameraTests(unittest.TestCase):
    def test_low_rate_source_analyzes_each_new_frame_with_worker_rate_limit(self):
        analyze = MagicMock(return_value=[])
        camera = self.make(analyze=analyze)
        camera.clients = 1
        camera._queue_video(jpeg(40), camera.generation)
        with camera.condition:
            self.assertTrue(camera.condition.wait_for(lambda: analyze.call_count == 1 and camera.detected_at is not None, timeout=1))
        first = camera.detected_at
        camera._queue_video(jpeg(90), camera.generation)
        with camera.condition:
            self.assertTrue(camera.condition.wait_for(lambda: analyze.call_count == 2 and camera.detected_at != first, timeout=1.5))
        self.assertEqual(analyze.call_count, 2, 'A slow source must not wait for three more images before refreshing detections')

    def test_viewer_lease_survives_browser_timeout_and_background_pacing_gap(self):
        camera = self.make()
        camera.thread = object()
        camera.publish(jpeg(50))
        first = camera.snapshot(('owner', 'viewer'), timeout=0)
        # A2.5s bounded browser request plus1s background pacing exceeds the
        # former3s lease. An image can still be fresh across this renewal gap.
        threading.Event().wait(3.3)
        with camera.condition:
            self.assertIn(('owner', 'viewer'), camera.snapshot_clients)
            self.assertEqual(camera.clients, 1)
            self.assertEqual(camera.generation, first['generation'])
        camera.snapshot(('owner', 'viewer'), first['sequence'], first['generation'], timeout=0)

    def test_identified_address_change_fences_old_frames_and_keeps_viewer_lease(self):
        camera = self.make()
        camera.thread = object()
        camera.publish(jpeg(50))
        frame = camera.snapshot(('owner', 'viewer'), timeout=0)
        response = camera.response = MagicMock()
        self.assertTrue(camera.set_url('http://new-camera:81/stream'))
        self.assertEqual(camera.clients, 1)
        self.assertFalse(camera.status()['connected'])
        self.assertFalse(camera.publish(jpeg(80), generation=frame['generation']))
        self.assertTrue(camera.publish(jpeg(90)))
        self.assertTrue(camera.status()['connected'])
        self.assertFalse(camera.set_url('http://new-camera:81/stream'))

    def make(self, **kwargs):
        camera = LiveCamera('http://camera:81/stream', MagicMock(), kwargs.pop('cv', cv2), np, **kwargs)
        self.addCleanup(self.finish, camera)
        return camera

    @staticmethod
    def finish(camera):
        with camera.condition:
            camera.snapshot_clients.clear()
            camera.clients = 0
            camera._clear_locked()
        thread = camera.analysis_thread
        if thread:
            thread.join(timeout=1)
        if camera.video_thread:
            camera.video_thread.join(timeout=1)
        if camera.snapshot_thread:
            camera.snapshot_thread.join(timeout=1)

    def test_snapshot_returns_only_latest_jpeg_and_preserves_cursor_and_reception_time(self):
        camera = self.make()
        camera.thread = object()
        camera.publish(jpeg(30))
        initial = camera.snapshot(('owner', 'viewer'), timeout=0)
        camera.publish(jpeg(100))
        camera.publish(jpeg(200))
        current = camera.snapshot(('owner', 'viewer'), initial['sequence'], initial['generation'], timeout=0)
        self.assertEqual(current['state'], 'frame')
        self.assertEqual(current['jpeg'], jpeg(200))
        self.assertEqual(current['sequence'], 3)
        self.assertEqual(current['received_at'], camera.updated_at)
        self.assertGreaterEqual(current['age_ms'], 0)
        self.assertEqual(camera.clients, 1, 'Sequential requests retain one shared subscription')
        self.assertEqual(camera.snapshot(('owner', 'viewer'), current['sequence'], current['generation'], timeout=0),
                         {'state': 'pending'})
        camera.close_snapshot(('owner', 'viewer'))

    def test_snapshots_and_mjpeg_share_upstream_and_last_close_releases_it_outside_lock(self):
        camera = self.make()
        camera.thread = object()
        response = camera.response = MagicMock()
        response.close.side_effect = lambda: self.assertFalse(camera.condition._is_owned())
        camera.publish(jpeg(100))
        camera.snapshot(('a', 'one'), timeout=0)
        stream = camera.frames()
        next(stream)
        camera.snapshot(('b', 'one'), timeout=0)
        self.assertEqual(camera.clients, 3)
        camera.close_snapshot(('a', 'one'))
        camera.close_snapshot(('a', 'one'))
        stream.close()
        response.close.assert_not_called()
        self.assertEqual(camera.clients, 1)
        camera.close_snapshot(('b', 'one'))
        response.close.assert_called_once()
        self.assertEqual(camera.clients, 0)
        self.assertIsNone(camera.frame)

    def test_last_viewer_release_can_return_while_transport_close_is_blocked(self):
        camera = self.make()
        camera.thread = object()
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        response = camera.response = MagicMock()
        response.close.side_effect = lambda: (entered.set(), release.wait(2))
        camera.publish(jpeg(100))
        camera.snapshot(('owner', 'viewer'), timeout=0)
        began = time.monotonic()
        self.assertTrue(camera.close_snapshot(('owner', 'viewer'), asynchronous=True))
        self.assertLess(time.monotonic() - began, .2)
        self.assertTrue(entered.wait(1))
        self.assertEqual(camera.clients, 0)
        self.assertIsNone(camera.response)
        self.assertFalse(camera.status()['connected'])
        self.assertFalse(camera.close_snapshot(('owner', 'viewer'), asynchronous=True))
        response.close.assert_called_once()
        release.set()

    def test_snapshot_abandoned_lease_expires_and_wakes_its_waiter(self):
        camera = self.make()
        camera.thread = object()
        camera.SNAPSHOT_LEASE = .03
        response = camera.response = MagicMock()
        result = camera.snapshot(('owner', 'viewer'), timeout=.2)
        self.assertEqual(result, {'state': 'pending'})
        with camera.condition:
            self.assertTrue(camera.condition.wait_for(lambda: camera.clients == 0, timeout=1))
        if camera.snapshot_thread:
            camera.snapshot_thread.join(timeout=1)
        self.assertEqual(camera.snapshot_clients, {})
        self.assertIsNone(camera.snapshot_thread)
        response.close.assert_called_once()

    def test_snapshot_wait_is_bounded_and_does_not_repeat_same_frame(self):
        camera = self.make()
        camera.thread = object()
        camera.publish(jpeg(100))
        current = camera.snapshot(('owner', 'viewer'), timeout=0)
        began = time.monotonic()
        self.assertEqual(camera.snapshot(('owner', 'viewer'), current['sequence'], current['generation'], timeout=.02),
                         {'state': 'pending'})
        self.assertLess(time.monotonic() - began, .5)
        camera.close_snapshot(('owner', 'viewer'))

    def test_snapshot_starts_one_actual_reader_shared_with_other_snapshots_and_mjpeg(self):
        camera = self.make()
        closed = threading.Event()
        self.addCleanup(closed.set)
        response = camera.http.get.return_value.__enter__.return_value
        response.headers = {'Content-Type': 'multipart/x-mixed-replace; boundary=frame'}
        response.close.side_effect = closed.set
        frame = jpeg(100)

        def read(*_args, **_kwargs):
            if response.raw.read1.call_count == 1:
                return frame
            closed.wait(2)
            return b''

        response.raw.read1.side_effect = read
        first = camera.snapshot(('a', 'one'))
        self.assertEqual(first['jpeg'], frame)
        second = camera.snapshot(('b', 'one'), timeout=0)
        self.assertEqual(second['jpeg'], frame)
        stream = camera.frames()
        self.assertIn(frame, next(stream))
        camera.http.get.assert_called_once()
        self.assertEqual(camera.clients, 3)
        camera.close_snapshot(('a', 'one'))
        camera.close_snapshot(('b', 'one'))
        self.assertFalse(closed.is_set())
        stream.close()
        self.assertTrue(closed.wait(1))
        with camera.condition:
            self.assertTrue(camera.condition.wait_for(lambda: camera.thread is None, timeout=1))
        self.assertEqual(camera.clients, 0)

    def test_snapshot_renewal_keeps_the_reader_past_the_original_expiry(self):
        camera = self.make()
        camera.thread = object()
        camera.SNAPSHOT_LEASE = .15
        response = camera.response = MagicMock()
        camera.snapshot(('owner', 'viewer'), timeout=0)
        time.sleep(.08)
        camera.snapshot(('owner', 'viewer'), timeout=0)
        time.sleep(.09)
        self.assertEqual(camera.clients, 1)
        self.assertIn(('owner', 'viewer'), camera.snapshot_clients)
        response.close.assert_not_called()
        with camera.condition:
            self.assertTrue(camera.condition.wait_for(lambda: camera.clients == 0, timeout=1))
        response.close.assert_called_once()

    def test_snapshot_never_returns_expired_error_or_previous_generation_jpeg(self):
        camera = self.make()
        camera.thread = object()
        camera.publish(jpeg(100))
        first = camera.snapshot(('owner', 'viewer'), timeout=0)
        with patch('features.live_camera.time.time', return_value=camera.updated_at + camera.VIDEO_TTL + .1):
            self.assertEqual(camera.snapshot(('owner', 'viewer'), timeout=0)['state'], 'unavailable')
        with camera.condition:
            camera._clear_locked('Disconnected')
        self.assertEqual(camera.snapshot(('owner', 'viewer'), timeout=0),
                         {'state': 'unavailable', 'message': 'Disconnected'})
        camera.publish(jpeg(200))
        current = camera.snapshot(('owner', 'viewer'), first['sequence'], first['generation'], timeout=0)
        self.assertEqual(current['jpeg'], jpeg(200))
        self.assertNotEqual(current['generation'], first['generation'])
        camera.close_snapshot(('owner', 'viewer'))

    def test_snapshot_limits_viewers_and_unconfigured_camera_does_not_start_reader(self):
        camera = self.make()
        camera.url = None
        self.assertEqual(camera.snapshot(('owner', 'viewer'), timeout=0)['state'], 'unavailable')
        self.assertIsNone(camera.thread)
        self.assertEqual(camera.clients, 0)
        camera.url = 'http://camera:81/stream'
        camera.thread = object()
        camera.MAX_SNAPSHOT_VIEWERS = 1
        self.assertEqual(camera.snapshot(('a', 'one'), timeout=0)['state'], 'pending')
        self.assertEqual(camera.snapshot(('a', 'two'), timeout=0)['state'], 'busy')
        self.assertEqual(camera.clients, 1)
        camera.close_snapshot(('a', 'one'))

    def wait_result(self, camera):
        with camera.condition:
            self.assertTrue(camera.condition.wait_for(lambda: camera.detected_at is not None, timeout=1))

    def test_slow_model_does_not_freeze_live_frames_and_pending_is_latest_only(self):
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        seen = []
        def analyze(frame):
            value = int(frame[0, 0, 0]); seen.append(value)
            if len(seen) == 1:
                entered.set(); release.wait(2)
            else:
                finished.set()
            return [{'value': value}]
        camera = self.make(analyze=analyze)
        self.addCleanup(release.set)
        camera.thread = object()  # Feed real JPEGs without starting a network reader.
        stream = camera.frames()
        camera.publish(jpeg(30), infer=True)
        self.assertTrue(entered.wait(1))
        self.assertIn(jpeg(30), next(stream))
        camera.publish(jpeg(100), infer=True)
        camera.publish(jpeg(200), infer=True)
        self.assertIn(jpeg(200), next(stream))
        self.assertTrue(camera.status()['connected'])
        self.assertEqual(seen, [30])
        release.set()
        self.assertTrue(finished.wait(1))
        self.assertEqual(seen, [30, 200])
        stream.close()
        self.assertEqual(camera.clients, 0)

    def test_inference_cooldown_replaces_work_without_stalling_video(self):
        first, second = threading.Event(), threading.Event()
        seen, starts, clock = [], [], [100.]
        def analyze(frame):
            seen.append(int(frame[0, 0, 0])); starts.append(clock[0])
            (first if len(seen) == 1 else second).set()
            return []
        camera = self.make(analyze=analyze)
        camera.thread = object()
        camera.INFERENCE_INTERVAL = 1
        with patch('features.live_camera.time.monotonic', side_effect=lambda: clock[0]):
            stream = camera.frames()
            camera.publish(jpeg(30), infer=True)
            next(stream)
            self.assertTrue(first.wait(1))
            camera.publish(jpeg(100), infer=True)
            camera.publish(jpeg(200), infer=True)
            self.assertIn(jpeg(200), next(stream))
            self.assertEqual(seen, [30])
            clock[0] = 101
            with camera.condition:
                camera.condition.notify_all()
            self.assertTrue(second.wait(1))
            self.assertEqual(seen, [30, 200])
            self.assertEqual(starts, [100, 101])
            stream.close()

    def test_expired_pending_analysis_is_dropped_before_running_the_model(self):
        analyze = MagicMock()
        camera = self.make(analyze=analyze)
        camera.publish(jpeg(100), infer=True, received_at=time.time() - 3)
        camera.analysis_thread.join(timeout=1)
        analyze.assert_not_called()
        self.assertTrue(camera.status()['connected'])
        self.assertFalse(camera.status()['detections_available'])

    def test_raw_jpeg_is_preserved_and_invalid_frame_never_becomes_live(self):
        camera = self.make()
        frame = jpeg(100)
        camera.publish(frame)
        self.assertEqual(camera.frame, frame)
        with self.assertRaises(ValueError):
            camera.publish(b'not a JPEG')
        fresh = self.make()
        with self.assertRaises(ValueError):
            fresh.publish(b'not a JPEG')
        self.assertFalse(fresh.status()['connected'])

    def test_overlay_uses_current_pixels_and_expires(self):
        drawn = []
        def render(frame, detections, age):
            drawn.append(int(frame[0, 0, 0]))
            return frame
        camera = self.make(analyze=lambda frame: [{'box': [1, 2, 3, 4]}], render=render)
        camera.publish(jpeg(30), infer=True)
        self.wait_result(camera)
        camera.publish(jpeg(200))
        self.assertEqual(drawn, [200])
        decoded = cv2.imdecode(np.frombuffer(camera.frame, dtype=np.uint8), cv2.IMREAD_COLOR)
        self.assertEqual(int(decoded[0, 0, 0]), 200)
        camera.detected_at = time.time() - 1.1
        camera.publish(jpeg(100))
        self.assertEqual(drawn, [200])
        self.assertEqual(camera.frame, jpeg(100))

    def test_failed_inference_does_not_mark_good_video_offline(self):
        def fail(frame): raise ValueError('model error')
        camera = self.make(analyze=fail)
        camera.publish(jpeg(100), infer=True)
        with camera.condition:
            self.assertTrue(camera.condition.wait_for(lambda: camera.analysis_error is not None, timeout=1))
        self.assertTrue(camera.status()['connected'])
        self.assertFalse(camera.status()['detections_available'])
        camera.publish(jpeg(200))
        self.assertEqual(camera.frame, jpeg(200))

    def test_old_generation_cannot_publish_a_result_into_a_reconnected_stream(self):
        entered, release = threading.Event(), threading.Event()
        accepted = MagicMock()
        def slow(frame):
            entered.set(); release.wait(2); return [{'old': True}]
        camera = self.make(analyze=slow, on_result=accepted)
        self.addCleanup(release.set)
        camera.publish(jpeg(30), infer=True)
        self.assertTrue(entered.wait(1))
        worker = camera.analysis_thread
        with camera.condition: camera._clear_locked()
        camera.publish(jpeg(200))
        release.set(); worker.join(timeout=1)
        accepted.assert_not_called()
        self.assertTrue(camera.status()['connected'])
        self.assertEqual(camera.status()['detections'], [])
        self.assertEqual(camera.frame, jpeg(200))

    def test_expired_inference_is_rejected_and_does_not_get_a_new_timestamp(self):
        entered, release = threading.Event(), threading.Event()
        accepted = MagicMock()
        def slow(frame):
            entered.set(); release.wait(2); return [{'old': True}]
        camera = self.make(analyze=slow, on_result=accepted)
        self.addCleanup(release.set)
        camera.publish(jpeg(30), infer=True)
        self.assertTrue(entered.wait(1))
        worker = camera.analysis_thread
        # Change the window to avoid a multi-second sleep in the test.
        camera.RESULT_TTL = 0
        release.set(); worker.join(timeout=1)
        self.assertIsNone(camera.detected_at)
        accepted.assert_not_called()

    def test_two_viewers_share_one_reader_and_last_close_releases_response(self):
        camera = self.make()
        camera.thread = object()
        camera.response = MagicMock()
        response = camera.response
        camera.publish(jpeg(100))
        first, second = camera.frames(), camera.frames()
        next(first); next(second)
        self.assertEqual(camera.clients, 2)
        first.close(); response.close.assert_not_called()
        second.close(); response.close.assert_called_once()
        self.assertEqual(camera.clients, 0)
        self.assertFalse(camera.status()['connected'])
        self.assertIsNone(camera.pending)

    def test_stream_closes_each_image_part_and_sends_complete_next_headers_immediately(self):
        camera = self.make()
        camera.thread = object()
        stream = camera.frames()
        initial = jpeg(30)
        ok, encoded = cv2.imencode('.jpg', np.full((48, 64, 3), 200, dtype=np.uint8))
        self.assertTrue(ok)
        following = encoded.tobytes()
        self.assertNotEqual(len(initial), len(following))
        camera.publish(initial)
        first = next(stream)
        camera.publish(following)
        second = next(stream)
        stream.close()

        boundary = b'--frame\r\n'
        expected_headers = b'Content-Type: image/jpeg\r\n\r\n'
        # Parsing two consecutive chunks yields exactly two intact image parts
        # plus the complete, empty header of the next part. No duplicate boundary
        # or fixed length can mislabel the next image when its size changes.
        parts = (first + second).split(boundary)
        self.assertEqual(parts[0], b'')
        self.assertEqual(parts[1], expected_headers + initial + b'\r\n')
        self.assertEqual(parts[2], expected_headers + following + b'\r\n')
        self.assertEqual(parts[3], expected_headers)
        self.assertEqual(first, boundary + parts[1] + boundary + expected_headers)
        self.assertEqual(second, following + b'\r\n' + boundary + expected_headers)
        # Finish the pending part and confirm a separate MIME parser accepts
        # the wire stream and extracts the exact image bytes, at different sizes.
        third = jpeg(100)
        message = BytesParser(policy=default).parsebytes(
            b'MIME-Version: 1.0\r\nContent-Type: multipart/x-mixed-replace; boundary=frame\r\n\r\n' +
            first + second + third + b'\r\n--frame--\r\n')
        self.assertEqual(message.defects, [])
        parsed = list(message.iter_parts())
        self.assertEqual([part.get_content_type() for part in parsed], ['image/jpeg'] * 3)
        self.assertEqual([part.get_payload(decode=True) for part in parsed], [initial, following, third])

    def test_network_batch_skips_old_complete_images(self):
        camera = self.make()
        camera.clients = 1
        response = camera.http.get.return_value.__enter__.return_value
        response.headers = {'Content-Type': 'multipart/x-mixed-replace; boundary=camera'}
        response.raw = None  # Exercise compatibility with HTTP adapters lacking read1.
        def chunks(**kwargs):
            yield jpeg(30) + jpeg(100) + jpeg(200)
            with camera.condition:
                self.assertTrue(camera.condition.wait_for(lambda: camera.sequence == 1, timeout=1))
            camera.clients = 0
        response.iter_content.side_effect = chunks
        camera._run()
        self.assertEqual(camera.sequence, 1)
        self.assertEqual(camera.frame, jpeg(200))
        camera.http.get.assert_called_once()
        response.iter_content.assert_called_once_with(chunk_size=1024)

    def test_available_read_publishes_partial_socket_batch_without_waiting_for_next_frame(self):
        camera = self.make()
        camera.clients = 1
        response = camera.http.get.return_value.__enter__.return_value
        response.headers = {'Content-Type': 'multipart/x-mixed-replace; boundary=camera'}
        frame = jpeg(100)
        # An available read can return less than the requested ceiling. At the
        # next read, prove that the completed frame is already visible even if
        # the camera has yet to expose/send another image.
        def read1(*_args, **_kwargs):
            if response.raw.read1.call_count == 1:
                return b'--camera\r\nContent-Type: image/jpeg\r\n\r\n' + frame
            with camera.condition:
                self.assertTrue(camera.condition.wait_for(lambda: camera.frame == frame, timeout=1))
            self.assertTrue(camera.status()['connected'])
            camera.clients = 0
            return b''
        response.raw.read1.side_effect = read1
        camera._run()
        self.assertEqual(camera.sequence, 1)
        response.iter_content.assert_not_called()

    def run_mock_stream(self, camera, chunks):
        camera.clients = 1
        response = camera.http.get.return_value.__enter__.return_value
        response.headers = {'Content-Type': 'multipart/x-mixed-replace; boundary=frame'}
        response.raw = None
        response.iter_content.side_effect = chunks

        def connect(*_args, **_kwargs):
            # Stop after an unexpected retry so a parser regression fails the
            # assertions instead of repeatedly reopening the fixture forever.
            if camera.http.get.call_count > 1:
                camera.clients = 0
            return camera.http.get.return_value

        camera.http.get.side_effect = connect
        camera._run()

    def test_complete_jpeg_after_frame_deadline_recovers_without_reopening(self):
        for split_image in (False, True):
            with self.subTest(split_image=split_image):
                camera = self.make()
                first, following = jpeg(30), jpeg(200)
                clock = SimpleNamespace(wall=1000., monotonic=100.)

                def chunks(**_kwargs):
                    yield first
                    with camera.condition:
                        self.assertTrue(camera.condition.wait_for(lambda: camera.frame == first, timeout=1))
                    cut = len(following) // 2 if split_image else 0
                    if cut:
                        yield b'\r\n--frame\r\nContent-Type: image/jpeg\r\n\r\n' + following[:cut]
                    clock.wall += 10.1
                    clock.monotonic += 10.1
                    self.assertFalse(camera.status()['connected'], 'The old image must expire during the gap')
                    yield following[cut:]
                    with camera.condition:
                        self.assertTrue(camera.condition.wait_for(lambda: camera.frame == following, timeout=1))
                        camera.clients = 0

                with patch('features.live_camera.time.time', lambda: clock.wall), \
                     patch('features.live_camera.time.monotonic', lambda: clock.monotonic):
                    self.run_mock_stream(camera, chunks)
                    self.assertEqual(camera.source_errors, 0)
                    self.assertEqual(camera.generation, 0)
                    self.assertEqual(camera.frame, following)
                    self.assertEqual(camera.received_frames, 2)
                    self.assertEqual(camera.updated_at, 1010.1)
                    self.assertTrue(camera.status()['connected'])
                    camera.http.get.assert_called_once()

    def test_incomplete_bytes_after_frame_deadline_still_fail_as_stalled(self):
        camera = self.make()
        clock = SimpleNamespace(monotonic=100.)

        def chunks(**_kwargs):
            yield b'--frame\r\nContent-Type: image/jpeg\r\n\r\n\xff\xd8incomplete'
            clock.monotonic += 10.1
            yield b'still no complete JPEG'
            camera.clients = 0

        with patch('features.live_camera.time.monotonic', lambda: clock.monotonic):
            self.run_mock_stream(camera, chunks)
        self.assertEqual(camera.source_errors, 1)
        self.assertEqual(camera.last_source_error_code, 'frame_stalled')
        self.assertEqual(camera.generation, 1)
        self.assertEqual(camera.received_frames, 0)
        self.assertIsNone(camera.frame)

    def test_oversized_buffer_is_rejected_even_when_it_contains_a_complete_jpeg(self):
        camera = self.make()

        def chunks(**_kwargs):
            yield b'x' * (2 * 1024 * 1024) + jpeg(200)
            camera.clients = 0

        self.run_mock_stream(camera, chunks)
        self.assertEqual(camera.source_errors, 1)
        self.assertEqual(camera.last_source_error_code, 'frame_too_large')
        self.assertEqual(camera.generation, 1)
        self.assertEqual(camera.received_frames, 0)
        self.assertIsNone(camera.frame)

    def test_stale_generation_input_cannot_replace_current_video(self):
        camera = self.make()
        previous = camera.generation
        with camera.condition: camera._clear_locked()
        camera.publish(jpeg(200))
        self.assertFalse(camera.publish(jpeg(30), generation=previous))
        self.assertEqual(camera.frame, jpeg(200))

    def paused_decoder(self):
        entered, release = threading.Event(), threading.Event()
        decoded = []
        def decode(*args):
            if not decoded:
                entered.set()
                release.wait(2)
            image = cv2.imdecode(*args)
            decoded.append(int(image[0, 0, 0]))
            return image
        self.addCleanup(release.set)
        return SimpleNamespace(imdecode=decode, IMREAD_COLOR=cv2.IMREAD_COLOR), entered, release, decoded

    def test_busy_video_decoder_keeps_only_latest_input_and_preserves_arrival_time(self):
        cv, entered, release, decoded = self.paused_decoder()
        camera = self.make(cv=cv)
        camera.clients = 1
        camera._queue_video(jpeg(30), camera.generation)
        self.assertTrue(entered.wait(1))
        camera._queue_video(jpeg(100), camera.generation)
        camera._queue_video(jpeg(200), camera.generation)
        received_at = camera.video_pending[1]
        self.assertEqual(camera.video_pending[0], jpeg(200))
        self.assertEqual(camera.status()['skipped_video_frames'], 1)
        release.set()
        with camera.condition:
            self.assertTrue(camera.condition.wait_for(lambda: camera.sequence == 2, timeout=1))
        self.assertEqual(decoded, [30, 200])
        self.assertEqual(camera.frame, jpeg(200))
        self.assertEqual(camera.updated_at, received_at)
        self.assertGreaterEqual(camera.status()['video_processing_ms'], 0)

    def test_last_viewer_close_drops_pending_video_and_fences_slow_decode(self):
        camera = self.make()
        camera.thread = object()
        camera.publish(jpeg(100))
        stream = camera.frames()
        next(stream)
        cv, entered, release, _ = self.paused_decoder()
        camera.cv = cv
        camera._queue_video(jpeg(30), camera.generation)
        self.assertTrue(entered.wait(1))
        worker = camera.video_thread
        camera._queue_video(jpeg(200), camera.generation)
        stream.close()
        self.assertIsNone(camera.video_pending)
        release.set(); worker.join(timeout=1)
        self.assertFalse(worker.is_alive())
        self.assertIsNone(camera.video_thread)
        self.assertIsNone(camera.frame)
        self.assertFalse(camera.status()['connected'])
        self.assertEqual(camera.status()['skipped_video_frames'], 0)
        self.assertIsNone(camera.status()['video_processing_ms'])

    def test_slow_previous_generation_video_cannot_replace_reconnected_frame(self):
        cv, entered, release, _ = self.paused_decoder()
        camera = self.make(cv=cv)
        camera.clients = 1
        camera._queue_video(jpeg(30), camera.generation)
        self.assertTrue(entered.wait(1))
        with camera.condition:
            camera._clear_locked()
        camera._queue_video(jpeg(200), camera.generation)
        release.set()
        with camera.condition:
            self.assertTrue(camera.condition.wait_for(lambda: camera.frame == jpeg(200), timeout=1))
        self.assertEqual(camera.sequence, 1)

    def test_persistent_invalid_video_clears_state_and_interrupts_upstream(self):
        camera = self.make()
        camera.INVALID_FRAME_GRACE = 0
        camera.clients = 1
        closed = threading.Event()
        camera.response = MagicMock()
        camera.response.close.side_effect = closed.set
        camera.publish(jpeg(30))
        generation = camera.generation
        camera._queue_video(b'not a JPEG', generation)
        self.assertTrue(closed.wait(1))
        self.assertGreater(camera.generation, generation)
        self.assertFalse(camera.status()['connected'])
        self.assertIsNone(camera.video_pending)
        camera._queue_video(jpeg(200), camera.generation)
        with camera.condition:
            self.assertTrue(camera.condition.wait_for(lambda: camera.frame == jpeg(200), timeout=1))
        self.assertTrue(camera.status()['connected'])

    def test_persistent_invalid_jpeg_reconnects_reader_and_accepts_new_frames(self):
        camera = self.make()
        camera.INVALID_FRAME_GRACE = 0
        camera.clients = 1
        closed = threading.Event()
        invalid, valid = MagicMock(), MagicMock()
        for response in (invalid, valid):
            response.headers = {'Content-Type': 'multipart/x-mixed-replace; boundary=frame'}
            response.__enter__.return_value = response
        invalid.close.side_effect = closed.set
        def invalid_read(*_args, **_kwargs):
            if invalid.raw.read1.call_count == 1:
                return b'\xff\xd8not a valid image\xff\xd9'
            self.assertTrue(closed.wait(1))
            return b''
        def valid_read(*_args, **_kwargs):
            if valid.raw.read1.call_count == 1:
                return jpeg(200)
            with camera.condition:
                self.assertTrue(camera.condition.wait_for(lambda: camera.frame == jpeg(200), timeout=1))
                camera.clients = 0
            return b''
        invalid.raw.read1.side_effect = invalid_read
        valid.raw.read1.side_effect = valid_read
        camera.http.get.side_effect = [invalid, valid]
        camera._run()
        self.assertEqual(camera.http.get.call_count, 2)
        invalid.close.assert_called_once()
        self.assertEqual(camera.generation, 1)
        self.assertEqual(camera.frame, jpeg(200))
        self.assertTrue(camera.status()['connected'])

    def test_isolated_bad_jpeg_is_dropped_without_disconnect_or_timestamp_renewal(self):
        camera = self.make()
        camera.clients = 1
        camera.response = MagicMock()
        camera.publish(jpeg(30))
        captured_at, generation = camera.updated_at, camera.generation
        camera._queue_video(b'not a jpeg', generation)
        with camera.condition:
            self.assertTrue(camera.condition.wait_for(lambda: camera.invalid_frames == 1, timeout=1))
        self.assertEqual(camera.updated_at, captured_at)
        self.assertEqual(camera.generation, generation)
        self.assertTrue(camera.status()['connected'])
        camera.response.close.assert_not_called()
        camera._queue_video(jpeg(200), generation)
        with camera.condition:
            self.assertTrue(camera.condition.wait_for(lambda: camera.frame == jpeg(200), timeout=1))
        self.assertEqual(camera.source_errors, 0)

    def test_multipart_resynchronizes_after_a_truncated_image_without_reopening(self):
        camera = self.make()
        camera.clients = 1
        response = camera.http.get.return_value.__enter__.return_value
        response.headers = {'Content-Type': 'multipart/x-mixed-replace; boundary=frame'}
        response.raw = None
        valid = jpeg(200)
        def chunks(**_kwargs):
            yield b'--frame\r\nContent-Type: image/jpeg\r\n\r\n\xff\xd8truncated'
            yield b'\r\n--frame\r\nContent-Type: image/jpeg\r\n\r\n' + valid
            with camera.condition:
                self.assertTrue(camera.condition.wait_for(lambda: camera.frame == valid, timeout=1))
            camera.clients = 0
        response.iter_content.side_effect = chunks
        camera._run()
        self.assertEqual(camera.invalid_frames, 1)
        self.assertEqual(camera.source_errors, 0)
        camera.http.get.assert_called_once()

    def test_large_changing_jpegs_cross_chunk_boundaries_without_connection_reset(self):
        camera = self.make()
        camera.clients = 1
        response = camera.http.get.return_value.__enter__.return_value
        response.headers = {'Content-Type': 'multipart/x-mixed-replace; boundary=frame'}
        response.raw = None
        random = np.random.default_rng(7)
        images = [cv2.imencode('.jpg', random.integers(0, 256, (240, 320, 3), dtype=np.uint8),
                               [cv2.IMWRITE_JPEG_QUALITY, 95])[1].tobytes() for _ in range(2)]
        self.assertTrue(all(len(value) > 64*1024 for value in images))
        def chunks(**_kwargs):
            for image in images:
                packet = b'\r\n--frame\r\nContent-Type: image/jpeg\r\n\r\n' + image
                for offset in range(0, len(packet), 1600):
                    yield packet[offset:offset+1600]
            with camera.condition:
                self.assertTrue(camera.condition.wait_for(lambda: camera.frame == images[-1], timeout=2))
            camera.clients = 0
        response.iter_content.side_effect = chunks
        camera._run()
        self.assertEqual(camera.invalid_frames, 0)
        self.assertEqual(camera.source_errors, 0)
        camera.http.get.assert_called_once()

    def test_optional_diagnostics_errors_cannot_interrupt_video_or_accept_stale_frames(self):
        camera = self.make()
        called = []
        def callback():
            self.assertFalse(camera.condition._is_owned())
            called.append(True)
            raise RuntimeError('Fixture diagnostics error')
        camera.on_frame = callback
        self.assertTrue(camera.publish(jpeg(100)))
        self.assertEqual(called, [True])
        self.assertFalse(camera.publish(jpeg(200), received_at=time.time()-6))
        self.assertEqual(called, [True])

    def test_expired_received_video_is_not_published_after_slow_processing(self):
        camera = self.make()
        self.assertFalse(camera.publish(jpeg(200), received_at=time.time() - camera.VIDEO_TTL - 1))
        self.assertIsNone(camera.frame)
        self.assertFalse(camera.status()['connected'])

    def test_read_tolerance_does_not_extend_five_second_video_freshness(self):
        camera = self.make()
        camera.publish(jpeg(100))
        received_at = camera.updated_at
        with patch('features.live_camera.time.time', return_value=received_at + 4.9):
            self.assertTrue(camera.status()['connected'])
        with patch('features.live_camera.time.time', return_value=received_at + 5.1):
            self.assertFalse(camera.status()['connected'])

    def test_expired_picture_resumes_on_same_upstream_after_six_second_gap(self):
        """An expired picture must not force a still-recoverable socket to reopen."""
        first, following = jpeg(30), jpeg(200)
        stop, resume = threading.Event(), threading.Event()
        connections = []

        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def log_message(self, *_args):
                pass

            def do_GET(self):
                connections.append(self.path)
                self.send_response(200)
                self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=camera')
                self.send_header('Transfer-Encoding', 'chunked')
                self.end_headers()

                def send(chunk):
                    self.wfile.write(f'{len(chunk):x}\r\n'.encode() + chunk + b'\r\n')
                    self.wfile.flush()

                try:
                    send(b'--camera\r\nContent-Type: image/jpeg\r\n\r\n' + first + b'\r\n')
                    if not resume.wait(15) or stop.is_set():
                        return
                    send(b'--camera\r\nContent-Type: image/jpeg\r\n\r\n' + following + b'\r\n')
                    while not stop.wait(.05):
                        send(b'\r\n')
                    self.wfile.write(b'0\r\n\r\n')
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        session = requests.Session()
        session.trust_env = False
        camera = LiveCamera(f'http://127.0.0.1:{server.server_port}/stream', session, cv2, np)
        viewer = ('owner', 'gap-viewer')
        server_thread.start()
        try:
            initial = camera.snapshot(viewer)
            self.assertEqual(initial['state'], 'frame')
            self.assertEqual(initial['jpeg'], first)
            generation, upstream = camera.generation, camera.response

            # Use the production timeouts: the former five-second socket limit
            # must fail this gap even though the viewer lease remains active.
            stop.wait(6)
            self.assertGreater(time.time() - initial['received_at'], camera.VIDEO_TTL)
            self.assertFalse(camera.status()['connected'])
            self.assertEqual(camera.snapshot(viewer, initial['sequence'], generation, timeout=0)['state'],
                             'unavailable', 'The expired JPEG must not be returned while waiting')
            self.assertEqual(camera.generation, generation)
            self.assertEqual(camera.source_errors, 0)
            self.assertIs(camera.response, upstream)
            self.assertEqual(connections, ['/stream'])

            resume.set()
            with camera.condition:
                self.assertTrue(camera.condition.wait_for(lambda: camera.sequence > initial['sequence'], timeout=2))
            current = camera.snapshot(viewer, initial['sequence'], generation, timeout=0)
            self.assertEqual(current['state'], 'frame')
            self.assertEqual(current['jpeg'], following)
            self.assertGreater(current['received_at'], initial['received_at'])
            self.assertTrue(camera.status()['connected'])
            self.assertEqual(current['generation'], generation)
            self.assertEqual(camera.source_errors, 0)
            self.assertIsNone(camera.error)
            self.assertIs(camera.response, upstream)
            self.assertEqual(connections, ['/stream'], 'Recovery must retain the original HTTP request')
        finally:
            stop.set()
            resume.set()
            camera.close_snapshot(viewer)
            if camera.thread:
                camera.thread.join(timeout=2)
            if camera.video_thread:
                camera.video_thread.join(timeout=1)
            if camera.snapshot_thread:
                camera.snapshot_thread.join(timeout=1)
            session.close()
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=1)

    def test_short_gap_keeps_the_same_chunked_upstream(self):
        """A 2.3-second gap is within video freshness, not a failed stream."""
        first, following = jpeg(30), jpeg(200)
        stop = threading.Event()
        connections = []

        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def log_message(self, *_args):
                pass

            def do_GET(self):
                connections.append(self.path)
                self.send_response(200)
                self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=camera')
                self.send_header('Transfer-Encoding', 'chunked')
                self.end_headers()

                def send(chunk):
                    self.wfile.write(f'{len(chunk):x}\r\n'.encode() + chunk + b'\r\n')
                    self.wfile.flush()

                try:
                    for image in (first, following):
                        send(b'--camera\r\nContent-Type: image/jpeg\r\n\r\n' + image + b'\r\n')
                        if image is first and stop.wait(2.3):
                            return
                    # Keep the response open until the consumer has checked the
                    # resumed image; tiny reads also make cleanup interruptible.
                    while not stop.wait(.05):
                        send(b'\r\n')
                    self.wfile.write(b'0\r\n\r\n')
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        session = requests.Session()
        session.trust_env = False
        camera = LiveCamera(f'http://127.0.0.1:{server.server_port}/stream', session, cv2, np)
        stream = camera.frames()
        server_thread.start()
        try:
            self.assertIn(first, next(stream))
            initial_at = camera.updated_at
            self.assertIn(following, next(stream))
            self.assertGreater(camera.updated_at - initial_at, 2)
            self.assertTrue(camera.status()['connected'])
            self.assertEqual(camera.generation, 0, 'A brief data gap must not reset video state')
            self.assertEqual(connections, ['/stream'], 'Resumption must reuse the original connection')
            decoded = cv2.imdecode(np.frombuffer(camera.frame, dtype=np.uint8), cv2.IMREAD_COLOR)
            self.assertEqual(int(decoded[0, 0, 0]), 200)
        finally:
            stop.set()
            stream.close()
            if camera.thread:
                camera.thread.join(timeout=2)
            if camera.video_thread:
                camera.video_thread.join(timeout=1)
            session.close()
            server.shutdown()
            server.server_close()
            server_thread.join(timeout=1)
