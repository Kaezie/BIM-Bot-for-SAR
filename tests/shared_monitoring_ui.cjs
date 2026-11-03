const {chromium} = require('playwright');
const {cameraFrameFixture}=require('./camera_frame_fixture.cjs');
const assert = require('node:assert/strict');

// All identities, sensor samples and camera frames in this suite are fixtures.
// It never authenticates against a cloud service or contacts robot hardware.
(async () => {
  const browser = await chromium.launch({
    headless:true,
    ...(process.env.CHROME_PATH ? {executablePath:process.env.CHROME_PATH} : {})
  });
  try {
    const page = await browser.newPage({viewport:{width:1440,height:1050}});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const frame = Buffer.from(await page.evaluate(() => {
      const canvas = document.createElement('canvas');
      canvas.width=640; canvas.height=480;
      canvas.getContext('2d').fillRect(0,0,640,480);
      return canvas.toDataURL('image/jpeg',0.8).split(',')[1];
    }), 'base64');
    let mode = 'fresh', detected = 2, mainRequests = 0, lightEnabled = false;
    const cameraFrames=cameraFrameFixture(frame,{onOpen:source=>{if(source==='main')mainRequests++;}});
    await page.route('**/static/js/auth.js', route => route.fulfill({
      contentType:'application/javascript',
      body:`window.BIM_AUTH={auth:{
        getSession:async()=>({data:{session:{local:true,user:{email:'fixture@example.test'}}}}),
        onAuthStateChange:()=>{},signOut:async()=>({error:null})
      }};`
    }));
    await page.route('**/api/**', route => {
      if(cameraFrames.matches(route))return cameraFrames.handle(route);
      const path = new URL(route.request().url()).pathname;
      const now = Date.now()/1000, updated = now-(mode==='stale'?30:0);
      if (mode==='unavailable' && ['/api/sensor-data','/api/survivors','/api/thermal-data','/api/sound-data'].includes(path)) {
        return route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'Fixture sensor unavailable'})});
      }
      let data = {};
      if (path==='/api/sensor-data') data={fresh:mode!=='stale',updated_at:updated,temperature:36,humidity:72,heat_index:43,danger_level:'Danger',interpretation:'Fixture heat warning',method:'threshold',confidence:.8,probabilities:{low:.1,moderate:.8,severe:.1}};
      if (path==='/api/survivors') data={available:true,updated_at:updated,survivors_found:detected,detections:detected?[{confidence:.94,age:'Adult',consciousness:'Unknown',injury:'Unknown',trapped:'Unknown',pose:'upright',thermal_alive:'No thermal camera',thermal_injury:'No thermal camera'}]:[]};
      if (path==='/api/device-status') data={nightvision:true,main_status:{connected:mainRequests>0},nightvision_status:{connected:true,detection_enabled:true,detections_available:true,detections:[{source:'nightvision',confidence:.8}],message:'Fixture night camera ready'}};
      if (path==='/api/nightvision/light') {
        if(route.request().method()==='POST') lightEnabled=route.request().postDataJSON().enabled;
        data={supported:true,available:true,firmware:'bimbot-nightvision/2',illumination:{enabled:lightEnabled,brightness:lightEnabled?32:0,lease_ms:15000}};
      }
      if (path==='/api/thermal-data') data=mode==='not-installed'?{configured:false,connected:false}:{configured:true,connected:true,simulated:true,updated_at:updated,grid:Array.from({length:24},()=>Array(32).fill(24)),min_temp:24,max_temp:38.5};
      if (path==='/api/sound-data') data=mode==='not-installed'?{configured:false,connected:false}:{configured:true,connected:true,simulated:true,updated_at:updated,db_level:67,classification:'Fixture sound'};
      if (path==='/api/history') data={samples:[],alerts:[]};
      if (path==='/api/mission') data={mission:null,can_start:false,control_configured:false,robot:{fresh:false}};
      if (path==='/api/survivor-events') data={events:[]};
      if (path==='/api/local-recordings') data={recordings:[],pending_count:0,has_more:false};
      return route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
    });
    await page.goto(process.env.UI_TEST_URL || 'http://127.0.0.1:5051/');
    await page.waitForFunction(()=>document.getElementById('survivorCount').textContent==='2' && document.getElementById('soundSummaryLevel').textContent.includes('67.0'));
    const shared = ['#survivorCard','.sensors-card','#riskCard','#mainThermalReading','#soundSummary'];
    const overlaps = (a,b) => a.x < b.x+b.width-1 && a.x+a.width > b.x+1 && a.y < b.y+b.height-1 && a.y+a.height > b.y+1;
    async function checkSharedLayout(width, feed, height=1050) {
      await page.evaluate(()=>scrollTo(0,0));
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`Horizontal overflow at ${width}px on ${feed}`);
      const imageBox = await page.locator('.feed-stage').boundingBox();
      if(width===1440) {
        const consoleBox=await page.locator('#monitor').boundingBox();
        const headerBox=await page.locator('.app-header').boundingBox();
        const tabsBox=await page.locator('.feed-tabs').boundingBox();
        const environmentBox=await page.locator('.sensors-card').boundingBox();
        const instrumentsBox=await page.locator('#riskCard').boundingBox();
        assert(Math.abs(consoleBox.x)<=1 && Math.abs(consoleBox.width-width)<=1,'The original camera console must span the desktop viewport');
        assert(Math.abs(consoleBox.y-(headerBox.y+headerBox.height))<=1,'The console must begin directly below the app header');
        assert(Math.abs(consoleBox.y+consoleBox.height-height)<=1,`The desktop console must fit below the header without a tall page of cards: ${JSON.stringify({consoleBox,headerBox})}`);
        assert(Math.abs(tabsBox.x-consoleBox.x)<=1 && Math.abs(tabsBox.width-consoleBox.width)<=1,'The original feed tabs must remain full width');
        assert(Math.abs(tabsBox.y+tabsBox.height-consoleBox.y-consoleBox.height)<=1,'Feed tabs must remain at the bottom edge of the console');
        assert(environmentBox.x+environmentBox.width<=imageBox.x+1,'Environment HUD must stay to the left of the central feed');
        assert(instrumentsBox.x>=imageBox.x+imageBox.width-1,'Instrument HUD must stay to the right of the central feed');
        assert(imageBox.width>=width*.45,'The camera must remain the central, dominant desktop view');
      }
      for (const selector of shared) {
        const item=page.locator(selector);
        assert(await item.isVisible(),`${selector} must remain visible on ${feed}`);
        const box=await item.boundingBox();
        assert(!overlaps(box,imageBox),`${selector} must not cover ${feed} imagery at ${width}px`);
      }
      for (let first=0;first<shared.length;first++) {
        for (let second=first+1;second<shared.length;second++) {
          assert(!overlaps(await page.locator(shared[first]).boundingBox(),await page.locator(shared[second]).boundingBox()),`${shared[first]} overlaps ${shared[second]} at ${width}px on ${feed}`);
        }
      }
      const summary=await page.locator('#survivorCard').boundingBox();
      assert(summary.y+summary.height<=imageBox.y+1,`Survivor telemetry must stay above ${feed} imagery at ${width}px`);
      assert(await page.locator('#survivorSource').isVisible(),'The count source must be visible');
      assert.match(await page.locator('#survivorSource').textContent(),/Main camera/i);
      assert(await page.locator('#detectionState').isVisible(),'Detection freshness must be visible');
      assert.equal(await page.locator('#survivorCount').textContent(),'2','The main count must not include the spare camera result');
      assert.equal(await page.locator('#tempDisplay').textContent(),'36.0');
      assert.equal(await page.locator('#mainThermalRange').textContent(),'24.0–38.5 °C');
      assert.match(await page.locator('#mainThermalState').textContent(),/SIMULATED/);
      assert.match(await page.locator('#soundSummaryLevel').textContent(),/67\.0/);
      assert.match(await page.locator('#soundSummaryState').textContent(),/SIMULATED/);
      if(feed==='nightvision') {
        const controls=await page.locator('.night-light-controls').boundingBox();
        for(const selector of shared) assert(!overlaps(await page.locator(selector).boundingBox(),controls),`${selector} overlaps white-light controls at ${width}px`);
        assert.match(await page.locator('#nvDetectionStatus').textContent(),/1 possible person/);
      }
      if(feed==='thermal') {
        for(const selector of ['#panel-thermal .empty-symbol','#thermalGrid']) {
          const box=await page.locator(selector).boundingBox();
          assert(box && box.width>0 && box.height>0,`${selector} must have visible area at ${width}px`);
          assert(box.x>=imageBox.x-1 && box.y>=imageBox.y-1 && box.x+box.width<=imageBox.x+imageBox.width+1 && box.y+box.height<=imageBox.y+imageBox.height+1,`${selector} must fit completely inside the thermal stage at ${width}px`);
        }
        const grid=await page.locator('#thermalGrid').boundingBox();
        assert(Math.abs(grid.height-grid.width*3/4)<=1,`The complete thermal grid must retain its 4:3 aspect ratio at ${width}px: ${JSON.stringify(grid)}`);
        assert.deepEqual(await page.locator('#thermalGrid').evaluate(canvas=>[canvas.width,canvas.height]),[32,24],'The heatmap must preserve every original sensor pixel');
        const available=await page.locator('.thermal-viewport').boundingBox();
        const fittedWidth=Math.min(available.width,available.height*4/3);
        assert(grid.width>=fittedWidth-1,`The heatmap must fill the available image area instead of keeping a small cap at ${width}x${height}`);
        assert(!overlaps(await page.locator('.thermal-caption').boundingBox(),grid),'The thermal status must not cover sensor pixels');
        if(width===1440) {
          assert(grid.y+grid.height<=height-68+1,'The full thermal image must remain above the bottom tabs in a short desktop window');
          if(height===1050) assert(grid.width>800,'The desktop heatmap must grow beyond the previous 420px cap');
        }
      }
    }
    // Beginning on a sensor tab must not silently subscribe to the main camera.
    await page.locator('#tab-sound').click();
    await page.locator('#tab-thermal').click();
    await page.locator('#tab-nightvision').click();
    await page.waitForFunction(()=>document.getElementById('availability-nightvision').textContent==='Live');
    assert.equal(mainRequests,0,'Other monitoring tabs must respect an unconnected main camera');
    assert(await page.locator('#sharedDetectionConnect').isVisible());
    await page.locator('#sharedDetectionConnect').click();
    await page.waitForFunction(()=>document.getElementById('availability-main').textContent==='Live');
    assert.equal(await page.locator('#monitor').getAttribute('data-active-feed'),'nightvision','Connecting main detection must retain the selected view');
    assert.equal(mainRequests,1);
    const mainSource=await page.locator('#camStream').getAttribute('data-viewer');
    for (const width of [320,390,768,1440]) {
      await page.setViewportSize({width,height:1050});
      for (const feed of ['main','nightvision','thermal','sound']) {
        await page.locator(`#tab-${feed}`).click();
        await checkSharedLayout(width,feed);
        assert.equal(await page.locator('#camStream').getAttribute('data-viewer'),mainSource,'Main detection subscription must continue across views');
        if(feed==='nightvision' && [320,1440].includes(width)) await page.screenshot({path:`/tmp/bimbot-shared-monitoring-${width}.png`,fullPage:true});
        if(feed==='thermal' && width===320) await page.screenshot({path:'/tmp/bimbot-shared-thermal-320-fixed.png',fullPage:true});
      }
    }
    for(const height of [720,650]) {
      await page.setViewportSize({width:1440,height});
      await page.locator('#tab-thermal').click();
      await checkSharedLayout(1440,'thermal',height);
    }
    await page.setViewportSize({width:1440,height:1050});
    assert.equal(mainRequests,1,'Tab changes must reuse the existing main-camera stream');
    await page.locator('#tab-main').click();
    await page.locator('#disconnectBtn').click();
    for (const feed of ['thermal','sound','nightvision']) await page.locator(`#tab-${feed}`).click();
    await page.evaluate(()=>refreshAll());
    assert.equal(await page.locator('#camStream').getAttribute('data-viewer'),null);
    assert.equal(mainRequests,1,'Refresh and sensor tabs must preserve manual main-camera Disconnect');
    assert(await page.locator('#sharedDetectionConnect').isVisible());

    detected=0;
    await page.evaluate(()=>refreshAll());
    assert.equal(await page.locator('#survivorCount').textContent(),'0','A fresh empty detection result is zero');
    assert.equal(await page.locator('#detectionState').textContent(),'Live');
    mode='stale';
    await page.evaluate(()=>refreshAll());
    assert.equal(await page.locator('#survivorCount').textContent(),'—','Old empty results must become unknown, not zero');
    assert.equal(await page.locator('#survivorConf').textContent(),'—');
    for (const selector of ['#tempDisplay','#humDisplay','#hiDisplay','#mainThermalRange','#soundSummaryLevel']) assert.equal(await page.locator(selector).textContent(),'—',`${selector} must clear when stale`);
    assert.equal(await page.locator('#riskLevel').textContent(),'Assessment unavailable');
    assert(await page.locator('#thermalGrid').isHidden());
    assert(await page.locator('#soundMeter').isHidden());
    mode='fresh'; detected=2;
    await page.evaluate(()=>refreshAll());
    assert.equal(await page.locator('#survivorCount').textContent(),'2');
    mode='unavailable';
    await page.evaluate(()=>refreshAll());
    for(const selector of ['#survivorCount','#survivorConf','#soundSummaryLevel']) assert.equal(await page.locator(selector).textContent(),'—',`${selector} must clear after request failure`);
    assert.equal(await page.locator('#tempDisplay').textContent(),'36.0');
    assert.equal(await page.locator('#sensorState').textContent(),'Retrying');
    assert.equal(await page.locator('#mainThermalRange').textContent(),'24.0–38.5 °C');
    assert.equal(await page.locator('#availability-thermal').textContent(),'Updating');
    mode='not-installed';
    await page.evaluate(()=>refreshAll());
    assert.equal(await page.locator('#mainThermalRange').textContent(),'—');
    assert.equal(await page.locator('#soundSummaryLevel').textContent(),'—');
    assert.equal(await page.locator('#availability-thermal').textContent(),'Not installed');
    assert.equal(await page.locator('#availability-sound').textContent(),'Not installed');
    assert.deepEqual(errors,[]);
    cameraFrames.assertSerial();
    console.log('PASS: shared monitoring telemetry across four tabs, responsive separation, source labels, manual main-camera connection, stream retention and stale/unavailable clearing.');
  } finally {
    await browser.close();
  }
})().catch(error=>{console.error(error);process.exit(1);});
