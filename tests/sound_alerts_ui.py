"""Run with project Python; generated samples, mocked APIs, isolated Chrome only."""
import html
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]

FIXTURE = r'''
window.fixtureErrors=[];window.fixturePosts=[];window.fixtureAlerts=[];
window.fixtureFailSave=false;window.fixtureMicRequests=0;
window.addEventListener('error',event=>fixtureErrors.push(event.message));
window.BIM_AUTH={auth:{getSession:async()=>({data:{session:{local:true,user:{email:'fixture@example.test'}}}}),onAuthStateChange:callback=>{window.fixtureSignOut=()=>callback('SIGNED_OUT',null);},signOut:async()=>({error:null})}};
if(navigator.mediaDevices) Object.defineProperty(navigator.mediaDevices,'getUserMedia',{value:async()=>{fixtureMicRequests++;throw Error('Real microphone forbidden');}});
window.fetch=async(path,options={})=>{
  const name=new URL(path,'http://fixture.test').pathname,now=Date.now()/1000;
  if(options.method&&options.method!=='GET') {
    fixturePosts.push({path:name,event:JSON.parse(options.body)});
    if(name!=='/api/sound-alerts') throw Error('Unexpected write: '+name);
    if(fixtureFailSave) return {ok:false,status:503,json:async()=>({error:'Fixture save failure'})};
    const event=JSON.parse(options.body);
    fixtureAlerts.unshift({at:now,kind:'sound',message:'Loud sound reported · '+event.source+' · '+event.level_percent+'% relative signal'});
    return {ok:true,status:200,json:async()=>({recorded:true})};
  }
  const data={
    '/api/device-status':{nightvision:false},
    '/api/sensor-data':{fresh:true,updated_at:now,temperature:26,humidity:70,heat_index:27},
    '/api/survivors':{available:true,updated_at:now,survivors_found:0,detections:[]},
    '/api/thermal-data':{configured:false,connected:false},
    '/api/sound-data':{configured:false,connected:false},
    '/api/history':{samples:[],alerts:fixtureAlerts},
    '/api/mission':{mission:null,can_start:false,control_configured:false,robot:{fresh:false}},
    '/api/survivor-events':{events:[]},
    '/api/local-recordings':{recordings:[],pending_count:0,has_more:false},
    '/api/nightvision/light':{supported:false}
  }[name]||{};
  return {ok:true,status:200,json:async()=>data};
};
'''

VERIFY = r'''
setTimeout(async()=>{
  const checks=[];
  const check=(condition,message)=>{if(!condition)throw Error(message);checks.push(message);};
  const flush=()=>new Promise(resolve=>setTimeout(resolve,0));
  const wave=amplitude=>Float32Array.from({length:2048},(_,i)=>amplitude*Math.sin(2*Math.PI*16*i/2048));
  let clock=0,tracksStopped=0;
  Object.defineProperty(performance,'now',{configurable:true,value:()=>clock});
  const samples=(amplitude,at)=>{clock=at;laptopSound.renderSamples(wave(amplitude));};
  const activate=()=>{
    const track={readyState:'live',stop(){this.readyState='ended';tracksStopped++;},getSettings:()=>({deviceId:'fixture-headset'})};
    laptopSound.stream={getTracks:()=>[track],getAudioTracks:()=>[track]};
    laptopSound.state='listening';
  };
  try {
    selectFeed('sound');await fetchHistory();
    samples(.9,0);await flush();
    check(fixturePosts.length===0,'Idle input cannot create sound alerts');
    activate();samples(.01,50);await flush();
    check(fixturePosts.length===0,'Quiet samples create no alerts');
    samples(.9,100);await flush();
    check(!document.getElementById('soundAlert').hidden,'Loud generated samples show the banner');
    check(fixturePosts.length===1&&fixturePosts[0].event.source==='laptop','First alert records the laptop source');
    check(document.getElementById('alertCount').textContent==='1 event'&&document.querySelector('#alertList .event-tag').textContent==='Sound alert','History refresh labels a sound alert');
    check(document.getElementById('soundAlertSaveState').textContent==='Saved in alert history.','Successful save is acknowledged');
    const banner=document.getElementById('soundAlert').getBoundingClientRect();
    check(banner.left>=0&&banner.right<=innerWidth&&document.documentElement.scrollWidth<=innerWidth,'Banner and page fit the viewport');
    samples(.9,200);samples(.9,20000);await flush();
    check(fixturePosts.length===1,'Sustained noise does not repeat after cooldown');
    samples(.01,20100);samples(.9,20500);await flush();
    check(fixturePosts.length===1,'A short quiet gap does not rearm the alert');
    samples(.01,21000);samples(.01,22000);samples(.9,22100);await flush();
    check(fixturePosts.length===2,'A full quiet gap rearms the next loud event');
    samples(.01,22200);samples(.01,23200);samples(.9,23300);await flush();
    check(fixturePosts.length===2,'Cooldown blocks repeated short loud events');
    document.getElementById('dismissSoundAlert').click();
    samples(.9,23400);await flush();
    check(document.getElementById('soundAlert').hidden&&fixturePosts.length===2,'Dismiss hides the banner without bypassing cooldown');
    const threshold=document.getElementById('loudSoundThreshold');threshold.value='90';threshold.dispatchEvent(new Event('input'));
    samples(.9,35000);await flush();
    check(fixturePosts.length===2&&document.getElementById('loudSoundThresholdValue').textContent==='90%','Changing the loud threshold controls triggering');
    threshold.value='20';threshold.dispatchEvent(new Event('input'));
    const mode=document.getElementById('soundSourceMode');mode.value='robot_headset';mode.dispatchEvent(new Event('change'));
    document.getElementById('soundInputDevice').add(new Option('Fixture headset','fixture-headset'));
    document.getElementById('soundInputDevice').value='fixture-headset';document.getElementById('soundMountConfirmed').checked=true;
    activate();samples(.9,36000);await flush();
    check(fixturePosts.length===3&&fixturePosts[2].event.source==='robot_headset'&&document.getElementById('soundAlertText').textContent.includes('operator-confirmed'),'Headset alerts retain their source label');
    fixtureFailSave=true;samples(.01,37000);samples(.01,38100);samples(.9,47000);await flush();
    check(fixturePosts.length===4&&fixtureAlerts.length===3&&document.getElementById('soundAlertSaveState').textContent.includes('not saved'),'History failure keeps the visible alert and reports failure');
    laptopSound.stop();samples(.9,60000);await flush();
    check(fixturePosts.length===4&&tracksStopped>0,'Stop releases the input and prevents new alerts');
    activate();selectFeed('thermal');samples(.9,71000);await flush();
    check(laptopSound.state==='idle'&&fixturePosts.length===4,'Leaving Sound stops input and new alerts');
    selectFeed('sound');activate();Object.defineProperty(document,'visibilityState',{configurable:true,value:'hidden'});document.dispatchEvent(new Event('visibilitychange'));
    samples(.9,82000);await flush();
    check(laptopSound.state==='idle'&&fixturePosts.length===4,'Hiding the page stops input and new alerts');
    Object.defineProperty(document,'visibilityState',{configurable:true,value:'visible'});
    activate();pendingClip={};fixtureSignOut();await flush();
    check(laptopSound.state==='idle'&&document.getElementById('soundAlert').hidden,'Session expiry stops input and clears the banner');
    check(fixtureMicRequests===0&&fixturePosts.every(post=>Object.keys(post.event).sort().join(',')==='level_percent,source,threshold_percent'),'Only event metadata is posted; no microphone is opened');
    check(fixtureErrors.length===0,'No browser errors');
    show('notice',false);show('soundAlert',true);text('soundAlertSaveState','History was not saved. Check your dashboard connection and session.');
    window.testResult={passed:true,checks,width:innerWidth,posts:fixturePosts.length,microphoneRequests:fixtureMicRequests};
  } catch(error) {window.testResult={passed:false,error:error.stack,checks,browserErrors:fixtureErrors};}
  const output=document.createElement('script');output.type='application/json';output.id='sound-test-result';output.textContent=JSON.stringify(testResult);document.body.append(output);
  if(parent!==window) parent.postMessage({soundTestResult:testResult},'*');
},500);
'''


