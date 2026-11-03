const {chromium}=require('playwright');
const assert=require('node:assert/strict');
(async()=>{
  const browser=await chromium.launch({headless:true,...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  let sdkRequests=0,exchanges=0;
  await page.route('**/api/local-session',route=>{if(route.request().method()==='POST')exchanges++;return route.fulfill({contentType:'application/json',body:'{"session":null}'});});
  await page.route('**/cdn.jsdelivr.net/**',route=>{
    sdkRequests++;
    assert.match(route.request().url(),/@supabase\/supabase-js@\d+\.\d+\.\d+\/dist\/umd\/supabase\.js$/);
    return route.fulfill({contentType:'application/javascript',body:`window.supabase={createClient:()=>({auth:{getSession:async()=>({data:{session:{access_token:'stale-fixture'}}}),onAuthStateChange:callback=>{setTimeout(()=>callback('INITIAL_SESSION',{access_token:'stale-fixture'}),0);},signOut:async()=>({error:null}),signInWithOAuth:async payload=>{window.googlePayload=payload;return window.cancelGoogle?{data:{url:'https://accounts.google.com/example'},error:null}:{error:{message:'Google sign-in test failure'}}}}})}`});
  });
  const root=process.env.UI_TEST_URL||'http://127.0.0.1:5051/';
  await page.goto(new URL('/login',root).href);
  await page.waitForFunction(()=>!!window.BIM_AUTH);
  assert.equal(sdkRequests,0,'Login page must not request cloud SDK before Google is clicked');
  assert.equal(await page.locator('input').count(),0,'Only Google sign-in is offered');
  assert.equal(await page.locator('a[href="/signup"]').count(),0);
  assert.equal(await page.getByRole('button',{name:'Sign in with Google'}).count(),1);
  await page.locator('#googleBtn').click();
  await page.waitForFunction(()=>!document.getElementById('errorMsg').hidden);
  assert.equal(await page.locator('#errorMsg').textContent(),'Google sign-in test failure');
  assert.equal(sdkRequests,1);assert(await page.locator('#googleBtn').isEnabled());
  const payload=await page.evaluate(()=>window.googlePayload);assert.equal(payload.provider,'google');assert.equal(payload.options.redirectTo,new URL('/',root).origin+'/');
  await page.waitForTimeout(50);assert.equal(exchanges,0,'A leftover INITIAL_SESSION must not restore sign-in after failed Google OAuth');
  await page.evaluate(()=>{window.cancelGoogle=true;});await page.locator('#googleBtn').click();
  await page.waitForTimeout(50);assert.equal(exchanges,0,'OAuth initiation alone must not exchange a stale SDK session');
  await page.reload();assert.equal(new URL(page.url()).pathname,'/login');assert.equal(sdkRequests,1,'Cancelled OAuth remains signed out after reload');
  for(const width of [320,390,768,1440]){await page.setViewportSize({width,height:900});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`Google login overflow at ${width}`);}
  await page.screenshot({path:'/tmp/bimbot-google-login.png'});
  await page.goto(new URL('/signup',root).href);
  assert.equal(await page.locator('input').count(),0);assert(await page.locator('#googleBtn').isVisible());
  await page.goto(new URL('/login?reason=expired',root).href);
  assert.match(await page.locator('#errorMsg').textContent(),/local session ended/);
  assert.deepEqual(errors,[]);
  console.log('PASS: Google-only login, pinned SDK lazy loading, actionable errors, expiry notice and responsive layout.');
  await browser.close();
})().catch(error=>{console.error(error);process.exit(1)});
