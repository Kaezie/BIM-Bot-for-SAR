'use strict';
const $ = id => document.getElementById(id);
const client = window.BIM_AUTH;
let session, selectedFeed = 'main', cameraConnected = false, connecting = false;
let recorder, recordingStream, drawTimer, clockTimer, recordingStarted, pendingClip, uploading = false;
let samples = [], recordingOffset = 0, historySignature = '', lastSensorAt = null, lastDetectionAt = null;
const text = (id, value) => { if ($(id).textContent !== String(value)) $(id).textContent = value; };
const show = (id, visible) => { $(id).toggleAttribute('hidden', !visible); };
const number = value => typeof value === 'number' && Number.isFinite(value) ? value.toFixed(1) : '—';
const percent = value => typeof value === 'number' && Number.isFinite(value) ? `${(value * 100).toFixed(1)}%` : '—';
const dateTime = value => new Date(typeof value === 'number' ? value * 1000 : value).toLocaleString();
function notify(message) { text('notice', message); show('notice', !!message); }
async function api(path, options = {}) {
  const response = await fetch(path, {...options, headers: {...options.headers, Authorization: `Bearer ${session.access_token}`}, signal: options.signal || AbortSignal.timeout(15000)});
  if (response.status === 401) { await client.auth.signOut(); window.location.assign('/login'); throw new Error('Please sign in again.'); }
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Could not reach the server. Please retry.');
  return data;
}
function element(tag, content, className) { const el = document.createElement(tag); if (content !== undefined) el.textContent = content; if (className) el.className = className; return el; }
function survivorDetails(detection, index) {
  const row = element('li', undefined, 'survivor-event');
  row.append(element('h3', `Detection ${index + 1} · ${percent(detection.confidence)}`));
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
function selectFeed(feed) {
  selectedFeed = feed;
  $('monitor').dataset.activeFeed = feed;
  document.querySelectorAll('[data-feed]').forEach(button => { const selected = button.dataset.feed === feed; button.setAttribute('aria-selected', selected); button.tabIndex = selected ? 0 : -1; show(`panel-${button.dataset.feed}`, selected); });
  text('feedTitle', {main:'Main camera', nightvision:'Night vision', thermal:'Thermal monitoring', sound:'Sound monitoring'}[feed]);
  // Recording controls remain visible on all sources so an active main-camera clip can always be stopped.
  show('connectBtn', feed === 'main' && !cameraConnected);
  show('disconnectBtn', feed === 'main' && cameraConnected);
  show('recordBtn', feed === 'main' && recorder?.state !== 'recording');
  text('cameraStatus', feed === 'main' ? (cameraConnected ? 'Live' : connecting ? 'Connecting' : 'Disconnected') : $(`availability-${feed}`).textContent);
  if (feed === 'nightvision' && $('availability-nightvision').textContent === 'Available' && !$('nvStream').getAttribute('src')) {
    $('nvStream').src = `/nightvision_feed?access_token=${encodeURIComponent(session.access_token)}`;
  }
}
document.querySelectorAll('[data-feed]').forEach((button, index, buttons) => {
  button.addEventListener('click', () => selectFeed(button.dataset.feed));
  button.addEventListener('keydown', event => {
    let next;
    if (event.key === 'ArrowRight') next = (index + 1) % buttons.length;
    if (event.key === 'ArrowLeft') next = (index + buttons.length - 1) % buttons.length;
    if (event.key === 'Home') next = 0;
    if (event.key === 'End') next = buttons.length - 1;
    if (next !== undefined) { event.preventDefault(); buttons[next].focus(); selectFeed(buttons[next].dataset.feed); }
  });
});
$('nvStream').onload = () => { show('nvStream', true); show('nvEmpty', false); };
$('nvStream').onerror = () => { show('nvStream', false); show('nvEmpty', true); text('nvStatus', 'Night vision feed unavailable. Check the camera connection.'); };
function sensorUnavailable(message, state = 'Disconnected') {
  ['tempDisplay', 'humDisplay', 'hiDisplay', 'mlConfidence', 'mlMethod'].forEach(id => text(id, '—'));
  text('mlAssessment', 'Fresh environmental readings required');
  text('robotStatus', `Sensors · ${state}`); text('sensorState', state); text('riskState', state);
  text('riskLevel', 'Assessment unavailable'); text('riskText', 'Fresh sensor readings are required to assess environmental risk.');
  text('sensorNote', message); $('probabilities').replaceChildren(); $('riskCard').classList.remove('is-alert', 'is-warning');
}
async function fetchSensors() {
  try {
    const data = await api('/api/sensor-data');
    if (!data.fresh || !data.updated_at || Date.now() / 1000 - data.updated_at > 10) { sensorUnavailable(data.updated_at ? `Last reading: ${dateTime(data.updated_at)}. Waiting for fresh data.` : 'No readings received. Check the robot connection.', data.updated_at ? 'Stale' : 'Waiting'); return; }
    lastSensorAt = data.updated_at;
    text('robotStatus', 'Sensors · Live'); text('sensorState', 'Live'); text('riskState', 'Live');
    text('tempDisplay', number(data.temperature)); text('humDisplay', number(data.humidity)); text('hiDisplay', number(data.heat_index));
    text('riskLevel', data.danger_level || data.risk_level || 'Unknown'); text('riskText', data.interpretation || 'Assessment unavailable.');
    text('hazardTime', `Updated ${dateTime(data.updated_at)}`); text('sensorNote', 'Readings update automatically.');
    $('riskCard').classList.toggle('is-alert', data.danger_level === 'Extreme Danger' || data.risk_level === 'Severe Risk'); $('riskCard').classList.toggle('is-warning', ['Caution','Extreme Caution','Danger'].includes(data.danger_level) || data.risk_level === 'Moderate Risk');
    text('mlMethod', data.method === 'nws_heat_index' ? 'NOAA / NWS heat index' : data.method === 'threshold' ? 'Threshold assessment' : data.method || '—');
    text('mlAssessment', 'SAR threshold rules · preset scores');
    text('mlConfidence', percent(data.confidence));
    $('probabilities').replaceChildren();
    ['low','moderate','severe'].forEach((key, index) => { const row = element('div', undefined, 'prob-row'); row.append(element('span', `${key[0].toUpperCase()}${key.slice(1)} risk`), element('strong', percent(Array.isArray(data.probabilities) ? data.probabilities[index] : data.probabilities?.[key]))); $('probabilities').append(row); });
  } catch { sensorUnavailable('Could not reach the server. Check your connection.'); }
}
async function fetchDetections() {
  try {
    const data = await api('/api/survivors');
    const fresh = data.available && data.updated_at && Date.now()/1000 - data.updated_at < 10;
    lastDetectionAt = fresh ? data.updated_at : null;
    const count = fresh ? data.survivors_found : null;
    text('survivorCount', count === null ? '—' : count); text('detectionState', fresh ? 'Live' : 'Unavailable');
    text('survivorHint', !fresh ? 'Detection is unavailable. Connect the camera and check the detector.' : count > 0 ? 'Possible survivors detected. Review the live feed and SAR classifications.' : 'No survivors detected in the current frame.');
    renderSurvivors(data.detections, fresh);
    text('survivorConf', fresh && data.detections.length ? percent(Math.max(...data.detections.map(item => item.confidence))) : '—');
    $('survivorCard').classList.toggle('is-alert', fresh && count > 0);
  } catch { renderSurvivors([], false); text('survivorCount','—'); text('survivorConf','—'); text('detectionState','Disconnected'); text('survivorHint','Could not retrieve detections. Check your connection.'); $('survivorCard').classList.remove('is-alert'); }
}
async function fetchDevices() {
  try {
    const data = await api('/api/device-status'); text('availability-nightvision', data.nightvision ? 'Available' : 'Not installed'); text('nvStatus', data.nightvision ? 'Select this tab to view the night vision feed.' : 'Night vision is not installed. This tab will become available when connected.');
  } catch { text('availability-nightvision','Unavailable'); text('nvStatus','Could not check availability. Check your connection.'); }
  for (const feed of ['thermal','sound']) {
    try {
      const data = await api(`/api/${feed}-data`);
      const live = feed === 'thermal' ? data.connected && data.grid?.length : data.connected && Number.isFinite(data.db_level);
      text(`availability-${feed}`, live ? 'Live' : data.configured ? 'Waiting' : 'Not installed');
      text(`${feed}Status`, live ? (feed === 'thermal' ? `${data.simulated ? 'SIMULATED · ' : ''}Range ${number(data.min_temp)}–${number(data.max_temp)} °C` : `${data.simulated ? 'SIMULATED · ' : ''}Sound level: ${number(data.db_level)} dB`) : data.message || (data.connected ? 'Connected. Waiting for sensor readings.' : `${feed === 'thermal' ? 'Thermal monitoring' : 'Sound monitoring'} is not installed yet.`));
      if (feed === 'sound') { show('soundMeter',live); show('soundClass',live); $('soundMeter').value = Math.max(0,Math.min(100,data.db_level || 0)); text('soundClass',`Classification: ${data.classification || 'Unknown'}`); }
      else { show('thermalGrid',live); $('thermalGrid').replaceChildren(); if(live) data.grid.flat().forEach(value => { const cell=element('div'); const ratio=data.max_temp > data.min_temp ? (value-data.min_temp)/(data.max_temp-data.min_temp) : .5; cell.style.background=`hsl(${240*(1-Math.max(0,Math.min(1,ratio)))} 85% 50%)`; $('thermalGrid').append(cell); }); }
    } catch { text(`availability-${feed}`,'Unavailable'); text(`${feed}Status`,'Could not reach the server. Check your connection.'); show(feed === 'sound' ? 'soundMeter' : 'thermalGrid',false); if(feed==='sound') show('soundClass',false); }
  }
  if (selectedFeed !== 'main') text('cameraStatus', $(`availability-${selectedFeed}`).textContent);
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
  $('reloadRecordings').disabled=true; $('loadMore').disabled=true;
  if(reset){recordingOffset=0;$('recordingList').replaceChildren();} text('libraryStatus','Loading recordings…');
  try {
    const data=await api(`/api/recordings?offset=${recordingOffset}`);
    data.recordings.forEach(clip=>{const row=element('li'),info=element('div',undefined,'clip-info');info.append(element('strong',clip.name),element('small',`${clip.created_at?dateTime(clip.created_at):'Date unavailable'} · ${(clip.size/1048576).toFixed(1)} MB`));const button=element('button','Open clip');button.addEventListener('click',async()=>{button.disabled=true;try{const data=await api(`/api/recordings/link?name=${encodeURIComponent(clip.name)}`);if(!data.link)throw new Error('Recording link unavailable.');const link=element('a','View recording');link.href=data.link;link.target='_blank';link.rel='noopener';button.replaceWith(link);link.click();}catch(error){text('libraryStatus',error.message);button.disabled=false;}});row.append(info,button);$('recordingList').append(row);});
    recordingOffset+=data.recordings.length;show('loadMore',data.has_more);text('libraryStatus',recordingOffset?`${recordingOffset} ${recordingOffset === 1 ? 'recording' : 'recordings'} loaded.`:'No saved recordings yet. Your first clip will appear after cloud saving finishes.');
  } catch(error){text('libraryStatus',error.message);}
  finally{$('reloadRecordings').disabled=false;$('loadMore').disabled=false;}
}
$('reloadRecordings').onclick=()=>loadRecordings();$('loadMore').onclick=()=>loadRecordings(false);
let connectTimeout;
function cameraFailed(message) {
  clearTimeout(connectTimeout);connecting=false;cameraConnected=false;$('camStream').removeAttribute('src');show('camStream',false);show('camOffline',true);
  text('cameraHint',message);text('availability-main','Disconnected');$('connectBtn').disabled=false;$('recordBtn').disabled=true;
  if(recorder?.state==='recording')stopRecording();selectFeed(selectedFeed);
}
$('connectBtn').onclick=()=>{
  if(!session||connecting)return;connecting=true;$('connectBtn').disabled=true;text('cameraStatus','Connecting');text('cameraHint','Connecting to the robot camera…');
  const image=$('camStream'); image.onload=()=>{clearTimeout(connectTimeout);connecting=false;cameraConnected=true;show('camStream',true);show('camOffline',false);$('connectBtn').disabled=false;$('recordBtn').disabled=!!pendingClip;text('availability-main','Live');selectFeed(selectedFeed);};
  image.onerror=()=>cameraFailed('Camera connection failed. Check the robot’s Wi-Fi and try again.');
  connectTimeout=setTimeout(()=>cameraFailed('Camera connection timed out. Check the robot’s Wi-Fi and try again.'),15000);
  image.src=`/video_feed?access_token=${encodeURIComponent(session.access_token)}&t=${Date.now()}`;
};
$('disconnectBtn').onclick=()=>cameraFailed('Camera disconnected. Connect again to resume monitoring.');
async function toggleServerRecording(action){try{await api('/toggle_recording',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action})});}catch{notify('Could not update the robot’s recording status. Check your connection.');}}
function finishRecordingUI(){clearInterval(drawTimer);clearInterval(clockTimer);recordingStream?.getTracks().forEach(track=>track.stop());show('recBadge',false);show('stopBtn',false);$('recordBtn').disabled=!cameraConnected||!!pendingClip;selectFeed(selectedFeed);}
$('recordBtn').onclick=()=>{
  if(!cameraConnected||pendingClip||uploading||recorder?.state==='recording')return;
  try {
    if(!window.MediaRecorder)throw new Error('Recording is not supported in this browser. Try a current Chrome, Edge, or Safari browser.');
    const canvas=$('recordCanvas'),image=$('camStream');canvas.width=image.naturalWidth||640;canvas.height=image.naturalHeight||480;const ctx=canvas.getContext('2d');ctx.drawImage(image,0,0,canvas.width,canvas.height);
    recordingStream=canvas.captureStream(30); const mime=['video/webm;codecs=vp9','video/webm','video/mp4'].find(type=>MediaRecorder.isTypeSupported(type));
    recorder=new MediaRecorder(recordingStream,mime?{mimeType:mime}:{});const chunks=[];
    recorder.ondataavailable=event=>{if(event.data.size)chunks.push(event.data);};
    recorder.onstop=()=>{const blob=new Blob(chunks,{type:recorder.mimeType});finishRecordingUI();if(!blob.size){notify('No video was captured. Reconnect the camera and retry.');return;}pendingClip={blob,name:`bimbot_${Date.now()}_${crypto.randomUUID()}.${blob.type.includes('mp4')?'mp4':'webm'}`};$('recordBtn').disabled=true;show('discardBtn',false);if(!$('saveDialog').open)$('saveDialog').showModal();saveClip();};
    recorder.onerror=()=>{notify('Recording stopped unexpectedly. Any captured footage will be saved.');stopRecording();};
    recorder.start(1000);recordingStarted=Date.now();text('recordTime','00:00');
    drawTimer=setInterval(()=>{try{ctx.drawImage(image,0,0,canvas.width,canvas.height);}catch{stopRecording();notify('Camera frames became unavailable. Saving captured footage.');}},33);
    clockTimer=setInterval(()=>{const seconds=Math.floor((Date.now()-recordingStarted)/1000);text('recordTime',`${Math.floor(seconds/60).toString().padStart(2,'0')}:${(seconds%60).toString().padStart(2,'0')}`);},1000);
    show('recBadge',true);show('recordBtn',false);show('stopBtn',true);toggleServerRecording('start');
  }catch(error){finishRecordingUI();notify(error.message);}
};
function stopRecording(){if(recorder?.state==='recording'){recorder.stop();toggleServerRecording('stop');}}
$('stopBtn').onclick=stopRecording;
async function saveClip(){
  if(!pendingClip||uploading)return;uploading=true;$('closeSave').disabled=true;show('retryUpload',false);show('discardBtn',false);text('saveTitle','Saving your recording');text('uploadStatus','Uploading automatically. Keep this page open until saved.');
  const form=new FormData();form.append('video',pendingClip.blob,pendingClip.name);form.append('filename',pendingClip.name);
  try{const data=await api('/api/upload-to-storage',{method:'POST',body:form,signal:AbortSignal.timeout(120000)});if(!data.success)throw new Error('Cloud save failed.');text('saveTitle','Recording saved');text('uploadStatus','Saved to your cloud library. You can also download a backup.');$('closeSave').disabled=false;await loadRecordings();}
  catch(error){text('saveTitle','Cloud save needs attention');text('uploadStatus',`${error.message} Your clip is still available here. Retry or download a backup before leaving.`);show('retryUpload',true);show('discardBtn',true);}
  finally{uploading=false;}
}
$('retryUpload').onclick=saveClip;
$('downloadBtn').onclick=()=>{if(!pendingClip)return;const url=URL.createObjectURL(pendingClip.blob),a=element('a');a.href=url;a.download=pendingClip.name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
function closeSave(){pendingClip=null;$('saveDialog').close();$('recordBtn').disabled=!cameraConnected;}
$('closeSave').onclick=closeSave;$('discardBtn').onclick=()=>{if(confirm('Discard this unsaved recording? Download a backup first if you need it.'))closeSave();};
$('saveDialog').addEventListener('cancel',event=>{if(uploading||$('closeSave').disabled)event.preventDefault();else closeSave();});
window.addEventListener('beforeunload',event=>{if(recorder?.state==='recording'||pendingClip||uploading){event.preventDefault();event.returnValue='';}});
$('logoutBtn').onclick=async()=>{if(recorder?.state==='recording'||pendingClip||uploading){notify('Finish recording and save or download your clip before signing out.');return;}await client.auth.signOut();window.location.assign('/login');};
let missionCommandPending = false;
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
async function refreshAll(){ $('refreshBtn').disabled=true; await Promise.allSettled([fetchSensors(),fetchDetections(),fetchDevices(),fetchHistory(),fetchMission(),fetchSurvivorEvents()]);$('refreshBtn').disabled=false; }
$('refreshBtn').onclick=refreshAll;
function poll(fn,interval){const run=async()=>{if(!session)return;await fn();setTimeout(run,interval);};setTimeout(run,interval);}
client.auth.onAuthStateChange((_event,newSession)=>{session=newSession;if(!session)window.location.assign('/login');});
(async()=>{try{const result=await client.auth.getSession();session=result.data.session;if(!session){window.location.assign('/login');return;}text('accountEmail',session.user.email||'Signed in');await Promise.allSettled([refreshAll(),loadRecordings()]);poll(fetchSensors,2000);poll(fetchDetections,1000);poll(fetchDevices,10000);poll(fetchHistory,10000);poll(fetchMission,2000);poll(fetchSurvivorEvents,10000);setInterval(()=>{if(lastSensorAt&&Date.now()/1000-lastSensorAt>10)sensorUnavailable(`Last reading: ${dateTime(lastSensorAt)}. Waiting for fresh data.`,'Stale');if(lastDetectionAt&&Date.now()/1000-lastDetectionAt>=10){renderSurvivors([],false);text('survivorCount','—');text('survivorConf','—');text('detectionState','Stale');text('survivorHint','Detection updates stopped. Check the camera connection.');$('survivorCard').classList.remove('is-alert');}},1000);}catch{notify('Could not initialize the dashboard. Reload the page to retry.');}})();
