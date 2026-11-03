"""Synthetic localhost check: real HTTP video continues while inference waits.

No robot, local credentials, account, cloud storage or camera config is used.
"""
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import threading
import time

import cv2
import numpy as np
import requests
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from features.live_camera import LiveCamera


def check_receive_tail():
    """Hold the next exposure: a completed JPEG must already be published.

    Test both plain multipart and ESP-IDF-style chunked multipart. Fixed-size
    requests reads buffer the plain stream; its chunked path already flushes at
    the end of each HTTP chunk. These timings measure localhost receive delay,
    never physical camera, radio, display or end-to-end latency.
    """
    stop = threading.Event()
    exposure_interval = .35
    ok, encoded = cv2.imencode('.jpg', np.full((24, 32, 3), 100, dtype=np.uint8))
    assert ok
    jpeg = encoded.tobytes()
    header = (b'--frame\r\nContent-Type: image/jpeg\r\nContent-Length: ' +
              str(len(jpeg)).encode() + b'\r\n\r\n')
    assert len(header + jpeg + b'\r\n') < 1024

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
        def log_message(self, *_args): pass
        def do_GET(self):
            self.close_connection = True
            chunked = self.path == '/chunked'
            self.send_response(200)
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=frame')
            if chunked:
                self.send_header('Transfer-Encoding', 'chunked')
            self.end_headers()
            try:
                for _ in range(2):
                    for data in (header, jpeg, b'\r\n'):
                        if chunked:
                            self.wfile.write(f'{len(data):x}\r\n'.encode() + data + b'\r\n')
                        else:
                            self.wfile.write(data)
                    self.wfile.flush()
                    if stop.wait(exposure_interval):
                        return
                stop.wait(2)
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    session = requests.Session()
    session.trust_env = False
    try:
        for transport in ('plain', 'chunked'):
            url = f'http://127.0.0.1:{server.server_port}/{transport}'
            began = time.monotonic()
            with session.get(url, stream=True, timeout=(1, 1)) as response:
                buffer = b''
                for chunk in response.iter_content(chunk_size=1024):
                    buffer += chunk
                    if b'\xff\xd9' in buffer:
                        break
            fixed_ms = (time.monotonic() - began) * 1000
            camera = LiveCamera(url, session, cv2, np)
            stream = camera.frames()
            began = time.monotonic()
            try:
                packet = next(stream)
                available_ms = (time.monotonic() - began) * 1000
                assert jpeg in packet
                assert available_ms < exposure_interval * 750, 'Frame waited for another exposure.'
            finally:
                stream.close()
                if camera.thread:
                    camera.thread.join(timeout=3)
            print(f'PASS: {transport} multipart first complete JPEG: fixed 1024-byte reader '
                  f'{fixed_ms:.1f} ms; available-byte pipeline {available_ms:.1f} ms '
                  f'(next exposure held {exposure_interval * 1000:.0f} ms).', flush=True)
    finally:
        stop.set()
        session.close()
        server.shutdown(); server.server_close(); thread.join(timeout=1)


def check_concurrent_viewers():
    stop, entered, release = threading.Event(), threading.Event(), threading.Event()
    connections = []
    rng = np.random.default_rng(7)
    frames = []
    for _ in range(20):
        ok, encoded = cv2.imencode('.jpg', rng.integers(0, 256, (48, 64, 3), dtype=np.uint8))
        assert ok
        frames.append(encoded.tobytes())

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args): pass
        def do_GET(self):
            connections.append(True)
            self.send_response(200)
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=frame')
            self.end_headers()
            index = 0
            try:
                while not stop.is_set():
                    data = frames[index % len(frames)]
                    self.wfile.write(b'--frame\r\nContent-Type: image/jpeg\r\nContent-Length: ' +
                                     str(len(data)).encode() + b'\r\n\r\n' + data + b'\r\n')
                    self.wfile.flush()
                    index += 1
                    stop.wait(.04)
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    calls = []
    def slow_model(frame):
        calls.append(True)
        entered.set()
        release.wait(5)
        return []
    session = requests.Session()
    session.trust_env = False
    camera = LiveCamera(f'http://127.0.0.1:{server.server_port}/stream', session, cv2, np, analyze=slow_model)
    first, second = camera.frames(), camera.frames()
    def collect(stream):
        return [next(stream) for _ in range(10)]
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            one, two = pool.submit(collect, first), pool.submit(collect, second)
            assert entered.wait(2), 'The slow model did not start.'
            a, b = one.result(timeout=4), two.result(timeout=4)
            assert len(set(a)) >= 8 and len(set(b)) >= 8, 'Video repeated old images while inference waited.'
            assert not release.is_set() and len(calls) == 1, 'Inference was not held during video delivery.'
            assert len(connections) == 1, 'Two viewers opened two upstream camera connections.'
            print('PASS: two viewers each received 10 changing HTTP frames while inference was blocked.', flush=True)
            print('PASS: one upstream connection; pending inference input remains a single latest frame.', flush=True)
    finally:
        first.close(); second.close()
        assert camera.clients == 0 and camera.pending is None
        release.set(); stop.set()
        if camera.analysis_thread: camera.analysis_thread.join(timeout=2)
        if camera.thread: camera.thread.join(timeout=3)
        session.close()
        server.shutdown(); server.server_close(); thread.join(timeout=1)
    print('PASS: final viewer cleanup released the synthetic stream. No physical FPS was measured.', flush=True)


