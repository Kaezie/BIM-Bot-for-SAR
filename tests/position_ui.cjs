const {chromium} = require('playwright');
const assert = require('node:assert/strict');

// All coordinates and authentication are generated fixtures. No receiver,
// personal location, map service, microphone or robot is contacted.
(async()=>{
  const browser=await chromium.launch({headless:true,
    ...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});
  try {
    const origin=new URL(process.env.UI_TEST_URL||'http://127.0.0.1:5051/').origin;
    const page=await browser.newPage({viewport:{width:1440,height:1050}});
    const errors=[],mapRequests=[];
    page.on('pageerror',error=>errors.push(error.message));
    await page.addInitScript(()=>{
      window.locationFixtureCalls=0;
      navigator.geolocation.getCurrentPosition=()=>{window.locationFixtureCalls++;throw new Error('Personal location forbidden');};
      navigator.geolocation.watchPosition=()=>{window.locationFixtureCalls++;throw new Error('Personal location forbidden');};
      navigator.mediaDevices.getUserMedia=()=>{throw new Error('Audio capture forbidden in position tests');};
    });
    await page.route('**/*',route=>{
      const url=new URL(route.request().url());
      if(url.hostname.endsWith('openstreetmap.org'))mapRequests.push(url.hostname);
      return url.origin===origin?route.continue():route.abort();
    });
    await page.route('**/static/js/auth.js',route=>route.fulfill({contentType:'application/javascript',body:`
      window.BIM_AUTH={auth:{getSession:async()=>({data:{session:{local:true,user:{email:'position-fixture@example.test'}}}}),
      onAuthStateChange:callback=>{window.expirePositionFixture=()=>callback('SIGNED_OUT',null);},signOut:async()=>({error:null})}};`}));
    let mode='missing',freezeAt,hold=false,release,held=false,active=0,maxActive=0;
    const sample=()=>({configured:true,connected:true,fresh:true,frame:'wgs84',source:'Generated GPS fixture',
      fix_valid:true,latitude:0,longitude:0,updated_at:mode==='frozen'?freezeAt:Date.now()/1000-.1,
      sample_age_ms:100,sequence:7,satellites:8,horizontal_accuracy_m:4.5,simulated:false});
    await page.route('**/api/**',async route=>{
      const path=new URL(route.request().url()).pathname;
      const now=Date.now()/1000;
      if(path==='/api/position-data') {
        active++;maxActive=Math.max(maxActive,active);
        try {
          if(hold){hold=false;held=true;await new Promise(resolve=>{release=resolve;});}
          if(mode==='failure')return await route.fulfill({status:503,contentType:'application/json',body:'{}'});
          let data=sample();
          if(mode==='missing')data={configured:false,connected:false,fresh:false};
          if(mode==='no-fix')data={...data,fix_valid:false,fresh:false,satellites:2};
          if(mode==='local')data={configured:true,connected:true,fresh:true,frame:'local_meters',source:'Generated local tracker',x:1.25,y:-2.5,updated_at:now};
          if(mode==='stale')data.updated_at-=20;
          if(mode==='invalid')data.latitude=200;
          if(mode==='simulated')data.simulated=true;
          if(mode==='untrusted')data.source='<img src=x onerror="window.injected=true">';
          await route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
        } finally {active--;}
        return;
      }
      const data={
        '/api/device-status':{nightvision:false},
        '/api/sensor-data':{fresh:true,updated_at:now,temperature:26,humidity:70,heat_index:27},
        '/api/survivors':{available:true,updated_at:now,survivors_found:0,detections:[]},
        '/api/thermal-data':{configured:false,connected:false},'/api/sound-data':{configured:false,connected:false},
        '/api/history':{samples:[],alerts:[]},'/api/mission':{mission:null,can_start:false,control_configured:false,robot:{fresh:false}},
        '/api/survivor-events':{events:[]},'/api/local-recordings':{recordings:[],pending_count:0,has_more:false},
        '/api/nightvision/light':{supported:false}
      }[path]||{};
      return route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
    });
    await page.goto(origin,{waitUntil:'domcontentloaded'});
    await page.locator('#missionTools > summary').click();
    await page.waitForFunction(()=>document.getElementById('positionState').textContent==='Not configured');
    assert.equal(await page.locator('#positionFirst').textContent(),'—');
    assert(await page.locator('#positionMap').isHidden());
    async function refresh(next) {
      mode=next;
      await page.locator('#refreshBtn').click();
      await page.waitForFunction(()=>!document.getElementById('refreshBtn').disabled);
    }
    await refresh('gps');
    await page.waitForFunction(()=>document.getElementById('positionState').textContent==='GPS fix');
    assert.equal(await page.locator('#positionFirst').textContent(),'0.000000');
    assert.equal(await page.locator('#positionSecond').textContent(),'0.000000');
    assert.match(await page.locator('#positionQuality').textContent(),/8 satellites.*4.5 m/);
    assert.match(await page.locator('#positionMap').getAttribute('href'),/^https:\/\/www\.openstreetmap\.org\//);
    assert.equal(await page.locator('#positionMap').getAttribute('rel'),'noopener noreferrer');
    await page.locator('#robotPosition').scrollIntoViewIfNeeded();
    await page.screenshot({path:'/private/tmp/bimbot-position-desktop-fixture.png',fullPage:false});

    await refresh('no-fix');
    assert.equal(await page.locator('#positionState').textContent(),'No GPS fix');
    assert.equal(await page.locator('#positionFirst').textContent(),'—');
    assert.equal(await page.locator('#positionMap').getAttribute('href'),null);
    await refresh('local');
    assert.equal(await page.locator('#positionState').textContent(),'Local position');
    assert.equal(await page.locator('#positionFirstLabel').textContent(),'Local X');
    assert.equal(await page.locator('#positionFirst').textContent(),'1.25 m');
    assert.equal(await page.locator('#positionSecond').textContent(),'-2.50 m');
    assert(await page.locator('#positionMap').isHidden());
    for(const unavailable of ['stale','invalid','failure']) {
      await refresh(unavailable);
      assert.equal(await page.locator('#positionState').textContent(),'Unavailable');
      assert.equal(await page.locator('#positionFirst').textContent(),'—');
      assert.equal(await page.locator('#positionMap').getAttribute('href'),null);
    }
    await refresh('simulated');
    assert.match(await page.locator('#positionState').textContent(),/^SIMULATED/);
    assert(await page.locator('#positionMap').isHidden());
    await refresh('untrusted');
    assert.equal(await page.locator('#positionSource img').count(),0);
    assert.equal(await page.evaluate(()=>window.injected),undefined);

    freezeAt=Date.now()/1000;await refresh('frozen');
    hold=true;
    await page.waitForFunction(()=>document.getElementById('positionState').textContent==='Stale',null,{timeout:8000});
    assert(held,'The outstanding position request must exercise expiry during slow transport');
    assert.equal(maxActive,1,'Position polls must stay single-flight');
    assert.equal(await page.locator('#positionFirst').textContent(),'—');
    mode='local';release();
    await page.waitForFunction(()=>document.getElementById('positionState').textContent==='Local position');
    for(const width of [320,390,768,1440]) {
      await page.setViewportSize({width,height:900});
      await page.locator('#robotPosition').scrollIntoViewIfNeeded();
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`Position layout overflow at ${width}`);
      if(width===390)await page.screenshot({path:'/private/tmp/bimbot-position-mobile-fixture.png',fullPage:false});
    }
    // A late successful response after session expiration must not repaint a
    // private position. An unsaved fixture clip prevents automatic navigation.
    hold=true;held=false;
    const refreshPromise=page.locator('#refreshBtn').click();
    await refreshPromise;
    await page.waitForTimeout(150);
    assert(held);
    await page.evaluate(()=>{pendingClip={};window.expirePositionFixture();});
    mode='gps';release();
    await page.waitForFunction(()=>document.getElementById('positionState').textContent==='Sign in');
    assert.equal(await page.locator('#positionMap').getAttribute('href'),null);
    assert.equal(await page.evaluate(()=>locationFixtureCalls),0);
    assert.deepEqual(mapRequests,[],'No map tiles or coordinates may be sent automatically');
    assert.deepEqual(errors,[]);
    console.log('Position UI: missing hardware, GPS/no-fix/local frames, invalid/stale clearing, source expiry, single-flight, map privacy, source escaping, session end and responsive layout pass.');
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
