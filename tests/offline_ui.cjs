const {chromium}=require('playwright');
const {cameraFrameFixture}=require('./camera_frame_fixture.cjs');
const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
(async()=>{
  const browser=await chromium.launch({headless:true,...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});
  const context=await browser.newContext({acceptDownloads:true});
  const page=await context.newPage();const errors=[];page.on('pageerror',error=>errors.push(error.message));
  let localSession={user:{id:'local-operator',email:'operator@example.test'},local:true,access_token:null,expires_at:Date.now()/1000+43200};
  let sdkRequests=0,cloudRequests=0,saveFails=false,saves=0,syncs=0,posts=0,deleteCount=0;
  const clips=[];let mp4;
  const frame=Buffer.from(await page.evaluate(()=>{const c=document.createElement('canvas');c.width=640;c.height=480;c.getContext('2d').fillRect(0,0,640,480);return c.toDataURL('image/jpeg',0.8).split(',')[1];}),'base64');
  const cameraFrames=cameraFrameFixture(frame,{checkRequest:request=>assert.equal(request.headers().authorization,undefined,'Local snapshot requests use cookies without null bearer tokens')});
  await page.route('**/cdn.jsdelivr.net/**',route=>{sdkRequests++;return route.abort();});
  await page.route('**/api/**',route=>{
    if(cameraFrames.matches(route))return cameraFrames.handle(route);
    const request=route.request(),url=new URL(request.url()),method=request.method();
    assert.equal(request.headers().authorization,undefined,'Local cookie requests must not send null/undefined bearer tokens');
    let data={},status=200;const now=Date.now()/1000;
    if(url.pathname==='/api/local-session'){
      if(method==='DELETE'){deleteCount++;localSession=null;}
      if(method==='POST')posts++;
      data={session:localSession};
    }else if(url.pathname==='/api/local-recordings'&&method==='POST'){
      saves++;
      if(saveFails)return route.fulfill({status:500,contentType:'application/json',body:'{"error":"Disk is full"}'});
      const body=request.postDataBuffer();assert(body.includes(Buffer.from('name="source"\r\n\r\nmain')));
      const position=body.indexOf(Buffer.from('ftyp'));assert(position>4,'Upload must contain actual MP4 data');
      mp4=body.subarray(position-4,body.indexOf(Buffer.from('\r\n--'),position));
      const clip={id:'clip-'+saves,name:'bimbot_main_saved.mp4',size:mp4.length,source:'main',created_at:new Date().toISOString(),sync_state:'pending',download_url:'/api/local-recordings/clip-'+saves+'/file'};
      clips.unshift(clip);data={success:true,recording:clip};status=201;
    }else if(url.pathname==='/api/local-recordings/sync'){
      syncs++;clips.forEach(clip=>{clip.sync_state='synced';});data={success:true};status=202;
    }else if(/\/api\/local-recordings\/[^/]+\/file/.test(url.pathname))return route.fulfill({contentType:'video/mp4',headers:{'Content-Disposition':'attachment; filename="bimbot_main_saved.mp4"'},body:mp4});
    else if(url.pathname==='/api/local-recordings')data={recordings:clips.slice(Number(url.searchParams.get('offset')||0)),has_more:false,pending_count:clips.filter(clip=>clip.sync_state!=='synced').length};
    else if(url.pathname==='/api/recordings'){cloudRequests++;return route.fulfill({status:500,contentType:'application/json',body:'{"error":"Cloud is offline"}'});}
    else if(url.pathname==='/api/sensor-data')data={fresh:false};
    else if(url.pathname==='/api/survivors')data={available:false,detections:[]};
    else if(url.pathname==='/api/device-status')data={nightvision:false};
    else if(url.pathname==='/api/thermal-data'||url.pathname==='/api/sound-data')data={configured:false,connected:false};
    else if(url.pathname==='/api/history')data={samples:[],alerts:[]};
    else if(url.pathname==='/api/mission')data={mission:null,can_start:false,control_configured:false,robot:{fresh:false}};
    else if(url.pathname==='/api/survivor-events')data={events:[]};
    return route.fulfill({status,contentType:'application/json',body:JSON.stringify(data)});
  });
  await page.route('**/toggle_recording',route=>route.fulfill({contentType:'application/json',body:'{}'}));
  const root=process.env.UI_TEST_URL||'http://127.0.0.1:5051/';
  await page.goto(root);await page.waitForFunction(()=>document.getElementById('accountEmail').textContent==='operator@example.test');
  assert.equal(await page.evaluate(()=>typeof window.supabase),'undefined');assert.equal(sdkRequests,0);assert.equal(posts,0);assert.equal(cloudRequests,0);
  await page.getByRole('tab',{name:/Main camera/}).click();await page.waitForFunction(()=>!document.getElementById('recordBtn').disabled);
  async function record(){await page.locator('#recordBtn').click();await page.waitForTimeout(1100);await page.locator('#stopBtn').click();}
  await record();await page.waitForFunction(()=>!document.getElementById('closeSave').disabled);
  assert.match(await page.locator('#uploadStatus').textContent(),/Queued for Supabase/);
  assert.equal(clips.length,1);assert.equal(cloudRequests,0);assert.equal(sdkRequests,0);
  const downloadPromise=page.waitForEvent('download');await page.locator('#downloadBtn').click();const backup=await downloadPromise;
  assert.equal((await fs.readFile(await backup.path())).toString('ascii',4,8),'ftyp');
  await page.locator('#closeSave').click();await page.reload();
  await page.waitForFunction(()=>document.querySelectorAll('#recordingList li').length===1);
  assert.match(await page.locator('#recordingList').textContent(),/queued for Supabase/);
  assert.equal(sdkRequests,0,'Reload offline must never depend on CDN cache');
  await page.locator('#missionTools > summary').click();
  await page.locator('#syncRecordings').click();await page.waitForFunction(()=>document.getElementById('recordingList').textContent.includes('in Supabase'));
  assert.equal(syncs,1);assert.equal(clips.length,1,'Sync must retain local files');
  await page.locator('#loadCloudRecordings').evaluate(button=>button.click());await page.waitForFunction(()=>document.getElementById('cloudLibraryStatus').textContent==='Cloud is offline');
  assert.equal(await page.locator('#recordingList li').count(),1,'Cloud failure must not affect local library');
  saveFails=true;await page.getByRole('tab',{name:/Main camera/}).click();await page.waitForFunction(()=>!document.getElementById('recordBtn').disabled);await record();
  await page.waitForFunction(()=>document.getElementById('saveTitle').textContent==='Local save needs attention');
  assert(await page.locator('#closeSave').isDisabled());assert(await page.locator('#retryUpload').isVisible());assert.match(await page.locator('#uploadStatus').textContent(),/Disk is full/);
  const failedDownload=page.waitForEvent('download');await page.locator('#downloadBtn').click();assert.match((await failedDownload).suggestedFilename(),/\.mp4$/);
  saveFails=false;await page.locator('#retryUpload').click();await page.waitForFunction(()=>!document.getElementById('closeSave').disabled);await page.locator('#closeSave').click();
  localSession.expires_at=Date.now()/1000+4;
  await page.reload();await page.getByRole('tab',{name:/Main camera/}).click();await page.waitForFunction(()=>!document.getElementById('recordBtn').disabled);
  await page.locator('#recordBtn').click();
  await page.waitForFunction(()=>document.getElementById('camStream').getAttribute('data-viewer')===null&&document.getElementById('saveDialog').open);
  assert.equal(await page.locator('#nvStream').getAttribute('data-viewer'),null,'Expiry must close both camera streams while preserving captured MP4');
  await page.waitForFunction(()=>!document.getElementById('closeSave').disabled);await page.locator('#closeSave').click();await page.waitForURL('**/login?reason=expired');
  localSession.expires_at=Date.now()/1000+43200;await page.goto(root);await page.waitForFunction(()=>document.getElementById('accountEmail').textContent==='operator@example.test');
  await page.locator('.account > summary').click();
  await page.locator('#logoutBtn').click();await page.waitForURL('**/login');assert.equal(deleteCount,1);
  await page.evaluate(()=>localStorage.setItem('sb-example-auth-token','stale-sdk-token-fixture'));
  await page.reload();await page.waitForFunction(()=>!!window.BIM_AUTH);assert.equal(sdkRequests,0,'Explicit logout blocks stale SDK auto sign-in');
  assert.equal(posts,0);
  await page.evaluate(()=>{localStorage.removeItem('bim-explicit-signout');localStorage.setItem('bim-local-session-expiry',String(Date.now()/1000-1));});
  await page.reload();await page.waitForFunction(()=>!document.getElementById('errorMsg').hidden);assert.match(await page.locator('#errorMsg').textContent(),/local session ended/);assert.equal(sdkRequests,0);
  assert.deepEqual(errors,[]);cameraFrames.assertSerial();console.log('PASS: cookie-first offline bootstrap/reload, no SDK or cloud dependency, local MP4 save+download, durable mock library, pending sync, cloud failure isolation, disk failure retry/backup, offline logout and expiry.');
  await browser.close();
})().catch(error=>{console.error(error);process.exit(1)});
