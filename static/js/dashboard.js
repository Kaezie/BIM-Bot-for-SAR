'use strict';
const $ = id => document.getElementById(id);
const client = window.BIM_AUTH;
const monitoringProfile = JSON.parse(document.getElementById('bim-monitoring-profile')?.textContent || '{}');
// A cached older template can coexist with current scripts during a reload.
if($('thermalGrid')?.tagName!=='CANVAS'){
  const old=$('thermalGrid');
  if(old){const canvas=document.createElement('canvas');for(const attr of old.attributes)canvas.setAttribute(attr.name,attr.value);canvas.width=32;canvas.height=24;old.replaceWith(canvas);}
}

let session, selectedFeed = 'main', cameraConnected = false, connecting = false;
let mainRequested = false, mainRetryTimeout;
let mainWaiting = false, nightWaiting = false;
let nvRequested = false, nvManual = false;
let nvConfigured = false, nvConnected = false, nvConnecting = false, nvRetryAt = 0, nvTimeout, nvFailureMessage = '', recordingSource = null;
let lastThermalAt = null;
let lastThermalSequence = null;
let thermalFlight = null, thermalExpiry, sensorFlight, deviceFlight, refreshFlight, detectionFlight;
let thermalPixels, latestThermalFrame;
let lastSoundAt = null;
let nightDetectionExpiry;
let positionFlight, positionExpiry;
function positionUnavailable(state, message) {
  clearTimeout(positionExpiry);
  if (!$('positionState')) return;
  text('positionState', state); text('positionMessage', message);
  for (const id of ['positionFrame','positionSource','positionFirst','positionSecond','positionQuality','positionTime']) text(id, '—');
  text('positionFirstLabel', 'Latitude / local X'); text('positionSecondLabel', 'Longitude / local Y');
  $('positionMap').removeAttribute('href'); show('positionMap', false);
}
let laptopSound, movementPanel, duplexAudio, soundRecognition, remoteSoundAvailability = 'Checking';
function updateSoundAvailability() {
  text('availability-sound', laptopSound?.active ? (laptopSound.robotInput ? 'Robot headset' : 'Laptop only') : remoteSoundAvailability);
  if (selectedFeed === 'sound') text('cameraStatus', $('availability-sound').textContent);
}
function thermalUnavailable(message) {
  clearTimeout(thermalExpiry);
  lastThermalAt = null; latestThermalFrame = null; text('mainThermalRange', '—'); text('mainThermalState', message);
  show('thermalGrid', false);
}
function soundUnavailable(message) {
  lastSoundAt = null; text('soundSummaryLevel', '—'); text('soundSummaryState', message);
  show('soundMeter', false); show('soundClass', false); $('soundMeter').value = 0;
}
const recordable = () => selectedFeed === 'main' ? cameraConnected : selectedFeed === 'nightvision' && nvConnected;
let recorder, recordingStream, drawTimer, clockTimer, recordingStarted, pendingClip, savedClip, uploading = false;
let libraryLoading = false, syncRequested = false, endingSession = false;
let nvLightPreference = false, nvLightDesired = false, nvLightConfirmed = null, nvLightState = 'idle';
let nvLightPending = false, nvLightQueued = false, nvLightRevision = 0, nvLightUsed = false, nvLightPaused = false;
let nvLightFlight;
let nvLightMessage = 'White light is not requested. Select On when needed.';
let samples = [], recordingOffset = 0, historySignature = '', lastSensorAt = null, lastDetectionAt = null;
const text = (id, value) => { if ($(id).textContent !== String(value)) $(id).textContent = value; };
const show = (id, visible) => { $(id).toggleAttribute('hidden', !visible); };
laptopSound = window.BIMLaptopSound && $('laptopSoundStart') ? new window.BIMLaptopSound({
  canStart: () => !!session && !endingSession && selectedFeed === 'sound' && document.visibilityState !== 'hidden',
  onState: () => {updateSoundAvailability();if(laptopSound?.state!=='listening')soundRecognition?.stop();soundRecognition?.controls();},
  onBeforeStart: () => duplexAudio?.stop('Stopped before starting sound analysis.')
}) : null;
soundRecognition=window.BIMSoundRecognition&&$('soundRecognitionEnabled')?new window.BIMSoundRecognition({api,getInput:()=>laptopSound,canStart:()=>!!session&&!endingSession&&selectedFeed==='sound'&&document.visibilityState!=='hidden'}):null;
duplexAudio=window.BIMDuplexAudio&&$('duplexFind')?new window.BIMDuplexAudio({canStart:()=>!!session&&!endingSession&&document.visibilityState!=='hidden',onBeforeStart:()=>laptopSound?.stop('Stopped before starting two-way audio.')}):null;
const number = value => typeof value === 'number' && Number.isFinite(value) ? value.toFixed(1) : '—';
const percent = value => typeof value === 'number' && Number.isFinite(value) ? `${(value * 100).toFixed(1)}%` : '—';
const dateTime = value => new Date(typeof value === 'number' ? value * 1000 : value).toLocaleString();
const cameraHeaders = () => session?.access_token ? {Authorization: `Bearer ${session.access_token}`} : {};
const cameraPacing = {minIntervalMs:monitoringProfile.video_interval_ms ?? 167,
  backgroundIntervalMs:monitoringProfile.background_video_interval_ms ?? 1000,
  retryIntervalMs:monitoringProfile.retry_interval_ms ?? 500};
