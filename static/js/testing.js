'use strict';
const $=id=>document.getElementById(id);
let testingSession=null,lastReadiness=null;
const diagnosticPlayers=[];
function stopDiagnosticCameras(){
  diagnosticPlayers.splice(0).forEach(player=>player.stop());
  if($('testingStartCameras'))$('testingStartCameras').disabled=false;
  if($('testingStopCameras'))$('testingStopCameras').disabled=true;
  if($('testingMainCameraState'))$('testingMainCameraState').textContent='Off';
  if($('testingNightCameraState'))$('testingNightCameraState').textContent='Off';
}
if($('testingStartCameras'))$('testingStartCameras').onclick=()=>{
  if(!testingSession){$('testingDiagnosticResult').textContent='Sign in online first, then repeat on ESP32_CAM.';return;}
  stopDiagnosticCameras();
  $('testingStartCameras').disabled=true;$('testingStopCameras').disabled=false;
  for(const [source,id,state] of [['main','testingMainCamera','testingMainCameraState'],['nightvision','testingNightCamera','testingNightCameraState']]){
    const canvas=$(id);$(state).textContent='Connecting…';
    canvas.onload=()=>{$(state).textContent='Live · compare the image with your hand movement';};
    canvas.onerror=()=>{$(state).textContent='No fresh video. Save a snapshot to record the failure.';};
    canvas.addEventListener('waiting',()=>{$(state).textContent='No fresh image. Waiting for this camera to resume.';});
    const profile=JSON.parse(document.getElementById('bim-monitoring-profile')?.textContent||'{}');
    const player=new window.BIMLiveFramePlayer(canvas,{source,minIntervalMs:profile.video_interval_ms??167,backgroundIntervalMs:profile.background_video_interval_ms??1000,retryIntervalMs:profile.retry_interval_ms??500,getHeaders:()=>testingSession?.access_token?{Authorization:`Bearer ${testingSession.access_token}`}:{},onUnauthorized:()=>{stopDiagnosticCameras();$('testingDiagnosticResult').textContent='Session expired. Sign in online before repeating.';}});
    diagnosticPlayers.push(player);player.start();
  }
};
if($('testingStopCameras'))$('testingStopCameras').onclick=stopDiagnosticCameras;
window.addEventListener('pagehide',stopDiagnosticCameras);
document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='hidden')stopDiagnosticCameras();});
window.BIM_AUTH.auth.getSession().then(result=>{testingSession=result.data.session;checkDashboardRecording();$('testingSession').textContent=testingSession?'Signed in. Readiness checks do not start devices.':'Sign in with Google while online before live readiness checks.';}).catch(()=>{$('testingSession').textContent='Sign-in status unavailable. You can still read these instructions.';});
const stages=[...document.querySelectorAll('.test-step')];
for(const stage of stages){
  const item=document.createElement('div');item.className='testing-outcome';item.dataset.step=stage.dataset.step;
  const title=document.createElement('h3');title.textContent=stage.querySelector('h2').textContent;
  const label=document.createElement('label');label.textContent='Your result';
  const select=document.createElement('select');select.setAttribute('aria-label',`${title.textContent} result`);
  for(const [value,text] of [['untested','Not tested'],['pass','Observed as expected'],['fail','Did not work as expected'],['unclear','Unclear / needs another check']])select.add(new Option(text,value));
  const note=document.createElement('label');note.textContent='What happened (optional)';const textarea=document.createElement('textarea');textarea.maxLength=1500;textarea.rows=2;note.append(textarea);
  label.append(select);item.append(title,label,note);$('testingOutcomes').append(item);
}
async function testingApi(path,options={}){
  const headers=testingSession?.access_token?{Authorization:`Bearer ${testingSession.access_token}`}:{ };
  const response=await fetch(path,{...options,headers,credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(5000)});
  if(!response.ok)throw new Error(response.status===401?'Sign in required':'Unavailable');
  return response.json();
}
async function checkDashboardRecording(){
  if(!$('testingRecordingState')||!testingSession)return;
  try{
    const state=await testingApi('/api/system-check/recording');
    $('testingRecordingState').textContent=state.running?`Recording normal dashboard: ${state.samples} samples so far. Keep the dashboard visible for the full minute.`:state.saved?`Saved locally: ${state.samples} normal-dashboard samples. Return to chat for analysis.`:state.error||'No dashboard recording saved yet.';
    if(state.running)setTimeout(checkDashboardRecording,2000);
  }catch{$('testingRecordingState').textContent='Sign in before starting/checking the dashboard recording.';}
}
if($('testingRecordDashboard'))$('testingRecordDashboard').onclick=async()=>{
  $('testingRecordDashboard').disabled=true;
  try{
    stopDiagnosticCameras();
    await testingApi('/api/system-check/recording',{method:'POST'});
    location.assign('/?view=main#monitor');
  }catch(error){$('testingRecordingState').textContent=`Not started: ${error.message}`;$('testingRecordDashboard').disabled=false;}
};
window.addEventListener('pageshow',event=>{if(event.persisted)checkDashboardRecording();});
$('testingSaveDiagnostics').onclick=async()=>{
  $('testingSaveDiagnostics').disabled=true;
  $('testingDiagnosticResult').textContent='Saving current connection and timing information…';
  try{
    const data=await testingApi('/api/system-check',{method:'POST'}),report=data.report;
    if(!data.saved||!report)throw new Error('Snapshot unavailable');
    $('testingDiagnosticResult').textContent=`Saved locally. Mac IP: ${report.network.ipv4||'unavailable'}; robot subnet: ${report.network.robot_subnet?'yes':'no'}. DHT: ${report.sensor.fresh?'fresh':'unavailable'}; thermal: ${report.thermal.fresh?'fresh':'unavailable'}; Main: ${report.cameras.main.connected?'connected':'not connected'}; Night: ${report.cameras.nightvision.connected?'connected':'not connected'}. You can return to chat after saving.`;
  }catch(error){$('testingDiagnosticResult').textContent=`Not saved: ${error.message}. Sign in online first, then repeat on ESP32_CAM.`;}
  finally{$('testingSaveDiagnostics').disabled=false;}
};
$('testingReadiness').onclick=async()=>{
  $('testingReadiness').disabled=true;$('testingReadings').replaceChildren();
  const checks=[['Camera connection','/api/device-status',d=>d.main_status?.connected?'Main connected; inspect fresh video':'Main not connected. Connect it manually for camera checks.'],['DHT readings','/api/sensor-data',d=>d.fresh?'Fresh sensor readings':'Waiting for fresh readings / robot network'],['Thermal','/api/thermal-data',d=>d.connected?'Connected; inspect changing temperatures':'Waiting for thermal / robot network'],['Sound model','/api/sound-model',d=>d.ready?'Local YAMNet ready; this check did not start a microphone':d.message||'Model not ready']];
  const records=[];
  for(const [name,path,describe] of checks){
    let message;try{message=describe(await testingApi(path));}catch(error){message=error.message;}
    const item=document.createElement('li');item.textContent=`${name}: ${message}`;$('testingReadings').append(item);records.push({name,message});
  }
  lastReadiness={at:new Date().toISOString(),records};$('testingSession').textContent='Readiness checked now; this is not continuous monitoring or a completed live test.';$('testingReadiness').disabled=false;
};
$('testingDownload').onclick=()=>{
  const results=[...document.querySelectorAll('.testing-outcome')].map(item=>({step:item.dataset.step,result:item.querySelector('select').value,notes:item.querySelector('textarea').value}));
  const data={saved_at:new Date().toISOString(),note:'Operator-entered stationary test observations. Not model accuracy or proof of medical condition. Untested items remain untested.',movement_on_hold:true,readiness:lastReadiness,results};
  const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'})),link=document.createElement('a');link.href=url;link.download=`bimbot_stationary_tests_${Date.now()}.json`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
};
