// Controlled localhost check of production snapshot selection and canvas playback.
// A generated 15 FPS QVGA source keeps publishing while real Chrome takes an
// extra 120 ms to decode each image. No robot, credentials or app config is read.
const assert = require('node:assert/strict');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { chromium } = require('playwright');

const ROOT = path.resolve(__dirname, '..');
const DECODE_DELAY_MS = 120;
const PAINTS = 36;
const FIXTURE = String.raw`
import json, pathlib, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import cv2, numpy as np
from features.live_camera import LiveCamera

camera = LiveCamera('synthetic-direct-publisher', None, cv2, np)
# Direct publication deliberately replaces only ingestion. Snapshot leases,
# freshness/cursors and condition signalling use the production implementation.
camera.thread = threading.current_thread()
metrics = {'generated': 0, 'get_active': 0, 'get_max': 0, 'get_total': 0, 'deletes': 0}
metrics_lock = threading.Lock()
stopping = threading.Event()
player = pathlib.Path('static/js/live_camera_player.js').read_bytes()

def publish():
    deadline = time.monotonic()
    index = 0
    while not stopping.is_set():
        index += 1
        image = np.empty((240, 320, 3), dtype=np.uint8)
        image[:] = ((index * 17) % 190 + 30, 65, 145)
        cv2.putText(image, str(index), (25, 135), cv2.FONT_HERSHEY_SIMPLEX,
                    2, (245, 245, 245), 3, cv2.LINE_AA)
        ok, jpeg = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, 80])
        assert ok
        camera.publish(jpeg.tobytes(), received_at=time.time())
        with metrics_lock:
            metrics['generated'] = index
        deadline += 1 / 15
        stopping.wait(max(0, deadline - time.monotonic()))

class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    def log_message(self, *args):
        pass
    def send(self, code, body=b'', headers=None):
        self.send_response(code)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        for key, value in (headers or {}).items():
            self.send_header(key, str(value))
        self.end_headers()
        if body:
            self.wfile.write(body)
    def do_GET(self):
        if self.path == '/':
            self.send(200, b'<!doctype html><canvas id="feed"></canvas><script src="/player.js"></script>',
                      {'Content-Type': 'text/html'})
        elif self.path == '/player.js':
            self.send(200, player, {'Content-Type': 'text/javascript'})
        elif self.path == '/stats':
            with metrics_lock:
                result = dict(metrics)
            with camera.condition:
                result.update(clients=camera.clients, leases=len(camera.snapshot_clients),
                              sequence=camera.sequence)
            self.send(200, json.dumps(result).encode(), {'Content-Type': 'application/json'})
        elif self.path == '/api/camera-frame/main':
            with metrics_lock:
                metrics['get_active'] += 1
                metrics['get_total'] += 1
                metrics['get_max'] = max(metrics['get_max'], metrics['get_active'])
            try:
                result = camera.snapshot(('synthetic-viewer', self.headers['X-Camera-Viewer']),
                    int(self.headers.get('X-Camera-Sequence', -1)),
                    int(self.headers.get('X-Camera-Generation', -1)))
                if result['state'] == 'frame':
                    self.send(200, result['jpeg'], {'Content-Type': 'image/jpeg',
                        'X-Camera-Sequence': result['sequence'],
                        'X-Camera-Generation': result['generation'],
                        'X-Camera-Received-At': result['received_at'],
                        'X-Camera-Age-Ms': result['age_ms']})
                else:
                    self.send(204 if result['state'] == 'pending' else 503)
            finally:
                with metrics_lock:
                    metrics['get_active'] -= 1
        else:
            self.send(404)
    def do_DELETE(self):
        if self.path != '/api/camera-frame/main':
            self.send(404)
            return
        camera.close_snapshot(('synthetic-viewer', self.headers['X-Camera-Viewer']))
        with metrics_lock:
            metrics['deletes'] += 1
        self.send(204)

threading.Thread(target=publish, daemon=True).start()
server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
server.daemon_threads = True
print(json.dumps({'port': server.server_address[1]}), flush=True)
try:
    server.serve_forever()
finally:
    stopping.set()
    server.server_close()
`;

function startFixture() {
  const child = spawn(process.env.BIMBOT_TEST_PYTHON || 'python3', ['-u', '-c', FIXTURE], {
    cwd: ROOT, stdio: ['ignore', 'pipe', 'pipe'],
  });
  let output = '', errors = '';
  child.stderr.on('data', chunk => { errors += chunk; });
  const ready = new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('Synthetic server startup timed out')), 15000);
    child.once('error', error => { clearTimeout(timer); reject(error); });
    child.once('exit', code => {
      clearTimeout(timer);
      reject(new Error(`Synthetic server exited ${code}: ${errors}`));
    });
    child.stdout.on('data', chunk => {
      output += chunk;
      if (!output.includes('\n')) return;
      clearTimeout(timer);
      try { resolve(JSON.parse(output.split('\n')[0]).port); }
      catch (error) { reject(error); }
    });
  });
  return { child, ready };
}

async function stopFixture(child) {
  if (child.exitCode !== null || child.signalCode !== null) return;
  await new Promise(resolve => {
    const timer = setTimeout(() => child.kill('SIGKILL'), 2000);
    child.once('exit', () => { clearTimeout(timer); resolve(); });
    child.kill('SIGTERM');
  });
}

