const assert = require('node:assert/strict');

// Snapshot transport fixture; all camera bytes/identities are generated tests.
function cameraFrameFixture(frame, options = {}) {
  const viewers = {main:new Set(),nightvision:new Set()};
  const sequences = {main:0,nightvision:0};
  const active = new Map(), peak = new Map();
  const deletes = [];
  return {
    viewers, deletes, peak,
    matches(route) { return /^\/api\/camera-frame\/(main|nightvision)$/.test(new URL(route.request().url()).pathname); },
    async handle(route) {
      const request=route.request(), url=new URL(request.url());
      const source=url.pathname.split('/').at(-1), viewer=request.headers()['x-camera-viewer'];
      assert.match(viewer || '', /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i,'Snapshot requests require a stable UUID viewer');
      assert.equal(url.searchParams.has('access_token'),false,'Camera credentials must not be put in URLs');
      if (options.checkRequest) options.checkRequest(request,source);
      if (request.method()==='DELETE') {
        deletes.push({source,viewer});
        return route.fulfill({status:204,headers:{'Cache-Control':'no-store'}});
      }
      assert.equal(request.method(),'GET');
      if (!viewers[source].has(viewer)) {
        viewers[source].add(viewer);
        if (options.onOpen) options.onOpen(source,viewer);
      }
      active.set(viewer,(active.get(viewer)||0)+1);
      peak.set(viewer,Math.max(peak.get(viewer)||0,active.get(viewer)));
      try {
        if (options.fail?.(source)) return await route.abort();
        await new Promise(resolve=>setTimeout(resolve,options.delayMs ?? 35));
        const sequence=++sequences[source];
        return await route.fulfill({contentType:'image/jpeg',headers:{
          'Cache-Control':'no-store',
          'X-Camera-Sequence':String(sequence),'X-Camera-Generation':'1',
          'X-Camera-Received-At':String(Date.now()/1000),'X-Camera-Age-Ms':'0',
        },body:frame});
      } finally {
        active.set(viewer,active.get(viewer)-1);
      }
    },
    assertSerial() {
      for (const maximum of peak.values()) assert.equal(maximum,1,'A viewer may have only one pending JPEG request');
    },
  };
}

module.exports = {cameraFrameFixture};
