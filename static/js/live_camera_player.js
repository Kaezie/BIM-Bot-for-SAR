'use strict';
// One requested image at a time: a slow display skips to the current frame
// instead of accumulating a continuous MJPEG response in the browser.
(() => {
  class LiveCameraPlayer {
    constructor(canvas, options) {
      this.canvas = canvas;
      this.source = options.source;
      this.getHeaders = options.getHeaders || (() => ({}));
      this.onUnauthorized = options.onUnauthorized || (() => {});
      this.fetchImpl = options.fetchImpl || window.fetch.bind(window);
      this.decode = options.decode || decodeImage;
      this.minIntervalMs = options.minIntervalMs ?? 33;
      this.shouldRender = options.shouldRender || (() => true);
      this.backgroundIntervalMs = options.backgroundIntervalMs ?? 500;
      this.retryIntervalMs = options.retryIntervalMs ?? 250;
      this.startupGraceMs = options.startupGraceMs ?? 12000;
      this.epoch = 0;
      this.viewer = null;
    }

    start() {
      this.stop();
      const epoch = ++this.epoch;
      const viewer = crypto.randomUUID();
      this.viewer = viewer;
      this.canvas.dataset.viewer = viewer;
      this.controller = new AbortController();
      this.sequence = -1;
      this.generation = -1;
      this.presented = false;
      this.waiting = false;
      this.startupDeadline = performance.now() + this.startupGraceMs;
      this.run(epoch, viewer, this.controller.signal).catch(() => this.fail(epoch));
      return this;
    }

    stop() {
      ++this.epoch;
      const viewer = this.viewer;
      this.viewer = null;
      this.controller?.abort();
      this.wake();
      clearTimeout(this.freshnessTimer);
      this.waiting = false;
      delete this.canvas.dataset.viewer;
      delete this.canvas.dataset.frameSequence;
      delete this.canvas.dataset.frameGeneration;
      this.canvas.getContext('2d')?.clearRect(0, 0, this.canvas.width, this.canvas.height);
      if (viewer) {
        try {
          Promise.resolve(this.fetchImpl(`/api/camera-frame/${this.source}`, {
            method: 'DELETE', credentials: 'same-origin', cache: 'no-store', keepalive: true,
            headers: {...this.getHeaders(), 'X-Camera-Viewer': viewer}
          })).catch(() => {});
        } catch { /* The short server lease also releases abandoned viewers. */ }
      }
    }

    active(epoch, viewer) { return epoch === this.epoch && viewer === this.viewer; }

    wake() { this.releaseDelay?.(); }

    async wait(ms) {
      await new Promise(resolve => {
        const timer=setTimeout(()=>{this.releaseDelay=null;resolve();},ms);
        this.releaseDelay=()=>{clearTimeout(timer);this.releaseDelay=null;resolve();};
      });
    }

    fail(epoch) {
      if (epoch !== this.epoch || !this.viewer) return;
      this.stop();
      this.canvas.dispatchEvent(new Event('error'));
    }

    waitForFrame(epoch) {
      if (epoch !== this.epoch || !this.viewer || this.waiting) return;
      this.waiting = true;
      clearTimeout(this.freshnessTimer);
      this.canvas.getContext('2d')?.clearRect(0, 0, this.canvas.width, this.canvas.height);
      delete this.canvas.dataset.frameSequence;
      delete this.canvas.dataset.frameGeneration;
      // Expire the image, not the operator's subscription. A still-reading
      // upstream can then complete its next JPEG without another handshake.
      this.canvas.dispatchEvent(new Event('waiting'));
    }

    async run(epoch, viewer, signal) {
      while (this.active(epoch, viewer)) {
        if (!this.presented && performance.now() >= this.startupDeadline) this.waitForFrame(epoch);
        const began = performance.now();
        const request = new AbortController();
        const abort = () => request.abort();
        signal.addEventListener('abort', abort, {once: true});
        const timeout = setTimeout(abort, 2500);
        let response, blob;
        try {
          response = await this.fetchImpl(`/api/camera-frame/${this.source}`, {
            credentials: 'same-origin', cache: 'no-store', signal: request.signal,
            headers: {...this.getHeaders(), 'X-Camera-Viewer': viewer,
              'X-Camera-Sequence': String(this.sequence), 'X-Camera-Generation': String(this.generation)}
          });
          if (!this.active(epoch, viewer)) return;
          if (response.status === 401) {
            this.stop();
            this.onUnauthorized();
            return;
          }
          if (response.status !== 204) {
            if (!response.ok) {
              const error = new Error('Camera unavailable');
              error.retryable = response.status >= 500 || response.status === 429;
              throw error;
            }
            const type = response.headers.get('Content-Type')?.split(';')[0].trim();
            if (!['image/jpeg', 'image/png'].includes(type)) throw new Error('Invalid camera image');
            blob = await response.blob();
            if (!blob.size || blob.size > 2 * 1024 * 1024) throw new Error('Invalid camera image size');
          }
        } catch (error) {
          if (!this.active(epoch, viewer) || signal.aborted) return;
          const retryable = error.retryable || error.name === 'AbortError' || error.name === 'TypeError';
          if (!retryable) throw error;
          if (!this.presented && performance.now() >= this.startupDeadline) this.waitForFrame(epoch);
          // The existing frame deadline still clears stale video. A transient
          // HTTP failure must not DELETE/recreate the upstream subscription.
          this.canvas.dispatchEvent(new Event('recovering'));
          await this.wait(this.retryIntervalMs);
          continue;
        } finally {
          clearTimeout(timeout);
          signal.removeEventListener('abort', abort);
        }
        if (!this.active(epoch, viewer)) return;
        if (blob) {
          const sequence = integerHeader(response, 'X-Camera-Sequence');
          const generation = integerHeader(response, 'X-Camera-Generation');
          const rawAge = response.headers.get('X-Camera-Age-Ms');
          const age = rawAge === null || rawAge.trim() === '' ? NaN : Number(rawAge);
          if (!Number.isFinite(age) || age < 0 || age >= 5000) throw new Error('Stale camera image');
          if (generation > this.generation || (generation === this.generation && sequence > this.sequence)) {
            const render = !this.presented || this.waiting || this.shouldRender();
            if (!render) {
              const effectiveAge = age + performance.now() - began;
              if (effectiveAge >= 5000) {this.waitForFrame(epoch);await this.wait(this.retryIntervalMs);continue;}
              this.sequence = sequence; this.generation = generation;
              clearTimeout(this.freshnessTimer);
              this.freshnessTimer = setTimeout(() => this.waitForFrame(epoch), 5000-effectiveAge);
              this.canvas.dispatchEvent(new Event('fresh'));
            } else {
            let decoded;
            try {
              decoded = await this.decode(blob);
              if (!this.active(epoch, viewer)) return;
              const image = decoded.image || decoded;
              const width = decoded.width || image.naturalWidth || image.width;
              const height = decoded.height || image.naturalHeight || image.height;
              if (!(width > 0 && height > 0)) throw new Error('Empty camera image');
              // Include time spent transferring/decoding this response. A slow
              // decoder cannot renew an image beyond its reception deadline.
              const effectiveAge = age + performance.now() - began;
              if (effectiveAge >= 5000) {decoded?.close?.();decoded=null;this.waitForFrame(epoch);await this.wait(this.retryIntervalMs);continue;}
              if (this.canvas.width !== width) this.canvas.width = width;
              if (this.canvas.height !== height) this.canvas.height = height;
              this.canvas.getContext('2d', {alpha: false}).drawImage(image, 0, 0);
              this.sequence = sequence;
              this.generation = generation;
              this.canvas.dataset.frameSequence = String(sequence);
              this.canvas.dataset.frameGeneration = String(generation);
              clearTimeout(this.freshnessTimer);
              this.freshnessTimer = setTimeout(() => this.waitForFrame(epoch), 5000 - effectiveAge);
              if (!this.presented || this.waiting) {
                this.presented = true;
                this.waiting = false;
                this.canvas.dispatchEvent(new Event('load'));
              }
              this.canvas.dispatchEvent(new Event('fresh'));
            } finally { decoded?.close?.(); }
            }
          }
        }
        const interval = this.shouldRender() ? this.minIntervalMs : this.backgroundIntervalMs;
        const delay = Math.max(0, interval - (performance.now() - began));
        if (delay) await this.wait(delay);
      }
    }
  }

  function integerHeader(response, name) {
    const raw = response.headers.get(name);
    const value = raw !== null && /^\d+$/.test(raw) ? Number(raw) : NaN;
    if (!Number.isSafeInteger(value)) throw new Error('Invalid camera cursor');
    return value;
  }

  async function decodeImage(blob) {
    if (typeof createImageBitmap === 'function') return createImageBitmap(blob);
    const url = URL.createObjectURL(blob);
    const image = new Image();
    try {
      await new Promise((resolve, reject) => {
        image.onload = resolve;
        image.onerror = () => reject(new Error('Camera image could not be decoded'));
        image.src = url;
      });
      return {image, width: image.naturalWidth, height: image.naturalHeight,
        close: () => URL.revokeObjectURL(url)};
    } catch (error) { URL.revokeObjectURL(url); throw error; }
  }
  window.BIMLiveFramePlayer = LiveCameraPlayer;
})();
