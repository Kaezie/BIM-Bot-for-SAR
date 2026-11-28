const {chromium}=require('playwright');
const {cameraFrameFixture}=require('./camera_frame_fixture.cjs');
const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
(async()=>{
const browser=await chromium.launch({headless:true,...(process.env.CHROME_PATH ? {executablePath:process.env.CHROME_PATH} : {})});const page=await browser.newPage({viewport:{width:1440,height:1050},timezoneId:'America/Los_Angeles'});const errors=[];page.on('pageerror',error=>errors.push(error.message));
// Realistic, even frame dimensions are required by the browser's H.264 encoder.
const cameraFrame=Buffer.from(await page.evaluate(()=>{const canvas=document.createElement('canvas');canvas.width=640;canvas.height=480;const ctx=canvas.getContext('2d');ctx.fillStyle='#456';ctx.fillRect(0,0,640,480);return canvas.toDataURL('image/jpeg',0.8).split(',')[1];}),'base64');
let stale=false,failed=false,uploads=0,mission=null,review=null,reportDownloads=0,nightEnabled=false,nightLive=true,nightUpload=false,thermalEnabled=false,thermalFresh=true,mainRequests=0,nightRequests=0,nightStreamFailed=false;
let savedReports=[], screenLocal=false;
const reportRequests=[];
let loseReportResponse=false;
let trackNumber=7,motionObserved=null,nightFresh=true,nightWrongSource=false;
let lowLight=false, severeHeat=false, recentPerson=false, detectionSlowdown='ready';
let postureScene=false;
let heatAssessment=null;
const lightCommands=[];
let nightConsciousness='Unknown';
const cameraFrames=cameraFrameFixture(cameraFrame,{fail:source=>source==='nightvision'&&nightStreamFailed,onOpen:source=>{if(source==='main')mainRequests++;else nightRequests++;}});
const localClips=[{id:'fixture',name:'bimbot_main_fixture.mp4',size:102400,created_at:new Date().toISOString(),source:'main',sync_state:'pending',download_url:'/api/local-recordings/fixture/file'}];
let capturedMP4;const uploadNames=[];
await page.addInitScript(() => {
  let timer;
  window.displayFixture = {options:null, sawAlert:false};
  Object.defineProperty(navigator.mediaDevices, 'getDisplayMedia', {value:async options => {
    window.displayFixture.options = options;
    const canvas = document.createElement('canvas'); canvas.width = 640; canvas.height = 480;
    const ctx = canvas.getContext('2d');
    const draw = () => {
      const alert = document.querySelector('#personNotice:not([hidden])');
      ctx.fillStyle = alert ? '#9a211f' : '#103545';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      if (alert) {
        window.displayFixture.sawAlert = true;
        ctx.fillStyle = '#fff'; ctx.font = '20px sans-serif'; ctx.fillText(alert.innerText.split('\n')[0], 16, 32);
      }
    };
    draw(); timer = setInterval(draw, 50);
    const stream = canvas.captureStream(20);
    const [track] = stream.getVideoTracks();
    window.displayFixture.end = () => { clearInterval(timer); track.dispatchEvent(new Event('ended')); };
    return stream;
  }});
});
await page.route('**/fonts.googleapis.com/**',route=>route.abort());
await page.route('**/static/js/auth.js',route=>route.fulfill({contentType:'application/javascript',body:`window.BIM_AUTH={auth:{getSession:async()=>({data:{session:{local:true,access_token:null,user:{email:'rescue@example.test'}}}}),onAuthStateChange:()=>{},signOut:async()=>({error:null})}};`}));
await page.route('**/api/**',route=>{
if(cameraFrames.matches(route))return cameraFrames.handle(route);
const url=new URL(route.request().url()),now=Date.now()/1000;let data={};
if(url.pathname==='/api/sensor-data')data={fresh:!stale,updated_at:now-(stale?30:0),temperature:36,humidity:72,heat_index:43,risk_level:severeHeat?'Severe Risk':'Moderate Risk',interpretation:'Heat stress likely',method:'threshold',confidence:.8,probabilities:{low:.1,moderate:.8,severe:.1},...(heatAssessment?{heat_alert:heatAssessment}:{})};
if(url.pathname==='/api/survivors')data={available:!stale,updated_at:now-(stale?30:0),survivors_found:2,low_light:lowLight,detection_slowdown:detectionSlowdown,recent_observation:recentPerson?{count:2,seen_at:now-(stale?3:0),cues:['Lying posture and little image motion.']}:null,detections:[{confidence:.94,age:'Adult',consciousness:motionObserved===true?'Conscious':'Unknown',injury:'Unknown',trapped:'Unknown',pose:'upright',thermal_alive:'No thermal camera',thermal_injury:'No thermal camera',track_number:trackNumber,track_id:`fixture-${trackNumber}`,pose_matched:true,motion_observed:motionObserved}]};
if(url.pathname==='/api/survivors') {
  data.light_state=stale?null:lowLight?'dark':'bright';
  if(postureScene){
    const [person]=data.detections;
    data.detections=['standing','standing','fallen'].map((posture,index)=>({...person,posture,track_number:20+index,track_id:`posture-${index}`}));
    data.survivors_found=data.detections.length;
  }
}
if(url.pathname==='/api/person-consciousness'){
  const report=route.request().postDataJSON();
  assert.equal(report.source,'nightvision');
  assert.equal(report.track_id,'fixture-night-3');
  nightConsciousness=report.status;
  data={consciousness:nightConsciousness};
}
if(url.pathname==='/api/mission')data={mission,can_start:!mission||mission.state==='stopped',control_configured:true,robot:{fresh:true,navigation_ready:true,simulated:true}};
if(url.pathname==='/api/mission/start'){const payload=route.request().postDataJSON();mission={id:'mission-fixture',state:'searching',area_label:payload.area_label};data={mission};}
if(url.pathname==='/api/mission/stop'){mission.state='stopped';data={mission};}
if(url.pathname==='/api/survivor-events')data={events:mission?[{id:'event-fixture',at:now-30,evidence:{detections:[{confidence:.9,age:'Adult',consciousness:'Conscious',injury:'No Visible Injury Indicators',trapped:'Free',pose:'upright',thermal_alive:'No thermal camera',thermal_injury:'No thermal camera'}],area_label:mission.area_label,environment:{danger_level:'Danger'},observation_position:null},review,reviewed_at:review?now-20:null}]:[]};
if(url.pathname==='/api/survivor-events/event-fixture/review'){review=route.request().postDataJSON();data={review};}
if(url.pathname==='/api/mission-reports') {
  if(route.request().method()==='POST') {
    const request=route.request().postDataJSON(), id=request.save_id;
    reportRequests.push(request);
    assert.match(id,/^[a-f0-9]{32}$/);
    let report=savedReports.find(entry=>entry.id===id);
    if(!report){
      report={id,name:`BIMBot_Report_${id}.json`,created_at:new Date().toISOString(),sync_state:'pending',message:'Saved on this laptop. Waiting to upload to Supabase.',download_url:`/api/mission-reports/${id}/file`};
      savedReports.push(report);
    }
    if(loseReportResponse){
      loseReportResponse=false;
      return route.fulfill({status:503,json:{error:'Report confirmation unavailable.'}});
    }
    data={report};
  } else data={reports:savedReports,pending_count:savedReports.length};
}
if(/^\/api\/mission-reports\/[a-f0-9]{32}\/file$/.test(url.pathname)) {
  reportDownloads++;
  return route.fulfill({contentType:'application/json',headers:{'Content-Disposition':`attachment; filename="${savedReports[0].name}"`},body:JSON.stringify({mission,requires_human_verification:true,events:[]})});
}
if(url.pathname==='/api/device-status')data={nightvision:nightEnabled,nightvision_status:{connected:nightLive,detection_enabled:true,person_analysis_enabled:true,detected_at:now-(nightFresh?0:3),detections_available:nightEnabled&&nightLive&&nightFresh,detections:[{source:nightWrongSource?'main':'nightvision',confidence:.8,age:'Child',age_years:null,consciousness:nightConsciousness,consciousness_method:nightConsciousness==='Unknown'?'unverified':'operator_reported',injury:'Unknown',trapped:'Unknown',pose:'upright',track_number:3,track_id:'fixture-night-3',motion_observed:false,immobility_seconds:4.2,gesture:'Possible waving/help gesture',gesture_state:'possible_wave'}],message:nightStreamFailed?'Select this camera to connect.':nightLive?'Select this tab to connect.':'Night camera offline.'}};
if(url.pathname==='/api/nightvision/light'&&route.request().method()==='POST')lightCommands.push(route.request().postDataJSON().enabled);
if(url.pathname==='/api/nightvision/light')data={supported:true,available:true,firmware:'bimbot-nightvision/2',illumination:{enabled:route.request().method()==='POST'?route.request().postDataJSON().enabled:false,brightness:32,lease_ms:15000}};
if(url.pathname==='/api/sound-data')data={connected:false};
if(url.pathname==='/api/thermal-data')data=thermalEnabled?{configured:true,connected:true,simulated:true,updated_at:now-(thermalFresh?0:30),grid:Array.from({length:24},()=>Array(32).fill(24)),min_temp:24,max_temp:38.5}:{connected:false,configured:false};
if(url.pathname==='/api/history')data={alerts:[{at:now,kind:'detection',message:'2 possible survivors detected. Verify in the feed.'}],samples:Array.from({length:20},(_,i)=>({at:now-60+i*3,temperature:30+i*.3,humidity:70+i*.1,heat_index:32+i*.4}))};
if(url.pathname==='/api/recordings')data={recordings:[{name:'bimbot_mission.webm',size:102400,created_at:new Date().toISOString()}],has_more:false};
if(url.pathname==='/api/local-recordings'&&route.request().method()==='GET')data={recordings:localClips,has_more:false,pending_count:localClips.length};
if(url.pathname==='/api/local-recordings'&&route.request().method()==='POST'){
  uploads++;const body=route.request().postDataBuffer();
  const filename=/name="filename"\r\n\r\n([^\r\n]+)/.exec(body.toString('latin1'))?.[1];
  assert.match(filename,/^BIMBot_(Main|NightVision|Screen)_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_[a-f0-9]{8}\.mp4$/);
  assert(body.includes(Buffer.from(`filename="${filename}"`)));uploadNames.push(filename);
  const source=filename.startsWith('BIMBot_Screen_')?'screen':filename.startsWith('BIMBot_NightVision_')?'nightvision':'main';if(source==='nightvision')nightUpload=true;if(source==='screen')screenLocal=true;
  if(failed)return route.fulfill({status:500,contentType:'application/json',body:JSON.stringify({error:'Local disk unavailable'})});
  const at=body.indexOf(Buffer.from('ftyp'));assert(at>=4);capturedMP4=body.subarray(at-4,body.indexOf(Buffer.from('\r\n--'),at));
  const id='saved-'+uploads;
  const clip={id,name:filename,source,size:capturedMP4.length,created_at:new Date().toISOString(),sync_state:source==='screen'?'local_only':'pending',download_url:`/api/local-recordings/${id}/file`};
  localClips.unshift(clip);data={success:true,recording:clip};
}
if(/^\/api\/local-recordings\/[^/]+\/file$/.test(url.pathname))return route.fulfill({contentType:'video/mp4',headers:{'Content-Disposition':`attachment; filename="bimbot_main_saved.mp4"`},body:capturedMP4});
return route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
});
await page.route('**/toggle_recording',route=>route.fulfill({contentType:'application/json',body:'{"is_recording":true}'}));
await page.goto((process.env.UI_TEST_URL || 'http://127.0.0.1:5051/'));await page.waitForFunction(()=>document.getElementById('survivorCount').textContent==='2');
const midnightNames=await page.evaluate(()=>['main','nightvision'].map(source=>recordingFilename(source,Date.parse('2026-11-12T16:00:05Z'))));
assert.match(midnightNames[0],/^BIMBot_Main_2026-11-13_00-00-05_[a-f0-9]{8}\.mp4$/);
assert.match(midnightNames[1],/^BIMBot_NightVision_2026-11-13_00-00-05_[a-f0-9]{8}\.mp4$/);
assert((await page.locator('#survivorCard').boundingBox()).height < 160, 'Survivor telemetry must remain compact');
assert.equal(await page.locator('#availability-thermal').textContent(),'Not installed');assert.equal(await page.locator('#recordingList li').count(),1);
assert.equal(await page.locator('#riskLevel').textContent(),'Moderate Risk');
thermalEnabled=true;await page.locator('#refreshBtn').click();await page.waitForFunction(()=>document.getElementById('mainThermalRange').textContent==='24.0–38.5 °C');
assert(await page.locator('#mainThermalReading').isVisible());assert.match(await page.locator('#mainThermalState').textContent(),/SIMULATED/);assert.equal(await page.locator('#tempDisplay').textContent(),'36.0');
await page.screenshot({path:'/tmp/bimbot-main-thermal.png',fullPage:false});
thermalFresh=false;await page.locator('#refreshBtn').click();await page.waitForFunction(()=>document.getElementById('mainThermalRange').textContent==='—');
assert.equal(await page.locator('#availability-thermal').textContent(),'Waiting');thermalEnabled=false;await page.locator('#refreshBtn').click();

await page.locator('#missionTools > summary').click();
assert.match(await page.locator('#survivorDetailList').textContent(),/Age estimate: Adult/);
assert.match(await page.locator('#survivorDetailList').textContent(),/Pose: upright/);
assert.match(await page.locator('#survivorDetailList h3').textContent(),/Track 7/);
assert.match(await page.locator('#survivorDetailList').textContent(),/Image motion: Unknown/);
assert.match(await page.locator('#survivorDetailList h3').getAttribute('title'),/Temporary camera track/);
trackNumber=12;motionObserved=true;await page.locator('#refreshBtn').click();
await page.waitForFunction(()=>document.querySelector('#survivorDetailList h3').textContent.includes('Track 12'));
assert.match(await page.locator('#survivorDetailList').textContent(),/Image motion: Region changed/);
await page.locator('#missionTools > summary').click();
assert.match(await page.locator('#mlAssessment').textContent(),/SAR threshold rules/);
await page.locator('#missionTools > summary').click();
await page.locator('#missionArea').fill('Simulated hallway');await page.locator('#missionStart').click();
await page.waitForFunction(()=>document.getElementById('missionState').textContent==='searching');
assert(await page.locator('#missionArea').isDisabled());assert(await page.locator('#missionStop').isEnabled());
await page.locator('#refreshBtn').click();await page.waitForFunction(()=>document.querySelectorAll('.review-form').length===1);
assert.match(await page.locator('#survivorEventList').textContent(),/Coordinates unavailable/);
assert.match(await page.locator('#survivorEventList').textContent(),/Pose: upright/);
assert.match(await page.locator('#communication').textContent(),/Start two-way audio/);
assert.match(await page.locator('#communication').textContent(),/Live test required/);
await page.locator('[name=notes]').fill('Existing observation.');
await page.getByRole('button',{name:'Add communication note'}).click();
assert.match(await page.locator('[name=notes]').inputValue(),/^Existing observation\.\n\nCommunication observation/);
assert.match(await page.locator('[name=notes]').inputValue(),/unknown unless confirmed/);
await page.getByRole('button',{name:'Save operator review'}).click();
await page.waitForFunction(()=>document.getElementById('notice').textContent==='Operator review saved.');
assert.match(review.notes,/Observed gesture or words/);
await page.locator('[name=notes]').fill('x'.repeat(2000));
await page.getByRole('button',{name:'Add communication note'}).click();
assert.equal((await page.locator('[name=notes]').inputValue()).length,2000);
assert.match(await page.locator('#notice').textContent(),/Review notes are full/);
await page.locator('[name=verification]').selectOption('confirmed');await page.locator('[name=age_group]').selectOption('adult');await page.locator('[name=notes]').fill('Confirmed in test fixture.');
await page.getByRole('button',{name:'Save operator review'}).click();await page.waitForFunction(()=>document.getElementById('notice').textContent==='Operator review saved.');
assert.equal(review.assessment.age_group,'adult');assert.equal(review.assessment.consciousness,'unknown');
assert(await page.locator('#mission #survivorEventList').isVisible());
await page.locator('#mission #saveMissionReport').click();
await page.waitForFunction(()=>document.getElementById('missionReportStatus').textContent.includes('Waiting to upload'));
assert.equal(reportRequests[0].excavation_assessment,null);
const downloadPromise=page.waitForEvent('download');
await page.locator('#mission #savedMissionReports a').click();
const download=await downloadPromise;
assert.match(download.suggestedFilename(),/^BIMBot_Report_/);
assert.equal(reportDownloads,1);
await page.locator('#missionStop').click();await page.waitForFunction(()=>document.getElementById('missionState').textContent==='stopped');
assert(await page.locator('#trendChart').isVisible());await page.waitForTimeout(500);await page.screenshot({path:'/tmp/bimbot-desktop.png',fullPage:true});
for(const width of [320,390,768,1440]){
await page.setViewportSize({width,height:900});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`Overflow at ${width}`);
const summaryBox=await page.locator('#survivorCard').boundingBox(),feedBox=await page.locator('.feed-stage').boundingBox();
assert(summaryBox.y+summaryBox.height<=feedBox.y,`Survivor summary must not cover the camera at ${width}px`);
if(width===390){await page.evaluate(()=>scrollTo(0,0));await page.screenshot({path:'/tmp/bimbot-survivor-mobile.png',fullPage:false});}
}
await page.setViewportSize({width:390,height:844});await page.waitForTimeout(500);await page.screenshot({path:'/tmp/bimbot-mobile.png',fullPage:false});
await page.getByRole('tab',{name:/Thermal/}).click();assert(await page.locator('#panel-thermal').isVisible());assert(await page.locator('#connectBtn').isHidden());
await page.getByRole('tab',{name:/Main camera/}).click();await page.waitForFunction(()=>!document.getElementById('recordBtn').disabled);
assert.equal(mainRequests,1,'Explicit main-tab selection must connect without another Connect click');
await page.locator('#disconnectBtn').click();
await page.locator('#refreshBtn').click();await page.waitForFunction(()=>!document.getElementById('refreshBtn').disabled);
assert.equal(await page.locator('#camStream').getAttribute('data-viewer'),null,'Refresh must respect a manual camera disconnect');
assert.equal(mainRequests,1,'Status refresh must not create a replacement main stream');
await page.getByRole('tab',{name:/Main camera/}).click();await page.waitForFunction(()=>!document.getElementById('recordBtn').disabled);
assert.equal(mainRequests,2,'Explicit main-tab selection must reconnect after manual disconnect');
await page.getByRole('tab',{name:/Thermal/}).click();
await page.locator('#camStream').evaluate(image=>image.dispatchEvent(new Event('error')));
assert.equal(await page.locator('#camStream').getAttribute('data-viewer'),null);
await page.getByRole('tab',{name:/Thermal/}).focus();await page.keyboard.press('Home');
await page.waitForFunction(()=>!document.getElementById('recordBtn').disabled);
assert.equal(mainRequests,3,'Keyboard selection must reconnect the main camera after a failure while away');
await page.evaluate(()=>{window.originalTypeSupported=MediaRecorder.isTypeSupported;MediaRecorder.isTypeSupported=()=>false;});
await page.locator('#recordBtn').click();assert.match(await page.locator('#notice').textContent(),/cannot record MP4/);assert(await page.locator('#recordBtn').isEnabled());assert.equal(uploads,0);
await page.evaluate(()=>{MediaRecorder.isTypeSupported=window.originalTypeSupported;});
const beforeMainStart=await page.evaluate(()=>Date.now());
await page.locator('#recordBtn').click();await page.waitForFunction(()=>!document.getElementById('stopBtn').hidden);
const afterMainStart=await page.evaluate(()=>Date.now());
const formatStart=time=>new Date(time+8*3600000).toISOString().slice(0,19).replace('T','_').replaceAll(':','-');
await page.waitForTimeout(1100);await page.locator('#stopBtn').click();await page.waitForFunction(()=>document.getElementById('saveTitle').textContent==='Recording saved on this laptop');assert.equal(uploads,1);
const mainStart=uploadNames[0].slice('BIMBot_Main_'.length,'BIMBot_Main_'.length+19);
assert(mainStart>=formatStart(beforeMainStart)&&mainStart<=formatStart(afterMainStart),'Filename must use recording start time');
const backupPromise=page.waitForEvent('download');await page.locator('#downloadBtn').click();const backup=await backupPromise;
assert.equal(backup.suggestedFilename(),uploadNames[0]);
const backupBytes=await fs.readFile(await backup.path());assert.equal(backupBytes.toString('ascii',4,8),'ftyp','Backup must contain an MP4 container, not renamed WebM');
await page.locator('#closeSave').click();
failed=true;await page.locator('#recordBtn').click();await page.waitForTimeout(1100);await page.locator('#stopBtn').click();await page.waitForFunction(()=>document.getElementById('saveTitle').textContent==='Local save needs attention');assert(await page.locator('#retryUpload').isVisible());assert(await page.locator('#closeSave').isDisabled());
await page.keyboard.press('Escape');assert(await page.locator('#saveDialog').isVisible());
const offlineBackupPromise=page.waitForEvent('download');await page.locator('#downloadBtn').click();const offlineBackup=await offlineBackupPromise;assert.match(offlineBackup.suggestedFilename(),/\.mp4$/);assert.equal((await fs.readFile(await offlineBackup.path())).toString('ascii',4,8),'ftyp');
failed=false;await page.locator('#retryUpload').click();await page.waitForFunction(()=>document.getElementById('saveTitle').textContent==='Recording saved on this laptop');
assert.equal(uploadNames[1],uploadNames[2],'Retry must preserve the original filename');assert.equal(offlineBackup.suggestedFilename(),uploadNames[2]);
await page.locator('#closeSave').click();
nightEnabled=true;await page.locator('#refreshBtn').click();
const mainSourceBeforeNight=await page.locator('#camStream').getAttribute('data-viewer'),mainRequestsBeforeNight=mainRequests;
postureScene=true;await page.evaluate(()=>refreshAll());
await page.waitForFunction(()=>document.getElementById('mainPosture-standing').textContent==='2');
for(const [id,expected] of [['survivorCount','3'],['mainPosture-standing','2'],['mainPosture-fallen','1'],['mainPosture-unknown','0']]) {
  assert.equal(await page.locator(`#${id}`).textContent(),expected);
}
assert.match(await page.locator('#survivorDetailList').textContent(),/Posture: Fallen figure/);
postureScene=false;
lowLight=true;severeHeat=true;recentPerson=true;
detectionSlowdown='slowing';
heatAssessment={label:'Extreme danger',severity:'alert',guidance:'Notify the rescue lead and follow site emergency procedures.'};
await page.locator('#refreshBtn').click();
await page.waitForFunction(()=>document.getElementById('monitor').dataset.activeFeed==='nightvision');
await page.waitForFunction(()=>document.getElementById('nvLightStatus').textContent==='White light: on');
assert.equal(lightCommands[0],true,'Confirmed low light must open Night and request the LED without an operator click');
assert(await page.locator('#heatNotice').isVisible());
assert.match(await page.locator('#heatNoticeTitle').textContent(),/Extreme danger/);
await page.locator('#emergencyResponseButton').click();
assert(await page.locator('#emergencyResponse').isVisible());
await page.locator('#emergencyResponseButton').click();
assert.match(await page.locator('#personNoticeTitle').textContent(), /Survivor alert/);
assert.match(await page.locator('#personNoticePause').textContent(), /acknowledged a slowdown/);
await page.getByRole('button',{name:'Dismiss Main camera notification'}).click();
await page.evaluate(()=>refreshAll());
assert(await page.locator('#personNotice').isHidden(),'A dismissed sighting stays dismissed while the same track remains live');
await page.locator('#tab-main').click();
await page.waitForFunction(()=>document.getElementById('nvLightStatus').textContent==='White light: off');
await page.evaluate(()=>refreshAll());
assert.equal(await page.locator('#monitor').getAttribute('data-active-feed'),'main','Returning to Main must override a continuing dark episode');
lowLight=false;
await page.waitForFunction(()=>!autoNightHandled);
lowLight=true;
await page.evaluate(()=>refreshAll());
await page.waitForFunction(()=>document.getElementById('tab-nightvision').getAttribute('aria-selected')==='true');
await page.waitForFunction(()=>document.getElementById('nvLightStatus').textContent==='White light: on');
assert.equal(lightCommands.at(-1),true,'A second dark episode must auto-open Night after stable bright Main frames');
await page.waitForFunction(()=>!document.getElementById('recordBtn').disabled);
lowLight=false;recentPerson=false;
detectionSlowdown='ready';
assert.equal(await page.locator('#camStream').getAttribute('data-viewer'),mainSourceBeforeNight,'Original camera remains subscribed during night viewing');
await page.waitForFunction(()=>document.getElementById('nvDetectionStatus').textContent.includes('1 possible person'));
assert.equal(await page.locator('#survivorCount').textContent(),'2','Night detections must not inflate main-camera counts');
await page.locator('#refreshBtn').click();
await page.waitForFunction(()=>document.getElementById('nightSurvivorDetailsState').textContent==='Live · Night camera');
assert.match(await page.locator('#nightPersonNoticeTitle').textContent(),/Survivor alert.*Night Vision/);
assert.match(await page.locator('#nightPersonNoticeText').textContent(),/1 possible person.*Little image motion/);
await page.locator('#personNotice').waitFor({state:'hidden'});
await page.locator('#emergencyResponseButton').click();
await page.locator('#emergencyResponse').waitFor({state:'visible'});
for(const [width,height] of [[1366,960],[390,844]]){
  await page.setViewportSize({width,height});
  const heat=await page.locator('#heatNotice').boundingBox(),link=await page.locator('#nvDetailsLink').boundingBox();
  assert(heat.y>=link.y+link.height || heat.y+heat.height<=link.y ||
    heat.x>=link.x+link.width || heat.x+heat.width<=link.x,'The expanded heat popup must leave Night person details clear');
  await page.locator('#nvDetailsLink').click();
  assert(await page.locator('#nightSurvivorDetails').isVisible());
  assert.equal(await page.locator('#missionTools').getAttribute('open'),'');
  await page.evaluate(()=>history.replaceState(null,'',location.pathname));
}
await page.setViewportSize({width:1440,height:1050});
severeHeat=false;heatAssessment=null;await page.locator('#refreshBtn').click();
await page.locator('#heatNotice').waitFor({state:'hidden'});
assert.match(await page.locator('#nightSurvivorDetailList').textContent(),/Track 3/);
assert.match(await page.locator('#nightSurvivorDetailList').textContent(),/Age estimate: Child/);
assert.match(await page.locator('#nightSurvivorDetailList').textContent(),/Little image motion observed/);
assert.match(await page.locator('#nightSurvivorDetailList').textContent(),/Help gesture: Possible waving/);
assert.match(await page.locator('#nightSurvivorDetailList').textContent(),/Image inactivity: 4.2 s/);
assert.match(await page.locator('#survivorDetailList').textContent(),/Age estimate: Adult/);
assert.doesNotMatch(await page.locator('#survivorDetailList').textContent(),/Track 3/);
assert.match(await page.locator('#nightSurvivorDetails').textContent(),/Age group is a size-based estimate/);
await page.locator('#nightSurvivorDetails').getByRole('button',{name:'Unconscious',exact:true}).click();
await page.waitForFunction(()=>document.getElementById('nightSurvivorDetails').textContent.includes('Unconscious · Operator reported'));
await page.locator('#nightSurvivorDetails').getByRole('button',{name:'Clear report'}).click();
await page.waitForFunction(()=>!document.getElementById('nightSurvivorDetails').textContent.includes('Operator reported'));
assert.doesNotMatch(await page.locator('#nightSurvivorDetails').textContent(), /Unverified/);
for(const width of [320,390,768,1440]){
  await page.setViewportSize({width,height:1050});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`Night details overflow at ${width}`);
}
await page.setViewportSize({width:1440,height:1050});
await page.screenshot({path:'/tmp/bimbot-night-person-details.png',fullPage:false});
nightWrongSource=true;await page.locator('#refreshBtn').click();
await page.waitForFunction(()=>!document.getElementById('nightSurvivorDetailList').textContent.includes('Track 3'));
assert.match(await page.locator('#nightPersonNoticeTitle').textContent(),/Recent observation.*Night Vision/);
assert.match(await page.locator('#nvDetectionStatus').textContent(),/No people detected/);
nightWrongSource=false;nightFresh=false;await page.locator('#refreshBtn').click();
await page.waitForFunction(()=>document.getElementById('nightSurvivorDetailsState').textContent==='Unavailable');
assert.doesNotMatch(await page.locator('#nightSurvivorDetailList').textContent(),/Age estimate: Child/);
await page.locator('#nightPersonNotice').waitFor({state:'hidden',timeout:6500});
nightFresh=true;await page.locator('#refreshBtn').click();
await page.waitForFunction(()=>document.getElementById('nightSurvivorDetailList').textContent.includes('Track 3'));
await page.locator('#missionTools > summary').click();
await page.evaluate(()=>scrollTo(0,0));

