"""Offline MJPEG, freshness, model isolation, and subscriber lifetime checks."""
import time
import unittest
from unittest.mock import MagicMock
import numpy as np
from features.nightvision import NightVision


class NightVisionTests(unittest.TestCase):
    def setUp(self):
        self.cv = MagicMock()
        self.cv.imdecode.return_value = object()
        self.cv.imencode.return_value = (True, np.array([255, 216, 255, 217], dtype=np.uint8))
        self.model = MagicMock()
        box = MagicMock()
        box.conf.item.return_value = .8
        box.xyxy[0].tolist.return_value = [1, 2, 3, 4]
        self.model.return_value = [MagicMock(boxes=[box])]
        self.factory = MagicMock(return_value=self.model)
        self.http = MagicMock()
        self.camera = NightVision('http://camera:81/stream', self.http, self.cv, np, self.factory)

    def test_constructor_does_not_connect_or_load_model(self):
        self.http.get.assert_not_called()
        self.factory.assert_not_called()
        self.assertTrue(self.camera.status()['configured'])
        self.assertFalse(self.camera.status()['connected'])

    def test_full_analysis_is_lazy_and_disabled_mode_never_loads_either_model(self):
        pose_factory = MagicMock()
        camera = NightVision('http://camera:81/stream', self.http, self.cv, np, self.factory,
                             detection=False, pose_factory=pose_factory, classifier=MagicMock())
        self.http.get.assert_not_called()
        self.factory.assert_not_called()
        pose_factory.assert_not_called()
        camera.publish(b'jpeg', infer=True)
        self.factory.assert_not_called()
        pose_factory.assert_not_called()
        self.assertFalse(camera.status()['person_analysis_enabled'])

    def test_invalid_frame_never_becomes_live(self):
        self.cv.imdecode.return_value = None
        with self.assertRaises(ValueError):
            self.camera.publish(b'bad')
        self.assertFalse(self.camera.status()['connected'])

    def test_detection_is_source_labelled_and_stale_results_disappear(self):
        self.camera.publish(b'jpeg', infer=True)
        with self.camera.condition:
            self.assertTrue(self.camera.condition.wait_for(lambda: self.camera.detected_at is not None, timeout=1))
        status = self.camera.status()
        self.assertTrue(status['detections_available'])
        self.assertEqual(status['detections'][0]['source'], 'nightvision')
        self.assertNotIn('age', status['detections'][0])
        self.model.assert_called_once_with(self.cv.imdecode.return_value, classes=[14], conf=.25, verbose=False)
        self.camera.updated_at = time.time() - 10
        self.assertFalse(self.camera.status()['connected'])
        self.assertEqual(self.camera.status()['detections'], [])

    def test_detection_can_be_disabled_without_losing_video(self):
        self.camera.detection = False
        self.camera.publish(b'jpeg', infer=True)
        self.factory.assert_not_called()
        self.cv.imencode.assert_not_called()
        self.assertEqual(self.camera.frame, b'jpeg')
        self.assertTrue(self.camera.status()['connected'])
        self.assertFalse(self.camera.status()['detections_available'])

    def test_multiple_viewers_share_worker_and_closing_releases_subscriptions(self):
        # Suppress the worker for this lifetime test; publish known frames directly.
        self.camera.thread = object()
        self.camera.publish(b'jpeg')
        a, b = self.camera.frames(), self.camera.frames()
        self.assertIn(b'Content-Type: image/jpeg', next(a))
        next(b)
        self.assertEqual(self.camera.clients, 2)
        a.close(); b.close()
        self.assertEqual(self.camera.clients, 0)

    def test_mjpeg_parser_handles_split_frames_and_closes_upstream(self):
        response = self.http.get.return_value.__enter__.return_value
        response.headers = {'Content-Type': 'multipart/x-mixed-replace; boundary=camera'}
        response.raw = None
        self.camera.clients = 1
        def chunks(**kwargs):
            yield b'--camera\r\nContent-Type: image/jpeg\r\n\r\n\xff'
            yield b'\xd8jpeg\xff\xd9\r\n'
            with self.camera.condition:
                self.assertTrue(self.camera.condition.wait_for(lambda: self.camera.sequence == 1, timeout=1))
            self.camera.clients = 0
        response.iter_content.side_effect = chunks
        self.camera._run()
        self.assertEqual(self.camera.sequence, 1)
        self.cv.imdecode.assert_called_once()
        self.http.get.return_value.__exit__.assert_called_once()
        self.assertIsNone(self.camera.thread)


if __name__ == '__main__':
    unittest.main()
