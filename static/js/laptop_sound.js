'use strict';

// Local, operator-started analysis only. No recording, network or storage path.
window.BIMLaptopSound = class {
  constructor({canStart, onState = () => {}, onBeforeStart = () => {}}) {
    this.canStart = canStart;
    this.onState = onState;
    this.onBeforeStart = onBeforeStart;
    this.state = 'idle';
    this.revision = 0;
    this.pendingPermission = false;
    this.context = null;
    this.stream = null;
    this.source = null;
    this.analyser = null;
    this.frame = null;
    this.inputId = null;
    this.devices = [];
    this.$ = id => document.getElementById(id);
    this.canvas = this.$('laptopSoundWave');
    this.paint = this.canvas.getContext('2d');
    this.$('laptopSoundStart').addEventListener('click', () => this.start());
    this.$('laptopSoundStop').addEventListener('click', () => this.stop('Stopped. Press Start to listen again.'));
    this.$('soundListInputs').addEventListener('click', () => this.findInputs());
    for (const id of ['soundSourceMode', 'soundInputDevice']) this.$(id).addEventListener('change', () => {
      this.stop('Input changed. Select and confirm the source, then press Start.');
      this.$('soundMountConfirmed').checked = false;
      this.controls();
    });
    this.$('soundMountConfirmed').addEventListener('change', () => {
      if (this.active) this.stop('Mount confirmation changed. Press Start to listen again.');
      this.controls();
    });
    navigator.mediaDevices?.addEventListener('devicechange', () => this.refreshInputs());
    this.$('laptopSoundThreshold').addEventListener('input', () => {
      this.$('laptopSoundThresholdValue').textContent = `${this.$('laptopSoundThreshold').value}%`;
    });
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'hidden' && this.active) this.stop('Stopped while this page is hidden.');
    });
    window.addEventListener('pagehide', () => this.stop('Stopped when this page closed.'));
    this.resetReadings();
    this.controls();
  }

  get active() { return this.state === 'requesting' || this.state === 'listening'; }
  get robotInput() { return this.$('soundSourceMode').value === 'robot_headset'; }

  controls() {
    this.$('laptopSoundStart').disabled = this.active || this.pendingPermission ||
      (this.robotInput && (!this.$('soundInputDevice').value || !this.$('soundMountConfirmed').checked));
    this.$('laptopSoundStop').disabled = !this.active;
    this.$('soundListInputs').disabled = this.active || this.pendingPermission;
    this.$('soundMountLabel').hidden = !this.robotInput;
    this.$('soundInputLocation').textContent = this.robotInput ? 'Robot headset · operator-confirmed placement' : 'Laptop demonstration';
    this.$('laptopSoundState').dataset.state = this.state;
  }

  status(message) {
    this.$('laptopSoundState').textContent = message;
    this.controls();
    this.onState();
  }

  resetReadings() {
    this.$('laptopSoundLevel').textContent = '—';
    this.$('laptopSoundPeak').textContent = '—';
    this.$('laptopSoundMeter').value = 0;
    this.$('laptopSoundActivity').textContent = 'No active input';
    this.$('laptopSoundActivity').dataset.active = 'false';
    this.canvas.dataset.live = 'false';
    this.paint.clearRect(0, 0, this.canvas.width, this.canvas.height);
  }

  stop(message) {
    this.revision++;
    this.state = 'idle';
    cancelAnimationFrame(this.frame);
    this.frame = null;
    if (this.stream) {
      for (const track of this.stream.getTracks()) {
        track.onended = null;
        track.stop();
      }
    }
    this.stream = null;
    this.inputId = null;
    this.$('soundActualDevice').textContent = 'No active microphone.';
    this.source?.disconnect();
    this.source = null;
    this.analyser = null;
    const context = this.context;
    this.context = null;
    if (context) {
      context.onstatechange = null;
      if (context.state !== 'closed') context.close().catch(() => {});
    }
    this.resetReadings();
    this.status(message || 'Stopped.');
  }

  async refreshInputs() {
    if (!navigator.mediaDevices?.enumerateDevices) return;
    try {
      const devices = (await navigator.mediaDevices.enumerateDevices()).filter(device => device.kind === 'audioinput' && device.deviceId && !['default','communications'].includes(device.deviceId));
      this.devices = devices;
      const select = this.$('soundInputDevice'), selected = select.value;
      select.replaceChildren(new Option('Default input (laptop demonstration only)', ''));
      devices.forEach((device, index) => select.add(new Option(device.label || `Microphone ${index + 1}`, device.deviceId)));
      select.value = devices.some(device => device.deviceId === selected) ? selected : '';
      if (this.inputId && !devices.some(device => device.deviceId === this.inputId)) {
        this.$('soundMountConfirmed').checked = false;
        this.stop('Selected microphone disconnected. No replacement input was started.');
      }
      this.$('soundDeviceStatus').textContent = devices.length ? `${devices.length} microphone input(s) available. Select the actual headset for robot mode.` : 'No named inputs available. Use Find microphones to grant permission.';
      this.controls();
    } catch {
      if (this.active && this.robotInput) this.stop('Cannot verify the selected headset. Press Find microphones to retry.');
      this.$('soundDeviceStatus').textContent = 'Could not list microphones. Check browser permissions.';
    }
  }

  async findInputs() {
    if (this.active || this.pendingPermission || !this.canStart()) return;
    this.onBeforeStart();
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
      this.status('Microphone access needs localhost or HTTPS in a supported browser.'); return;
    }
    const revision = ++this.revision;
    this.pendingPermission = true; this.state = 'requesting';
    this.status('Waiting for permission to list microphone inputs.');
    let probe;
    try {
      probe = await navigator.mediaDevices.getUserMedia({audio:true, video:false});
      if (revision !== this.revision || !this.canStart()) return;
      this.stream = probe;
      await this.refreshInputs();
      if (revision === this.revision) this.stop('Inputs listed. Select your source, then press Start microphone.');
    } catch {
      if (revision === this.revision) this.stop('Could not list microphones. Check permission and connection.');
    } finally {
      probe?.getTracks().forEach(track => track.stop());
      this.pendingPermission = false; this.controls();
    }
  }

  async start() {
    this.onBeforeStart();
    if (this.active || this.pendingPermission || !this.canStart()) return;
    const selected = this.$('soundInputDevice').value;
    if (this.robotInput && (!selected || !this.$('soundMountConfirmed').checked)) {
      this.status('Select a specific headset and confirm it is mounted on the robot.'); return;
    }
    const AudioContext = window.AudioContext || window.webkitAudioContext;
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia || !AudioContext) {
      this.status('Microphone access needs localhost or HTTPS in a supported browser.');
      return;
    }
    const revision = ++this.revision;
    this.state = 'requesting';
    this.pendingPermission = true;
    this.status('Waiting for microphone permission. Stop cancels listening.');
    let incoming;
    try {
      // Create/resume during the click for browsers that require user activation.
      const context = this.context = new AudioContext();
      const resumed = context.resume();
      resumed.catch(() => {});
      incoming = await navigator.mediaDevices.getUserMedia({
        audio: {echoCancellation: false, noiseSuppression: false, autoGainControl: false,
          ...(selected ? {deviceId:{exact:selected}} : {})},
        video: false
      });
      if (revision !== this.revision || !this.canStart()) {
        incoming.getTracks().forEach(track => track.stop());
        if (revision === this.revision) this.stop('Stopped before listening started.');
        return;
      }
      this.stream = incoming;
      const tracks = incoming.getAudioTracks();
      if (!tracks.length || tracks.some(track => track.readyState !== 'live')) throw new Error('NoAudioTrack');
      if (selected && tracks.some(track => track.getSettings().deviceId !== selected)) throw new Error('WrongInput');
      this.inputId = selected || null;
      tracks.forEach(track => { track.onended = () => this.stop('Microphone disconnected. Press Start to retry.'); });
      await resumed;
      if (revision !== this.revision || !this.canStart()) {
        if (revision === this.revision) this.stop('Stopped before listening started.');
        return;
      }
      if (context.state !== 'running') throw new Error('AudioSuspended');
      if (tracks.some(track => track.readyState !== 'live')) throw new Error('NoAudioTrack');
      this.source = context.createMediaStreamSource(incoming);
      this.analyser = context.createAnalyser();
      this.analyser.fftSize = 2048;
      this.source.connect(this.analyser);
      // Deliberately leave the analyser output unconnected: no speaker playback.
      context.onstatechange = () => {
        if (this.state === 'listening' && context.state !== 'running') this.stop('Audio paused. Press Start to resume.');
      };
      this.state = 'listening';
      this.$('soundActualDevice').textContent = `Active input: ${tracks[0].label || 'Browser default microphone'}${this.robotInput ? ' · Robot placement confirmed by operator' : ' · Laptop demonstration'}`;
      this.status(this.robotInput ? 'Listening · selected robot headset · placement confirmed by operator' : 'Listening · laptop audio input only');
      const samples = new Float32Array(this.analyser.fftSize);
      let lastPaint = 0;
      const update = now => {
        if (revision !== this.revision || this.state !== 'listening') return;
        if (now - lastPaint >= 50) {
          lastPaint = now;
          if (selected && tracks.some(track => track.getSettings().deviceId !== selected)) {
            this.stop('Microphone source changed. No replacement input was started.'); return;
          }
          if (tracks.some(track => track.muted || !track.enabled)) {
            this.resetReadings();
            this.$('laptopSoundActivity').textContent = 'Input muted';
          } else {
            this.analyser.getFloatTimeDomainData(samples);
            this.renderSamples(samples);
          }
        }
        this.frame = requestAnimationFrame(update);
      };
      this.frame = requestAnimationFrame(update);
    } catch (error) {
      incoming?.getTracks().forEach(track => track.stop());
      if (revision !== this.revision) return;
      const messages = {
        NotAllowedError: 'Microphone permission was not granted. You can retry with Start.',
        NotFoundError: 'No microphone input was found on this laptop.',
        NotReadableError: 'Microphone is unavailable or in use by another application.',
        OverconstrainedError: 'Selected microphone is unavailable. No replacement input was started.',
        WrongInput: 'Browser did not provide the selected microphone. No replacement input was started.',
        NoAudioTrack: 'No live microphone input was returned.',
        AudioSuspended: 'Audio could not start. Press Start to retry.'
      };
      this.stop(messages[error.name] || messages[error.message] || 'Could not start this audio input. Press Start to retry.');
    } finally {
      this.pendingPermission = false;
      this.controls();
    }
  }

  renderSamples(samples) {
    let total = 0, square = 0, peak = 0;
    for (const value of samples) total += value;
    const mean = total / samples.length;
    for (const value of samples) {
      const centered = value - mean;
      square += centered * centered;
      peak = Math.max(peak, Math.abs(centered));
    }
    const level = Math.min(100, Math.sqrt(square / samples.length) * 100);
    const active = level >= Number(this.$('laptopSoundThreshold').value);
    this.$('laptopSoundLevel').textContent = `${level.toFixed(1)}%`;
    this.$('laptopSoundPeak').textContent = `${Math.min(100, peak * 100).toFixed(1)}% peak`;
    this.$('laptopSoundMeter').value = level;
    this.$('laptopSoundActivity').textContent = active ? 'Sound activity' : 'Below activity threshold';
    this.$('laptopSoundActivity').dataset.active = String(active);
    this.canvas.dataset.live = 'true';
    const ctx = this.paint, width = this.canvas.width, height = this.canvas.height;
    ctx.clearRect(0, 0, width, height);
    ctx.strokeStyle = '#1b4d40';
    ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(0, height / 2); ctx.lineTo(width, height / 2); ctx.stroke();
    ctx.strokeStyle = '#44e6ae';
    ctx.lineWidth = 2;
    ctx.beginPath();
    for (let x = 0; x < width; x++) {
      const value = samples[Math.floor(x * samples.length / width)] - mean;
      const y = height / 2 - Math.max(-1, Math.min(1, value)) * height * .46;
      if (x === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.stroke();
  }
};