await page.evaluate(()=>{window.recordedSources=[];const original=CanvasRenderingContext2D.prototype.drawImage;CanvasRenderingContext2D.prototype.drawImage=function(image,...args){if(this.canvas.id==='recordCanvas')window.recordedSources.push(image.id);return original.call(this,image,...args);};});
await page.screenshot({path:'/tmp/bimbot-nightvision.png',fullPage:false});await page.locator('#recordBtn').click();await page.getByRole('tab',{name:/Main camera/}).click();await page.waitForTimeout(1100);
assert.equal(await page.locator('#camStream').getAttribute('data-viewer'),mainSourceBeforeNight);
assert.equal(mainRequests,mainRequestsBeforeNight,'Returning to a live original camera must reuse its existing stream');
assert((await page.evaluate(()=>window.recordedSources)).every(source=>source==='nvStream'),'Switching tabs must not switch the recording source');
const nightSave=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/local-recordings' && response.request().method()==='POST');nightLive=false;await page.locator('#nvStream').evaluate(image=>image.dispatchEvent(new Event('error')));await nightSave;await page.waitForFunction(()=>document.getElementById('saveTitle').textContent==='Recording saved on this laptop');
assert(nightUpload,'Night recordings must carry a source-labelled filename');assert.equal(uploads,4);await page.locator('#closeSave').click();
nightLive=true;await page.getByRole('tab',{name:/Night vision/}).click();await page.waitForFunction(()=>document.getElementById('availability-nightvision').textContent==='Live',{timeout:15000});
const retainedNight=await page.locator('#nvStream').getAttribute('data-viewer');
await page.getByRole('tab',{name:/Main camera/}).click();
assert.equal(await page.locator('#nvStream').getAttribute('data-viewer'),retainedNight,'Switching away must keep Night connected');
nightStreamFailed=true;nightLive=false;
await page.waitForTimeout(700);await page.locator('#refreshBtn').click();
assert.equal(await page.locator('#nvStream').getAttribute('data-viewer'),retainedNight,'A short fault/status sample must not tear down fresh Night video');
nightStreamFailed=false;nightLive=true;
await page.waitForFunction(()=>document.getElementById('availability-nightvision').textContent==='Live',{timeout:10000});
for(const feed of ['Thermal','Main camera','Night vision'])await page.getByRole('tab',{name:new RegExp(feed)}).click();
assert.equal(await page.locator('#nvStream').getAttribute('data-viewer'),retainedNight);
assert.equal(await page.locator('#camStream').getAttribute('data-viewer'),mainSourceBeforeNight);
assert.equal(mainRequests,mainRequestsBeforeNight);
await page.getByRole('tab',{name:/Main camera/}).click();
stale=true;await page.locator('#refreshBtn').click();await page.waitForFunction(()=>document.getElementById('tempDisplay').textContent==='—'&&document.getElementById('survivorCount').textContent==='—');assert.equal(await page.locator('#survivorCount').textContent(),'—');assert.equal(await page.locator('#riskLevel').textContent(),'Assessment unavailable');assert.equal(await page.locator('#survivorDetailsState').textContent(),'Unavailable');assert.doesNotMatch(await page.locator('#survivorDetailList').textContent(),/Consciousness: Conscious/);
stale=false;recentPerson=true;
await page.locator('#refreshBtn').click();
await page.locator('#personNotice').waitFor({state:'visible'});
await page.locator('#recordScreenBtn').click();
await page.locator('#screenRecordState').waitFor({state:'visible'});
assert.equal(await page.evaluate(()=>window.displayFixture.options.video.displaySurface),'monitor');
assert.equal(await page.evaluate(()=>window.displayFixture.options.audio),false);
await page.evaluate(()=>document.querySelector('#camStream').dispatchEvent(new Event('waiting')));
assert(await page.locator('#screenRecordState').isVisible(),'Camera waiting must not stop screen capture');
await page.waitForFunction(()=>window.displayFixture.sawAlert);
await page.waitForTimeout(1100);
await page.evaluate(()=>window.displayFixture.end());
await page.waitForFunction(()=>document.getElementById('uploadStatus').textContent==='Screen capture is saved on this laptop.');
assert(screenLocal);
assert.match(uploadNames.at(-1),/^BIMBot_Screen_/);
await page.locator('#closeSave').click();
for(const [label,severity,guidance] of [
  ['Below heat warning','info','Confirm site conditions with the rescue lead before continuing the search.'],
  ['Caution','warning','Review heat precautions with the rescue lead before continuing.'],
  ['Extreme caution','warning','Notify the rescue lead and review heat precautions before advancing.'],
  ['Danger','alert','Pause the search and notify the rescue lead.'],
  ['Extreme danger','alert','Notify the rescue lead and follow site emergency procedures.']
]){
  heatAssessment={label,severity,guidance};
  await page.evaluate(()=>refreshAll());
  assert.equal(await page.locator('#heatNoticeTitle').textContent(),`Heat · ${label}`);
  assert.equal(await page.locator('#riskLevel').textContent(),label);
  assert.equal(await page.locator('#heatNoticeGuidance').textContent(),guidance);
  assert.equal(await page.locator('#heatNotice').getAttribute('data-severity'),severity);
  assert.equal(await page.locator('#emergencyResponseButton').isVisible(),severity==='alert');
  assert.equal(await page.locator('#heatNotice').isVisible(),severity==='alert'||label==='Extreme caution');
}
await page.locator('#emergencyResponseButton').click();
stale=true;await page.evaluate(()=>refreshAll());
assert.match(await page.locator('#heatNoticeTitle').textContent(),/Reading unavailable/);
assert(await page.locator('#emergencyResponse').isHidden());
assert(await page.locator('#emergencyResponseButton').isHidden());
assert.match(await page.locator('#excavationNoticeTitle').textContent(),/Not assessed/);
assert(await page.locator('#excavationNotice').isHidden());
await page.locator('#cameraExcavationStatus').click();
const recordDecision=page.getByRole('button',{name:'Record excavation decision'});
await page.locator('#excavationArea').fill('Course A, east bay');
await page.locator('#excavationLead').fill('Rescue Lead 1');
await page.locator('#excavationDecision').selectOption('cleared');
await recordDecision.click();
assert.match(await page.locator('#excavationNoticeTitle').textContent(),/Clearance reported/);
assert.match(await page.locator('#excavationNoticeDetails').textContent(),/Course A, east bay.*Rescue Lead 1.*Recorded/);
assert.match(await page.locator('#cameraExcavationStatus').textContent(),/Clearance reported.*Course A, east bay/);
assert.match(await page.locator('#heatNoticeTitle').textContent(),/Reading unavailable/);
loseReportResponse=true;
await page.locator('#saveMissionReport').click();
await page.waitForFunction(()=>document.getElementById('missionReportStatus').textContent.includes('retry this report'));
const originalReport=reportRequests.at(-1);
const {at,...recordedAssessment}=originalReport.excavation_assessment;
assert(Number.isFinite(at) && at>0 && at<=Date.now()/1000);
assert.deepEqual(recordedAssessment,{area:'Course A, east bay',lead:'Rescue Lead 1',decision:'cleared'});
await page.locator('#excavationArea').fill('Course A, west bay');
assert.match(await page.locator('#excavationNoticeTitle').textContent(),/Not assessed/);
assert.equal(await page.locator('#excavationDecision').inputValue(),'');
await page.locator('#saveMissionReport').click();
await page.waitForFunction(()=>document.getElementById('missionReportStatus').textContent.includes('Waiting to upload'));
assert.deepEqual(reportRequests.at(-1),originalReport,'Retry must retain the previous area, decision, and original time');
await page.locator('#excavationDecision').selectOption('hold');
await recordDecision.click();
assert.match(await page.locator('#excavationNoticeTitle').textContent(),/Hold excavation/);
await page.locator('#excavationDecision').selectOption('danger');
await recordDecision.click();
await page.getByRole('tab',{name:/Night vision/}).click();
assert.match(await page.locator('#excavationNoticeTitle').textContent(),/Extreme danger.*do not excavate/);
assert.equal(await page.locator('#excavationNoticeTitle').getAttribute('role'),'alert');
assert.match(await page.locator('#cameraExcavationStatus').textContent(),/Extreme danger.*do not excavate.*Course A, west bay/);
await page.locator('#clearExcavationDecision').click();
assert.match(await page.locator('#excavationNoticeTitle').textContent(),/Not assessed/);
await page.locator('#excavationDecision').selectOption('cleared');
await recordDecision.click();
await page.reload();
await page.locator('#excavationNotice').waitFor({state:'hidden'});
assert.match(await page.locator('#excavationNoticeTitle').textContent(),/Not assessed/);
assert.deepEqual(errors,[]);cameraFrames.assertSerial();console.log('PASS: mission report save and download, screen capture during camera waiting, and existing SAR dashboard and MP4 recording flows.');
await browser.close();
})().catch(error=>{console.error(error);process.exit(1)});