def check_slow_video_processing():
    """Real chunked HTTP at 15 FPS with a deliberately slow 120 ms decoder.

    Compare synchronous receive/decode with the production latest-only publisher.
    This injects processing delay to prove bounded queuing, rather than claiming
    that normal QVGA decoding takes 120 ms on the operator's laptop.
    """
    stop = threading.Event()
    sent = {'/synchronous': {}, '/latest': {}}
    frames = []
    for index in range(200):
        ok, encoded = cv2.imencode('.jpg', np.full((24, 32, 3), index, dtype=np.uint8))
        assert ok
        frames.append(encoded.tobytes())
    assert len(set(frames)) == len(frames)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
        def log_message(self, *_args): pass
        def do_GET(self):
            self.close_connection = True
            self.send_response(200)
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=frame')
            self.send_header('Transfer-Encoding', 'chunked')
            self.end_headers()
            began = time.monotonic()
            try:
                for index, jpeg in enumerate(frames):
                    if stop.is_set(): return
                    sent[self.path][jpeg] = time.monotonic()
                    # The current ESP firmware sends one multipart image packet
                    # per HTTP chunk; a read1 cannot combine subsequent chunks.
                    packet = (b'--frame\r\nContent-Type: image/jpeg\r\nContent-Length: ' +
                              str(len(jpeg)).encode() + b'\r\n\r\n' + jpeg + b'\r\n')
                    self.wfile.write(f'{len(packet):x}\r\n'.encode() + packet + b'\r\n')
                    self.wfile.flush()
                    stop.wait(max(0, began + (index + 1) / 15 - time.monotonic()))
            except (BrokenPipeError, ConnectionResetError):
                pass

    class SlowCV:
        def __getattr__(self, name): return getattr(cv2, name)
        def imdecode(self, *args):
            time.sleep(.12)
            return cv2.imdecode(*args)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    session = requests.Session()
    session.trust_env = False
    try:
        old_ages = []
        url = f'http://127.0.0.1:{server.server_port}'
        with session.get(url + '/synchronous', stream=True, timeout=(1, 2)) as response:
            buffer = b''
            for chunk in LiveCamera._chunks(response):
                buffer += chunk
                start = buffer.find(b'\xff\xd8')
                end = buffer.find(b'\xff\xd9', start + 2) if start >= 0 else -1
                if end < 0: continue
                jpeg, buffer = buffer[start:end + 2], buffer[end + 2:]
                assert SlowCV().imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR) is not None
                old_ages.append((time.monotonic() - sent['/synchronous'][jpeg]) * 1000)
                if len(old_ages) == 20: break

        camera = LiveCamera(url + '/latest', session, SlowCV(), np)
        ages = []
        published = threading.Condition()
        publish = camera.publish
        def measured_publish(jpeg, **kwargs):
            accepted = publish(jpeg, **kwargs)
            if accepted:
                with published:
                    ages.append((time.monotonic() - sent['/latest'][jpeg]) * 1000)
                    published.notify_all()
            return accepted
        camera.publish = measured_publish
        stream = camera.frames()
        try:
            for _ in range(20): next(stream)
            with published:
                assert published.wait_for(lambda: len(ages) >= 20, timeout=1)
                delivered_ages = ages[:20]
            status = camera.status()
            assert old_ages[-1] > 800, 'The reference did not accumulate a processing backlog.'
            assert max(delivered_ages) < 550, 'Video input queued behind the deliberately slow decoder.'
            assert status['skipped_video_frames'] > 0, 'No pending frames were replaced.'
            print(f'PASS: 15 FPS chunked HTTP, injected 120 ms decode: synchronous frame20 '
                  f'age {old_ages[-1]:.1f} ms; latest-only max age {max(delivered_ages):.1f} ms, '
                  f'frame20 age {delivered_ages[-1]:.1f} ms; '
                  f'{status["skipped_video_frames"]} pending frames skipped.', flush=True)
        finally:
            stream.close()
            assert camera.video_pending is None
            if camera.video_thread: camera.video_thread.join(timeout=2)
            if camera.thread: camera.thread.join(timeout=3)
    finally:
        stop.set(); session.close()
        server.shutdown(); server.server_close(); thread.join(timeout=1)


if __name__ == '__main__':
    check_receive_tail()
    check_concurrent_viewers()
    check_slow_video_processing()