def main():
    chrome = os.environ.get('CHROME_PATH') or shutil.which('google-chrome') or '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
    spec = importlib.util.spec_from_file_location('bimbot_preview', ROOT / 'scripts/preview_ui.py')
    preview = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(preview)
    markup = preview.app.test_client().get('/').get_data(as_text=True)
    scripts = re.findall(r'<script src="(/static/[^"?]+)"[^>]*></script>', markup)
    markup = re.sub(r'<script src="/static/[^"?]+"[^>]*></script>', '', markup)
    markup = re.sub(r'<link rel="stylesheet" href="(/static/[^"?]+)"[^>]*>',
                    lambda match: '<style>' + (ROOT / match[1].lstrip('/')).read_text() + '</style>', markup)
    code = [FIXTURE] + [(ROOT / path.lstrip('/')).read_text() for path in scripts if not path.endswith('/auth.js')] + [VERIFY]
    markup = markup.replace('</body>', ''.join('<script>' + source.replace('</script', '<\\/script') + '</script>' for source in code) + '</body>')
    # Keep the screenshots/results outside the checkout for review.
    folder = Path(tempfile.mkdtemp(prefix='bimbot-sound-alerts-'))
    results = []
    for width in (320, 390, 768, 1440):
        # Chrome's native window has a 500px minimum. A same-origin iframe
        # exercises the actual dashboard at the requested phone width.
        page = folder / f'check-{width}.html'
        wrapper = ('<!doctype html><html><body style="margin:0">'
                   '<script>addEventListener("message",event=>{if(event.data.soundTestResult){'
                   'const output=document.createElement("script");output.type="application/json";'
                   'output.id="sound-test-result";output.textContent=JSON.stringify(event.data.soundTestResult);'
                   'document.body.append(output);}});</script>'
                   f'<iframe style="display:block;border:0;width:{width}px;height:1000px" '
                   f'srcdoc="{html.escape(markup, quote=True)}"></iframe></body></html>')
        page.write_text(wrapper)
        command = [chrome, '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
                   '--disable-background-networking', f'--user-data-dir={folder / str(width)}',
                   f'--window-size={width},1000', f'--screenshot={folder / (str(width) + ".png")}',
                   '--dump-dom', '--virtual-time-budget=3000', page.as_uri()]
        completed = subprocess.run(command, capture_output=True, text=True, timeout=30)
        match = re.search(r'<script type="application/json" id="sound-test-result">(.*?)</script>', completed.stdout, re.S)
        if match is None:
            raise RuntimeError(f'Chrome produced no result: exit {completed.returncode}; {completed.stderr[-1000:]}')
        result = json.loads(html.unescape(match[1]))
        if result.get('width') != width:
            raise AssertionError(f'Expected viewport {width}, got {result}')
        results.append(result)
        print(json.dumps(result, indent=2))
    (folder / 'result.json').write_text(json.dumps(results, indent=2) + '\n')
    print(f'Browser artifacts: {folder}')
    if not all(result['passed'] for result in results):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
