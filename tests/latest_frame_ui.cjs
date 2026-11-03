const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const path=require('node:path');

// The player uses injected fetch/decode fixtures. No camera, auth or server runs.
(async()=>{
  const browser=await chromium.launch({headless:true,...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});
  try {
    const errors=[];
    async function fixturePage() {
      const page=await browser.newPage();
      page.on('pageerror',error=>errors.push(error.message));
      await page.route('http://127.0.0.1:5059/**',route=>route.fulfill({contentType:'text/html',body:'<!doctype html><canvas id="feed" width="32" height="24"></canvas>'}));
      await page.goto('http://127.0.0.1:5059/player-fixture');
      await page.addScriptTag({path:process.env.BIMBOT_PLAYER_SCRIPT||path.join(__dirname,'../static/js/live_camera_player.js')});
      await page.evaluate(()=>{
        window.frameResponse=(sequence,generation=1,age=0)=>new Response(`${generation}:${sequence}`,{
          status:200,headers:{'Content-Type':'image/jpeg','X-Camera-Sequence':String(sequence),
            'X-Camera-Generation':String(generation),'X-Camera-Received-At':String(Date.now()/1000-age/1000),
            'X-Camera-Age-Ms':String(age),'Cache-Control':'no-store'},
        });
        window.frameAsset=(identity,closed)=>{
          const image=document.createElement('canvas');image.width=32;image.height=24;image.identity=identity;
          image.getContext('2d').fillStyle=identity.startsWith('2:')?'#0f0':'#f00';
          image.getContext('2d').fillRect(0,0,32,24);
          return {image,width:32,height:24,close:()=>closed(identity)};
        };
        window.until=async predicate=>{
          const deadline=performance.now()+3000;
          while(!predicate()){if(performance.now()>deadline)throw new Error('Fixture condition timed out');await new Promise(resolve=>setTimeout(resolve,10));}
        };
      });
      return page;
    }

    let page=await fixturePage();
    const serial=await page.evaluate(async()=>{
      const canvas=document.getElementById('feed'),context=canvas.getContext('2d'),painted=[],closed=[];
      const draw=context.drawImage.bind(context);context.drawImage=(image,...args)=>{painted.push(image.identity);draw(image,...args);};
      let gets=0,deletes=0,decodes=0,decoding=false,overlap=false,work=0,peak=0;
      const began=performance.now(),viewers=new Set(),cursors=[];
      const player=new BIMLiveFramePlayer(canvas,{source:'main',minIntervalMs:33,
        getHeaders:()=>({'X-Fixture-Auth':'local-fixture'}),
        fetchImpl:async(url,options)=>{
          if(options.method==='DELETE'){deletes++;return new Response(null,{status:204});}
          gets++;if(decoding)overlap=true;peak=Math.max(peak,++work);
          const headers=new Headers(options.headers);viewers.add(headers.get('X-Camera-Viewer'));
          cursors.push([headers.get('X-Camera-Sequence'),headers.get('X-Camera-Generation')]);
          if(headers.get('X-Fixture-Auth')!=='local-fixture')throw new Error('Configured authentication headers were lost');
          if(options.cache!=='no-store')throw new Error('Snapshot requests must disable caching');
          if(new URL(url,location.href).searchParams.has('access_token'))throw new Error('Camera credentials leaked into a URL');
          return frameResponse(1+Math.floor((performance.now()-began)/30));
        },
        decode:async blob=>{
          decodes++;decoding=true;await new Promise(resolve=>setTimeout(resolve,120));
          const identity=await blob.text();decoding=false;
          return frameAsset(identity,id=>{closed.push(id);work--;});
        },
      }).start();
      await until(()=>painted.length>=5);player.stop();
      await new Promise(resolve=>setTimeout(resolve,150));
      return {gets,deletes,decodes,overlap,peak,painted,closed,viewers:[...viewers],cursors,viewer:canvas.getAttribute('data-viewer')};
    });
    assert.equal(serial.overlap,false,'The next fetch must wait for decoding');
    assert.equal(serial.peak,1,'There must be only one frame request/decode in progress');
    assert.equal(serial.viewers.length,1);assert.match(serial.viewers[0],/^[0-9a-f-]{36}$/i);
    assert.deepEqual(serial.cursors[0],['-1','-1']);
    const paintedSequences=serial.painted.map(id=>Number(id.split(':')[1]));
    assert(paintedSequences.slice(1).every((seq,index)=>seq-paintedSequences[index]>=3),'Slow decoding must skip older source frames');
    assert.equal(serial.closed.length,serial.decodes,'Every decoded asset, including a late one, must close');
    assert.equal(serial.deletes,1);assert.equal(serial.viewer,null);
    await page.close();

    page=await fixturePage();
    const ordered=await page.evaluate(async()=>{
      const canvas=document.getElementById('feed'),context=canvas.getContext('2d'),painted=[];
      const draw=context.drawImage.bind(context);context.drawImage=(image,...args)=>{painted.push(image.identity);draw(image,...args);};
      const replies=[[5,1],[5,1],[9,0],[1,2]];let gets=0,loads=0;
      canvas.addEventListener('load',()=>loads++);
      const player=new BIMLiveFramePlayer(canvas,{source:'nightvision',fetchImpl:async(_url,options)=>{
        if(options.method==='DELETE')return new Response(null,{status:204});
        const frame=replies[gets++];return frame?frameResponse(...frame):new Response(null,{status:204});
      },decode:async blob=>frameAsset(await blob.text(),()=>{})}).start();
      await until(()=>gets>=5);await new Promise(resolve=>setTimeout(resolve,50));player.stop();
      return {painted,loads};
    });
    assert.deepEqual(ordered.painted,['1:5','2:1'],'Duplicate sequences and older generations must never repaint');
    assert.equal(ordered.loads,1,'Only the first successful paint announces the connection');
    await page.close();

    page=await fixturePage();
    const cancelled=await page.evaluate(async()=>{
      const canvas=document.getElementById('feed'),context=canvas.getContext('2d'),painted=[],closed=[];
      const draw=context.drawImage.bind(context);context.drawImage=(image,...args)=>{painted.push(image.identity);draw(image,...args);};
      let gets=0,deletes=0,release;
      const player=new BIMLiveFramePlayer(canvas,{source:'main',fetchImpl:async(_url,options)=>{
        if(options.method==='DELETE'){deletes++;return new Response(null,{status:204});}
        return frameResponse(++gets,gets===1?1:2);
      },decode:async blob=>{
        const identity=await blob.text(),asset=frameAsset(identity,id=>closed.push(id));
        if(identity==='1:1')await new Promise(resolve=>release=resolve);
        return asset;
      }}).start();
      await until(()=>!!release);const oldViewer=canvas.getAttribute('data-viewer');player.stop();player.start();
      await until(()=>painted.length>0);const newViewer=canvas.getAttribute('data-viewer');
      release();await new Promise(resolve=>setTimeout(resolve,80));player.stop();
      return {oldViewer,newViewer,painted,closed,deletes,viewer:canvas.getAttribute('data-viewer')};
    });
    assert.notEqual(cancelled.oldViewer,cancelled.newViewer);
    assert(!cancelled.painted.includes('1:1'),'A decode from the previous connection must never paint');
    assert.equal(cancelled.closed.filter(id=>id==='1:1').length,1,'The obsolete decoded asset must close exactly once');
    assert.equal(cancelled.deletes,2);assert.equal(cancelled.viewer,null);
    await page.close();

    page=await fixturePage();
    const freshness=await page.evaluate(async()=>{
      const canvas=document.getElementById('feed');let gets=0,loads=0;
      canvas.addEventListener('load',()=>loads++);
      const began=performance.now();
      const failed=new Promise(resolve=>canvas.addEventListener('waiting',()=>resolve(performance.now()-began),{once:true}));
      const player=new BIMLiveFramePlayer(canvas,{source:'main',fetchImpl:async(_url,options)=>{
        if(options.method==='DELETE')return new Response(null,{status:204});
        return ++gets===1?frameResponse(1):new Response(null,{status:204});
      },decode:async blob=>frameAsset(await blob.text(),()=>{})}).start();
      const elapsed=await Promise.race([failed,new Promise((_,reject)=>setTimeout(()=>reject(new Error('204 replies kept stale video Live')),6500))]);
      player.stop();return {elapsed,loads,gets,viewer:canvas.getAttribute('data-viewer')};
    });
    assert.equal(freshness.loads,1);assert(freshness.gets>3);
    assert(freshness.elapsed>=4900&&freshness.elapsed<6500,'No-new-frame replies must not extend five-second freshness');
    assert.equal(freshness.viewer,null);
    await page.close();

    page=await fixturePage();
    const decodeExpired=await page.evaluate(async()=>{
      const canvas=document.getElementById('feed');let paints=0,closed=0;
      canvas.addEventListener('load',()=>paints++);
      const failed=new Promise(resolve=>canvas.addEventListener('waiting',resolve,{once:true}));
      const player=new BIMLiveFramePlayer(canvas,{source:'main',fetchImpl:async(_url,options)=>
        options.method==='DELETE'?new Response(null,{status:204}):frameResponse(1,1,4900),
        decode:async blob=>{
          await new Promise(resolve=>setTimeout(resolve,160));
          return frameAsset(await blob.text(),()=>closed++);
        },
      }).start();
      await Promise.race([failed,new Promise((_,reject)=>setTimeout(()=>reject(new Error('Decode extended stale frame lifetime')),1200))]);
      player.stop();return {paints,closed,viewer:canvas.getAttribute('data-viewer')};
    });
    assert.deepEqual(decodeExpired,{paints:0,closed:1,viewer:null},'An image that expires during decoding must close without painting');
    await page.close();

    page=await fixturePage();
    const remainingFreshness=await page.evaluate(async()=>{
      const canvas=document.getElementById('feed');let gets=0,loads=0;
      canvas.addEventListener('load',()=>loads++);
      const began=performance.now();
      const failed=new Promise(resolve=>canvas.addEventListener('waiting',()=>resolve(performance.now()-began),{once:true}));
      const player=new BIMLiveFramePlayer(canvas,{source:'main',fetchImpl:async(_url,options)=>{
        if(options.method==='DELETE')return new Response(null,{status:204});
        return ++gets===1?frameResponse(1,1,4700):new Response(null,{status:204});
      },decode:async blob=>frameAsset(await blob.text(),()=>{})}).start();
      const elapsed=await Promise.race([failed,new Promise((_,reject)=>setTimeout(()=>reject(new Error('Paint incorrectly renewed an aged frame for five more seconds')),1200))]);
      player.stop();return {elapsed,loads,viewer:canvas.getAttribute('data-viewer')};
    });
    assert.equal(remainingFreshness.loads,1);
    assert(remainingFreshness.elapsed>=150&&remainingFreshness.elapsed<1200,'An aged frame must keep only its remaining freshness');
    assert.equal(remainingFreshness.viewer,null);
    await page.close();

    page=await fixturePage();
    const stale=await page.evaluate(async()=>{
      const canvas=document.getElementById('feed');let paints=0;
      canvas.addEventListener('load',()=>paints++);
      const failed=new Promise(resolve=>canvas.addEventListener('error',resolve,{once:true}));
      const player=new BIMLiveFramePlayer(canvas,{source:'main',fetchImpl:async(_url,options)=>
        options.method==='DELETE'?new Response(null,{status:204}):frameResponse(1,1,6000),
        decode:async blob=>frameAsset(await blob.text(),()=>{}),
      }).start();
      await Promise.race([failed,new Promise((_,reject)=>setTimeout(()=>reject(new Error('Stale response was accepted')),1000))]);
      player.stop();return {paints,viewer:canvas.getAttribute('data-viewer')};
    });
    assert.deepEqual(stale,{paints:0,viewer:null},'An already stale JPEG must never become Live');
    await page.close();

    page=await fixturePage();
    const fallback=await page.evaluate(async()=>{
      const canvas=document.getElementById('feed'),source=document.createElement('canvas');source.width=32;source.height=24;
      source.getContext('2d').fillRect(0,0,32,24);
      const body=Uint8Array.from(atob(source.toDataURL('image/jpeg',.8).split(',')[1]),ch=>ch.charCodeAt(0));
      let created=0,revoked=0,gets=0;
      const create=URL.createObjectURL.bind(URL),revoke=URL.revokeObjectURL.bind(URL);
      URL.createObjectURL=blob=>{created++;return create(blob);};
      URL.revokeObjectURL=url=>{revoked++;return revoke(url);};
      Object.defineProperty(window,'createImageBitmap',{configurable:true,value:undefined});
      const loaded=new Promise(resolve=>canvas.addEventListener('load',resolve,{once:true}));
      const player=new BIMLiveFramePlayer(canvas,{source:'main',fetchImpl:async(_url,options)=>{
        if(options.method==='DELETE'||gets++)return new Response(null,{status:204});
        const response=frameResponse(1);return new Response(body,{status:200,headers:response.headers});
      }}).start();
      await Promise.race([loaded,new Promise((_,reject)=>setTimeout(()=>reject(new Error('Image decoder fallback did not paint')),1500))]);
      player.stop();await new Promise(resolve=>setTimeout(resolve,50));
      return {created,revoked,width:canvas.width,height:canvas.height};
    });
    assert(fallback.created>0,'The fallback fixture must exercise object URLs');
    assert.equal(fallback.revoked,fallback.created,'Fallback object URLs must all be revoked');
    assert.equal(fallback.width,32);assert.equal(fallback.height,24);
    await page.close();

    page=await fixturePage();
    const unauthorized=await page.evaluate(async()=>{
      const canvas=document.getElementById('feed');let revoked=0,gets=0,deletes=0;
      const player=new BIMLiveFramePlayer(canvas,{source:'main',onUnauthorized:()=>revoked++,fetchImpl:async(_url,options)=>{
        if(options.method==='DELETE'){deletes++;return new Response(null,{status:204});}
        gets++;return new Response(null,{status:401});
      }}).start();
      await until(()=>revoked===1);await new Promise(resolve=>setTimeout(resolve,100));
      return {revoked,gets,deletes,viewer:canvas.getAttribute('data-viewer')};
    });
    assert.deepEqual(unauthorized,{revoked:1,gets:1,deletes:1,viewer:null});
    await page.close();
    page=await fixturePage();
    const recovered=await page.evaluate(async()=>{
      const canvas=document.getElementById('feed'),viewers=new Set();let gets=0,deletes=0,loads=0,failures=0;
      canvas.addEventListener('load',()=>loads++);canvas.addEventListener('error',()=>failures++);
      const player=new BIMLiveFramePlayer(canvas,{source:'main',retryIntervalMs:30,fetchImpl:async(_url,options)=>{
        if(options.method==='DELETE'){deletes++;return new Response(null,{status:204});}
        viewers.add(new Headers(options.headers).get('X-Camera-Viewer'));gets++;
        if(gets<=2||gets===4||gets===5)return new Response(null,{status:503});
        return frameResponse(gets);
      },decode:async blob=>frameAsset(await blob.text(),()=>{})}).start();
      await until(()=>Number(canvas.dataset.frameSequence)>=6);
      const beforeStop={viewers:viewers.size,deletes,loads,failures};player.stop();return beforeStop;
    });
    assert.deepEqual(recovered,{viewers:1,deletes:0,loads:1,failures:0},'Startup/brief HTTP failures must retain the same viewer and preserve video freshness');
    await page.close();

    page=await fixturePage();
    const gapRecovery=await page.evaluate(async()=>{
      const canvas=document.getElementById('feed'),viewers=new Set();let gets=0,deletes=0,loads=0,failures=0,waits=0,cleared=false;
      const began=performance.now();
      canvas.addEventListener('load',()=>loads++);canvas.addEventListener('error',()=>failures++);
      canvas.addEventListener('waiting',()=>{waits++;cleared=canvas.getContext('2d').getImageData(0,0,1,1).data[3]===0;});
      const player=new BIMLiveFramePlayer(canvas,{source:'main',retryIntervalMs:30,fetchImpl:async(_url,options)=>{
        if(options.method==='DELETE'){deletes++;return new Response(null,{status:204});}
        viewers.add(new Headers(options.headers).get('X-Camera-Viewer'));
        if(++gets===1)return frameResponse(1,1,4700);
        return performance.now()-began<700?new Response(null,{status:204}):frameResponse(2);
      },decode:async blob=>frameAsset(await blob.text(),()=>{})}).start();
      await until(()=>loads===2);
      const result={loads,waits,failures,cleared,viewers:viewers.size,deletes,sequence:canvas.dataset.frameSequence};
      player.stop();return result;
    });
    assert.deepEqual(gapRecovery,{loads:2,waits:1,failures:0,cleared:true,viewers:1,deletes:0,sequence:'2'},'Expire a stale image, retain its reader and automatically resume a new frame on the SAME viewer');
    await page.close();

    page=await fixturePage();
    const startupRecovery=await page.evaluate(async()=>{
      const canvas=document.getElementById('feed'),viewers=new Set();let deletes=0,waits=0,loads=0;
      const began=performance.now();canvas.addEventListener('waiting',()=>waits++);canvas.addEventListener('load',()=>loads++);
      const player=new BIMLiveFramePlayer(canvas,{source:'main',startupGraceMs:80,retryIntervalMs:30,fetchImpl:async(_url,options)=>{
        if(options.method==='DELETE'){deletes++;return new Response(null,{status:204});}
        viewers.add(new Headers(options.headers).get('X-Camera-Viewer'));
        return performance.now()-began<300?new Response(null,{status:503}):frameResponse(1);
      },decode:async blob=>frameAsset(await blob.text(),()=>{})}).start();
      await until(()=>loads===1);const result={waits,loads,deletes,viewers:viewers.size};player.stop();return result;
    });
    assert.deepEqual(startupRecovery,{waits:1,loads:1,deletes:0,viewers:1},'A delayed first image must not repeatedly destroy its upstream reader');
    await page.close();

    assert.deepEqual(errors,[]);
    console.log('PASS: latest-frame serial fetch/decode, skipped obsolete frames, cursor deduplication, generation fencing, late-decode closure,204 freshness expiry, stale-response rejection, Image fallback cleanup and401 cancellation.');
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exit(1);});
