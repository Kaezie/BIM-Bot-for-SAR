const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs/promises');

// Generated oscillator streams and stubbed audio outputs only. No real input,
// speaker, robot, cloud account or personal browser profile is used.
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1050},acceptDownloads:true});
  const origin=new URL(process.env.UI_TEST_URL||'http://127.0.0.1:5051/').origin;
  const errors=[],posts=[];let delayClassification=false,heldClassification;page.on('pageerror',error=>errors.push(error.message));
  await page.addInitScript(()=>{
   const Native=window.AudioContext;
   const f=window.headsetFixture={calls:[],streams:[],played:[],mode:'allow',devices:[
    {kind:'audioinput',deviceId:'laptop-mic',label:'Fixture laptop microphone'},
    {kind:'audioinput',deviceId:'headset-mic',label:'Fixture headset microphone'},
    {kind:'audiooutput',deviceId:'laptop-out',label:'Fixture laptop output'},
    {kind:'audiooutput',deviceId:'headset-out',label:'Fixture headset earpiece'}]};
   Object.defineProperty(navigator.mediaDevices,'enumerateDevices',{value:async()=>f.devices,configurable:true});
   Object.defineProperty(navigator.mediaDevices,'getUserMedia',{configurable:true,value:async constraints=>{
    f.calls.push(constraints);
    if(f.mode==='deny')throw new DOMException('Fixture denial','NotAllowedError');
    if(f.mode==='pending')await new Promise(resolve=>{f.release=resolve;});
    const context=new Native(),osc=context.createOscillator(),gain=context.createGain(),dest=context.createMediaStreamDestination();
    gain.gain.value=.2;osc.connect(gain);gain.connect(dest);osc.start();await context.resume();
    const track=dest.stream.getAudioTracks()[0],stop=track.stop.bind(track);
    track.getSettings=()=>({deviceId:f.mode==='wrong'?'wrong-input':constraints.audio?.deviceId?.exact||'laptop-mic'});
    track.stop=()=>{stop();osc.stop();context.close().catch(()=>{});};
    f.streams.push(dest.stream);return dest.stream;
   }});
   Object.defineProperty(HTMLMediaElement.prototype,'setSinkId',{configurable:true,value:async function(id){this.__sink=f.mode==='wrong-output'?'wrong-output':id;}});
   Object.defineProperty(HTMLMediaElement.prototype,'sinkId',{configurable:true,get(){return this.__sink||'';}});
   HTMLMediaElement.prototype.play=async function(){this.__playing=true;f.played.push(this.sinkId);};
   HTMLMediaElement.prototype.pause=function(){this.__playing=false;};
  });
  await page.route('**/*',route=>new URL(route.request().url()).origin===origin?route.continue():route.abort());
  await page.route('**/static/js/auth.js',route=>route.fulfill({contentType:'application/javascript',body:`window.BIM_AUTH={auth:{getSession:async()=>({data:{session:location.pathname==='/login'?null:{local:true,user:{email:'fixture@example.test'}}}}),onAuthStateChange:cb=>{window.fixtureSignOut=()=>cb('SIGNED_OUT',null)},signOut:async()=>({error:null})}};`}));
  await page.route('**/api/**',route=>{
   const path=new URL(route.request().url()).pathname,now=Date.now()/1000;
   if(route.request().method()!=='GET')posts.push(path);
   if(path==='/api/sound-classify'){
    const pcm=route.request().postDataBuffer();assert.equal(pcm.length,62400);let power=0;
    for(let i=0;i<pcm.length;i+=4){const value=pcm.readFloatLE(i);assert(Number.isFinite(value)&&Math.abs(value)<=1);power+=value*value;}
    assert(power>1,'Generated audio samples must actually reach the classifier');
    if(delayClassification){heldClassification=route;return;}
    return route.fulfill({contentType:'application/json',body:JSON.stringify({event:'Possible speech',model_label:'Speech',score:.8})});
   }
   const data={
    '/api/device-status':{nightvision:false,main_status:{connected:false}},
    '/api/sensor-data':{fresh:true,updated_at:now,temperature:27,humidity:60,heat_index:28},
    '/api/survivors':{available:true,updated_at:now,survivors_found:0,detections:[]},
    '/api/thermal-data':{configured:false,connected:false},'/api/sound-data':{configured:false,connected:false},
    '/api/sound-model':{ready:true,model:'YAMNet'},'/api/history':{samples:[],alerts:[]},
    '/api/mission':{mission:null,can_start:false,control_configured:false,robot:{fresh:false}},
    '/api/survivor-events':{events:[]},'/api/local-recordings':{recordings:[],pending_count:0},
    '/api/nightvision/light':{supported:false}
   }[path]||{};
   return route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
  });
  await page.goto(origin+'/?view=sound#monitor');
  await page.waitForFunction(()=>document.getElementById('tab-sound').getAttribute('aria-selected')==='true');
  assert.equal((await page.evaluate(()=>headsetFixture.calls)).length,0);
  await page.selectOption('#soundSourceMode','robot_headset');await page.click('#soundListInputs');
  await page.waitForFunction(()=>document.querySelectorAll('#soundInputDevice option').length===3);
  await page.selectOption('#soundInputDevice','headset-mic');await page.check('#soundMountConfirmed');await page.click('#laptopSoundStart');
  await page.waitForFunction(()=>document.getElementById('laptopSoundWave').dataset.live==='true');
  assert.deepEqual(posts,[],'No classification audio until recognition is enabled');
  await page.check('#soundRecognitionEnabled');
  await page.waitForFunction(()=>document.getElementById('soundRecognitionResult').textContent.includes('Possible speech'));
  assert(posts.includes('/api/sound-classify'));
  const mediaCalls=(await page.evaluate(()=>headsetFixture.calls)).length;
  await page.uncheck('#soundRecognitionEnabled');await page.check('#soundRecognitionEnabled');
  await page.waitForFunction(()=>document.getElementById('soundRecognitionResult').textContent.includes('Possible speech'));
  assert.equal((await page.evaluate(()=>headsetFixture.calls)).length,mediaCalls,'Toggling recognition must reuse the selected input');
  await page.uncheck('#soundRecognitionEnabled');delayClassification=true;await page.check('#soundRecognitionEnabled');
  for(let attempt=0;attempt<40&&!heldClassification;attempt++)await page.waitForTimeout(100);
  assert(heldClassification,'A generated PCM frame should be waiting');
  await page.click('#laptopSoundStop');
  await heldClassification.fulfill({contentType:'application/json',body:JSON.stringify({event:'LATE RESULT',model_label:'Speech',score:1})}).catch(()=>{});delayClassification=false;
  assert.equal(await page.isChecked('#soundRecognitionEnabled'),false);
  assert.match(await page.textContent('#soundRecognitionResult'),/No current/);

  await page.locator('#missionTools>summary').click();
  await page.click('#duplexFind');
  await page.waitForFunction(()=>document.querySelectorAll('#duplexRobotOutput option').length===3);
  async function routeDevices(){
   await page.selectOption('#duplexRobotMic','headset-mic');await page.selectOption('#duplexOperatorMic','laptop-mic');
   await page.selectOption('#duplexRobotOutput','headset-out');await page.selectOption('#duplexOperatorOutput','laptop-out');await page.check('#duplexMounted');
  }
  await routeDevices();await page.click('#duplexStart');
  await page.waitForFunction(()=>document.getElementById('duplexState').textContent.includes('Two-way audio active'));
  assert.deepEqual(await page.evaluate(()=>headsetFixture.played.slice(-2)),['laptop-out','headset-out']);
  const calls=await page.evaluate(()=>headsetFixture.calls.slice(-2));
  assert.equal(calls[0].audio.deviceId.exact,'headset-mic');assert.equal(calls[1].audio.deviceId.exact,'laptop-mic');
  await page.click('#duplexStop');
  await page.waitForFunction(()=>headsetFixture.streams.every(s=>s.getTracks().every(t=>t.readyState==='ended')));

  await routeDevices();await page.evaluate(()=>{headsetFixture.mode='pending'});await page.click('#duplexStart');
  await page.waitForFunction(()=>!!headsetFixture.release);await page.click('#duplexStop');
  await page.evaluate(()=>{headsetFixture.mode='allow';headsetFixture.release();});
  await page.waitForFunction(()=>!document.getElementById('duplexFind').disabled);
  await page.waitForFunction(()=>headsetFixture.streams.every(s=>s.getTracks().every(t=>t.readyState==='ended')));

  await routeDevices();await page.evaluate(()=>{headsetFixture.mode='deny'});await page.click('#duplexStart');
  await page.waitForFunction(()=>!document.getElementById('duplexFind').disabled);
  await page.waitForFunction(()=>headsetFixture.streams.every(s=>s.getTracks().every(t=>t.readyState==='ended')));

  await routeDevices();await page.evaluate(()=>{headsetFixture.mode='wrong-output'});await page.click('#duplexStart');
  await page.waitForFunction(()=>document.getElementById('duplexState').textContent.includes('selected audio output'));
  await page.waitForFunction(()=>headsetFixture.streams.every(s=>s.getTracks().every(t=>t.readyState==='ended')));

  await routeDevices();await page.evaluate(()=>{headsetFixture.mode='wrong'});await page.click('#duplexStart');
  await page.waitForFunction(()=>document.getElementById('duplexState').textContent.includes('selected microphone'));
  await page.waitForFunction(()=>headsetFixture.streams.every(s=>s.getTracks().every(t=>t.readyState==='ended')));
  await page.evaluate(()=>{headsetFixture.mode='allow'});await routeDevices();await page.click('#duplexStart');
  await page.waitForFunction(()=>document.getElementById('duplexState').textContent.includes('Two-way audio active'));
  await page.evaluate(()=>{Object.defineProperty(document,'visibilityState',{configurable:true,get:()=> 'hidden'});document.dispatchEvent(new Event('visibilitychange'));});
  await page.waitForFunction(()=>headsetFixture.streams.every(s=>s.getTracks().every(t=>t.readyState==='ended')));
  await page.evaluate(()=>{delete document.visibilityState;document.dispatchEvent(new Event('visibilitychange'));});
  await routeDevices();await page.click('#duplexStart');
  await page.waitForFunction(()=>document.getElementById('duplexState').textContent.includes('Two-way audio active'));
  await page.evaluate(()=>{headsetFixture.devices=headsetFixture.devices.filter(d=>d.deviceId!=='headset-out');navigator.mediaDevices.dispatchEvent(new Event('devicechange'));});
  await page.waitForFunction(()=>document.getElementById('duplexState').textContent.includes('disconnected'));
  await page.waitForFunction(()=>headsetFixture.streams.every(s=>s.getTracks().every(t=>t.readyState==='ended')));
  assert(posts.every(path=>path==='/api/sound-classify'),'No motor, cloud or recording writes permitted');

  await page.evaluate(()=>{headsetFixture.devices.push({kind:'audiooutput',deviceId:'headset-out',label:'Fixture headset earpiece'});navigator.mediaDevices.dispatchEvent(new Event('devicechange'));});
  await page.waitForFunction(()=>document.querySelectorAll('#duplexRobotOutput option').length===3);
  await routeDevices();await page.click('#duplexStart');
  await page.waitForFunction(()=>document.getElementById('duplexState').textContent.includes('Two-way audio active'));
  assert(await page.evaluate(()=>{const streams=[...headsetFixture.streams];fixtureSignOut();return streams.every(s=>s.getTracks().every(t=>t.readyState==='ended'));}));
  await page.waitForURL(url=>url.pathname==='/login');

  await page.route('**/api/system-check',route=>route.fulfill({contentType:'application/json',body:JSON.stringify({saved:true,report:{network:{ipv4:'192.168.4.3',robot_subnet:true},sensor:{fresh:true},thermal:{fresh:true},cameras:{main:{connected:false},nightvision:{connected:false}}}})}));
  await page.goto(origin+'/testing');await page.click('#testingSaveDiagnostics');
  await page.waitForFunction(()=>document.getElementById('testingDiagnosticResult').textContent.startsWith('Saved locally.'));
  assert.match(await page.locator('#testingDiagnosticResult').textContent(),/192\.168\.4\.3/);
  await page.click('#testingReadiness');
  await page.waitForFunction(()=>document.querySelectorAll('#testingReadings li').length===4);
  assert.equal((await page.evaluate(()=>headsetFixture.calls)).length,0,'Guide must not request media');
  assert.equal(await page.locator('.testing-outcome select').count(),6);
  for(const select of await page.locator('.testing-outcome select').all())assert.equal(await select.inputValue(),'untested');
  await page.locator('.testing-outcome select').first().selectOption('pass');
  const downloadPromise=page.waitForEvent('download');await page.click('#testingDownload');
  const download=await downloadPromise,report=JSON.parse(await fs.readFile(await download.path(),'utf8'));
  assert.equal(report.results[0].result,'pass');assert(report.results.slice(1).every(r=>r.result==='untested'));
  for(const width of [320,390,768,1440]){await page.setViewportSize({width,height:1000});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`Guide overflow at ${width}`);}
  await page.screenshot({path:'/private/tmp/bimbot-testing-guide.png',fullPage:true});
  assert.deepEqual(errors,[]);
  console.log('PASS: generated audio PCM, manual recognition, exact two-way routes, mismatch/disconnect cleanup, no motor/cloud writes, guided readiness/download and responsive layout.');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exit(1)});
