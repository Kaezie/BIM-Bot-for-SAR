// Synthetic localhost test: measure when Chrome can paint a complete MJPEG
// frame while the sender holds the following frame. No robot or login needed.
const assert = require('node:assert/strict');
const http = require('node:http');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { chromium } = require('playwright');

const HOLD_MS = 900;
const results = [];
let jpegs, productionParts;
const server = http.createServer((request, response) => {
  const mode = new URL(request.url, 'http://localhost').searchParams.get('mode');
  if (!mode) {
    response.writeHead(200, { 'Content-Type': 'text/html' });
    response.end('<!doctype html><img id="feed"><canvas id="probe" width="1" height="1"></canvas>');
    return;
  }
  response.writeHead(200, {
    'Content-Type': 'multipart/x-mixed-replace; boundary=frame',
    'Cache-Control': 'no-store',
  });
  response.socket.setNoDelay(true);
  const writeFrame = index => {
    if (mode === 'production') return response.write(productionParts[index]);
    const length = mode === 'without-length' ? '' : `Content-Length: ${jpegs[index].length}\r\n`;
    const boundary = index && mode === 'next-boundary' ? '' : '--frame\r\n';
    response.write(Buffer.concat([
      Buffer.from(`${boundary}Content-Type: image/jpeg\r\n${length}\r\n`),
      jpegs[index],
      Buffer.from(mode === 'next-boundary' ? '\r\n--frame\r\n' : '\r\n'),
    ]));
  };
  writeFrame(0);
  const timers = [1, 2].map(index => setTimeout(() => writeFrame(index), HOLD_MS * index));
  response.on('close', () => timers.forEach(clearTimeout));
});

(async () => {
  const browser = await chromium.launch({
    headless: true,
    ...(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {}),
  });
  try {
    const page = await browser.newPage();
    jpegs = (await page.evaluate(() => [0, 1, 2].map(channel => {
      const canvas = document.createElement('canvas');
      canvas.width = 320; canvas.height = 240;
      const context = canvas.getContext('2d');
      // A realistic-size JPEG avoids Chrome's separate tiny-response buffering.
      for (let y = 0; y < canvas.height; y += 4) {
        for (let x = 0; x < canvas.width; x += 4) {
          const color = [20, (x * 5 + y * 17) % 60, 20];
          color[channel] = 220 + (x * 13 + y * 7) % 35;
          context.fillStyle = `rgb(${color.join(',')})`;
          context.fillRect(x, y, 4, 4);
        }
      }
      return canvas.toDataURL('image/jpeg', 0.8).split(',')[1];
    }))).map(data => Buffer.from(data, 'base64'));
    // Produce the optimized bytes through the real shared-camera generator.
    // Ingestion is supplied directly; OpenCV still validates the generated JPEGs.
    const fixture = spawnSync(process.env.BIMBOT_TEST_PYTHON || 'python3', ['-c', `
import base64, json, sys, threading
import cv2, numpy as np
from features.live_camera import LiveCamera
camera = LiveCamera('synthetic', None, cv2, np)
camera.thread = threading.current_thread()  # No hardware or upstream HTTP reader.
stream = camera.frames()
parts = []
for encoded in json.load(sys.stdin):
    camera.publish(base64.b64decode(encoded))
    parts.append(base64.b64encode(next(stream)).decode())
stream.close()
print(json.dumps(parts))
`], {
      cwd: path.resolve(__dirname, '..'),
      input: JSON.stringify(jpegs.map(jpeg => jpeg.toString('base64'))),
      encoding: 'utf8',
    });
    if (fixture.status !== 0) throw new Error(`Production framing fixture failed: ${fixture.stderr}`);
    productionParts = JSON.parse(fixture.stdout).map(part => Buffer.from(part, 'base64'));
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    const url = `http://127.0.0.1:${server.address().port}`;
    for (const mode of ['without-length', 'with-length', 'next-boundary', 'production']) {
      await page.goto(url);
      const paints = await page.evaluate(({ mode, hold }) => new Promise((resolve, reject) => {
        const image = document.getElementById('feed');
        const context = document.getElementById('probe').getContext('2d', { willReadFrequently: true });
        const started = performance.now();
        let redAt = null;
        image.src = `/?mode=${mode}`;
        const check = () => {
          if (image.naturalWidth) {
            context.drawImage(image, 0, 0, 1, 1);
            const [red, green, blue] = context.getImageData(0, 0, 1, 1).data;
            if (redAt === null && red > 200 && green < 80 && blue < 80) redAt = performance.now() - started;
            if (green > 200 && red < 80 && blue < 80) {
              image.removeAttribute('src');
              resolve({ redAt, greenAt: performance.now() - started });
              return;
            }
          }
          if (performance.now() - started > 2 * hold + 2000) {
            reject(new Error(`Chrome never painted the ${mode} frame`));
            return;
          }
          setTimeout(check, 10);
        };
        check();
      }), { mode, hold: HOLD_MS });
      assert(paints.redAt !== null, `Chrome must show the first ${mode} frame`);
      results.push({ mode, first_frame_paint_ms: Math.round(paints.redAt),
        second_frame_paint_ms: Math.round(paints.greenAt),
        second_frame_after_send_ms: Math.round(paints.greenAt - HOLD_MS) });
    }
    console.log(JSON.stringify({ synthetic: true, jpeg_bytes: jpegs.map(jpeg => jpeg.length), next_frame_held_ms: HOLD_MS, results }, null, 2));
    const production = results.find(result => result.mode === 'production');
    assert(production.first_frame_paint_ms < HOLD_MS / 2,
      'The production generator must let Chrome paint the first image before another frame arrives');
    assert(production.second_frame_after_send_ms < HOLD_MS / 2,
      'The production generator must also paint later images without waiting for the following frame');
  } finally {
    await browser.close();
    server.closeAllConnections();
    await new Promise(resolve => server.close(resolve));
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
