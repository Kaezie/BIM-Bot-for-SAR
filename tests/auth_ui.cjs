const {chromium}=require('playwright');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});
 const page=await browser.newPage({viewport:{width:1440,height:1000}});
 const errors=[];page.on('pageerror',error=>errors.push(error.message));
 await page.route('**/fonts.googleapis.com/**',route=>route.abort());
 await page.route('**/cdn.jsdelivr.net/**',route=>route.fulfill({contentType:'application/javascript',body:`window.supabase={createClient:()=>({auth:{getSession:async()=>({data:{session:null}}),signInWithPassword:async payload=>{window.loginPayload=payload;return {error:{message:'Invalid login credentials'}}},signUp:async payload=>{window.signupPayload=payload;return {data:{session:null},error:null}}}})}` }));
 const root=process.env.UI_TEST_URL||'http://127.0.0.1:5051/';
 await page.goto(new URL('/login',root).href);
 await page.screenshot({path:'/tmp/bimbot-login.png'});
 await page.locator('#email').fill('operator@example.test');await page.locator('#password').fill('example-password');await page.locator('#authSubmit').click();
 await page.waitForFunction(()=>!document.getElementById('errorMsg').hidden);
 assert.equal(await page.locator('#errorMsg').textContent(),'Invalid login credentials');assert(await page.locator('#authSubmit').isEnabled());
 assert.deepEqual(await page.evaluate(()=>window.loginPayload),{email:'operator@example.test',password:'example-password'});
 await page.getByRole('link',{name:'Create one'}).click();assert.equal(new URL(page.url()).pathname,'/signup');
 await page.screenshot({path:'/tmp/bimbot-signup.png'});
 await page.locator('#username').fill('Rescue operator');await page.locator('#email').fill('operator@example.test');await page.locator('#password').fill('example-password');await page.locator('#confirmPassword').fill('different-password');await page.locator('#authSubmit').click();
 assert.equal(await page.locator('#errorMsg').textContent(),'Passwords do not match.');assert.equal(await page.evaluate(()=>window.signupPayload),undefined);
 await page.locator('#confirmPassword').fill('example-password');await page.locator('#authSubmit').click();
 await page.waitForFunction(()=>!document.getElementById('successMsg').hidden);
 assert.match(await page.locator('#successMsg').textContent(),/Check your email/);
 const payload=await page.evaluate(()=>window.signupPayload);assert.equal(payload.options.data.username,'Rescue operator');assert.equal(payload.email,'operator@example.test');assert(await page.locator('#authSubmit').isEnabled());
 for(const width of [320,390,768,1440]){await page.setViewportSize({width,height:900});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`Signup overflow at ${width}`);}
 assert.deepEqual(errors,[]);console.log('PASS: email login errors, signup mismatch validation, signup request and confirmation, responsive account forms; no JavaScript errors.');
 await browser.close();
})().catch(error=>{console.error(error);process.exit(1)});