const mainPlayer = new window.BIMLiveFramePlayer($('camStream'), {
  ...cameraPacing,
  source: 'main', getHeaders: cameraHeaders, onUnauthorized: () => sessionEnded(),
  shouldRender: () => selectedFeed === 'main' || recordingSource === 'main'
});
const nightPlayer = new window.BIMLiveFramePlayer($('nvStream'), {
  ...cameraPacing,
  source: 'nightvision', getHeaders: cameraHeaders, onUnauthorized: () => sessionEnded(),
  shouldRender: () => selectedFeed === 'nightvision' || recordingSource === 'nightvision'
});
for(const [id,source] of [['camStream','main'],['nvStream','nightvision']]){
  $(id).addEventListener('waiting',()=>{
    if(source==='main'){
      clearTimeout(connectTimeout);connecting=false;cameraConnected=false;mainWaiting=true;
      show('camStream',false);show('camOffline',true);
      text('cameraHint','Waiting for a fresh camera frame. Retrying automatically.');
    }else{
      clearTimeout(nvTimeout);nvConnecting=false;nvConnected=false;nightWaiting=true;
      show('nvStream',false);show('nvEmpty',true);
      nvFailureMessage='';text('nvStatus','Waiting for a fresh night-camera frame. Retrying automatically.');
      clearNightDetections('Waiting for fresh night-camera detections.');
    }
    text(`availability-${source}`,'Waiting');
    if(recordingSource===source&&recorder?.state==='recording')stopRecording();
    selectFeed(selectedFeed);
  });
  $(id).addEventListener('recovering',()=>{
    if(source==='main'?cameraConnected:nvConnected){
      text(`availability-${source}`,'Updating');
      if(selectedFeed===source)text('cameraStatus','Updating');
    }
  });
  $(id).addEventListener('fresh',()=>{
    if(source==='main'?cameraConnected:nvConnected){
      text(`availability-${source}`,'Live');
      if(selectedFeed===source)text('cameraStatus','Live');
    }
  });
}
function notify(message) { text('notice', message); show('notice', !!message); }
async function api(path, options = {}) {
  const headers = {...options.headers};
  if (session?.access_token) headers.Authorization = `Bearer ${session.access_token}`;
  const response = await fetch(path, {cache:'no-store', ...options, credentials: 'same-origin', headers, signal: options.signal || AbortSignal.timeout(options.method && options.method !== 'GET' ? 15000 : 4000)});
  if (response.status === 401) { sessionEnded(); throw new Error('Your local session ended. Download any unsaved clip, then sign in with Google while online.'); }
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Could not reach the server. Please retry.');
  return data;
}
function sessionEnded(reason = 'expired') {
  if (endingSession) return;
  endingSession = true;
  if (laptopSound?.active) laptopSound.stop('Stopped because your session ended.');
  soundRecognition?.stop('Stopped because your session ended.');
  duplexAudio?.stop('Stopped because your session ended.');
  updateNightLight();
  const active = recorder?.state === 'recording'; session = null;
  thermalUnavailable('Sign in to view thermal readings');
  positionUnavailable('Sign in', 'Sign in to view robot position.');
  movementPanel?.invalidate('Sign in to view movement history.');
  if (active) stopRecording();
  clearTimeout(connectTimeout); clearTimeout(mainRetryTimeout); clearTimeout(nvTimeout);
  mainRequested = false; nvRequested = false; nvManual = false;mainWaiting=false;nightWaiting=false;
  connecting=false;cameraConnected=false;nvConnecting=false;nvConnected=false;
  mainPlayer.stop(); nightPlayer.stop();
  clearNightDetections('Sign in to view night-camera detections.');
  ['camStream','nvStream'].forEach(id=>show(id,false));
  show('camOffline',true);show('nvEmpty',true);text('availability-main','Disconnected');text('availability-nightvision','Disconnected');
  if (active || pendingClip || uploading) notify('Your local session ended. Download your unsaved MP4 backup before signing in again while online.');
  else window.location.assign(`/login${reason === 'expired' ? '?reason=expired' : ''}`);
}
function element(tag, content, className) { const el = document.createElement(tag); if (content !== undefined) el.textContent = content; if (className) el.className = className; return el; }
function survivorDetails(detection, index) {
  const row = element('li', undefined, 'survivor-event');
  const tracked = Number.isInteger(detection.track_number) && detection.track_number > 0;
  const heading = element('h3', `${tracked ? `Track ${detection.track_number}` : `Detection ${index + 1}`} · ${percent(detection.confidence)}`);
  if (tracked) heading.title = 'Temporary camera track; identity can change after overlap, loss or reconnection.';
  row.append(heading);
  if (tracked) row.append(element('p', `Image motion: ${detection.motion_observed === true ? 'Region changed' : detection.motion_observed === false ? 'No region change observed' : 'Unknown'}`));
  if (typeof detection.gesture === 'string') row.append(element('p', `Help gesture: ${detection.gesture} · operator verification required`));
  if ('immobility_seconds' in detection) row.append(element('p', `Image inactivity: ${Number.isFinite(detection.immobility_seconds) ? detection.immobility_seconds.toFixed(1) + ' s' : 'Unknown'}`));
  for (const [key, label] of [['age','Age'], ['consciousness','Consciousness'], ['injury','Injury'], ['trapped','Entrapment'], ['pose','Pose'], ['thermal_alive','Thermal signal'], ['thermal_injury','Thermal pattern']]) {
    row.append(element('p', `${label}: ${typeof detection[key] === 'string' ? detection[key] : 'Unknown'}`));
  }
  return row;
}
function renderSurvivors(detections, fresh) {
  text('survivorDetailsState', fresh ? 'Live' : 'Unavailable');
  $('survivorDetailList').replaceChildren();
  if (!fresh || !detections.length) {
    $('survivorDetailList').append(element('li', fresh ? 'No survivors detected in the current frame.' : 'Waiting for fresh camera detections.', 'empty-row'));
    return;
  }
  detections.forEach((detection, index) => $('survivorDetailList').append(survivorDetails(detection, index)));
}
function clearNightDetections(message = 'Waiting for fresh night-camera analysis.') {
  clearTimeout(nightDetectionExpiry);
  text('nightSurvivorDetailsState', 'Unavailable');
  $('nightSurvivorDetailList').replaceChildren(element('li', message, 'empty-row'));
}
function renderNightDetections(nv, sameViewer) {
  clearTimeout(nightDetectionExpiry);
  show('nightSurvivorDetails', nvConfigured);
  const age = Date.now()/1000 - nv?.detected_at;
  const fresh = sameViewer && nvConnected && nv?.connected && nv?.person_analysis_enabled &&
    nv?.detections_available && Number.isFinite(nv.detected_at) && age >= 0 && age < 2;
  if (!fresh) {
    clearNightDetections(nv?.detection_enabled === false ? 'Night-camera detection is disabled.' : 'Waiting for fresh night-camera analysis.');
    return;
  }
  const detections = Array.isArray(nv.detections) ? nv.detections.filter(item => item.source === 'nightvision') : [];
  text('nightSurvivorDetailsState', 'Live · Night camera');
  $('nightSurvivorDetailList').replaceChildren();
  if (!detections.length) $('nightSurvivorDetailList').append(element('li', 'No people detected in the current night-camera frame.', 'empty-row'));
  detections.forEach((detection, index) => $('nightSurvivorDetailList').append(survivorDetails(detection, index)));
  nightDetectionExpiry = setTimeout(() => {
    clearNightDetections('Night-camera analysis is stale. Waiting for fresh detections.');
    text('nvDetectionStatus', 'Waiting for fresh night-camera detections.');
  }, Math.max(0, (2-age)*1000));
}
function nightVisionRetryPending() {
  return nvConfigured && !!nvFailureMessage && !nvConnected && !nvConnecting &&
    (nvRequested || recordingSource === 'nightvision');
}
function selectFeed(feed, connectOnSelect = false) {
  if (feed !== 'sound' && laptopSound?.active) laptopSound.stop('Stopped when you left Sound.');
  const previousFeed = selectedFeed;
  selectedFeed = feed;
  if(feed==='main')mainPlayer.wake?.();
  if(feed==='nightvision')nightPlayer.wake?.();
  $('monitor').dataset.activeFeed = feed;
  document.querySelectorAll('[data-feed]').forEach(button => { const selected = button.dataset.feed === feed; button.setAttribute('aria-selected', selected); button.tabIndex = selected ? 0 : -1; show(`panel-${button.dataset.feed}`, selected); });
  text('feedTitle', {main:'Main camera', nightvision:'Night vision', thermal:'Thermal monitoring', sound:'Sound monitoring'}[feed]);
  // Capture remains tied to the camera selected when recording starts.
  show('connectBtn', feed === 'main' && !cameraConnected && !$('camStream').dataset.viewer || feed === 'nightvision' && nvConfigured && !nvConnected && !$('nvStream').dataset.viewer);
  show('disconnectBtn', feed === 'main' && mainRequested || feed === 'nightvision' && nvRequested);
  show('sharedDetectionConnect', feed !== 'main' && !cameraConnected);
  $('sharedDetectionConnect').disabled = !session || endingSession || connecting || !!$('camStream').dataset.viewer;
  text('sharedDetectionConnect', mainWaiting ? 'Main detector waiting…' : connecting ? 'Connecting main detector…' : 'Connect main detector');
  show('nightCameraControls', feed === 'nightvision');
  show('recordBtn', ['main', 'nightvision'].includes(feed) && recorder?.state !== 'recording');
  $('recordBtn').disabled = !recordable() || !!pendingClip || uploading;
  $('connectBtn').disabled = feed === 'nightvision' ? nvConnecting : connecting;
  if (nightVisionRetryPending()) {
    text('availability-nightvision', 'Disconnected'); text('nvStatus', nvFailureMessage);
  }
  text('cameraStatus', feed === 'main' ? (cameraConnected ? 'Live' : mainWaiting ? 'Waiting' : connecting ? 'Connecting' : 'Disconnected') : $(`availability-${feed}`).textContent);
  if (nvConfigured && !nvManual && (feed === 'nightvision' || nvRequested) &&
      !$('nvStream').dataset.viewer && Date.now() >= nvRetryAt && document.visibilityState !== 'hidden') {
    connectNightVision();
  }
  if (feed === 'thermal' && previousFeed !== feed && session) {renderThermalGrid();fetchThermal();}
  if (connectOnSelect && feed === 'main' && !cameraConnected && !connecting) connectMainCamera();
  updateNightLight();
}
function nightLightNeeded() {
  return !!session && !endingSession && !nvLightPaused && document.visibilityState !== 'hidden' && nvLightPreference &&
    ((selectedFeed === 'nightvision' && nvConfigured && nvRequested) || (recordingSource === 'nightvision' && recorder?.state === 'recording'));
}
function renderNightLight() {
  text('nvLightStatus', nvLightMessage);
  $('nvLightStatus').dataset.state = nvLightState;
  const disabled = !session || endingSession || !nvConfigured;
  $('nvLightOnBtn').disabled = disabled;
  $('nvLightOffBtn').disabled = disabled;
  // A requested state is not an acknowledgement from the camera.
  $('nvLightOnBtn').setAttribute('aria-pressed', nvLightState === 'confirmed' && nvLightConfirmed === true);
  $('nvLightOffBtn').setAttribute('aria-pressed', nvLightState === 'confirmed' && nvLightConfirmed === false);
}
function updateNightLight(force = false) {
  const desired = nightLightNeeded();
  if (desired !== nvLightDesired || (force && !nvLightPending)) {
    nvLightDesired = desired; nvLightRevision++; nvLightQueued = true;
    nvLightState = 'pending'; nvLightMessage = `White light: turning ${desired ? 'on' : 'off'}…`;
  }
  renderNightLight();
  if (nvLightQueued && !nvLightPending) nvLightFlight = sendNightLight();
  return nvLightFlight;
}
async function sendNightLight() {
  nvLightPending = true;
  try {
    while (nvLightQueued) {
      nvLightQueued = false;
      const desired = nvLightDesired, revision = nvLightRevision;
      const headers = {'Content-Type':'application/json'};
      if (session?.access_token) headers.Authorization = `Bearer ${session.access_token}`;
      nvLightUsed = true;
      try {
        const response = await fetch('/api/nightvision/light', {method:'POST', credentials:'same-origin', headers,
          body:JSON.stringify({enabled:desired}), keepalive:!desired, signal:AbortSignal.timeout(7000)});
        const data = await response.json();
        if (response.status === 401) { sessionEnded(); throw new Error('The local session ended.'); }
        // Queue the newest command before displaying anything from an older one.
        if (revision !== nvLightRevision) continue;
        if (!response.ok || !data.supported || !data.available || typeof data.illumination?.enabled !== 'boolean' || data.illumination.enabled !== desired) {
          nvLightConfirmed = null;
          nvLightState = data.code === 'unsupported_firmware' ? 'unsupported' : 'unavailable';
          nvLightMessage = nvLightState === 'unsupported' ? 'Firmware update needed · white light control is unavailable.' :
            data.code === 'invalid_target' ? 'Light unavailable · check the configured spare-camera address.' :
            data.code === 'unreachable' ? 'Light unavailable · check spare power and Wi-Fi.' : 'Light unavailable · camera did not confirm the command.';
        } else {
          nvLightConfirmed = data.illumination.enabled; nvLightState = 'confirmed';
          nvLightMessage = `White light: ${nvLightConfirmed ? 'on' : 'off'}`;
        }
      } catch {
        if (revision !== nvLightRevision) continue;
        nvLightConfirmed = null; nvLightState = 'unavailable';
        nvLightMessage = 'Light unavailable · camera did not confirm the command.';
      }
      renderNightLight();
    }
  } finally { nvLightPending = false; }
}
$('nvLightOnBtn').onclick = () => { nvLightPreference = true; updateNightLight(true); };
$('nvLightOffBtn').onclick = () => { nvLightPreference = false; updateNightLight(true); };
// Firmware expires each on-command after 15 seconds if these renewals stop.
setInterval(() => { if (nightLightNeeded() && nvLightState !== 'unsupported') updateNightLight(true); }, 5000);
document.addEventListener('visibilitychange', () => {
  updateNightLight();
  if(document.visibilityState==='hidden'){
    clearTimeout(mainRetryTimeout);clearTimeout(connectTimeout);clearTimeout(nvTimeout);
    if(recordingSource!=='main'){
      mainPlayer.stop();connecting=false;cameraConnected=false;
      show('camStream',false);show('camOffline',true);
      text('availability-main',mainRequested?'Paused':'Disconnected');
    }
    if(recordingSource!=='nightvision'){
      nightPlayer.stop();nvConnecting=false;nvConnected=false;
      show('nvStream',false);show('nvEmpty',true);clearNightDetections('Viewing paused while this browser tab is hidden.');
      text('availability-nightvision',nvRequested?'Paused':'Configured');
    }
  }else if(session&&!endingSession){
    if(mainRequested)connectMainCamera();
    if(nvRequested)connectNightVision();
    refreshAll();
  }
});
window.addEventListener('pagehide', () => {
  nvLightPaused = true; updateNightLight();
  clearTimeout(connectTimeout); clearTimeout(mainRetryTimeout); clearTimeout(nvTimeout);
  mainPlayer.stop(); nightPlayer.stop();
  connecting = false; cameraConnected = false; nvConnecting = false; nvConnected = false;
  show('camStream', false); show('nvStream', false); show('camOffline', true); show('nvEmpty', true);
  text('availability-main', 'Disconnected'); text('availability-nightvision', 'Disconnected');
});
window.addEventListener('pageshow', event => {
  nvLightPaused = false; updateNightLight();
  if (event.persisted && session && !endingSession) {
    if (mainRequested) connectMainCamera();
    if (nvRequested || recordingSource === 'nightvision') connectNightVision();
    selectFeed(selectedFeed);
  }
});
document.querySelectorAll('[data-feed]').forEach((button, index, buttons) => {
  button.addEventListener('click', () => selectFeed(button.dataset.feed, true));
  button.addEventListener('keydown', event => {
    let next;
    if (event.key === 'ArrowRight') next = (index + 1) % buttons.length;
    if (event.key === 'ArrowLeft') next = (index + buttons.length - 1) % buttons.length;
    if (event.key === 'Home') next = 0;
    if (event.key === 'End') next = buttons.length - 1;
    if (next !== undefined) { event.preventDefault(); buttons[next].focus(); selectFeed(buttons[next].dataset.feed, true); }
  });
});
function connectNightVision() {
  if($('nvStream').dataset.viewer){nightPlayer.wake();return;}
  if (!session || endingSession || nvConnecting || nvConnected || document.visibilityState === 'hidden' && recordingSource !== 'nightvision') return;
  nvRequested = true; nvManual = false; nightWaiting=false;
  nvFailureMessage = ''; nvRetryAt = 0;
  clearNightDetections();
  nvConnecting = true; text('availability-nightvision', 'Connecting'); text('nvStatus', 'Connecting to the night camera…');
  nightPlayer.start();
}
function nightVisionFailed(message) {
  nightWaiting=false;
  clearTimeout(nvTimeout); nvConnected = false; nvConnecting = false; nvRetryAt = Date.now() + 1000;
  nvFailureMessage = message;
  nightPlayer.stop(); show('nvStream', false); show('nvEmpty', true);
  clearNightDetections(message);
  text('availability-nightvision', 'Disconnected'); text('nvStatus', message);
  if (recordingSource === 'nightvision' && recorder?.state === 'recording') stopRecording();
  selectFeed(selectedFeed);
}
$('nvStream').onload = () => {
  if(!nvRequested||!session||endingSession||!$('nvStream').dataset.viewer)return;
  clearTimeout(nvTimeout); nvConnecting = false; nvConnected = true; nvFailureMessage = ''; nvRetryAt = 0;
  nightWaiting=false;
  show('nvStream', true); show('nvEmpty', false); text('availability-nightvision', 'Live'); selectFeed(selectedFeed);
};
$('nvStream').onerror = () => {if(nvRequested&&!endingSession)nightVisionFailed('Night camera unavailable. Check its power and Wi-Fi. Retrying…');};
function sensorUnavailable(message, state = 'Disconnected') {
  ['tempDisplay', 'humDisplay', 'hiDisplay', 'mlConfidence', 'mlMethod'].forEach(id => text(id, '—'));
  text('mlAssessment', 'Fresh environmental readings required');
  text('robotStatus', `Sensors · ${state}`); text('sensorState', state); text('riskState', state);
  text('riskLevel', 'Assessment unavailable'); text('riskText', 'Fresh sensor readings are required to assess environmental risk.');
  text('sensorNote', message); $('probabilities').replaceChildren(); $('riskCard').classList.remove('is-alert', 'is-warning');
}
function fetchSensors() {
  if (sensorFlight) return sensorFlight;
  if (!session || endingSession) return Promise.resolve();
  const currentSession = session;
  sensorFlight = (async () => {
  try {
    const data = await api('/api/sensor-data', {signal: AbortSignal.timeout(2500), cache: 'no-store'});
    if (session !== currentSession || endingSession) return;
    if (!data.fresh || !data.updated_at || Date.now() / 1000 - data.updated_at > 10) { sensorUnavailable(data.updated_at ? `Last reading: ${dateTime(data.updated_at)}. Waiting for fresh data.` : data.message || 'No readings received. Check the robot connection.', data.updated_at ? 'Stale' : 'Waiting'); return; }
    lastSensorAt = data.updated_at;
    text('robotStatus', data.retrying?'Sensors · Updating':'Sensors · Live'); text('sensorState', data.retrying?'Retrying':'Live'); text('riskState', data.retrying?'Recent reading':'Live');
    text('tempDisplay', number(data.temperature)); text('humDisplay', number(data.humidity)); text('hiDisplay', number(data.heat_index));
    text('riskLevel', data.danger_level || data.risk_level || 'Unknown'); text('riskText', data.interpretation || 'Assessment unavailable.');
    text('hazardTime', `Updated ${dateTime(data.updated_at)}`); text('sensorNote', data.retrying ? `Last reading: ${dateTime(data.updated_at)}. Retrying connection.` : 'Readings update automatically.');
    $('riskCard').classList.toggle('is-alert', data.danger_level === 'Extreme Danger' || data.risk_level === 'Severe Risk'); $('riskCard').classList.toggle('is-warning', ['Caution','Extreme Caution','Danger'].includes(data.danger_level) || data.risk_level === 'Moderate Risk');
    text('mlMethod', data.method === 'nws_heat_index' ? 'NOAA / NWS heat index' : data.method === 'threshold' ? 'Threshold assessment' : data.method || '—');
    text('mlAssessment', 'SAR threshold rules · preset scores');
    text('mlConfidence', percent(data.confidence));
    $('probabilities').replaceChildren();
    ['low','moderate','severe'].forEach((key, index) => { const row = element('div', undefined, 'prob-row'); row.append(element('span', `${key[0].toUpperCase()}${key.slice(1)} risk`), element('strong', percent(Array.isArray(data.probabilities) ? data.probabilities[index] : data.probabilities?.[key]))); $('probabilities').append(row); });
  } catch {
    if(session===currentSession&&!endingSession){
      if(lastSensorAt&&Date.now()/1000-lastSensorAt<10){text('sensorState','Retrying');text('riskState','Recent reading');text('robotStatus','Sensors · Updating');text('sensorNote',`Last reading: ${dateTime(lastSensorAt)}. Retrying connection.`);}
      else sensorUnavailable('Could not reach the server. Retrying sensor readings.');
    }
  }
  })().finally(() => { sensorFlight = null; });
  return sensorFlight;
}
function fetchDetections() {
  if(detectionFlight)return detectionFlight;
  if(!session||endingSession)return Promise.resolve();
  const currentSession=session;
  detectionFlight=(async()=>{
  try {
    const data = await api('/api/survivors');
    if(session!==currentSession||endingSession)return;
    const age=Date.now()/1000-data.updated_at;
    const fresh = data.available && data.updated_at && age>=0 && age<2;
    lastDetectionAt = fresh ? data.updated_at : null;
    const count = fresh ? data.survivors_found : null;
    text('survivorCount', count === null ? '—' : count); text('detectionState', fresh ? 'Live' : 'Unavailable');
    text('survivorHint', !fresh ? 'Detection is unavailable. Connect the camera and check the detector.' : count > 0 ? 'Possible survivors detected. Review the live feed and SAR classifications.' : 'No survivors detected in the current frame.');
    renderSurvivors(data.detections, fresh);
    text('survivorConf', fresh && data.detections.length ? percent(Math.max(...data.detections.map(item => item.confidence))) : '—');
    $('survivorCard').classList.toggle('is-alert', fresh && count > 0);
  } catch { if(session!==currentSession||endingSession)return;renderSurvivors([], false); text('survivorCount','—'); text('survivorConf','—'); text('detectionState','Disconnected'); text('survivorHint','Could not retrieve detections. Check your connection.'); $('survivorCard').classList.remove('is-alert'); }
  })().finally(()=>{detectionFlight=null;});
  return detectionFlight;
}
function renderThermalGrid(data=latestThermalFrame){
  if(!data||!Number.isFinite(data.updated_at)||Date.now()/1000-data.updated_at>=5)return;
  const canvas=$('thermalGrid'),context=canvas.getContext('2d',{alpha:false});
  if(!thermalPixels)thermalPixels=context.createImageData(32,24);
  const range=data.max_temp-data.min_temp;
  let index=0;
  for(const row of data.grid)for(const value of row){
    const ratio=range>0?Math.max(0,Math.min(1,(value-data.min_temp)/range)):.5;
    const hue=240*(1-ratio),c=.85,x=c*(1-Math.abs((hue/60)%2-1));
    const rgb=hue<60?[c,x,0]:hue<120?[x,c,0]:hue<180?[0,c,x]:[0,x,c];
    for(const channel of rgb)thermalPixels.data[index++]=Math.round((channel+.075)*255);
    thermalPixels.data[index++]=255;
  }
  context.putImageData(thermalPixels,0,0);show('thermalGrid',true);
}
function fetchThermal() {
  // Manual refresh and the live loop share one request, so slow reads cannot queue.
  if (thermalFlight) return thermalFlight;
  if (!session || endingSession) return Promise.resolve();
  const currentSession = session;
  thermalFlight = (async () => {
    try {
      const data = await api('/api/thermal-data', {signal: AbortSignal.timeout(2500), cache:'no-store'});
      if (!session || session !== currentSession || endingSession) return;
      const age = Date.now()/1000 - data.updated_at;
      const validGrid = Array.isArray(data.grid) && data.grid.length === 24 &&
        data.grid.every(row => Array.isArray(row) && row.length === 32 && row.every(Number.isFinite));
      const live = data.connected && data.fresh !== false && Number.isFinite(data.updated_at) &&
        age >= 0 && age < 5 && validGrid && Number.isFinite(data.min_temp) &&
        Number.isFinite(data.max_temp) && data.min_temp <= data.max_temp;
      if (!live) {
        text('availability-thermal', data.configured ? 'Waiting' : 'Not installed');
        text('thermalStatus', data.message || 'Waiting for fresh thermal readings.');
        thermalUnavailable(data.configured ? 'Waiting for fresh thermal readings' : 'Not configured');
      } else {
        // Sequence progression survives conservative timing jitter; a later
        // source timestamp still permits resets after a board restart.
        const sequence = Number.isSafeInteger(data.sequence) && data.sequence >= 0 ? data.sequence : null;
        const advancing = sequence !== null && lastThermalSequence !== null && sequence > lastThermalSequence;
        if (!advancing && lastThermalAt !== null && data.updated_at < lastThermalAt - .05) return;
        lastThermalSequence = sequence;
        lastThermalAt = data.updated_at;
        text('availability-thermal', data.retrying?'Updating':'Live');
        text('thermalStatus', `${data.simulated ? 'SIMULATED · ' : ''}Range ${number(data.min_temp)}–${number(data.max_temp)} °C`);
        text('mainThermalRange', `${number(data.min_temp)}–${number(data.max_temp)} °C`);
        text('mainThermalState', data.retrying ? 'Recent reading · retrying connection' : `${data.simulated ? 'SIMULATED · ' : ''}Live surface range`);
        latestThermalFrame=data;
        if(selectedFeed==='thermal')renderThermalGrid(data);
        // Expire using acquisition time, even if a subsequent HTTP read stalls.
        clearTimeout(thermalExpiry);
        thermalExpiry = setTimeout(() => {
          thermalUnavailable('Thermal readings stale');
          text('availability-thermal', 'Waiting');
          text('thermalStatus', 'Waiting for fresh thermal readings');
          if (selectedFeed === 'thermal') text('cameraStatus', 'Waiting');
        }, Math.max(0, (data.updated_at+5)*1000-Date.now()));
      }
    } catch {
      if (!session || session !== currentSession || endingSession) return;
      if(lastThermalAt!==null&&Date.now()/1000-lastThermalAt<5){
        text('availability-thermal','Updating');text('thermalStatus','Showing the last recent frame while retrying.');text('mainThermalState','Recent reading · retrying connection');
      }else{
        text('availability-thermal', 'Unavailable');
        text('thermalStatus', 'Could not reach the server. Check your connection.');
        thermalUnavailable('Thermal sensor unavailable');
      }
    }
    if (selectedFeed === 'thermal') text('cameraStatus', $('availability-thermal').textContent);
  })().finally(() => { thermalFlight = null; });
  return thermalFlight;
}
function fetchDevices() {
  if(deviceFlight)return deviceFlight;
  if(!session||endingSession)return Promise.resolve();
  deviceFlight=(async()=>{
  // An older idle response cannot judge a stream that connected afterward.
  const mainSource = cameraConnected ? $('camStream').dataset.viewer : null;
  const nightSource = nvConnected ? $('nvStream').dataset.viewer : null;
  try {
    const data = await api('/api/device-status'); nvConfigured = data.nightvision;
    const nv = data.nightvision_status;
    const retrying = nightVisionRetryPending();
    text('availability-nightvision', !nvConfigured ? 'Not installed' : nvConnected ? 'Live' : nightWaiting ? 'Waiting' : nvConnecting ? 'Connecting' : retrying ? 'Disconnected' : 'Configured');
    if (!nvConnected && !nvConnecting && !nightWaiting) text('nvStatus', retrying ? nvFailureMessage : nv?.message || (nvConfigured ? 'Select this tab to connect.' : 'Night camera not configured.'));
    text('nvDetectionStatus', nv?.detection_enabled === false ? 'Night-camera detection is disabled.' : nv?.detections_available ? `${nv.detections.length} possible person detections · Night camera only · Verify in the feed.` : 'Waiting for night-camera detections. Infrared accuracy requires verification.');
    renderNightDetections(nv, !!nightSource && $('nvStream').dataset.viewer === nightSource);
    selectFeed(selectedFeed);
  } catch {
    clearNightDetections('Could not retrieve night-camera analysis.');
    text('availability-nightvision', nvConnected ? 'Updating' : nightWaiting ? 'Waiting' : nightVisionRetryPending() ? 'Disconnected' : 'Unavailable');
    text('nvStatus', nightVisionRetryPending() ? nvFailureMessage : 'Could not check availability. Check your connection.');
  }
  try {
    const data = await api('/api/sound-data');
    const age = Date.now()/1000 - data.updated_at;
    const fresh = data.connected && Number.isFinite(data.updated_at) && age >= 0 && age < 10;
    const live = fresh && Number.isFinite(data.db_level);
    remoteSoundAvailability = live ? 'Live' : data.configured ? 'Waiting' : 'Not installed';
    updateSoundAvailability();
    text('soundStatus', live ? `${data.simulated ? 'SIMULATED · ' : ''}Sound level: ${number(data.db_level)} dB` : data.message || (data.connected ? 'Connected. Waiting for sensor readings.' : 'Sound monitoring is not installed yet.'));
    if (live) {
      lastSoundAt = data.updated_at;
      const classification = (data.classification || 'Unknown').replaceAll('_', ' ');
      text('soundSummaryLevel', `${number(data.db_level)} dB`);
      text('soundSummaryState', `${data.simulated ? 'SIMULATED · ' : ''}Live · ${classification}`);
      show('soundMeter', true); show('soundClass', true);
      $('soundMeter').value = Math.max(0,Math.min(100,data.db_level));
      text('soundClass', `Classification: ${classification}`);
    } else soundUnavailable(data.configured ? 'Waiting for fresh sound readings' : 'Not configured');
  } catch { remoteSoundAvailability='Unavailable'; updateSoundAvailability(); text('soundStatus','Could not reach the server. Check your connection.'); soundUnavailable('Sound sensor unavailable'); }
  if (selectedFeed !== 'main') text('cameraStatus', $(`availability-${selectedFeed}`).textContent);
  })().finally(()=>{deviceFlight=null;});
  return deviceFlight;
}
function renderChart() {
  const key=$('trendMetric').value, unit=key==='humidity'?'%':'°C';
  const valid=samples.filter(s=>Number.isFinite(s[key]));
  const chart=$('trendChart'); chart.replaceChildren(); show('trendChart',valid.length>=2);
  if(valid.length<2){text('trendSummary',valid.length?'First reading received. Waiting for another reading to show a trend.':'No readings in the last hour. Trends appear when sensors send data.');return;}
  const values=valid.map(s=>s[key]), low=Math.min(...values), high=Math.max(...values), pad=Math.max((high-low)*.1,1), min=low-pad,max=high+pad;
  const start=valid[0].at,end=valid.at(-1).at;
  const x=t=>55+(t-start)/(end-start||1)*720,y=v=>145-(v-min)/(max-min)*125;
  const svg=(tag,attributes,content)=>{const el=document.createElementNS('http://www.w3.org/2000/svg',tag);Object.entries(attributes).forEach(([k,v])=>el.setAttribute(k,v));if(content)el.textContent=content;chart.append(el);return el;};
  [low,(low+high)/2,high].forEach(v=>{svg('line',{x1:55,y1:y(v),x2:775,y2:y(v),stroke:'#dde5df'});svg('text',{x:2,y:y(v)+4},`${v.toFixed(1)}${unit}`);});
  // Break the line across missing data so outages do not look like continuous readings.
  let segments=[],points=[]; valid.forEach((s,i)=>{if(i && s.at-valid[i-1].at>10){segments.push(points);points=[];}points.push(`${x(s.at)},${y(s[key])}`);});segments.push(points);
  segments.forEach(points=>svg('polyline',{points:points.join(' '),fill:'none',stroke:'#216c48','stroke-width':2.5}));
  svg('text',{x:55,y:175},new Date(start*1000).toLocaleTimeString());svg('text',{x:775,y:175,'text-anchor':'end'},new Date(end*1000).toLocaleTimeString());
  const summary=`${$('trendMetric').selectedOptions[0].text.split(' · ')[0]}: ${low.toFixed(1)} to ${high.toFixed(1)} ${unit}. ${valid.length} readings. Gaps indicate missing data.`;
  text('trendSummary',summary);chart.setAttribute('aria-label',summary);
}
$('trendMetric').addEventListener('change',renderChart);
async function fetchHistory() {
  try {
    const data=await api('/api/history');samples=data.samples;renderChart();
    $('sensorTable').replaceChildren(); samples.slice(-60).reverse().forEach(s=>{const row=element('tr');[dateTime(s.at),number(s.temperature),number(s.humidity),number(s.heat_index)].forEach(v=>row.append(element('td',v)));$('sensorTable').append(row);});
    const signature=JSON.stringify(data.alerts);if(signature===historySignature)return;historySignature=signature;
    text('alertCount',`${data.alerts.length} ${data.alerts.length === 1 ? 'event' : 'events'}`);$('alertList').replaceChildren();
    if(!data.alerts.length)$('alertList').append(element('li','No alerts yet. New events will appear here.','empty-row'));
    data.alerts.forEach(event=>{const row=element('li');const time=element('time',dateTime(event.at));time.dateTime=new Date(event.at*1000).toISOString();row.append(element('span',event.kind==='detection'?'Detection':'Risk alert','event-tag'),time,element('p',event.message));$('alertList').append(row);});
  } catch { text('alertCount','Unavailable'); historySignature=''; $('alertList').replaceChildren(element('li','History could not be loaded. Use Refresh status to retry.','empty-row')); text('trendSummary','Could not refresh trends. Any chart shown contains previously received readings.'); }
}
async function loadRecordings(reset=true) {
  if (libraryLoading) return;
  libraryLoading = true;
  $('reloadRecordings').disabled=true; $('loadMore').disabled=true;
  if(reset){recordingOffset=0;$('recordingList').replaceChildren();} text('libraryStatus','Loading recordings…');
  try {
    const data=await api(`/api/local-recordings?offset=${recordingOffset}`);
    data.recordings.forEach(clip=>{
      const row=element('li'),info=element('div',undefined,'clip-info'); row.dataset.recordingId=clip.id;
      const source=clip.source==='nightvision'?'Night camera':'Main camera';
      const state=clip.sync_state==='synced'?'Saved locally + in Supabase':clip.sync_state==='syncing'?'Saved locally · syncing to Supabase':'Saved locally · queued for Supabase';
      info.append(element('strong',clip.name),element('small',`${clip.created_at?dateTime(clip.created_at):'Date unavailable'} · ${(clip.size/1048576).toFixed(1)} MB · ${source}`),element('small',state));
      if(clip.sync_error) info.append(element('small',clip.sync_error));
      const link=element('a','Download MP4');link.href=clip.download_url;link.download=clip.name;row.append(info,link);$('recordingList').append(row);
    });
    recordingOffset+=data.recordings.length;show('loadMore',data.has_more);
    text('libraryStatus',recordingOffset?`${recordingOffset} local ${recordingOffset===1?'recording':'recordings'} loaded.`:'No local recordings yet. Stopping a recording saves it to this laptop.');
    text('syncStatus',data.pending_count?`${data.pending_count} queued for Supabase. Internet is required; the app retries automatically while running.`:'All local recordings are synced to Supabase. Local files are kept on this laptop.');
  } catch(error){text('libraryStatus',error.message);}
  finally{libraryLoading=false;$('reloadRecordings').disabled=false;$('loadMore').disabled=false;}
}
$('reloadRecordings').onclick=()=>loadRecordings();$('loadMore').onclick=()=>loadRecordings(false);
async function requestSync(){
  if(syncRequested||!session)return;syncRequested=true;$('syncRecordings').disabled=true;
  try{await api('/api/local-recordings/sync',{method:'POST'});text('syncStatus','Sync requested. Clips stay saved locally until Supabase confirms the upload.');setTimeout(()=>loadRecordings(),2000);}
  catch(error){text('syncStatus',`Local copies are safe. ${error.message}`);}
  finally{syncRequested=false;$('syncRecordings').disabled=false;}
}
$('syncRecordings').onclick=requestSync;
window.addEventListener('online',()=>requestSync());
// navigator.onLine also reports true on robot-only Wi-Fi. Only confirmed server
// sync states mark clips as uploaded; the online event is just a retry signal.
$('loadCloudRecordings').onclick=async()=>{
  const button=$('loadCloudRecordings');button.disabled=true;text('cloudLibraryStatus','Loading earlier cloud recordings. Internet is required…');
  try{
    const data=await api('/api/recordings?offset=0');$('cloudRecordingList').replaceChildren();
    data.recordings.forEach(clip=>{const row=element('li'),button=element('button','Open cloud clip');row.append(element('span',clip.name),button);button.onclick=async()=>{button.disabled=true;try{const data=await api(`/api/recordings/link?name=${encodeURIComponent(clip.name)}`);if(!data.link)throw new Error('Cloud recording link unavailable.');const link=element('a','View recording');link.href=data.link;link.target='_blank';link.rel='noopener';button.replaceWith(link);link.click();}catch(error){text('cloudLibraryStatus',error.message);button.disabled=false;}};$('cloudRecordingList').append(row);});
    text('cloudLibraryStatus',data.recordings.length?'Earlier cloud recordings loaded.':'No cloud recordings found.');
  }catch(error){text('cloudLibraryStatus',error.message);}finally{button.disabled=false;}
};
let connectTimeout;
function cameraFailed(message) {
  mainWaiting=false;
  clearTimeout(mainRetryTimeout);
  clearTimeout(connectTimeout);connecting=false;cameraConnected=false;mainPlayer.stop();show('camStream',false);show('camOffline',true);
  const retry = mainRequested && session && !endingSession && document.visibilityState !== 'hidden';
  text('cameraHint',retry ? `${message} Retrying…` : message);text('availability-main','Disconnected');$('connectBtn').disabled=false;$('recordBtn').disabled=true;
  if (retry) mainRetryTimeout = setTimeout(() => {
    if (mainRequested && session && !endingSession) connectMainCamera();
  }, 1000);
  if(recordingSource==='main'&&recorder?.state==='recording')stopRecording();selectFeed(selectedFeed);
}
function connectMainCamera(){
  if($('camStream').dataset.viewer){mainPlayer.wake();return;}
  if(!session||endingSession||connecting||cameraConnected||document.visibilityState==='hidden'&&recordingSource!=='main')return;
  mainRequested=true;mainWaiting=false;clearTimeout(mainRetryTimeout);connecting=true;$('connectBtn').disabled=true;text('cameraStatus','Connecting');text('cameraHint','Connecting to the robot camera…');
  const image=$('camStream'); image.onload=()=>{if(!mainRequested||!session||endingSession)return;clearTimeout(connectTimeout);mainWaiting=false;connecting=false;cameraConnected=true;show('camStream',true);show('camOffline',false);$('connectBtn').disabled=false;$('recordBtn').disabled=!!pendingClip;text('availability-main','Live');selectFeed(selectedFeed);};
  image.onerror=()=>{if(mainRequested)cameraFailed('Camera connection failed. Check the robot’s Wi-Fi.');};
  mainPlayer.start();
  selectFeed(selectedFeed);
}
$('connectBtn').onclick=()=>selectedFeed==='nightvision'?connectNightVision():connectMainCamera();
$('sharedDetectionConnect').onclick=connectMainCamera;
$('disconnectBtn').onclick=()=>{
  if(selectedFeed==='nightvision'){
    nvRequested=false;nvManual=true;nightWaiting=false;nvFailureMessage='';clearTimeout(nvTimeout);
    nvConnected=false;nvConnecting=false;nightPlayer.stop();show('nvStream',false);show('nvEmpty',true);
    if(recordingSource==='nightvision'&&recorder?.state==='recording')stopRecording();
    clearNightDetections('Night camera disconnected by the operator.');
    text('availability-nightvision','Disconnected');text('nvStatus','Camera disconnected. Press Connect to resume.');
    selectFeed(selectedFeed);
  }else{mainRequested=false;cameraFailed('Camera disconnected. Connect again to resume monitoring.');}
};
async function toggleServerRecording(action){try{await api('/toggle_recording',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action})});}catch{notify('Could not update the robot’s recording status. Check your connection.');}}
function finishRecordingUI(){clearInterval(drawTimer);clearInterval(clockTimer);recordingStream?.getTracks().forEach(track=>track.stop());recordingSource=null;show('recBadge',false);show('nvRecordBadge',false);show('stopBtn',false);$('recordBtn').disabled=!recordable()||!!pendingClip;selectFeed(selectedFeed);}
$('recordBtn').onclick=()=>{
  if(!recordable()||pendingClip||uploading||recorder?.state==='recording')return;
  try {
    if(!window.MediaRecorder)throw new Error('Recording is not supported in this browser. Try a current Chrome, Edge, or Safari browser.');
    const mime=['video/mp4;codecs=avc1.424028','video/mp4'].find(type=>MediaRecorder.isTypeSupported(type));
    if(!mime)throw new Error('This browser cannot record MP4 video. Open BIM-BOT in an updated Safari, Chrome, or Edge browser to record and download MP4 backups.');
    const source=selectedFeed;recordingSource=source;
    const canvas=$('recordCanvas'),image=$(source==='nightvision'?'nvStream':'camStream');canvas.width=image.naturalWidth||image.width||640;canvas.height=image.naturalHeight||image.height||480;const ctx=canvas.getContext('2d');ctx.drawImage(image,0,0,canvas.width,canvas.height);
    recordingStream=canvas.captureStream(30);
    recorder=new MediaRecorder(recordingStream,{mimeType:mime});const chunks=[];
    recorder.ondataavailable=event=>{if(event.data.size)chunks.push(event.data);};
    recorder.onstop=()=>{const blob=new Blob(chunks,{type:recorder.mimeType});finishRecordingUI();if(!blob.size){notify('No video was captured. Reconnect the camera and retry.');return;}savedClip=null;pendingClip={blob,name:`bimbot_${source}_${Date.now()}_${crypto.randomUUID()}.mp4`,source};$('recordBtn').disabled=true;show('discardBtn',false);if(!$('saveDialog').open)$('saveDialog').showModal();saveClip();};
    recorder.onerror=()=>{notify('Recording stopped unexpectedly. Any captured footage will be saved.');stopRecording();};
    recorder.start(1000);recordingStarted=Date.now();text('recordTime','00:00');
    drawTimer=setInterval(()=>{try{ctx.drawImage(image,0,0,canvas.width,canvas.height);}catch{stopRecording();notify('Camera frames became unavailable. Saving captured footage.');}},33);
    clockTimer=setInterval(()=>{const seconds=Math.floor((Date.now()-recordingStarted)/1000);text('recordTime',`${Math.floor(seconds/60).toString().padStart(2,'0')}:${(seconds%60).toString().padStart(2,'0')}`);},1000);
    show(source==='nightvision'?'nvRecordBadge':'recBadge',true);show('recordBtn',false);show('stopBtn',true);toggleServerRecording('start');updateNightLight();
  }catch(error){finishRecordingUI();notify(error.message);}
};
function stopRecording(){if(recorder?.state==='recording'){recorder.stop();toggleServerRecording('stop');updateNightLight();}}
$('stopBtn').onclick=stopRecording;
async function saveClip(){
  if(!pendingClip||uploading)return;uploading=true;$('closeSave').disabled=true;show('retryUpload',false);show('discardBtn',false);text('saveTitle','Saving to this laptop');text('uploadStatus','Keep this page open until the local save finishes. Internet is not required.');
  const form=new FormData();form.append('video',pendingClip.blob,pendingClip.name);form.append('filename',pendingClip.name);form.append('source',pendingClip.source);
  try{
    const data=await api('/api/local-recordings',{method:'POST',body:form,signal:AbortSignal.timeout(120000)});
    if(!data.success||!data.recording?.download_url)throw new Error('The laptop did not confirm the local save.');
    savedClip=data.recording;pendingClip=null;text('saveTitle','Recording saved on this laptop');
    text('uploadStatus',savedClip.sync_state==='synced'?'Saved locally and in Supabase. The local copy is kept.':'Queued for Supabase. You can continue offline; uploads retry while the app runs and internet is available.');
    $('closeSave').disabled=false;loadRecordings();
  }
  catch(error){text('saveTitle','Local save needs attention');text('uploadStatus',`${error.message} This clip is still held in this page. Retry or download an MP4 backup before leaving.`);show('retryUpload',true);show('discardBtn',true);}
  finally{uploading=false;selectFeed(selectedFeed);}
}
$('retryUpload').onclick=saveClip;
$('downloadBtn').onclick=async()=>{
  const button=$('downloadBtn');button.disabled=true;
  try{
    let blob=pendingClip?.blob,name=pendingClip?.name;
    if(savedClip){
      const headers=session?.access_token?{Authorization:`Bearer ${session.access_token}`} : {};
      const response=await fetch(savedClip.download_url,{credentials:'same-origin',headers,signal:AbortSignal.timeout(120000)});
      if(!response.ok)throw new Error('Could not download the saved local file. Refresh the local library or sign in again if your session ended.');
      blob=await response.blob();name=savedClip.name;
    }
    if(!blob)return;const url=URL.createObjectURL(blob),a=element('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }catch(error){text('uploadStatus',error.message);}finally{button.disabled=false;}
};
function closeSave(){pendingClip=null;savedClip=null;$('saveDialog').close();selectFeed(selectedFeed);if(!session)window.location.assign('/login?reason=expired');}
$('closeSave').onclick=closeSave;$('discardBtn').onclick=()=>{if(confirm('Discard this unsaved recording? Download a backup first if you need it.'))closeSave();};
$('saveDialog').addEventListener('cancel',event=>{if(uploading||$('closeSave').disabled)event.preventDefault();else closeSave();});
window.addEventListener('beforeunload',event=>{if(recorder?.state==='recording'||pendingClip||uploading){event.preventDefault();event.returnValue='';}});
$('logoutBtn').onclick=async()=>{if(recorder?.state==='recording'||pendingClip||uploading){notify('Finish recording and save or download your clip before signing out.');return;}if(laptopSound?.active)laptopSound.stop('Stopped for sign out.');nvLightPaused=true;await updateNightLight();const result=await client.auth.signOut();if(result.error){notify(result.error.message);nvLightPaused=false;updateNightLight();}};
let missionCommandPending = false;
function fetchPosition() {
  if (positionFlight) return positionFlight;
  if (!session || endingSession || !$('positionState')) return Promise.resolve();
  positionFlight = (async () => {
    try {
      const data = await api('/api/position-data');
      if (!session || endingSession) { positionUnavailable('Sign in', 'Sign in to view robot position.'); return; }
      if (!data.configured) { positionUnavailable('Not configured', 'No robot position source is configured. A GPS receiver or indoor tracker is needed.'); return; }
      const source = typeof data.source === 'string' && data.source.trim().length > 0 && data.source.length <= 80;
      if (data.connected && data.frame === 'wgs84' && data.fix_valid === false && source) {
        positionUnavailable('No GPS fix', 'Receiver connected. Waiting for a valid satellite fix.');
        text('positionFrame', 'Global coordinates (WGS84)'); text('positionSource', data.source);
        if (Number.isInteger(data.satellites) && data.satellites >= 0) text('positionQuality', `${data.satellites} satellites reported`);
        return;
      }
      const global = data.frame === 'wgs84';
      const limit = global || Number.isFinite(data.sample_age_ms) ? 5 : 10;
      const age = Date.now()/1000 - data.updated_at;
      const valid = source && data.fresh === true && data.connected === true && Number.isFinite(data.updated_at) && age >= 0 && age < limit &&
        (global ? data.fix_valid === true && Number.isFinite(data.latitude) && Math.abs(data.latitude) <= 90 && Number.isFinite(data.longitude) && Math.abs(data.longitude) <= 180 :
          data.frame === 'local_meters' && Number.isFinite(data.x) && Number.isFinite(data.y));
      if (!valid) { positionUnavailable('Unavailable', 'No fresh valid robot position. Check receiver/tracker status.'); return; }
      clearTimeout(positionExpiry);
      text('positionState', `${data.simulated ? 'SIMULATED · ' : ''}${global ? 'GPS fix' : 'Local position'}`);
      text('positionMessage', global ? 'Geographic position of the robot. This does not identify an indoor room or floor.' : 'Robot position relative to the local tracker origin. GPS coordinates are not available from this frame.');
      text('positionFrame', global ? 'Global coordinates (WGS84)' : 'Local coordinates (metres)');
      text('positionSource', data.source);
      text('positionFirstLabel', global ? 'Latitude' : 'Local X');
      text('positionSecondLabel', global ? 'Longitude' : 'Local Y');
      text('positionFirst', global ? data.latitude.toFixed(6) : `${data.x.toFixed(2)} m`);
      text('positionSecond', global ? data.longitude.toFixed(6) : `${data.y.toFixed(2)} m`);
      const quality = [];
      if (global && Number.isInteger(data.satellites) && data.satellites >= 0) quality.push(`${data.satellites} satellites reported`);
      if (global && Number.isFinite(data.horizontal_accuracy_m) && data.horizontal_accuracy_m >= 0) quality.push(`Reported accuracy ±${number(data.horizontal_accuracy_m)} m`);
      text('positionQuality', quality.join(' · ') || 'Accuracy not reported');
      text('positionTime', dateTime(data.updated_at));
      const map = $('positionMap');
      if (global && !data.simulated) map.href = `https://www.openstreetmap.org/?mlat=${data.latitude}&mlon=${data.longitude}#map=17/${data.latitude}/${data.longitude}`;
      else map.removeAttribute('href');
      show('positionMap', global && !data.simulated);
      positionExpiry = setTimeout(() => positionUnavailable('Stale', 'Position updates stopped. Waiting for a new robot sample.'), Math.max(1,(limit-age)*1000));
    } catch {
      positionUnavailable('Unavailable', 'Could not retrieve robot position.');
    }
  })().finally(() => { positionFlight = null; });
  return positionFlight;
}
async function fetchMission() {
  try {
    const data = await api('/api/mission'), mission = data.mission;
    text('missionState', mission ? mission.state.replaceAll('_', ' ') : 'Idle');
    $('missionStart').disabled = missionCommandPending || !data.can_start;
    $('missionStop').disabled = missionCommandPending || !mission || !['searching','command_uncertain'].includes(mission.state);
    $('missionArea').disabled = !!mission && ['searching','command_uncertain'].includes(mission.state);
    text('missionHint', `${data.robot.simulated ? 'SIMULATED ROBOT · ' : ''}${data.robot_busy ? 'Another operator has an active mission.' : mission?.state === 'command_uncertain' ? 'Command acknowledgement was lost. Verify robot motion and retry Stop.' : !data.control_configured ? 'Robot control is not configured. Configure the firmware bridge before starting.' : !data.robot.fresh ? 'Waiting for fresh robot telemetry.' : !data.robot.navigation_ready ? 'Ultrasonic navigation is not ready.' : mission?.state === 'searching' ? `Searching · ${mission.area_label}.` : 'Robot ready. Enter an observation area to start.'}`);
  } catch { text('missionState', 'Unavailable'); text('missionHint', 'Could not retrieve mission status.'); $('missionStart').disabled = true; /* Keep an existing Stop available for retries. */ }
}
async function missionCommand(action) {
  if (missionCommandPending) return;
  if (action === 'start' && !$('missionArea').value.trim()) { notify('Enter an observation area before starting.'); $('missionArea').focus(); return; }
  missionCommandPending = true; $('missionStart').disabled = true; $('missionStop').disabled = true;
  try { await api(`/api/mission/${action}`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({area_label:$('missionArea').value.trim()})}); notify(`Mission ${action === 'start' ? 'started' : 'stopped'}; robot acknowledged the command.`); }
  catch(error) { notify(error.message); }
  finally { missionCommandPending = false; await fetchMission(); }
}
$('missionStart').onclick = () => missionCommand('start');
$('missionStop').onclick = () => missionCommand('stop');
$('downloadReport').onclick = async () => {
  try { const report = await api('/api/situational-report'); const url = URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:'application/json'})); const link = element('a'); link.href=url; link.download=`bimbot_report_${Date.now()}.json`; link.click(); setTimeout(()=>URL.revokeObjectURL(url),1000); }
  catch(error) { notify(error.message); }
};
let eventSignature = '';
async function fetchSurvivorEvents() {
  try {
    const data = await api('/api/survivor-events');
    const signature=JSON.stringify(data.events); if(signature===eventSignature || $('survivorEventList').contains(document.activeElement))return; eventSignature=signature;
    text('survivorEventCount', `${data.events.length} records`); $('survivorEventList').replaceChildren();
    if(!data.events.length)$('survivorEventList').append(element('li','No mission detections recorded yet.','empty-row'));
    data.events.forEach(event => {
      const row=element('li',undefined,'survivor-event'), evidence=event.evidence;
      row.append(element('h3',`${evidence.detections.length} possible survivor(s) · ${evidence.area_label}`),element('p',dateTime(event.at)),element('p',`${evidence.environment?.danger_level || 'Environment unavailable'} · ${evidence.observation_position ? 'Robot observation position recorded' : 'Coordinates unavailable'}`));
      const details = element('details'), summary = element('summary', 'SAR classifications recorded');
      const detectionList = element('ul', undefined, 'event-list');
      evidence.detections.forEach((detection, index) => detectionList.append(survivorDetails(detection, index)));
      details.append(summary, detectionList); row.append(details);
      const form=element('form',undefined,'review-form');
      const selectField=(key,label,values,current)=>{const wrapper=element('label',label),select=element('select');select.name=key;values.forEach(v=>{const option=element('option',v.replaceAll('_',' '));option.value=v;select.append(option);});select.value=current||values[0];wrapper.append(select);form.append(wrapper);};
      selectField('verification','Verification',['uncertain','confirmed','false_positive'],event.review?.verification);
      for(const [key,label,values] of [['age_group','Age group',['unknown','adult','child']],['consciousness','Consciousness',['unknown','conscious','unconscious']],['injury','Injury',['unknown','injured','uninjured']],['entrapment','Entrapment',['unknown','trapped','not_trapped']]])selectField(key,label,values,event.review?.assessment[key]);
      const notesLabel=element('label','Review notes'),notes=element('textarea');notes.name='notes';notes.maxLength=2000;notes.value=event.review?.notes||'';notesLabel.append(notes);form.append(notesLabel);
      const communicationNote=element('button','Add communication note');communicationNote.type='button';
      communicationNote.onclick=()=>{
        const entry=`Communication observation · ${new Date().toLocaleString()}\nPrompt and how it reached the survivor: [not sent / describe actual channel]\nObserved gesture or words: [describe / no response / unclear]\nOperator interpretation: [unknown unless confirmed]\n`;
        const separator=notes.value ? '\n\n' : '';
        if(notes.value.length+separator.length+entry.length>notes.maxLength){notify('Review notes are full. Shorten them before adding a communication note.');return;}
        const start=notes.value.length+separator.length;
        notes.value+=separator+entry;notes.focus();notes.setSelectionRange(start,notes.value.length);
      };
      form.append(communicationNote,element('p','Communication notes are saved with this review. They do not send a message to the robot.','muted'));
      const save=element('button','Save operator review');save.type='submit';form.append(save);
      if(event.reviewed_at)form.append(element('p',`Reviewed ${dateTime(event.reviewed_at)}`,'muted'));
      form.onsubmit=async e=>{e.preventDefault();save.disabled=true;const values=Object.fromEntries(new FormData(form)),assessment={};['age_group','consciousness','injury','entrapment'].forEach(k=>assessment[k]=values[k]);try{await api(`/api/survivor-events/${event.id}/review`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({verification:values.verification,notes:values.notes,assessment})});notify('Operator review saved.');save.blur();eventSignature='';await fetchSurvivorEvents();}catch(error){notify(error.message);save.disabled=false;}};
      row.append(form);$('survivorEventList').append(row);
    });
  } catch { text('survivorEventCount','Unavailable'); }
}
movementPanel = window.BIMMovement && $('movementState') ? new window.BIMMovement({api,canAct:()=>!!session && !endingSession,notify}) : null;
function refreshAll(){
  if(refreshFlight)return refreshFlight;
  $('refreshBtn').disabled=true;
  refreshFlight=Promise.allSettled([fetchThermal(),fetchSensors(),fetchDetections(),fetchDevices(),fetchHistory(),fetchMission(),fetchPosition(),fetchSurvivorEvents(),movementPanel?.load()]).finally(()=>{refreshFlight=null;$('refreshBtn').disabled=false;});
  return refreshFlight;
}
$('refreshBtn').onclick=refreshAll;
function openGuidedTarget(){
  const view=new URLSearchParams(location.search).get('view');
  if(['main','nightvision','thermal','sound'].includes(view)&&view!==selectedFeed)selectFeed(view,false);
  let target='';try{target=decodeURIComponent(location.hash.slice(1));}catch{return;}
  if(['survivorDetails','nightSurvivorDetails','communication','recordings','monitor'].includes(target)){
    const node=$(target);if(!node)return;const tools=node.closest('details');if(tools)tools.open=true;
    requestAnimationFrame(()=>node.scrollIntoView({block:'start'}));
  }
}
window.addEventListener('hashchange',openGuidedTarget);
openGuidedTarget();
function poll(fn,interval){
  const run=async()=>{
    if(!session||endingSession)return;
    try{if(document.visibilityState!=='hidden')await fn();}catch{/* One failed check cannot kill the worker. */}
    finally{if(session&&!endingSession)setTimeout(run,document.visibilityState==='hidden'?1000:typeof interval==='function'?interval():interval);}
  };
  setTimeout(run,typeof interval==='function'?interval():interval);
}
client.auth.onAuthStateChange((event,newSession)=>{session=newSession;if(!session)sessionEnded(event==='SIGNED_OUT'?'logout':'expired');});
(async()=>{try{const result=await client.auth.getSession();session=result.data.session;if(!session){window.location.assign(result.error?'/login?reason=expired':'/login');return;}text('accountEmail',session.user.email||'Signed in');poll(fetchThermal,()=>selectedFeed==='thermal'?(monitoringProfile.thermal_view_poll_ms??1000):(monitoringProfile.thermal_summary_poll_ms??2000));Promise.allSettled([refreshAll(),loadRecordings()]);poll(fetchSensors,2000);poll(fetchDetections,1000);poll(fetchDevices,monitoringProfile.device_poll_ms??3000);poll(fetchHistory,10000);poll(fetchMission,2000);poll(fetchPosition,2000);poll(()=>movementPanel?.load(),1000);poll(fetchSurvivorEvents,10000);poll(loadRecordings,15000);setInterval(()=>{if(lastSoundAt&&Date.now()/1000-lastSoundAt>=10){soundUnavailable('Sound readings stale');remoteSoundAvailability='Waiting';updateSoundAvailability();text('soundStatus','Waiting for fresh sound readings');}if(lastSensorAt&&Date.now()/1000-lastSensorAt>10)sensorUnavailable(`Last reading: ${dateTime(lastSensorAt)}. Waiting for fresh data.`,'Stale');if(lastDetectionAt&&Date.now()/1000-lastDetectionAt>=2){renderSurvivors([],false);text('survivorCount','—');text('survivorConf','—');text('detectionState','Stale');text('survivorHint','Detection updates stopped. Check the camera connection.');$('survivorCard').classList.remove('is-alert');}},1000);}catch{notify('Could not initialize the dashboard. Reload the page to retry.');}})();
