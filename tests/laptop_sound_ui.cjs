const {chromium} = require('playwright');
const assert = require('node:assert/strict');

// Generated oscillator audio only, in an isolated browser. getUserMedia is
// replaced before any app script loads; no real microphone or robot is used.
(async () => {
  const browser = await chromium.launch({headless:true,
    ...(process.env.CHROME_PATH ? {executablePath:process.env.CHROME_PATH} : {})});
  try {
    const origin = new URL(process.env.UI_TEST_URL || 'http://127.0.0.1:5051/').origin;
    const page = await browser.newPage({viewport:{width:1440,height:1050}});
    const errors = [], writes = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.addInitScript(() => {
      const fixture = window.audioFixture = {calls:0, mode:'allow', streams:[], contexts:[], constraints:[]};
      fixture.devices=[{kind:'audioinput',deviceId:'fixture-laptop',label:'Fixture laptop microphone'}, {kind:'audioinput',deviceId:'fixture-headset',label:'Fixture Bluetooth headset'}];
      Object.defineProperty(navigator.mediaDevices,'enumerateDevices',{configurable:true,value:async()=>fixture.devices});
      Object.defineProperty(navigator.mediaDevices, 'getUserMedia', {configurable:true, value:async constraints => {
        fixture.calls++;
        fixture.constraints.push(constraints);
        if (fixture.mode === 'deny') throw new DOMException('Fixture denial', 'NotAllowedError');
        if (fixture.mode === 'missing_selected') throw new DOMException('Fixture unavailable', 'OverconstrainedError');
        if (fixture.mode === 'pending') await new Promise(resolve => { fixture.release = resolve; });
        const ctx = new realAudioContext();
        const osc = ctx.createOscillator(), gain = ctx.createGain(), destination = ctx.createMediaStreamDestination();
        gain.gain.value = .25;
        osc.connect(gain); gain.connect(destination); osc.start();
        await ctx.resume();
        fixture.streams.push(destination.stream);
        const deviceId=constraints.audio?.deviceId?.exact || 'fixture-laptop';
        destination.stream.getAudioTracks()[0].getSettings=()=>({deviceId:fixture.reportedInput || deviceId});
        Object.defineProperty(destination.stream.getAudioTracks()[0],'label',{value:deviceId==='fixture-headset'?'Fixture Bluetooth headset':'Fixture laptop microphone'});
        fixture.contexts.push(ctx);
        return destination.stream;
      }});
      const realAudioContext = window.AudioContext;
      fixture.analysisContexts = [];
      window.AudioContext = class extends realAudioContext {
        constructor(...args) { super(...args); fixture.analysisContexts.push(this); }
      };
    });
    await page.route('**/*', route => new URL(route.request().url()).origin === origin ? route.continue() : route.abort());
    await page.route('**/static/js/auth.js', route => route.fulfill({contentType:'application/javascript',body:`
      window.BIM_AUTH={auth:{
        getSession:async()=>({data:{session:{local:true,user:{email:'sound-fixture@example.test'}}}}),
        onAuthStateChange:callback=>{window.endSoundFixtureSession=()=>callback('SIGNED_OUT',null);},
        signOut:async()=>({error:null})
      }};`}));
    await page.route('**/api/**', route => {
      const path = new URL(route.request().url()).pathname;
      if (route.request().method() !== 'GET') writes.push(path);
      const now = Date.now()/1000;
      const data = {
        '/api/device-status':{nightvision:false},
        '/api/sensor-data':{fresh:true,updated_at:now,temperature:26,humidity:70,heat_index:27},
        '/api/survivors':{available:true,updated_at:now,survivors_found:0,detections:[]},
        '/api/thermal-data':{configured:false,connected:false},
        '/api/sound-data':{configured:false,connected:false},
        '/api/history':{samples:[],alerts:[]},
        '/api/mission':{mission:null,can_start:false,control_configured:false,robot:{fresh:false}},
        '/api/survivor-events':{events:[]},
        '/api/local-recordings':{recordings:[],pending_count:0,has_more:false},
        '/api/nightvision/light':{supported:false}
      }[path] || {};
      return route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
    });
    await page.goto(origin, {waitUntil:'domcontentloaded'});
    await page.locator('#tab-sound').click();
    assert.equal(await page.evaluate(()=>audioFixture.calls),0,'Loading/selecting Sound must not request a microphone');
    assert.equal(await page.locator('.camera-sound-source').count(),2);
    for (const card of await page.locator('.camera-sound-source').all()) assert.match(await card.textContent(),/Unavailable.*No microphone installed/s);
    assert.match(await page.locator('#panel-sound').textContent(),/hears sound near the laptop/);
    assert.equal(await page.locator('#laptopSoundLevel').textContent(),'—');

    async function start() {
      await page.locator('#laptopSoundStart').click();
      await page.waitForFunction(()=>document.getElementById('laptopSoundWave').dataset.live === 'true');
      await page.waitForFunction(()=>parseFloat(document.getElementById('laptopSoundLevel').textContent)>10);
    }
    async function stopped() {
      await page.waitForFunction(()=>audioFixture.streams.every(stream=>stream.getTracks().every(track=>track.readyState==='ended')));
      await page.waitForFunction(()=>audioFixture.analysisContexts.every(ctx=>ctx.state==='closed'));
      assert.equal(await page.locator('#laptopSoundLevel').textContent(),'—');
      assert.equal(await page.locator('#laptopSoundWave').getAttribute('data-live'),'false');
      assert.equal(await page.locator('#laptopSoundMeter').evaluate(el=>el.value),0);
    }
    await start();
    assert.match(await page.locator('#availability-sound').textContent(),/Laptop only/);
    assert.equal(await page.locator('#laptopSoundActivity').textContent(),'Sound activity');
    assert.equal(await page.locator('#soundSummaryLevel').textContent(),'—','Laptop signal must not become remote sensor telemetry');
    await page.evaluate(()=>{const el=document.getElementById('laptopSoundThreshold');el.value='100';el.dispatchEvent(new Event('input'));});
    await page.waitForFunction(()=>document.getElementById('laptopSoundActivity').textContent==='Below activity threshold');
    await page.evaluate(()=>{const el=document.getElementById('laptopSoundThreshold');el.value='3';el.dispatchEvent(new Event('input'));});
    await page.waitForFunction(()=>document.getElementById('laptopSoundActivity').textContent==='Sound activity');
    await page.screenshot({path:'/private/tmp/bimbot-laptop-sound-desktop.png',fullPage:false});
    await page.locator('#laptopSoundStop').click(); await stopped();
    assert(await page.locator('#laptopSoundStart').isEnabled());

    await start();
    await page.locator('#tab-thermal').click(); await stopped();
    await page.locator('#tab-sound').click();
    assert.equal(await page.evaluate(()=>audioFixture.calls),2,'Returning to Sound must not restart audio');
    await start();
    await page.evaluate(()=>{
      Object.defineProperty(document,'visibilityState',{configurable:true,value:'hidden'});
      document.dispatchEvent(new Event('visibilitychange'));
    });
    await stopped();
    await page.evaluate(()=>{Object.defineProperty(document,'visibilityState',{configurable:true,value:'visible'});document.dispatchEvent(new Event('visibilitychange'));});
    assert.equal(await page.evaluate(()=>audioFixture.calls),3,'Restoring visibility must not restart audio');

    await page.evaluate(()=>{audioFixture.mode='pending';});
    await page.locator('#laptopSoundStart').click();
    await page.waitForFunction(()=>typeof audioFixture.release === 'function');
    await page.locator('#laptopSoundStop').click();
    assert(await page.locator('#laptopSoundStart').isDisabled(),'An unresolved permission request must not create duplicate prompts');
    await page.evaluate(()=>audioFixture.release());
    await page.waitForFunction(()=>audioFixture.streams.length===4);
    await stopped();
    await page.waitForFunction(()=>!document.getElementById('laptopSoundStart').disabled);
    assert.match(await page.locator('#laptopSoundState').textContent(),/Stopped/);

    await page.evaluate(()=>{audioFixture.mode='deny';});
    await page.locator('#laptopSoundStart').click();
    await page.waitForFunction(()=>document.getElementById('laptopSoundState').textContent.includes('not granted'));
    await stopped();
    assert(await page.locator('#laptopSoundStart').isEnabled(),'Permission denial must allow a deliberate retry');

    await page.evaluate(()=>{audioFixture.mode='allow';});
    await start();
    await page.evaluate(()=>audioFixture.streams.at(-1).getAudioTracks()[0].dispatchEvent(new Event('ended')));
    await stopped();
    assert.match(await page.locator('#laptopSoundState').textContent(),/disconnected/);
    await start();
    await page.locator('.account > summary').click();
    await page.locator('#logoutBtn').click(); await stopped();
    await page.locator('.account > summary').click();
    await start();
    await page.evaluate(()=>window.dispatchEvent(new Event('pagehide'))); await stopped();

    for (const [width,height] of [[320,844],[390,844],[768,900],[1440,650]]) {
      await page.setViewportSize({width,height});
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`Page overflow at ${width}`);
      assert(await page.locator('.sound-view').evaluate(el=>el.scrollWidth<=el.clientWidth),`Sound overflow at ${width}`);
      await page.locator('#laptopSoundStart').scrollIntoViewIfNeeded();
      assert(await page.locator('#laptopSoundStart').isVisible());
      if(width===390) await page.screenshot({path:'/private/tmp/bimbot-laptop-sound-mobile.png',fullPage:false});
    }
    const constraints = await page.evaluate(()=>audioFixture.constraints);
    assert(constraints.every(value=>value.video===false && value.audio),'Only audio may be requested');
    assert.deepEqual(writes,[],'Local sound analysis must not upload audio or levels');
    assert.deepEqual(errors,[]);

    // Explicit robot-headset source selection; all samples remain generated.
    const beforeSelection=await page.evaluate(()=>audioFixture.calls);
    await page.locator('#soundSourceMode').selectOption('robot_headset');
    assert(await page.locator('#laptopSoundStart').isDisabled());
    assert.equal(await page.evaluate(()=>audioFixture.calls),beforeSelection);
    await page.locator('#soundListInputs').click();
    await page.waitForFunction(()=>document.querySelectorAll('#soundInputDevice option').length===3 && !document.getElementById('soundListInputs').disabled);
    await stopped();
    assert(await page.locator('#laptopSoundStart').isDisabled(),'Default input is forbidden in robot mode');
    await page.locator('#soundInputDevice').selectOption('fixture-headset');
    assert(await page.locator('#laptopSoundStart').isDisabled(),'Robot placement needs explicit confirmation');
    await page.locator('#soundMountConfirmed').check();
    await start();
    assert.equal(await page.locator('#availability-sound').textContent(),'Robot headset');
    assert.match(await page.locator('#soundActualDevice').textContent(),/Fixture Bluetooth headset.*operator/);
    assert.equal(await page.evaluate(()=>audioFixture.constraints.at(-1).audio.deviceId.exact),'fixture-headset');
    assert.equal(await page.locator('#soundSummaryLevel').textContent(),'—','Headset input is not a calibrated remote sensor');
    await page.evaluate(()=>{audioFixture.reportedInput='fixture-laptop';});
    await stopped();
    assert.match(await page.locator('#laptopSoundState').textContent(),/source changed/);
    await page.evaluate(()=>{audioFixture.reportedInput=null;});
    await start();
    const beforeDisconnect=await page.evaluate(()=>audioFixture.calls);
    await page.evaluate(()=>{audioFixture.devices=audioFixture.devices.filter(device=>device.deviceId!=='fixture-headset');navigator.mediaDevices.dispatchEvent(new Event('devicechange'));});
    await stopped();
    assert.match(await page.locator('#laptopSoundState').textContent(),/disconnected/);
    assert.equal(await page.locator('#soundInputDevice').inputValue(),'');
    assert.equal(await page.evaluate(()=>audioFixture.calls),beforeDisconnect,'Disconnect must not fall back to the laptop');
    await page.evaluate(()=>{audioFixture.devices.push({kind:'audioinput',deviceId:'fixture-headset',label:'Fixture Bluetooth headset'});navigator.mediaDevices.dispatchEvent(new Event('devicechange'));});
    await page.waitForFunction(()=>document.querySelectorAll('#soundInputDevice option').length===3);
    assert.equal(await page.evaluate(()=>audioFixture.calls),beforeDisconnect,'Reconnect must not start capture');
    await page.locator('#soundInputDevice').selectOption('fixture-headset');
    await page.locator('#soundMountConfirmed').check();
    await page.evaluate(()=>{audioFixture.mode='missing_selected';});
    await page.locator('#laptopSoundStart').click();
    await page.waitForFunction(()=>document.getElementById('laptopSoundState').textContent.includes('No replacement'));
    await stopped();
    await page.evaluate(()=>{audioFixture.mode='allow';});
    await start();
    for(const width of [320,390,768,1440]) {
      await page.setViewportSize({width,height:900});
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`Headset controls overflow at ${width}`);
    }
    await page.screenshot({path:'/private/tmp/bimbot-headset-fixture.png',fullPage:false});
    await page.locator('#soundSourceMode').selectOption('laptop'); await stopped();
    await page.locator('#soundInputDevice').selectOption('');
    assert.deepEqual(writes,[],'Headset samples must not be uploaded or written to robot endpoints');
    assert.deepEqual(errors,[]);
    await start();
    // An unsaved fixture clip keeps the page visible after session expiration,
    // allowing us to assert that real input resources were still released.
    await page.evaluate(()=>{pendingClip={};window.endSoundFixtureSession();}); await stopped();
    await page.evaluate(async()=>{await Promise.all(audioFixture.contexts.map(ctx=>ctx.state==='closed'?null:ctx.close()));});
    console.log('Microphone: laptop regression plus exact headset selection, mount confirmation, discovery cleanup, wrong-source rejection, disconnect/no fallback, reconnect/no capture and responsive layout pass (generated audio only).');
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1;});
