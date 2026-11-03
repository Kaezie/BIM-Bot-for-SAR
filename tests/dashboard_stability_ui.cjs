const {chromium}=require('playwright');
const {cameraFrameFixture}=require('./camera_frame_fixture.cjs');
const assert=require('node:assert/strict');

// Generated feeds and cached sensor fixtures only. No robot/cloud access.
(async()=>{
  const browser=await chromium.launch({headless:true,...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});
  try{
    const page=await browser.newPage({viewport:{width:1440,height:1050}}),errors=[];
    page.on('pageerror',error=>errors.push(error.message));
    const frame=Buffer.from(await page.evaluate(()=>{const c=document.createElement('canvas');c.width=320;c.height=240;return c.toDataURL('image/jpeg').split(',')[1];}),'base64');
    let failFrames=false,thermalRequests=0,sequence=0,sourceStatus=true,diagnosticStarts=0;
    let detectorAvailable=false,detectorAge=0;
    const opens={main:0,nightvision:0};
    const frames=cameraFrameFixture(frame,{fail:()=>failFrames,onOpen:source=>opens[source]++});
    await page.route('**/static/js/auth.js',route=>route.fulfill({contentType:'application/javascript',body:`window.BIM_AUTH={auth:{getSession:async()=>({data:{session:{local:true,user:{email:'fixture@example.test'}}}}),onAuthStateChange:()=>{},signOut:async()=>({error:null})}};`}));
    await page.route('**/api/**',route=>{
      if(frames.matches(route))return frames.handle(route);
      const path=new URL(route.request().url()).pathname,now=Date.now()/1000;
      let data={};
      if(path==='/api/device-status')data={nightvision:true,main_status:{connected:sourceStatus},nightvision_status:{connected:sourceStatus,detection_enabled:false}};
      if(path==='/api/sensor-data')data={fresh:true,updated_at:now,temperature:28,humidity:65,heat_index:29,risk_level:'Low Risk'};
      if(path==='/api/thermal-data'){
        thermalRequests++;
        const grid=Array.from({length:24},()=>Array(32).fill(25));grid[23][31]=35;
        data={configured:true,connected:true,fresh:true,updated_at:now,sequence:++sequence,grid,min_temp:25,max_temp:35};
      }
      if(path==='/api/system-check/recording'){if(route.request().method()==='POST')diagnosticStarts++;data={running:route.request().method()==='POST',saved:false,samples:0};}
      if(path==='/api/survivors')data={available:detectorAvailable,updated_at:now-detectorAge,survivors_found:0,detections:[]};
      if(path==='/api/nightvision/light')data={supported:true,available:true,illumination:{enabled:route.request().postDataJSON().enabled}};
      if(path==='/api/sound-data'||path==='/api/position-data')data={configured:false,connected:false};
      if(path==='/api/history')data={samples:[],alerts:[]};
      if(path==='/api/mission')data={mission:null,can_start:false,robot:{fresh:false}};
      if(path==='/api/survivor-events')data={events:[]};
      if(path==='/api/local-recordings')data={recordings:[],pending_count:0,has_more:false};
      return route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
    });
    await page.goto(process.env.UI_TEST_URL||'http://127.0.0.1:5051/');
    await page.waitForFunction(()=>document.getElementById('availability-nightvision').textContent==='Configured');
    await page.locator('#connectBtn').click();
    await page.waitForFunction(()=>document.getElementById('availability-main').textContent==='Live');
    const main=await page.locator('#camStream').getAttribute('data-viewer');
    detectorAvailable=true;detectorAge=0;await page.evaluate(()=>fetchDetections());
    assert.equal(await page.locator('#survivorCount').textContent(),'0');
    detectorAge=4;await page.evaluate(()=>fetchDetections());
    assert.equal(await page.locator('#survivorCount').textContent(),'—','A delayed four-second result must not outlive the backend two-second detection limit');
    detectorAvailable=false;
    await page.locator('#tab-nightvision').click();
    await page.waitForFunction(()=>document.getElementById('availability-nightvision').textContent==='Live');
    const night=await page.locator('#nvStream').getAttribute('data-viewer');
    for(const feed of ['thermal','main','sound','nightvision','thermal','main','thermal']){
      await page.locator('#tab-'+feed).click();
      assert.equal(await page.locator('#camStream').getAttribute('data-viewer'),main);
      assert.equal(await page.locator('#nvStream').getAttribute('data-viewer'),night);
    }
    assert.deepEqual(opens,{main:1,nightvision:1},'Section switches must retain both camera subscriptions');
    await page.waitForFunction(()=>document.getElementById('mainThermalRange').textContent==='25.0–35.0 °C');
    assert.deepEqual(await page.locator('#thermalGrid').evaluate(c=>Array.from(c.getContext('2d').getImageData(31,23,1,1).data)),[236,19,19,255]);
    failFrames=true;sourceStatus=false;
    await page.evaluate(()=>fetchDevices());
    await page.waitForTimeout(900);
    assert.equal(await page.locator('#camStream').getAttribute('data-viewer'),main);
    assert.equal(await page.locator('#nvStream').getAttribute('data-viewer'),night);
    assert.equal(frames.deletes.length,0,'A brief fault must not tear down either camera');
    failFrames=false;sourceStatus=true;
    await page.waitForFunction(()=>document.getElementById('availability-main').textContent==='Live'&&document.getElementById('availability-nightvision').textContent==='Live');
    assert.equal(await page.locator('#tempDisplay').textContent(),'28.0');
    await page.locator('#tab-main').click();
    const before=thermalRequests;await page.waitForTimeout(1100);
    assert(thermalRequests-before<=3,'Non-thermal views must not poll the full heatmap eight times per second');

    await page.evaluate(()=>{Object.defineProperty(document,'visibilityState',{configurable:true,value:'hidden'});document.dispatchEvent(new Event('visibilitychange'));});
    assert.equal(await page.locator('#camStream').getAttribute('data-viewer'),null);
    assert.equal(await page.locator('#nvStream').getAttribute('data-viewer'),null);
    await page.waitForTimeout(100);const paused=thermalRequests;await page.waitForTimeout(1200);
    assert.equal(thermalRequests,paused,'Hidden dashboards must stop competing for browser request slots');
    await page.evaluate(()=>{Object.defineProperty(document,'visibilityState',{configurable:true,value:'visible'});document.dispatchEvent(new Event('visibilitychange'));});
    await page.waitForFunction(()=>document.getElementById('availability-main').textContent==='Live'&&document.getElementById('availability-nightvision').textContent==='Live');
    assert.deepEqual(opens,{main:2,nightvision:2});
    await page.locator('#tab-nightvision').click();await page.locator('#disconnectBtn').click();
    assert.equal(await page.locator('#nvStream').getAttribute('data-viewer'),null);
    for(const feed of ['thermal','main','nightvision'])await page.locator('#tab-'+feed).click();
    assert.equal(await page.locator('#nvStream').getAttribute('data-viewer'),null,'Manual Night disconnect must remain in effect across sections');
    await page.locator('#connectBtn').click();
    await page.waitForFunction(()=>document.getElementById('availability-nightvision').textContent==='Live');
    const beforeGuide={...opens};
    const origin=new URL(process.env.UI_TEST_URL||'http://127.0.0.1:5051/').origin;
    await page.goto(origin+'/testing#diagnostics');
    await page.waitForFunction(()=>document.getElementById('testingSession').textContent.startsWith('Signed in.'));
    await page.locator('#testingRecordDashboard').click();
    await page.waitForURL(url=>url.pathname==='/'&&url.searchParams.get('view')==='main');
    assert.equal(diagnosticStarts,1);
    assert.deepEqual(opens,beforeGuide,'Starting the internal cache recorder must not start device streams');
    frames.assertSerial();assert.deepEqual(errors,[]);
    await page.screenshot({path:'/tmp/bimbot-stable-dashboard.png'});
    console.log('PASS: retained Main/Night across Thermal, brief fault recovery without teardown, faithful thermal pixels, reduced hidden-view traffic, hidden-browser pause/resume and explicit Night disconnect.');
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
