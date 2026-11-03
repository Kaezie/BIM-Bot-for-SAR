const {chromium} = require('playwright');
const assert = require('node:assert/strict');

// All readings and identities are fixtures. Only the hardware-free preview's
// HTML, CSS and JavaScript are loaded; robot and cloud requests are intercepted.
(async () => {
  const browser = await chromium.launch({
    headless: true,
    ...(process.env.CHROME_PATH ? {executablePath: process.env.CHROME_PATH} : {})
  });
  try {
    const preview = process.env.UI_TEST_URL || 'http://127.0.0.1:5051/';
    const previewOrigin = new URL(preview).origin;
    const page = await browser.newPage({viewport: {width: 1440, height: 1050}});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/*', route => {
      const url = new URL(route.request().url());
      return url.origin === previewOrigin ? route.continue() : route.abort();
    });
    await page.route('**/static/js/auth.js', route => route.fulfill({
      contentType: 'application/javascript',
      body: `window.BIM_AUTH={auth:{
        getSession:async()=>({data:{session:{local:true,user:{email:'thermal-fixture@example.test'}}}}),
        onAuthStateChange:()=>{},signOut:async()=>({error:null})
      }};`
    }));

    let releaseDevices;
    const devicesGate = new Promise(resolve => { releaseDevices = resolve; });
    let deviceReplies = 0, deviceRequests = 0;
    let mode = 'fresh', minimum = 26, maximum = 30, sequence = 100, hotSpot = false;
    let thermalRequests = 0, thermalReplies = 0, activeThermal = 0, maximumActiveThermal = 0;
    let holdNextThermal = false, releaseThermal, thermalHeld = false;
    let lastFrame, olderFrame, jitterFrame, fixedFrame;

    const freshFrame = () => {
      const grid = Array.from({length: 24}, () => Array(32).fill(minimum));
      grid[0][0] = hotSpot ? maximum : minimum;
      grid[23][31] = maximum;
      return {configured: true, connected: true, fresh: true, simulated: false,
        sequence: sequence++, frame_age_ms: 100, updated_at: Date.now()/1000 - .1,
        min_temp: minimum, max_temp: maximum, grid};
    };
    await page.route('**/api/**', async route => {
      const path = new URL(route.request().url()).pathname;
      if (path === '/api/device-status') {
        deviceRequests++;
        await devicesGate;
        deviceReplies++;
        return route.fulfill({contentType: 'application/json', body: JSON.stringify({nightvision: false})});
      }
      if (path === '/api/thermal-data') {
        thermalRequests++;
        activeThermal++;
        maximumActiveThermal = Math.max(maximumActiveThermal, activeThermal);
        try {
          if (holdNextThermal) {
            holdNextThermal = false;
            thermalHeld = true;
            await new Promise(resolve => { releaseThermal = resolve; });
          }
          let data;
          if (mode === 'older') data = olderFrame;
          else if (mode === 'jitter') data = jitterFrame;
          else if (mode === 'fixed') data = fixedFrame;
          else {
            data = freshFrame();
            if (mode === 'stale') { data.updated_at -= 6; data.frame_age_ms = 6100; }
            if (mode === 'invalid') data.grid[23][31] = null;
          }
          lastFrame = data;
          await route.fulfill({contentType: 'application/json', body: JSON.stringify(data)});
          thermalReplies++;
        } finally {
          activeThermal--;
        }
        return;
      }
      const now = Date.now()/1000;
      const data = {
        '/api/sensor-data': {fresh: true, updated_at: now, temperature: 26, humidity: 70, heat_index: 27},
        '/api/survivors': {available: true, updated_at: now, survivors_found: 0, detections: []},
        '/api/sound-data': {configured: false, connected: false},
        '/api/mission': {mission: null, can_start: false, control_configured: false, robot: {fresh: false}},
        '/api/survivor-events': {events: []},
        '/api/history': {samples: [], alerts: []},
        '/api/local-recordings': {recordings: [], pending_count: 0, has_more: false},
        '/api/nightvision/light': {supported: false}
      }[path] || {};
      return route.fulfill({contentType: 'application/json', body: JSON.stringify(data)});
    });

    await page.goto(preview, {waitUntil: 'domcontentloaded'});
    await page.locator('#tab-thermal').click();
    await page.waitForFunction(() => document.getElementById('mainThermalRange').textContent === '26.0–30.0 °C', null, {timeout: 1800});
    assert.equal(deviceReplies, 0, 'Thermal must render while unrelated camera-status requests are still pending');
    assert(deviceRequests > 0, 'The delayed status fixture must have been exercised');
    const firstReplies = thermalReplies;
    await page.waitForFunction(() => document.getElementById('thermalGrid').width === 32 && document.getElementById('thermalGrid').height === 24);
    await page.evaluate(() => {
      window.thermalFixtureCanvas = document.getElementById('thermalGrid');
      window.thermalFixtureFirstColor = Array.from(window.thermalFixtureCanvas.getContext('2d').getImageData(0,0,1,1).data).join(',');
    });
    const nextThermalDeadline=Date.now()+2000;
    while(thermalReplies<=firstReplies&&Date.now()<nextThermalDeadline)await page.waitForTimeout(25);
    assert(thermalReplies > firstReplies, 'Conservative thermal polling must continue while unrelated status is pending');
    assert.equal(deviceReplies,0,'A held status response must not gate thermal polling');

    releaseDevices();
    await page.waitForFunction(() => !document.getElementById('refreshBtn').disabled);
    minimum = 27; maximum = 33; hotSpot = true;
    await page.waitForFunction(() => document.getElementById('mainThermalRange').textContent === '27.0–33.0 °C');
    assert(await page.evaluate(() => window.thermalFixtureCanvas === document.getElementById('thermalGrid')),
      'Updating temperatures must reuse the same 32×24 thermal canvas');
    assert.deepEqual(await page.locator('#thermalGrid').evaluate(canvas=>[canvas.width,canvas.height]),[32,24]);
    assert(await page.evaluate(() => Array.from(window.thermalFixtureCanvas.getContext('2d').getImageData(0,0,1,1).data).join(',') !== window.thermalFixtureFirstColor),
      'The retained cells must paint newly received thermal pixels');
    assert(await page.locator('#thermalGrid').isVisible());
    assert.deepEqual(await page.locator('#thermalGrid').evaluate(canvas=>Array.from(canvas.getContext('2d').getImageData(0,0,1,1).data)),[236,19,19,255],'Maximum temperature must render red with no interpolated pixels');

    // A manual refresh must join an existing thermal request, rather than queue
    // a second response which could paint over a more recent acquisition.
    holdNextThermal = true;
    const heldDeadline = Date.now() + 3000;
    while (!thermalHeld && Date.now() < heldDeadline) await page.waitForTimeout(25);
    assert(thermalHeld, 'The slow thermal fixture must have been exercised');
    await page.locator('#refreshBtn').click();
    await page.waitForTimeout(300);
    assert.equal(activeThermal, 1);
    assert.equal(maximumActiveThermal, 1, 'Thermal polling and manual refresh must never overlap requests');
    minimum = 28; maximum = 34;
    releaseThermal();
    await page.waitForFunction(() => document.getElementById('mainThermalRange').textContent === '28.0–34.0 °C');
    const acceptedFrame = lastFrame;

    // Return an older, still-fresh acquisition with deliberately different
    // temperatures; it must not replace the latest accepted sensor frame.
    olderFrame = {...acceptedFrame, sequence: acceptedFrame.sequence - 1, updated_at: acceptedFrame.updated_at - .3,
      grid: Array.from({length: 24}, () => Array(32).fill(5)), min_temp: 5, max_temp: 6};
    mode = 'older';
    const beforeOlder = thermalReplies;
    const olderDeadline = Date.now() + 2500;
    while (thermalReplies < beforeOlder + 2 && Date.now() < olderDeadline) await page.waitForTimeout(25);
    assert(thermalReplies >= beforeOlder + 2);
    assert.equal(await page.locator('#mainThermalRange').textContent(), '28.0–34.0 °C', 'Older acquisitions must not roll the displayed temperatures backward');

    // A conservative transport-age estimate can move backward even when the
    // hardware sequence advances. That new image must not be silently skipped.
    const jitterGrid = Array.from({length: 24}, () => Array(32).fill(28.5));
    jitterGrid[23][31] = 34.5;
    jitterFrame = {...acceptedFrame, sequence: acceptedFrame.sequence + 1,
      updated_at: acceptedFrame.updated_at - .2, grid: jitterGrid, min_temp: 28.5, max_temp: 34.5};
    mode = 'jitter';
    await page.waitForFunction(() => document.getElementById('mainThermalRange').textContent === '28.5–34.5 °C', null, {timeout: 1800});
    assert(await page.locator('#thermalGrid').isVisible(), 'A newer valid sensor sequence must survive conservative timestamp jitter');
    sequence = jitterFrame.sequence + 1;

    mode = 'invalid';
    await page.waitForFunction(() => document.getElementById('thermalGrid').hidden && document.getElementById('mainThermalRange').textContent === '—');
    mode = 'fresh'; minimum = 29; maximum = 35;
    await page.waitForFunction(() => document.getElementById('mainThermalRange').textContent === '29.0–35.0 °C');
    assert(await page.evaluate(() => window.thermalFixtureCanvas === document.getElementById('thermalGrid')),
      'Recovery from invalid data must retain the reusable heatmap cells');
    mode = 'stale';
    await page.waitForFunction(() => document.getElementById('thermalGrid').hidden && document.getElementById('mainThermalRange').textContent === '—');
    assert.equal(await page.locator('#availability-thermal').textContent(), 'Waiting', 'A six-second-old acquisition must not appear live');

    // Repeated receipt of the same source timestamp must not extend freshness.
    mode = 'fresh'; minimum = 30; maximum = 36; sequence = 1;
    await page.waitForFunction(() => document.getElementById('mainThermalRange').textContent === '30.0–36.0 °C');
    fixedFrame = lastFrame;
    mode = 'fixed';
    const fixedReplies = thermalReplies;
    await page.waitForFunction(() => document.getElementById('thermalGrid').hidden && document.getElementById('mainThermalRange').textContent === '—', null, {timeout: 6500});
    assert(thermalReplies > fixedReplies + 2, 'The repeated source timestamp fixture must continue receiving responses');
    assert.equal(maximumActiveThermal, 1);
    assert.deepEqual(errors, []);
    console.log('PASS: thermal updates independently of slow camera status, serial requests, stable32x24pixel rendering, sequence advancement despite timing jitter, older-frame protection, invalid/stale clearing and source-timestamp expiry.');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exit(1); });