(async () => {
  const fixture = startFixture();
  let browser;
  try {
    const port = await fixture.ready;
    browser = await chromium.launch({
      headless: true,
      ...(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {}),
    });
    const page = await browser.newPage();
    const pageErrors = [];
    page.on('pageerror', error => pageErrors.push(error.message));
    await page.goto(`http://127.0.0.1:${port}`);
    const result = await page.evaluate(async ({ delay, count }) => {
      const canvas = document.getElementById('feed');
      const context = canvas.getContext('2d');
      const draw = context.drawImage.bind(context);
      const paints = [];
      let metadata, drawing, loads = 0, requests = 0, active = 0, maxActive = 0;
      const started = performance.now();
      let finish, fail;
      const completed = new Promise((resolve, reject) => { finish = resolve; fail = reject; });
      const timer = setTimeout(() => fail(new Error('Not enough current frames painted')), 12000);
      context.drawImage = (...args) => {
        draw(...args);
        active--;
        paints.push({ sequence: drawing.sequence,
          age_ms: Date.now() - drawing.received_at * 1000,
          elapsed_ms: performance.now() - started });
        if (paints.length === count) finish();
      };
      canvas.addEventListener('load', () => { loads++; });
      canvas.addEventListener('error', () => fail(new Error('Production player failed')));
      const player = new window.BIMLiveFramePlayer(canvas, {
        source: 'main',
        fetchImpl: async (url, options) => {
          if (options.method === 'DELETE') return fetch(url, options);
          requests++;
          active++;
          maxActive = Math.max(maxActive, active);
          try {
            const response = await fetch(url, options);
            if (response.status !== 200) active--;
            metadata = { sequence: Number(response.headers.get('X-Camera-Sequence')),
              received_at: Number(response.headers.get('X-Camera-Received-At')) };
            return response;
          } catch (error) { active--; throw error; }
        },
        decode: async blob => {
          const current = metadata;
          const bitmap = await createImageBitmap(blob);
          await new Promise(resolve => setTimeout(resolve, delay));
          drawing = current;
          return bitmap;
        },
      });
      try {
        player.start();
        await completed;
        // Draw instrumentation runs before the production player updates its
        // cursor. Yield so normal publication completes before stopping it.
        await new Promise(resolve => setTimeout(resolve, 0));
        const dimensions = [canvas.width, canvas.height];
        player.stop();
        let cleanup;
        for (let attempt = 0; attempt < 30; attempt++) {
          cleanup = await (await fetch('/stats')).json();
          if (!cleanup.leases && !cleanup.clients && cleanup.deletes) break;
          await new Promise(resolve => setTimeout(resolve, 20));
        }
        return { paints, loads, requests, maxActive, dimensions, cleanup,
          viewer_released: !canvas.dataset.viewer };
      } finally { clearTimeout(timer); player.stop(); }
    }, { delay: DECODE_DELAY_MS, count: PAINTS });

    assert.deepEqual(pageErrors, [], 'The real browser must not emit script errors');
    assert.deepEqual(result.dimensions, [320, 240], 'Real JPEG decoding must preserve QVGA dimensions');
    assert.equal(result.loads, 1, 'Only the first painted image signals connection');
    assert.equal(result.maxActive, 1, 'The browser must fetch only one frame at a time');
    assert.equal(result.cleanup.get_max, 1, 'The server must not receive overlapping frame requests');
    assert.equal(result.cleanup.clients, 0, 'Stopping playback must release its upstream client count');
    assert.equal(result.cleanup.leases, 0, 'Stopping playback must release its snapshot lease');
    assert.equal(result.cleanup.deletes, 1, 'The player must explicitly release its viewer once');
    assert.equal(result.viewer_released, true);
    const ages = result.paints.map(paint => paint.age_ms);
    assert(ages.every(age => age >= 0 && age < 500), 'A delayed decoder must keep painted source age below 500 ms');
    const mean = values => values.reduce((a, b) => a + b, 0) / values.length;
    const first = mean(ages.slice(0, 6)), last = mean(ages.slice(-6));
    assert(last < first + 150, 'Image age must stay bounded instead of growing with playback time');
    const skipped = result.paints.slice(1).reduce((total, paint, index) =>
      total + Math.max(0, paint.sequence - result.paints[index].sequence - 1), 0);
    assert(skipped >= 10, 'Slow playback must skip obsolete generated frames');
    const sorted = [...ages].sort((a, b) => a - b);
    const round = value => Math.round(value * 10) / 10;
    console.log(JSON.stringify({ synthetic_localhost: true, physical_robot_test: false,
      source_fps: 15, dimensions: result.dimensions, injected_decode_delay_ms: DECODE_DELAY_MS,
      painted_frames: result.paints.length, skipped_source_frames: skipped,
      max_painted_reception_age_ms: round(Math.max(...ages)),
      p95_painted_reception_age_ms: round(sorted[Math.ceil(sorted.length * .95) - 1]),
      first_six_mean_age_ms: round(first), last_six_mean_age_ms: round(last),
      duration_ms: round(result.paints.at(-1).elapsed_ms),
      maximum_concurrent_frame_requests: result.maxActive,
      remaining_viewer_leases: result.cleanup.leases,
      remaining_upstream_clients: result.cleanup.clients }, null, 2));
  } finally {
    try { await browser?.close(); }
    finally { await stopFixture(fixture.child); }
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
