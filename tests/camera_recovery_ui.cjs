const {chromium} = require('playwright');
const {cameraFrameFixture}=require('./camera_frame_fixture.cjs');
const assert = require('node:assert/strict');

// Fixture cameras and local authentication only; no robot or cloud access.
(async () => {
  const browser = await chromium.launch({headless:true, ...(process.env.CHROME_PATH ? {executablePath:process.env.CHROME_PATH} : {})});
  try {
    const page = await browser.newPage({viewport:{width:1440,height:1050}});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const frame = Buffer.from(await page.evaluate(() => {
      const canvas = document.createElement('canvas'); canvas.width=640; canvas.height=480;
      canvas.getContext('2d').fillRect(0,0,640,480);
      return canvas.toDataURL('image/jpeg',0.8).split(',')[1];
    }), 'base64');
    let sensorValue=28,thermalValue=24,sensorFailed=false,thermalFailed=false;
    let failMain = true, mainLive = true, nightLive = true, mainRequests = 0, holdDevices = false, releaseDevices, devicesHeld;
    const cameraFrames=cameraFrameFixture(frame,{
      fail:source=>source==='main' && failMain,
      onOpen:source=>{if(source==='main')mainRequests++;},
    });
    function holdDeviceResponse() {
      holdDevices=true; releaseDevices=undefined;
      return new Promise(resolve=>devicesHeld=resolve);
    }
    await page.route('**/fonts.googleapis.com/**', route => route.abort());
    await page.route('**/static/js/auth.js', route => route.fulfill({contentType:'application/javascript',body:`
      window.BIM_AUTH={auth:{
        getSession:async()=>({data:{session:{local:true,user:{email:'fixture@example.test'}}}}),
        onAuthStateChange:callback=>window.authCallback=callback,signOut:async()=>({error:null})
      }};`}));
    await page.route('**/api/**', async route => {
      if (cameraFrames.matches(route)) return cameraFrames.handle(route);
      const path = new URL(route.request().url()).pathname;
      let data = {};
      if (path==='/api/device-status') {
        data={nightvision:true,main_status:{connected:mainLive},nightvision_status:{connected:nightLive,detection_enabled:false}};
        if (holdDevices) {
          holdDevices=false;
          await new Promise(resolve => { releaseDevices=resolve; devicesHeld(); });
        }
      }
      if (path==='/api/nightvision/light') data={supported:true,available:true,firmware:'bimbot-nightvision/2',illumination:{enabled:false,brightness:0,lease_ms:15000}};
      if (path==='/api/sensor-data') {
        if(sensorFailed)return route.fulfill({status:503,contentType:'application/json',body:'{}'});
        data={fresh:true,updated_at:Date.now()/1000,temperature:sensorValue,humidity:65,heat_index:sensorValue,risk_level:'Low Risk'};
      }
      if (path==='/api/survivors') data={available:false,detections:[]};
      if (path==='/api/thermal-data') {
        if(thermalFailed)return route.fulfill({status:503,contentType:'application/json',body:'{}'});
        data={configured:true,connected:true,fresh:true,updated_at:Date.now()/1000,min_temp:thermalValue,max_temp:thermalValue+5,
          grid:Array.from({length:24},()=>Array(32).fill(thermalValue))};
      }
      if (path==='/api/sound-data') data={connected:false};
      if (path==='/api/system-check/recording') data={running:route.request().method()==='POST',saved:false,samples:0};
      if (path==='/api/system-check') data={saved:true,report:{network:{ipv4:'192.168.4.3',robot_subnet:true},sensor:{fresh:true},thermal:{fresh:true},cameras:{main:{connected:true},nightvision:{connected:true}}}};
      if (path==='/api/history') data={samples:[],alerts:[]};
      if (path==='/api/mission') data={mission:null,can_start:false,control_configured:false,robot:{fresh:false}};
      if (path==='/api/survivor-events') data={events:[]};
      if (path==='/api/local-recordings') data={recordings:[],pending_count:0,has_more:false};
      await route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
    });
    await page.goto(process.env.UI_TEST_URL || 'http://127.0.0.1:5051/');
    await page.waitForFunction(()=>document.getElementById('availability-nightvision').textContent==='Configured');
    await page.evaluate(()=>{mainPlayer.startupGraceMs=400;});
    await page.waitForFunction(()=>document.getElementById('tempDisplay').textContent==='28.0');
    sensorFailed=true;thermalFailed=true;
    await page.evaluate(()=>Promise.all([fetchSensors(),fetchThermal()]));
    assert.equal(await page.locator('#tempDisplay').textContent(),'28.0');
    assert.equal(await page.locator('#sensorState').textContent(),'Retrying');
    assert.equal(await page.locator('#mainThermalRange').textContent(),'24.0–29.0 °C');
    sensorValue=29;thermalValue=25;sensorFailed=false;thermalFailed=false;
    await page.waitForFunction(()=>document.getElementById('tempDisplay').textContent==='29.0' && document.getElementById('mainThermalRange').textContent==='25.0–30.0 °C',null,{timeout:5000});
    // A rejected callback must not permanently kill the repeating worker.
    await page.evaluate(()=>{window.retryProbe=0;poll(()=>{window.retryProbe++;if(window.retryProbe===1)throw new Error('Fixture transient');return new Promise(()=>{});},20);});
    await page.waitForFunction(()=>window.retryProbe===2);


    // A pending idle status response must not disconnect a Night stream that
    // starts successfully while that response is still in flight.
    nightLive=false;
    const idleNightResponse = holdDeviceResponse();
    await page.evaluate(()=>{window.heldNightCheck=fetchDevices();});
    await idleNightResponse;
    nightLive=true;
    await page.locator('#tab-nightvision').click();
    await page.waitForFunction(()=>document.getElementById('availability-nightvision').textContent==='Live');
    const connectedNightSource = await page.locator('#nvStream').getAttribute('data-viewer');
    assert(releaseDevices,'The fixture must hold the earlier Night idle status response');
    releaseDevices();
    await page.evaluate(()=>window.heldNightCheck);
    assert.equal(await page.locator('#availability-nightvision').textContent(),'Live','An older idle response must not tear down a new Night connection');
    assert.equal(await page.locator('#nvStream').getAttribute('data-viewer'),connectedNightSource);
    await page.locator('#tab-main').click();

    await page.waitForFunction(()=>document.getElementById('cameraHint').textContent.includes('Retrying'));
    assert.equal(mainRequests,1);
    failMain=false;
    await page.waitForFunction(()=>document.getElementById('availability-main').textContent==='Live',null,{timeout:10000});
    assert.equal(mainRequests,1,'Initial frame delay must recover without replacing its reader');

    // A browser may retain its last painted MJPEG image without an error event.
    mainLive=false;failMain=true;
    await page.evaluate(()=>fetchDevices());
    await page.waitForFunction(()=>document.getElementById('availability-main').textContent==='Waiting');
    assert.match(await page.locator('#cameraHint').textContent(),/Retrying/);
    assert(await page.locator('#camStream').isHidden(),'Stale Main frames must not remain labelled Live');
    failMain=false;
    sensorValue=30;thermalValue=26;
    await page.waitForFunction(()=>document.getElementById('tempDisplay').textContent==='30.0' && document.getElementById('mainThermalRange').textContent==='26.0–31.0 °C',null,{timeout:5000});

    mainLive=true;failMain=false;
    await page.waitForFunction(()=>document.getElementById('availability-main').textContent==='Live',null,{timeout:10000});
    assert.equal(mainRequests,1,'Frame freshness loss must retain Main subscription while hiding expired images');

    await page.locator('#tab-nightvision').click();
    await page.waitForFunction(()=>document.getElementById('availability-nightvision').textContent==='Live');
    const nightSource = await page.locator('#nvStream').getAttribute('data-viewer');
    await page.locator('#camStream').evaluate(image=>image.dispatchEvent(new Event('error')));
    await page.waitForFunction(()=>document.getElementById('availability-main').textContent==='Live',null,{timeout:10000});
    assert.equal(mainRequests,2,'Main monitoring must recover while another camera is selected');
    assert.equal(await page.locator('#nvStream').getAttribute('data-viewer'),nightSource,'Main retry must retain the Night stream');
    assert.equal(await page.locator('#monitor').getAttribute('data-active-feed'),'nightvision');

    const recoveredMainSource = await page.locator('#camStream').getAttribute('data-viewer');
    nightLive=false;
    await page.evaluate(()=>fetchDevices());
    assert.equal(await page.locator('#nvStream').getAttribute('data-viewer'),nightSource,'A status poll must not override fresh frame delivery');
    assert.equal(await page.locator('#camStream').getAttribute('data-viewer'),recoveredMainSource);
    nightLive=true;
    await page.waitForFunction(()=>document.getElementById('availability-nightvision').textContent==='Live',null,{timeout:10000});
    assert.equal(await page.locator('#camStream').getAttribute('data-viewer'),recoveredMainSource,'Night retry must retain the Main stream');
    assert.equal(mainRequests,2,'Night retry must not reconnect Main');

    await page.locator('#tab-main').click();
    await page.locator('#camStream').evaluate(image=>image.dispatchEvent(new Event('error')));
    await page.locator('#disconnectBtn').click();
    await page.locator('#camStream').evaluate(image=>image.dispatchEvent(new Event('load')));
    for (const feed of ['thermal','sound','nightvision']) await page.locator(`#tab-${feed}`).click();
    await page.evaluate(()=>refreshAll());
    await page.waitForTimeout(5500);
    assert.equal(mainRequests,2,'Manual Disconnect must cancel an already scheduled retry across other tabs');
    assert.equal(await page.locator('#camStream').getAttribute('data-viewer'),null);
    assert.equal(await page.locator('#availability-main').textContent(),'Disconnected','A late load event must not undo manual Disconnect');

    // An idle status check that began before a new connection is not evidence
    // that the newly connected stream is stale.
    mainLive=false;
    const idleMainResponse = holdDeviceResponse();
    await page.evaluate(()=>{window.heldDeviceCheck=fetchDevices();});
    await idleMainResponse;
    mainLive=true;
    await page.locator('#sharedDetectionConnect').click();
    await page.waitForFunction(()=>document.getElementById('availability-main').textContent==='Live');
    assert(releaseDevices,'The fixture must hold the earlier idle status response');
    releaseDevices();
    await page.evaluate(()=>window.heldDeviceCheck);
    assert.equal(await page.locator('#availability-main').textContent(),'Live','An older idle response must not tear down a new connection');
    assert.equal(mainRequests,3);

    await page.locator('#camStream').evaluate(image=>image.dispatchEvent(new Event('error')));
    await page.evaluate(()=>{
      pendingClip={};
      window.authCallback('SIGNED_OUT',null);
    });
    await page.waitForTimeout(5500);
    assert.equal(mainRequests,3,'Ending the local session must cancel Main retries');
    assert.equal(await page.locator('#camStream').getAttribute('data-viewer'),null);
    const beforeDiagnostic=mainRequests;
    const origin=new URL(process.env.UI_TEST_URL||'http://127.0.0.1:5051/').origin;
    await page.goto(origin+'/testing#diagnostics');
    await page.waitForFunction(()=>document.getElementById('testingSession').textContent.startsWith('Signed in.'));
    assert.equal(mainRequests,beforeDiagnostic,'Internal guide must never start video automatically');
    await page.locator('#testingStartCameras').click();
    await page.waitForFunction(()=>document.getElementById('testingMainCamera').dataset.frameSequence&&document.getElementById('testingNightCamera').dataset.frameSequence);
    assert.equal(mainRequests,beforeDiagnostic+1);
    await page.locator('#testingSaveDiagnostics').click();
    await page.waitForFunction(()=>document.getElementById('testingDiagnosticResult').textContent.startsWith('Saved locally.'));
    assert.match(await page.locator('#testingDiagnosticResult').textContent(),/Main: connected; Night: connected/);
    await page.locator('#testingStopCameras').click();
    assert.equal(await page.locator('#testingMainCamera').getAttribute('data-viewer'),null);
    assert.equal(await page.locator('#testingNightCamera').getAttribute('data-viewer'),null);
    for(const width of [320,390,768,1440]){
      await page.setViewportSize({width,height:900});
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`Internal video test overflow at ${width}`);
    }
    assert.deepEqual(errors,[]);
    cameraFrames.assertSerial();
    console.log('PASS: Main automatic recovery, stale-frame clearing, background retry, retained Night stream, manual Disconnect, Main/Night idle-response fencing and session cancellation.');
  } finally {
    await browser.close();
  }
})().catch(error=>{console.error(error);process.exit(1)});
