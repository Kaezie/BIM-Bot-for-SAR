const {chromium}=require('playwright');
const assert=require('node:assert/strict');
(async()=>{
const browser=await chromium.launch({headless:true,...(process.env.CHROME_PATH ? {executablePath:process.env.CHROME_PATH} : {})});const page=await browser.newPage({viewport:{width:1440,height:1050}});const errors=[];page.on('pageerror',error=>errors.push(error.message));
let stale=false,failed=false,uploads=0,mission=null,review=null,reportDownloads=0;
await page.route('**/fonts.googleapis.com/**',route=>route.abort());
await page.route('**/cdn.jsdelivr.net/**',route=>route.fulfill({contentType:'application/javascript',body:`window.supabase={createClient:()=>({auth:{getSession:async()=>({data:{session:{access_token:'preview',user:{email:'rescue@example.test'}}}}),onAuthStateChange:()=>{},signOut:async()=>{}}})}` }));
await page.route('**/api/**',route=>{
const url=new URL(route.request().url()),now=Date.now()/1000;let data={};
if(url.pathname==='/api/sensor-data')data={fresh:!stale,updated_at:now-(stale?30:0),temperature:36,humidity:72,heat_index:43,risk_level:'Moderate Risk',interpretation:'Heat stress likely',method:'threshold',confidence:.8,probabilities:{low:.1,moderate:.8,severe:.1}};
if(url.pathname==='/api/survivors')data={available:!stale,updated_at:now-(stale?30:0),survivors_found:2,detections:[{confidence:.94,age:'Adult',consciousness:'Conscious',injury:'No Visible Injury Indicators',trapped:'Free',pose:'upright',thermal_alive:'No thermal camera',thermal_injury:'No thermal camera'}]};
if(url.pathname==='/api/mission')data={mission,can_start:!mission||mission.state==='stopped',control_configured:true,robot:{fresh:true,navigation_ready:true,simulated:true}};
if(url.pathname==='/api/mission/start'){const payload=route.request().postDataJSON();mission={id:'mission-fixture',state:'searching',area_label:payload.area_label};data={mission};}
if(url.pathname==='/api/mission/stop'){mission.state='stopped';data={mission};}
if(url.pathname==='/api/survivor-events')data={events:mission?[{id:'event-fixture',at:now-30,evidence:{detections:[{confidence:.9,age:'Adult',consciousness:'Conscious',injury:'No Visible Injury Indicators',trapped:'Free',pose:'upright',thermal_alive:'No thermal camera',thermal_injury:'No thermal camera'}],area_label:mission.area_label,environment:{danger_level:'Danger'},observation_position:null},review,reviewed_at:review?now-20:null}]:[]};
if(url.pathname==='/api/survivor-events/event-fixture/review'){review=route.request().postDataJSON();data={review};}
if(url.pathname==='/api/situational-report'){reportDownloads++;data={requires_human_verification:true,mission,events:[]};}
if(url.pathname==='/api/device-status')data={nightvision:false};
if(url.pathname==='/api/thermal-data'||url.pathname==='/api/sound-data')data={connected:false};
if(url.pathname==='/api/history')data={alerts:[{at:now,kind:'detection',message:'2 possible survivors detected. Verify in the feed.'}],samples:Array.from({length:20},(_,i)=>({at:now-60+i*3,temperature:30+i*.3,humidity:70+i*.1,heat_index:32+i*.4}))};
if(url.pathname==='/api/recordings')data={recordings:[{name:'bimbot_mission.webm',size:102400,created_at:new Date().toISOString()}],has_more:false};
if(url.pathname==='/api/upload-to-storage'){uploads++;if(failed)return route.fulfill({status:502,contentType:'application/json',body:JSON.stringify({error:'Cloud unavailable'})});data={success:true};}
return route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
});
await page.route('**/toggle_recording',route=>route.fulfill({contentType:'application/json',body:'{"is_recording":true}'}));
await page.route('**/video_feed?**',route=>route.fulfill({contentType:'image/png',body:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aK30AAAAASUVORK5CYII=','base64')}));
await page.goto((process.env.UI_TEST_URL || 'http://127.0.0.1:5051/'));await page.waitForFunction(()=>document.getElementById('survivorCount').textContent==='2');
assert((await page.locator('#survivorCard').boundingBox()).height < 160, 'Survivor telemetry must remain a compact overlay');
assert.equal(await page.locator('#availability-thermal').textContent(),'Not installed');assert.equal(await page.locator('#recordingList li').count(),1);
assert.equal(await page.locator('#riskLevel').textContent(),'Moderate Risk');
await page.locator('#missionTools > summary').click();
assert.match(await page.locator('#survivorDetailList').textContent(),/Age: Adult/);
assert.match(await page.locator('#survivorDetailList').textContent(),/Pose: upright/);
await page.locator('#missionTools > summary').click();
assert.match(await page.locator('#mlAssessment').textContent(),/SAR threshold rules/);
await page.locator('#missionTools > summary').click();
await page.locator('#missionArea').fill('Simulated hallway');await page.locator('#missionStart').click();
await page.waitForFunction(()=>document.getElementById('missionState').textContent==='searching');
assert(await page.locator('#missionArea').isDisabled());assert(await page.locator('#missionStop').isEnabled());
await page.locator('#refreshBtn').click();await page.waitForFunction(()=>document.querySelectorAll('.review-form').length===1);
assert.match(await page.locator('#survivorEventList').textContent(),/Coordinates unavailable/);
assert.match(await page.locator('#survivorEventList').textContent(),/Pose: upright/);
assert.match(await page.locator('#communication').textContent(),/Two-way communication is not available yet/);
await page.locator('[name=notes]').fill('Existing observation.');
await page.getByRole('button',{name:'Add communication note'}).click();
assert.match(await page.locator('[name=notes]').inputValue(),/^Existing observation\.\n\nCommunication observation/);
assert.match(await page.locator('[name=notes]').inputValue(),/unknown unless confirmed/);
await page.getByRole('button',{name:'Save operator review'}).click();
await page.waitForFunction(()=>document.getElementById('notice').textContent==='Operator review saved.');
assert.match(review.notes,/Observed gesture or words/);
await page.locator('[name=notes]').fill('x'.repeat(2000));
await page.getByRole('button',{name:'Add communication note'}).click();
assert.equal((await page.locator('[name=notes]').inputValue()).length,2000);
assert.match(await page.locator('#notice').textContent(),/Review notes are full/);
await page.locator('[name=verification]').selectOption('confirmed');await page.locator('[name=age_group]').selectOption('adult');await page.locator('[name=notes]').fill('Confirmed in test fixture.');
await page.getByRole('button',{name:'Save operator review'}).click();await page.waitForFunction(()=>document.getElementById('notice').textContent==='Operator review saved.');
assert.equal(review.assessment.age_group,'adult');assert.equal(review.assessment.consciousness,'unknown');
const downloadPromise=page.waitForEvent('download');await page.locator('#downloadReport').click();const download=await downloadPromise;assert.match(download.suggestedFilename(),/bimbot_report_/);assert.equal(reportDownloads,1);
await page.locator('#missionStop').click();await page.waitForFunction(()=>document.getElementById('missionState').textContent==='stopped');
assert(await page.locator('#trendChart').isVisible());await page.waitForTimeout(500);await page.screenshot({path:'/tmp/bimbot-desktop.png',fullPage:true});
for(const width of [320,390,768,1440]){await page.setViewportSize({width,height:900});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`Overflow at ${width}`);}
await page.setViewportSize({width:390,height:844});await page.waitForTimeout(500);await page.screenshot({path:'/tmp/bimbot-mobile.png',fullPage:false});
await page.getByRole('tab',{name:/Thermal/}).click();assert(await page.locator('#panel-thermal').isVisible());assert(await page.locator('#connectBtn').isHidden());
await page.getByRole('tab',{name:/Main camera/}).click();await page.locator('#connectBtn').click();await page.waitForFunction(()=>!document.getElementById('recordBtn').disabled);
await page.locator('#recordBtn').click();await page.waitForFunction(()=>!document.getElementById('stopBtn').hidden);await page.waitForTimeout(1100);await page.locator('#stopBtn').click();await page.waitForFunction(()=>document.getElementById('saveTitle').textContent==='Recording saved');assert.equal(uploads,1);await page.locator('#closeSave').click();
failed=true;await page.locator('#recordBtn').click();await page.waitForTimeout(1100);await page.locator('#stopBtn').click();await page.waitForFunction(()=>document.getElementById('saveTitle').textContent==='Cloud save needs attention');assert(await page.locator('#retryUpload').isVisible());assert(await page.locator('#closeSave').isDisabled());
await page.keyboard.press('Escape');assert(await page.locator('#saveDialog').isVisible());failed=false;await page.locator('#retryUpload').click();await page.waitForFunction(()=>document.getElementById('saveTitle').textContent==='Recording saved');await page.locator('#closeSave').click();
stale=true;await page.locator('#refreshBtn').click();await page.waitForFunction(()=>document.getElementById('tempDisplay').textContent==='—');assert.equal(await page.locator('#survivorCount').textContent(),'—');assert.equal(await page.locator('#riskLevel').textContent(),'Assessment unavailable');assert.equal(await page.locator('#survivorDetailsState').textContent(),'Unavailable');assert.doesNotMatch(await page.locator('#survivorDetailList').textContent(),/Consciousness: Conscious/);
let signedIn=false;
await page.route('**/cdn.jsdelivr.net/**',route=>route.fulfill({contentType:'application/javascript',body:`
window.oauthShouldFail=true;
window.supabase={createClient:()=>({auth:{
  getSession:async()=>({data:{session:${signedIn ? "{access_token:'preview',user:{email:'rescue@example.test'}}" : 'null'}}}),
  onAuthStateChange:()=>{},signOut:async()=>{},
  signInWithOAuth:async options=>{window.lastOAuthOptions=options;return {error:window.oauthShouldFail?{message:'Google sign-in unavailable'}:null};}
}})};` }));
await page.goto(new URL('/login',process.env.UI_TEST_URL || 'http://127.0.0.1:5051/').href);
assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
await page.locator('#googleBtn').click();
await page.waitForFunction(()=>!document.getElementById('errorMsg').hidden);
assert.equal(await page.locator('#errorMsg').textContent(),'Google sign-in unavailable');
assert(await page.locator('#googleBtn').isEnabled());
assert.deepEqual(await page.evaluate(()=>window.lastOAuthOptions),{provider:'google',options:{redirectTo:new URL('/',page.url()).href}});
await page.evaluate(()=>{window.oauthShouldFail=false;});
await page.locator('#googleBtn').click();
assert(await page.locator('#googleBtn').isDisabled());
assert.equal(await page.locator('#googleBtnLabel').textContent(),'Redirecting to Google…');
signedIn=true;
await page.goto(new URL('/login',process.env.UI_TEST_URL || 'http://127.0.0.1:5051/').href);
await page.waitForURL(url=>url.pathname==='/');
assert.deepEqual(errors,[]);console.log('PASS: mission start/stop, area label, operator review, report download, SAR classifications and threshold scores, responsive widths 320/390/768/1440, tabs, library, automatic recording save, failed upload retry, Escape protection, stale readings, login OAuth/error handling/session redirect; no JavaScript errors.');
await browser.close();
})().catch(error=>{console.error(error);process.exit(1)});
