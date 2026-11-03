"""Local YAMNet inference on explicit, short PCM requests. No audio storage."""
import csv
import hashlib
import json
from pathlib import Path
import threading
import time

import numpy as np
from flask import jsonify, request

SAMPLE_RATE = 16000
SAMPLE_COUNT = 15600
PCM_BYTES = SAMPLE_COUNT * 4
EVENTS = {
    'Speech': 'Possible speech', 'Child speech, kid speaking': 'Possible speech',
    'Conversation': 'Possible speech', 'Narration, monologue': 'Possible speech',
    'Shout': 'Possible shout', 'Yell': 'Possible shout', 'Children shouting': 'Possible shout',
    'Screaming': 'Possible scream', 'Crying, sobbing': 'Possible crying',
    'Baby cry, infant cry': 'Possible crying', 'Whimper': 'Possible crying',
    'Knock': 'Possible knock', 'Tap': 'Possible tapping', 'Silence': 'Silence/background',
}


class InvalidAudio(ValueError):
    pass


class YamNetEngine:
    def __init__(self, folder):
        from ai_edge_litert.compiled_model import CompiledModel
        from ai_edge_litert.hardware_accelerator import HardwareAccelerator

        folder = Path(folder)
        manifest = json.loads((folder / 'sources.json').read_text())
        for name in ('yamnet.tflite', 'yamnet_class_map.csv'):
            path = folder / name
            if hashlib.sha256(path.read_bytes()).hexdigest() != manifest[name]['sha256']:
                raise ValueError('Sound asset checksum mismatch.')
        with (folder / 'yamnet_class_map.csv').open(newline='') as source:
            rows = list(csv.DictReader(source))
        if len(rows) != 521 or [int(row['index']) for row in rows] != list(range(521)):
            raise ValueError('Unexpected sound label map.')
        self.labels = [row['display_name'] for row in rows]
        self.model = CompiledModel.from_file(str(folder / 'yamnet.tflite'), hardware_accel=HardwareAccelerator.CPU)
        key = next(iter(self.model.get_signature_list()))
        inputs, outputs = self.model.get_input_tensor_details(key), self.model.get_output_tensor_details(key)
        if [v['shape'] for v in inputs.values()] != [[SAMPLE_COUNT]] or [v['shape'] for v in outputs.values()] != [[1, 521]]:
            raise ValueError('Unexpected sound model dimensions.')
        self.inputs, self.outputs = self.model.create_input_buffers(0), self.model.create_output_buffers(0)

    def predict(self, samples):
        self.inputs[0].write(samples)
        self.model.run_by_index(0, self.inputs, self.outputs)
        return self.outputs[0].read(521, np.float32).reshape(-1)


class SoundClassifier:
    def __init__(self, folder, engine_factory=None):
        self.engine_factory = engine_factory or (lambda: YamNetEngine(folder))
        self.engine = None
        self.lock = threading.Lock()

    def prepare(self):
        if self.engine is None:
            self.engine = self.engine_factory()
        return self.engine

    def status(self):
        if not self.lock.acquire(blocking=False):
            return {'ready': False, 'busy': True, 'model': 'YAMNet'}
        try:
            self.prepare()
            return {'ready': True, 'model': 'YAMNet', 'sample_rate': SAMPLE_RATE,
                    'sample_count': SAMPLE_COUNT, 'audio_saved': False, 'words_recognized': False,
                    'message': 'Local sound-event model ready. Enable recognition manually; live accuracy remains unverified.'}
        except Exception:
            return {'ready': False, 'model': 'YAMNet', 'message': 'Local sound model unavailable. Check the model setup and restart the dashboard.'}
        finally:
            self.lock.release()

    def classify(self, raw):
        if len(raw) != PCM_BYTES:
            raise InvalidAudio('Expected one 0.975-second mono PCM frame at 16 kHz.')
        samples = np.frombuffer(raw, dtype='<f4').astype(np.float32, copy=True)
        if not np.isfinite(samples).all() or np.max(np.abs(samples)) > 1:
            raise InvalidAudio('Audio samples must be finite values from -1 to 1.')
        if not self.lock.acquire(blocking=False):
            raise BlockingIOError('Sound model is busy; retry with a fresh frame.')
        try:
            engine = self.prepare()
            started = time.perf_counter()
            scores = np.asarray(engine.predict(samples), dtype=float).reshape(-1)
            if len(scores) != 521 or not np.isfinite(scores).all() or np.min(scores) < 0 or np.max(scores) > 1:
                raise RuntimeError('Invalid sound model output.')
            indices = np.argsort(scores)[-5:][::-1]
            top = [{'label': engine.labels[int(i)], 'score': float(scores[i])} for i in indices]
            best = top[0]
            event = EVENTS.get(best['label'], 'Other audio event') if best['score'] >= .35 else 'Uncertain sound'
            return {'event': event, 'model_label': best['label'], 'score': best['score'], 'top_events': top,
                    'model': 'YAMNet', 'inference_ms': round((time.perf_counter() - started) * 1000, 2),
                    'audio_saved': False, 'words_recognized': False, 'survivor_confirmed': False,
                    'requires_verification': True, 'threshold': .35}
        finally:
            self.lock.release()

    def register(self, app, auth):
        @app.get('/api/sound-model')
        @auth
        def sound_model_status():
            response = jsonify(self.status())
            response.headers['Cache-Control'] = 'no-store'
            return response

        @app.post('/api/sound-classify')
        @auth
        def sound_classify():
            if request.content_length != PCM_BYTES or request.mimetype != 'application/octet-stream':
                return jsonify(error='Expected a bounded float32 PCM audio frame.'), 400
            if request.headers.get('X-Sample-Rate') != str(SAMPLE_RATE):
                return jsonify(error='Expected mono audio resampled to 16 kHz.'), 400
            try:
                result, status = self.classify(request.get_data(cache=False)), 200
            except InvalidAudio as error:
                result, status = {'error': str(error)}, 400
            except BlockingIOError:
                result, status = {'error': 'Sound model busy. The next fresh frame may be retried.'}, 429
            except Exception:
                result, status = {'error': 'Local sound model unavailable. Check setup; no audio was saved.'}, 503
            response = jsonify(result)
            response.status_code = status
            response.headers['Cache-Control'] = 'no-store'
            return response
