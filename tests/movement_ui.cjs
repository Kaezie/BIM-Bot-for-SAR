const {chromium}=require('playwright');
const assert=require('node:assert/strict');
// Generated movement records and mocked commands. No robot, GPS or microphone.
(async()=>{
  const browser=await chromium.launch({headless:true,...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});
  try {
    const origin=new URL(process.env.UI_TEST_URL||'http://127.0.0.1:5051/').origin;
    const page=await browser.newPage({viewport:{width:1440,height:1050}});
    const errors=[],commands=[]; let mode='missing',frozenAt;
    page.on('pageerror',error=>errors.push(error.message));
    await page.addInitScript(()=>{
      navigator.mediaDevices.getUserMedia=()=>{throw new Error('Real microphone forbidden');};
      navigator.geolocation.getCurrentPosition=()=>{throw new Error('Personal location forbidden');};
    });
    await page.route('**/*',route=>new URL(route.request().url()).origin===origin?route.continue():route.abort());
    await page.route('**/static/js/auth.js',route=>route.fulfill({contentType:'application/javascript',body:`window.BIM_AUTH={auth:{getSession:async()=>({data:{session:{user:{email:'movement-fixture@example.test'}}}}),onAuthStateChange:()=>{},signOut:async()=>({error:null})}};`}));
    function trace(){return {configured:true,connected:true,fresh:true,source:mode==='untrusted'?'<img src=x onerror="window.injected=true">':'uno_fixture',trace_id:'fixture-1',state:mode==='complete'?'replay_complete':'stopped',current_move:'S',returned_steps:mode==='complete'?2:0,trace_complete:mode!=='incomplete',return_ready:true,control_configured:true,can_return:mode==='ready',can_stop:mode==='returning'||mode==='uncertain'||mode==='frozen',return_state:mode==='returning'?'returning':mode==='uncertain'?'command_uncertain':null,lease_required:mode==='returning',command_id:'fixture-command',updated_at:mode==='frozen'?frozenAt:Date.now()/1000-.1,total_duration_ms:1650,segments:[{direction:'F',duration_ms:1200},{direction:'L',duration_ms:450}]};}
    await page.route('**/api/**',async route=>{
      const path=new URL(route.request().url()).pathname,now=Date.now()/1000;
      if(route.request().method()==='POST') {
        commands.push({path,payload:route.request().postDataJSON()});
        if(path==='/api/return_to_base')mode='returning';
        if(path==='/api/movement/stop')mode='complete';
        return route.fulfill({contentType:'application/json',body:JSON.stringify(trace())});
      }
      if(path==='/api/movement-data') {
        if(mode==='failure')return route.fulfill({status:503,body:'{}',contentType:'application/json'});
        return route.fulfill({contentType:'application/json',body:JSON.stringify(mode==='missing'?{configured:false,fresh:false}:trace())});
      }
      const data={
        '/api/device-status':{nightvision:false},'/api/sensor-data':{fresh:true,updated_at:now,temperature:26,humidity:70,heat_index:27},
        '/api/survivors':{available:true,updated_at:now,survivors_found:0,detections:[]},'/api/thermal-data':{configured:false,connected:false},
        '/api/sound-data':{configured:false,connected:false},'/api/history':{samples:[],alerts:[]},
        '/api/mission':{mission:null,can_start:false,control_configured:false,robot:{fresh:false}},'/api/survivor-events':{events:[]},
        '/api/local-recordings':{recordings:[],pending_count:0,has_more:false},'/api/nightvision/light':{supported:false},'/api/position-data':{configured:false,fresh:false}
      }[path]||{};
      return route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
    });
    await page.goto(origin,{waitUntil:'domcontentloaded'});
    await page.locator('#missionTools > summary').click();
    await page.waitForFunction(()=>document.getElementById('movementState').textContent==='Not configured');
    assert(await page.locator('#movementReturn').isDisabled());
    assert.equal(commands.length,0,'Page load must not command movement');
    mode='ready'; await page.locator('#refreshBtn').click();
    await page.waitForFunction(()=>!document.getElementById('movementReturn').disabled);
    assert.match(await page.locator('#movementList').textContent(),/Forward.*1.20.*Left turn.*0.45/s);
    assert.equal(await page.locator('#movementTime').textContent(),'1.65 s');
    assert.equal(await page.locator('#positionFirst').textContent(),'—','Motor commands must not create GPS fixes');
    await page.locator('#movementReturn').click();
    await page.waitForFunction(()=>!document.getElementById('movementStop').disabled);
    assert.equal(commands[0].path,'/api/return_to_base');
    assert.deepEqual(commands[0].payload,{trace_id:'fixture-1',segment_count:2,total_duration_ms:1650});
    assert(await page.locator('#movementReturn').isDisabled());
    await page.waitForFunction(()=>document.getElementById('movementState').textContent==='returning');
    await page.locator('#movementStop').click();
    await page.waitForFunction(()=>document.getElementById('movementState').textContent==='replay complete');
    assert.match(await page.locator('#movementMessage').textContent(),/arrival.*unverified/);
    assert(await page.locator('#movementReturn').isDisabled());
    mode='uncertain'; await page.locator('#refreshBtn').click();
    await page.waitForFunction(()=>document.getElementById('movementState').textContent==='command uncertain');
    assert(await page.locator('#movementStop').isEnabled());
    mode='untrusted'; await page.locator('#refreshBtn').click();
    await page.waitForFunction(()=>document.getElementById('movementSource').textContent.includes('<img'));
    assert.equal(await page.locator('#movementSource img').count(),0);
    assert.equal(await page.evaluate(()=>window.injected),undefined);
    mode='uncertain';await page.locator('#refreshBtn').click();
    await page.waitForFunction(()=>!document.getElementById('movementStop').disabled);
    mode='frozen';frozenAt=Date.now()/1000-4.8;
    await page.locator('#refreshBtn').click();
    await page.waitForFunction(()=>/Unavailable|Stale/.test(document.getElementById('movementState').textContent));
    assert(await page.locator('#movementReturn').isDisabled());
    mode='failure';await page.locator('#refreshBtn').click();
    await page.waitForFunction(()=>document.getElementById('movementMessage').textContent.includes('Could not retrieve'));
    assert(await page.locator('#movementStop').isEnabled(),'Connection failure must retain Stop for an owned return');
    mode='ready';await page.locator('#refreshBtn').click();
    for(const width of [320,390,768,1440]) {
      await page.setViewportSize({width,height:900});
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`Movement overflow at ${width}`);
    }
    await page.locator('#recordedMovement').scrollIntoViewIfNeeded();
    await page.screenshot({path:'/private/tmp/bimbot-movement-fixture.png',fullPage:false});
    assert.deepEqual(errors,[]);
    console.log('Movement UI: missing/live/stale, real command durations, no invented GPS, acknowledged return/stop, uncertain state, escaped source and responsive layouts pass (fixtures only).');
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
