const {chromium} = require('playwright');
const {cameraFrameFixture}=require('./camera_frame_fixture.cjs');
const assert = require('node:assert/strict');

(async () => {
  const browser = await chromium.launch({headless:true, ...(process.env.CHROME_PATH ? {executablePath:process.env.CHROME_PATH} : {})});
  try {
    const page = await browser.newPage({viewport:{width:390,height:844}});
    const errors = [], commands = [];
    page.on('pageerror', error => errors.push(error.message));
    const frame = Buffer.from(await page.evaluate(() => {
      const canvas = document.createElement('canvas'); canvas.width=640; canvas.height=480;
      canvas.getContext('2d').fillRect(0,0,640,480);
      return canvas.toDataURL('image/jpeg',0.8).split(',')[1];
    }), 'base64');
    let mode = 'ok', releaseCommand, holdNext = false, renewals = 0;
    const cameraFrames=cameraFrameFixture(frame);
    await page.route('**/static/js/auth.js', route => route.fulfill({contentType:'application/javascript', body:`
      window.BIM_AUTH={auth:{
        getSession:async()=>({data:{session:{local:true,user:{email:'rescue@example.test'}}}}),
        onAuthStateChange:callback=>window.authCallback=callback,
        signOut:async()=>{window.signedOut=true;return {error:null};}
      }};`}));
    await page.route('**/api/**', async route => {
      if(cameraFrames.matches(route))return cameraFrames.handle(route);
      const path = new URL(route.request().url()).pathname, now = Date.now()/1000;
      let data = {};
      if (path === '/api/nightvision/light') {
        const enabled = route.request().postDataJSON().enabled;
        commands.push(enabled); if (enabled) renewals++;
        if (holdNext) { holdNext=false; await new Promise(resolve=>releaseCommand=resolve); }
        if (mode !== 'ok') return route.fulfill({status:mode==='unsupported'?409:503,contentType:'application/json',body:JSON.stringify({code:mode==='unsupported'?'unsupported_firmware':'unreachable',supported:false,available:false,illumination:null,error:'Fixture control failure'})});
        data = {supported:true,available:true,firmware:'bimbot-nightvision/2',illumination:{enabled,brightness:enabled?32:0,lease_ms:15000}};
      }
      if (path === '/api/device-status') data={nightvision:true,nightvision_status:{connected:true,detection_enabled:false}};
      if (path === '/api/sensor-data') data={fresh:false};
      if (path === '/api/survivors') data={available:false,detections:[]};
      if (path === '/api/thermal-data' || path === '/api/sound-data') data={connected:false};
      if (path === '/api/history') data={samples:[],alerts:[]};
      if (path === '/api/mission') data={mission:null,can_start:false,control_configured:false,robot:{fresh:false}};
      if (path === '/api/survivor-events') data={events:[]};
      if (path === '/api/local-recordings') data=route.request().method()==='POST'?{success:true,recording:{download_url:'/fixture.mp4',sync_state:'pending'}}:{recordings:[],pending_count:0,has_more:false};
      return route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
    });
    await page.route('**/toggle_recording',route=>route.fulfill({contentType:'application/json',body:'{}'}));
    await page.goto(process.env.UI_TEST_URL || 'http://127.0.0.1:5051/');
    await page.waitForFunction(()=>document.getElementById('availability-nightvision').textContent==='Configured');
    assert.equal(commands.length,0,'The main view must not activate the spare light');
    await page.locator('#tab-nightvision').click();
    await page.waitForTimeout(600);
    assert.equal(commands.length,0,'Selecting Night must leave the white light off until explicitly requested');
    await page.locator('#nvLightOnBtn').click();
    await page.waitForFunction(()=>document.getElementById('nvLightStatus').textContent==='White light: on');
    assert.equal(await page.locator('#nvLightOnBtn').getAttribute('aria-pressed'),'true');
    assert(await page.locator('#nvStream').isVisible());
    for (const width of [320,390,768,1440]) {
      await page.setViewportSize({width,height:844});
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`Night-light controls overflow at ${width}px`);
      const detectionBox=await page.locator('#nvDetectionStatus').boundingBox(), lightBox=await page.locator('.night-light-controls').boundingBox(), feedBox=await page.locator('.feed-stage').boundingBox();
      assert(lightBox.y>=detectionBox.y+detectionBox.height,'Lighting controls must not overlap the camera-detection status');
      assert(lightBox.y+lightBox.height<=feedBox.y,'Lighting controls must stay above the image so they do not cover the feed');
    }
    await page.setViewportSize({width:390,height:844});
    await page.screenshot({path:'/tmp/bimbot-night-light-mobile.png'});
    const beforeRenew = renewals;
    await page.waitForFunction(()=>document.getElementById('nvLightStatus').dataset.state==='confirmed');
    await page.waitForTimeout(5200);
    assert(renewals>beforeRenew,'A visible spare view must renew the firmware light lease');
    await page.locator('#nvLightOffBtn').click();
    await page.waitForFunction(()=>document.getElementById('nvLightStatus').textContent==='White light: off');
    const manualOffCount = commands.length;
    await page.waitForTimeout(5200);
    assert.equal(commands.length,manualOffCount,'A manual off must survive status polling and lease renewal ticks');
    await page.locator('#nvLightOnBtn').click();
    await page.waitForFunction(()=>document.getElementById('nvLightStatus').textContent==='White light: on');
    await page.locator('#tab-main').click();
    await page.waitForFunction(()=>document.getElementById('nvLightStatus').textContent==='White light: off');
    assert.equal(commands.at(-1),false,'Leaving the spare view must turn its light off');

    holdNext=true;
    await page.locator('#tab-nightvision').click();
    await page.waitForFunction(()=>document.getElementById('nvLightStatus').dataset.state==='pending');
    while (!releaseCommand) await page.waitForTimeout(10);
    await page.locator('#nvLightOffBtn').click();
    await page.locator('#nvLightOnBtn').click();
    await page.locator('#nvLightOffBtn').click();
    releaseCommand(); releaseCommand=null;
    await page.waitForFunction(()=>document.getElementById('nvLightStatus').textContent==='White light: off');
    assert.equal(commands.at(-1),false,'A delayed on acknowledgement must not overwrite the newest off request');
    assert.equal(await page.locator('#nvLightOnBtn').getAttribute('aria-pressed'),'false');

    holdNext=true; await page.locator('#nvLightOnBtn').click();
    while (!releaseCommand) await page.waitForTimeout(10);
    const slowCount=commands.length; await page.waitForTimeout(5200);
    releaseCommand(); releaseCommand=null;
    await page.waitForFunction(()=>document.getElementById('nvLightStatus').textContent==='White light: on');
    assert.equal(commands.length,slowCount,'A renewal tick must not invalidate a slower acknowledgement or queue duplicate commands');

    mode='unsupported'; await page.locator('#nvLightOnBtn').click();
    await page.waitForFunction(()=>document.getElementById('nvLightStatus').textContent.startsWith('Firmware update needed'));
    assert(await page.locator('#nvStream').isVisible(),'Older firmware must still stream video');
    assert.equal(await page.locator('#nvLightOnBtn').getAttribute('aria-pressed'),'false');
    const unsupportedCount=commands.length; await page.waitForTimeout(5200);
    assert.equal(commands.length,unsupportedCount,'Unsupported firmware must not be retried every five seconds');
    mode='unreachable'; await page.locator('#nvLightOnBtn').click();
    await page.waitForFunction(()=>document.getElementById('nvLightStatus').textContent.startsWith('Light unavailable'));
    assert.equal(await page.locator('#nvLightOnBtn').getAttribute('aria-pressed'),'false','A failed on command must not be shown as on');
    mode='ok'; await page.locator('#nvLightOnBtn').click();
    await page.waitForFunction(()=>document.getElementById('nvLightStatus').textContent==='White light: on');
    await page.evaluate(()=>{
      Object.defineProperty(document,'visibilityState',{configurable:true,value:'hidden'});
      document.dispatchEvent(new Event('visibilitychange'));
    });
    await page.waitForFunction(()=>document.getElementById('nvLightStatus').textContent==='White light: off');
    const hiddenCount=commands.length; await page.waitForTimeout(5200);
    assert.equal(commands.length,hiddenCount,'A hidden page must stop renewing the light');
    await page.evaluate(()=>{
      Object.defineProperty(document,'visibilityState',{configurable:true,value:'visible'});
      document.dispatchEvent(new Event('visibilitychange'));
    });
    await page.waitForFunction(()=>document.getElementById('nvLightStatus').textContent==='White light: on');

    // Recorder state is mocked here to isolate lighting lifecycle; dashboard_ui
    // separately checks a real browser MP4 and immutable camera capture source.
    await page.evaluate(()=>{
      window.MediaRecorder=class {
        static isTypeSupported(){return true;}
        constructor(stream,options){this.state='inactive';this.mimeType=options.mimeType;}
        start(){this.state='recording';}
        stop(){this.state='inactive';this.ondataavailable({data:new Blob(['fixture'],{type:this.mimeType})});setTimeout(()=>this.onstop(),0);}
      };
    });
    await page.locator('#recordBtn').click();
    await page.waitForFunction(()=>!document.getElementById('stopBtn').hidden);
    const recordingCommands = commands.length;
    await page.locator('#tab-main').click();
    await page.waitForTimeout(200);
    assert.equal(commands.length,recordingCommands,'Spare recordings must retain lighting across tabs');
    assert.notEqual(await page.locator('#nvStream').getAttribute('data-viewer'),null);
    const recordingViewer=await page.locator('#nvStream').getAttribute('data-viewer');
    await page.evaluate(()=>window.dispatchEvent(new PageTransitionEvent('pagehide',{persisted:true})));
    await page.waitForFunction(()=>document.getElementById('nvLightStatus').textContent==='White light: off');
    assert.equal(await page.locator('#nvStream').getAttribute('data-viewer'),null);
    await page.evaluate(()=>window.dispatchEvent(new PageTransitionEvent('pageshow',{persisted:true})));
    await page.waitForFunction(()=>document.getElementById('availability-nightvision').textContent==='Live');
    await page.waitForFunction(()=>document.getElementById('nvLightStatus').textContent==='White light: on');
    assert.equal(await page.locator('#monitor').getAttribute('data-active-feed'),'main','Restoring Night recording must retain the selected Main tab');
    assert.notEqual(await page.locator('#nvStream').getAttribute('data-viewer'),recordingViewer,'A Night recording must renew its hidden viewer after page restoration');
    assert(await page.locator('#stopBtn').isVisible(),'Restoring camera viewers must preserve recording controls');
    await page.locator('#stopBtn').click();
    await page.waitForFunction(()=>document.getElementById('nvLightStatus').textContent==='White light: off');
    await page.waitForFunction(()=>document.getElementById('saveTitle').textContent==='Recording saved on this laptop');
    await page.locator('#closeSave').click();
    await page.locator('#tab-nightvision').click();
    await page.waitForFunction(()=>document.getElementById('nvLightStatus').textContent==='White light: on');
    const beforePageHide=await page.locator('#nvStream').getAttribute('data-viewer');
    await page.evaluate(()=>window.dispatchEvent(new PageTransitionEvent('pagehide',{persisted:true})));
    await page.waitForFunction(()=>document.getElementById('nvLightStatus').textContent==='White light: off');
    assert.equal(await page.locator('#nvStream').getAttribute('data-viewer'),null,'Page hide must release Night viewing');
    assert.equal(await page.locator('#camStream').getAttribute('data-viewer'),null,'Page hide must release Main viewing');
    await page.evaluate(()=>window.dispatchEvent(new PageTransitionEvent('pageshow',{persisted:true})));
    await page.waitForFunction(()=>document.getElementById('nvLightStatus').textContent==='White light: on');
    await page.waitForFunction(()=>document.getElementById('availability-nightvision').textContent==='Live');
    assert.notEqual(await page.locator('#nvStream').getAttribute('data-viewer'),beforePageHide,'Back-forward restoration must create a fresh Night viewer');
    await page.locator('.account summary').click(); await page.locator('#logoutBtn').click();
    await page.waitForFunction(()=>window.signedOut===true);
    assert.equal(commands.at(-1),false,'Logout must request off before revoking the session');
    assert.deepEqual(errors,[]);
    cameraFrames.assertSerial();
    console.log('PASS: white-light activation, lease renewal, manual off, newest-command ordering, old firmware/failure states, hidden/page lifecycle, recording across tabs and logout.');
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exit(1);});
