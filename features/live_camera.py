"""One MJPEG reader with latest-only video/inference slots for all viewers.

Timestamps measure reception on the laptop, not exposure or end-to-end latency.
"""
from collections import deque
from email.message import Message
from requests.exceptions import Timeout, ConnectionError, HTTPError
from urllib3.exceptions import ReadTimeoutError, ProtocolError, NewConnectionError
import threading
import time
from .monitoring_profile import PROFILE


class LiveCamera:
    VIDEO_TTL = 5
    # Image freshness and transport recovery have different deadlines. Clear
    # expired pixels at VIDEO_TTL while allowing the same source socket to
    # resume, instead of forcing another handshake at that exact boundary.
    READ_TIMEOUT = PROFILE['upstream_read_timeout_seconds']
    RESULT_TTL = 2
    OVERLAY_TTL = 1
    SNAPSHOT_LEASE = PROFILE['snapshot_lease_seconds']
    SNAPSHOT_WAIT = .75
    MAX_SNAPSHOT_VIEWERS = 128
    # Keep video publication independent of the two-model analysis workload.
    # Pending analysis is always replaced, never queued during this pause.
    INFERENCE_INTERVAL = PROFILE['inference_interval_seconds']
    INVALID_FRAME_GRACE = VIDEO_TTL

    def __init__(self, url, http, cv, np, analyze=None, render=None,
                 on_result=None, on_clear=None, source='main'):
        self.url, self.http, self.cv, self.np = url, http, cv, np
        self.analyze, self.render = analyze, render
        self.on_result, self.on_clear, self.source = on_result, on_clear, source
        self.condition = threading.Condition()
        self.clients = 0
        self.thread = self.analysis_thread = self.response = None
        self.video_thread = None
        self.frame = self.pending = self.video_pending = None
        self.sequence = self.generation = 0
        self.updated_at = self.detected_at = None
        self.detections = []
        self.error = self.analysis_error = None
        self.inference_ms = None
        self.video_processing_ms = None
        self.skipped_video_frames = 0
        self.analysis_generation = None
        self.analysis_received_at = None
        self.source_errors = 0
        self.last_source_error_at = self.last_source_error_stage = None
        self.last_source_error_code = None
        self.received_bytes = self.received_chunks = self.received_frames = 0
        self.last_byte_at = self.last_frame_bytes = None
        self.invalid_frames = 0
        self.last_invalid_frame_at = None
        self.on_frame = None
        self.arrivals = deque(maxlen=120)
        self.snapshot_clients = {}
        self.snapshot_thread = None

    def _retain_locked(self):
        self.clients += 1
        if self.clients == 1:
            self.error = None
        if self.thread is None:
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()

    def _release_locked(self, count=1):
        self.clients -= count
        response = None
        if self.clients == 0:
            response, self.response = self.response, None
            self._clear_locked()
        self.condition.notify_all()
        return response

    @staticmethod
    def _close_response(response):
        if response is not None:
            try:
                response.close()
            except Exception:
                pass

    def _expire_snapshot_clients(self):
        """Keep sequential image requests on one upstream, then release it."""
        while True:
            response = None
            with self.condition:
                now = time.monotonic()
                expired = [key for key, expires in self.snapshot_clients.items() if expires <= now]
                for key in expired:
                    del self.snapshot_clients[key]
                if expired:
                    response = self._release_locked(len(expired))
                if not self.snapshot_clients:
                    self.snapshot_thread = None
                    done = True
                else:
                    done = False
                    timeout = max(0, min(self.snapshot_clients.values()) - now)
                    if response is None:
                        self.condition.wait(timeout=timeout)
            self._close_response(response)
            if done:
                return

    def close_snapshot(self, viewer, *, asynchronous=False):
        """Release only this authenticated viewer's latest-image lease."""
        with self.condition:
            if viewer not in self.snapshot_clients:
                return False
            del self.snapshot_clients[viewer]
            response = self._release_locked()
        if asynchronous and response is not None:
            # Closing an upstream currently blocked in read can itself wait for
            # its socket timeout. Do not occupy a browser HTTP slot until then.
            threading.Thread(target=self._close_response, args=(response,), daemon=True).start()
        else:
            self._close_response(response)
        return True

    def set_url(self, url):
        """Fence an identified DHCP-address change without removing viewers."""
        with self.condition:
            if self.url == url:
                return False
            self.url = url
            response, self.response = self.response, None
            self._clear_locked()
        if response is not None:
            threading.Thread(target=self._close_response, args=(response,), daemon=True).start()
        return True

    def snapshot(self, viewer, sequence=-1, generation=-1, timeout=SNAPSHOT_WAIT):
        """Return one current JPEG, never a queue of earlier image responses.

        A viewer lease shares the ordinary MJPEG reader. Reception age is
        laptop-side freshness; it does not measure the camera's exposure time.
        """
        with self.condition:
            if not self.url:
                return {'state': 'unavailable', 'message': 'Camera not configured.'}
            if viewer not in self.snapshot_clients:
                if len(self.snapshot_clients) >= self.MAX_SNAPSHOT_VIEWERS:
                    return {'state': 'busy', 'message': 'Camera viewer limit reached.'}
                self._retain_locked()
            self.snapshot_clients[viewer] = time.monotonic() + self.SNAPSHOT_LEASE
            if self.snapshot_thread is None:
                self.snapshot_thread = threading.Thread(target=self._expire_snapshot_clients, daemon=True)
                self.snapshot_thread.start()
            self.condition.notify_all()
            deadline = time.monotonic() + min(self.SNAPSHOT_WAIT, max(0, timeout))
            while True:
                if viewer not in self.snapshot_clients:
                    return {'state': 'pending'}
                if self.error:
                    return {'state': 'unavailable', 'message': self.error}
                age = None if self.updated_at is None else time.time() - self.updated_at
                if self.frame is not None and age is not None:
                    if not 0 <= age < self.VIDEO_TTL:
                        return {'state': 'unavailable', 'message': 'Camera frame is no longer current.'}
                    if (sequence, generation) != (self.sequence, self.generation):
                        return {'state': 'frame', 'jpeg': self.frame,
                                'sequence': self.sequence, 'generation': self.generation,
                                'received_at': self.updated_at, 'age_ms': age * 1000}
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return {'state': 'pending'}
                self.condition.wait(timeout=remaining)

    def _clear_locked(self, message=None):
        self.generation += 1
        self.frame = self.pending = self.video_pending = None
        self.updated_at = self.detected_at = None
        self.detections = []
        self.arrivals.clear()
        self.video_processing_ms = None
        self.skipped_video_frames = 0
        self.error, self.analysis_error = message, None
        if self.on_clear:
            self.on_clear()
        self.condition.notify_all()

    def status(self):
        with self.condition:
            now = time.time()
            fresh = bool(self.updated_at and 0 <= now - self.updated_at < self.VIDEO_TTL and not self.error)
            results_fresh = bool(fresh and self.detected_at and 0 <= now - self.detected_at < self.RESULT_TTL)
            samples = list(self.arrivals)
            fps = ((len(samples) - 1) / (samples[-1] - samples[0])
                   if fresh and len(samples) > 1 and samples[-1] > samples[0] else None)
            return {'configured': bool(self.url), 'connected': fresh,
                    'updated_at': self.updated_at, 'source': self.source,
                    'detections_available': results_fresh,
                    'detections': list(self.detections) if results_fresh else [],
                    'detected_at': self.detected_at, 'received_fps': fps,
                    'inference_ms': self.inference_ms, 'analysis_error': self.analysis_error,
                    'video_processing_ms': self.video_processing_ms,
                    'skipped_video_frames': self.skipped_video_frames,
                    'source_errors': self.source_errors, 'last_source_error_at': self.last_source_error_at,
                    'last_source_error_stage': self.last_source_error_stage,
                    'last_source_error_code': self.last_source_error_code,
                    'received_bytes': self.received_bytes, 'received_chunks': self.received_chunks,
                    'received_frames': self.received_frames, 'last_byte_at': self.last_byte_at,
                    'last_frame_bytes': self.last_frame_bytes,
                    'invalid_frames': self.invalid_frames, 'last_invalid_frame_at': self.last_invalid_frame_at,
                    'message': self.error or ('Live camera.' if fresh else
                               'Select this camera to connect.' if self.url else 'Camera not configured.')}

    def publish(self, jpeg, infer=False, generation=None, received_at=None):
        received_at = time.time() if received_at is None else received_at
        with self.condition:
            generation = self.generation if generation is None else generation
            if generation != self.generation:
                return False
        decoded = self.cv.imdecode(self.np.frombuffer(jpeg, dtype=self.np.uint8), self.cv.IMREAD_COLOR)
        if decoded is None:
            raise ValueError('Invalid JPEG frame')
        with self.condition:
            if generation != self.generation:
                return False
            age = time.time() - self.detected_at if self.detected_at else None
            overlay = list(self.detections) if age is not None and 0 <= age < self.OVERLAY_TTL else []
        # Reuse the camera JPEG unless drawing an overlay on THIS current image.
        output = jpeg
        if overlay and self.render:
            try:
                image = self.render(decoded.copy(), overlay, age)
                ok, encoded = self.cv.imencode('.jpg', image, [self.cv.IMWRITE_JPEG_QUALITY, 80])
                if ok:
                    output = encoded.tobytes()
            except Exception:
                pass  # Overlay errors must not disable live video.
        with self.condition:
            if generation != self.generation or not 0 <= time.time() - received_at < self.VIDEO_TTL:
                return False
            self.frame, self.updated_at = output, received_at
            self.video_processing_ms = max(0, (time.time() - received_at) * 1000)
            self.sequence += 1
            self.arrivals.append(time.monotonic())
            self.error = None
            if infer and self.analyze:
                self.pending = (decoded, received_at, generation)
                if self.analysis_thread is None:
                    self.analysis_thread = threading.Thread(target=self._infer, daemon=True)
                    self.analysis_thread.start()
            self.condition.notify_all()
        callback = self.on_frame
        if callable(callback):
            try:
                callback()
            except Exception:
                pass  # Diagnostics must never interrupt valid video.
        return True

    def _queue_video(self, jpeg, generation):
        received_at = time.time()
        with self.condition:
            if not self.clients or generation != self.generation:
                return
            # Keep draining the socket even while JPEG validation/drawing is
            # busy. ESP HTTP chunks can contain only one image, so batching a
            # single read does not by itself discard a backlog across chunks.
            if self.video_pending is not None:
                self.skipped_video_frames += 1
            self.video_pending = (jpeg, received_at, generation)
            if self.video_thread is None:
                self.video_thread = threading.Thread(target=self._publish_video, daemon=True)
                self.video_thread.start()
            self.condition.notify_all()

    def _publish_video(self):
        previous_generation, invalid_since = None, None
        while True:
            with self.condition:
                while self.video_pending is None:
                    if not self.clients:
                        self.video_thread = None
                        return
                    self.condition.wait()
                jpeg, received_at, generation = self.video_pending
                self.video_pending = None
                if generation != self.generation:
                    continue
                if generation != previous_generation:
                    previous_generation, invalid_since = generation, None
            try:
                accepted = self.publish(jpeg, infer=True,
                                        generation=generation, received_at=received_at)
                if accepted:
                    invalid_since = None
            except Exception:
                response = None
                with self.condition:
                    if generation == self.generation:
                        self.invalid_frames += 1
                        self.last_invalid_frame_at = time.time()
                        self.condition.notify_all()
                        invalid_since = time.monotonic() if invalid_since is None else invalid_since
                        # Keep draining after an isolated damaged frame. Never
                        # renew the last valid image's reception timestamp.
                        if time.monotonic() - invalid_since < self.INVALID_FRAME_GRACE:
                            continue
                        self.source_errors += 1
                        self.last_source_error_at = time.time()
                        self.last_source_error_stage = 'video_decode'
                        self.last_source_error_code = 'invalid_jpeg'
                        response = self.response
                        self._clear_locked('Camera unavailable. Check Wi-Fi, power and stream address.')
                # Interrupt the corresponding reader so invalid JPEGs reconnect
                # just as they did when validation ran in that reader itself.
                if response is not None:
                    try:
                        response.close()
                    except Exception:
                        pass

    def _infer(self):
        next_analysis = 0
        while True:
            with self.condition:
                while self.pending is None or time.monotonic() < next_analysis:
                    if self.clients == 0 and self.pending is None:
                        self.analysis_thread = None
                        return
                    delay = max(0, next_analysis - time.monotonic()) if self.pending is not None else None
                    self.condition.wait(timeout=delay)
                image, received_at, generation = self.pending
                self.pending = None
                if generation != self.generation or not 0 <= time.time() - received_at < self.RESULT_TTL:
                    continue
                self.analysis_generation = generation
                self.analysis_received_at = received_at
            began = time.monotonic()
            next_analysis = began + self.INFERENCE_INTERVAL
            try:
                result = self.analyze(image)
                deferred = None
                with self.condition:
                    if generation != self.generation or not 0 <= time.time() - received_at < self.RESULT_TTL:
                        continue
                    self.detections, self.detected_at = list(result), received_at
                    self.inference_ms = (time.monotonic() - began) * 1000
                    self.analysis_error = None
                    # Commit state while fenced; run any returned evidence I/O
                    # after releasing the frame lock.
                    if self.on_result:
                        deferred = self.on_result(self.detections, received_at)
                    self.condition.notify_all()
                if callable(deferred):
                    deferred()
            except Exception:
                with self.condition:
                    if generation == self.generation:
                        self.detections, self.detected_at = [], None
                        self.analysis_error = 'Detection unavailable; live video continues.'
                        if self.on_clear:
                            self.on_clear()
                        self.condition.notify_all()

    def _active(self):
        with self.condition:
            return self.clients > 0

    @staticmethod
    def _chunks(response):
        # A fixed-size requests read can hold the end of a JPEG until the NEXT
        # exposure fills its buffer on non-chunked camera servers. read1 returns
        # already-buffered bytes or makes one socket read, without filling amt.
        # Its larger ceiling also lets the parser discard complete older images
        # together when several frames have accumulated in the receive buffer.
        read1 = getattr(getattr(response, 'raw', None), 'read1', None)
        if callable(read1):
            while True:
                chunk = read1(64 * 1024, decode_content=True)
                if not chunk:
                    return
                yield chunk
        else:
            # Retain support for adapters/older urllib3 without read1.
            yield from response.iter_content(chunk_size=1024)

    def _run(self):
        try:
            while self._active():
                with self.condition:
                    generation = self.generation
                    url = self.url
                failure_code = 'transport_error'
                try:
                    with self.http.get(url, stream=True, timeout=(3, self.READ_TIMEOUT), allow_redirects=False) as response:
                        response.raise_for_status()
                        if 'multipart/x-mixed-replace' not in response.headers.get('Content-Type', '').lower():
                            failure_code = 'invalid_content_type'
                            raise ValueError('Expected MJPEG stream')
                        mime = Message()
                        mime['Content-Type'] = response.headers.get('Content-Type', '')
                        boundary = mime.get_param('boundary')
                        delimiter = None
                        if isinstance(boundary, str) and 0 < len(boundary) <= 128:
                            try:
                                delimiter = b'\r\n--' + boundary.encode('ascii')
                            except UnicodeError:
                                pass
                        with self.condition:
                            if generation != self.generation or not self.clients:
                                continue
                            self.response = response
                        buffer = b''
                        last_frame = time.monotonic()
                        for chunk in self._chunks(response):
                            with self.condition:
                                if not self.clients or generation != self.generation:
                                    break
                                self.received_bytes += len(chunk)
                                self.received_chunks += 1
                                self.last_byte_at = time.time()
                            buffer += chunk
                            if len(buffer) > 2 * 1024 * 1024:
                                failure_code = 'frame_too_large'
                                raise ValueError('Camera stream stalled or frame too large')
                            newest = None
                            while True:
                                start = buffer.find(b'\xff\xd8')
                                end = buffer.find(b'\xff\xd9', start + 2) if start >= 0 else -1
                                next_start = buffer.find(b'\xff\xd8', start + 2) if start >= 0 else -1
                                if (next_start >= 0 and (end < 0 or next_start < end) and delimiter and
                                        delimiter in buffer[start + 2:next_start]):
                                    # A new MIME part proves the previous JPEG
                                    # was truncated. Do not concatenate images.
                                    with self.condition:
                                        self.invalid_frames += 1
                                        self.last_invalid_frame_at = time.time()
                                    buffer = buffer[next_start:]
                                    continue
                                if end < 0:
                                    break
                                newest, buffer = buffer[start:end + 2], buffer[end + 2:]
                            if newest is not None:
                                with self.condition:
                                    self.received_frames += 1
                                    self.last_frame_bytes = len(newest)
                                self._queue_video(newest, generation)
                                last_frame = time.monotonic()
                            elif time.monotonic() - last_frame > 10:
                                # A late chunk can complete a recovered image.
                                # Parse it before treating an incomplete stream
                                # as stalled; pixel freshness stays independent.
                                failure_code = 'frame_stalled'
                                raise ValueError('Camera stream stalled or frame too large')
                        if self._active():
                            failure_code = 'stream_ended'
                            raise ValueError('Camera stream ended')
                except Exception as error:
                    with self.condition:
                        if generation == self.generation:
                            if self.clients:
                                self.source_errors += 1
                                self.last_source_error_at = time.time()
                                self.last_source_error_stage = 'upstream_transport'
                                self.last_source_error_code = ('timeout' if isinstance(error, (Timeout, ReadTimeoutError)) else
                                    'http_error' if isinstance(error, HTTPError) else
                                    'protocol_error' if isinstance(error, ProtocolError) else
                                    'connection_error' if isinstance(error, NewConnectionError) else
                                    'connection_error' if isinstance(error, ConnectionError) else failure_code)
                            self._clear_locked('Camera unavailable. Check Wi-Fi, power and stream address.')
                        if self.clients:
                            self.condition.wait(timeout=1)
                finally:
                    with self.condition:
                        self.response = None
        finally:
            with self.condition:
                self.thread = None
                if self.clients:
                    self.thread = threading.Thread(target=self._run, daemon=True)
                    self.thread.start()
                self.condition.notify_all()

    def frames(self):
        with self.condition:
            self._retain_locked()
        sequence = -1
        header = b'--frame\r\nContent-Type: image/jpeg\r\n\r\n'
        prefix = header
        try:
            while True:
                with self.condition:
                    ready = self.condition.wait_for(
                        lambda: (self.frame is not None and self.sequence != sequence) or self.error, timeout=8)
                    if not ready or self.error:
                        return
                    jpeg, sequence = self.frame, self.sequence
                # Chrome waits for the following part's complete headers before
                # painting this JPEG. Send those headers now, without waiting
                # for the next exposure. Its length is not known yet, so each
                # part uses the multipart boundary rather than Content-Length.
                yield prefix + jpeg + b'\r\n' + header
                prefix = b''
        finally:
            with self.condition:
                response = self._release_locked()
            self._close_response(response)
