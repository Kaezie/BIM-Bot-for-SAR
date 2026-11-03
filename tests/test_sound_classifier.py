"""Synthetic PCM/scores only; never opens a microphone or cloud."""
from pathlib import Path
import unittest
import numpy as np
from flask import Flask, request
from features.sound_classifier import SoundClassifier, SAMPLE_COUNT, PCM_BYTES


class FakeEngine:
    labels = ['Other'] * 521
    labels[0], labels[11], labels[353] = 'Speech', 'Screaming', 'Knock'
    chosen, score = 0, .9
    def predict(self, samples):
        assert samples.shape == (SAMPLE_COUNT,)
        values = np.zeros(521, dtype=np.float32)
        values[self.chosen] = self.score
        return values


class SoundTests(unittest.TestCase):
    def setUp(self):
        self.engine = FakeEngine()
        self.classifier = SoundClassifier(Path('/nonexistent'), engine_factory=lambda: self.engine)
        self.raw = np.zeros(SAMPLE_COUNT, dtype='<f4').tobytes()

    def test_event_scores_never_claim_words_or_survivors(self):
        result = self.classifier.classify(self.raw)
        self.assertEqual(result['event'], 'Possible speech')
        self.assertFalse(result['words_recognized'])
        self.assertFalse(result['survivor_confirmed'])
        self.assertFalse(result['audio_saved'])
        self.engine.chosen = 11
        self.assertEqual(self.classifier.classify(self.raw)['event'], 'Possible scream')
        self.engine.chosen = 353
        self.assertEqual(self.classifier.classify(self.raw)['event'], 'Possible knock')
        self.engine.score = .1
        self.assertEqual(self.classifier.classify(self.raw)['event'], 'Uncertain sound')

    def test_bad_lengths_and_invalid_samples_fail(self):
        for raw in (b'', self.raw[:-4], self.raw + b'xxxx',
                    np.full(SAMPLE_COUNT, np.nan, dtype='<f4').tobytes(),
                    np.full(SAMPLE_COUNT, 1.01, dtype='<f4').tobytes()):
            with self.assertRaises(ValueError):self.classifier.classify(raw)

    def test_busy_model_does_not_queue_requests(self):
        with self.classifier.lock:
            with self.assertRaises(BlockingIOError):self.classifier.classify(self.raw)
            self.assertTrue(self.classifier.status()['busy'])

    def test_missing_runtime_or_assets_hides_internal_errors(self):
        def unavailable():raise RuntimeError('private-path-or-key')
        status = SoundClassifier('/missing', engine_factory=unavailable).status()
        self.assertFalse(status['ready'])
        self.assertNotIn('private-path', str(status))

    def test_routes_require_auth_and_bounded_binary_input(self):
        app = Flask(__name__)
        def auth(function):
            def wrapped(*args, **kwargs):
                if request.headers.get('Authorization') != 'Bearer fixture':return {'error': 'Sign in'}, 401
                return function(*args, **kwargs)
            wrapped.__name__ = function.__name__
            return wrapped
        self.classifier.register(app, auth);client = app.test_client()
        self.assertEqual(client.get('/api/sound-model').status_code, 401)
        self.assertEqual(client.post('/api/sound-classify', data=self.raw).status_code, 401)
        headers = {'Authorization': 'Bearer fixture', 'X-Sample-Rate': '16000', 'Content-Type': 'application/octet-stream'}
        self.assertEqual(client.post('/api/sound-classify', data=b'bad', headers=headers).status_code, 400)
        response = client.post('/api/sound-classify', data=self.raw, headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertEqual(len(self.raw), PCM_BYTES)
        def unavailable():raise ValueError('private-runtime-detail')
        self.classifier.engine = None
        self.classifier.engine_factory = unavailable
        response = client.post('/api/sound-classify', data=self.raw, headers=headers)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('private-runtime-detail', response.get_data(as_text=True))


if __name__ == '__main__':unittest.main()
