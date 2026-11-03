'use strict';

window.BIMSoundRecognition = class {
  constructor({api, getInput, canStart}) {
    this.api=api;this.getInput=getInput;this.canStart=canStart;this.revision=0;this.active=false;this.modules=new WeakMap();
    this.$=id=>document.getElementById(id);
    this.$('soundRecognitionEnabled').addEventListener('change',()=>this.$('soundRecognitionEnabled').checked?this.start():this.stop());
    this.controls();
  }
  controls() { this.$('soundRecognitionEnabled').disabled=this.getInput()?.state!=='listening'; }
  stop(message='Sound recognition off.') {
    this.revision++;this.active=false;clearTimeout(this.expiry);this.abort?.abort();this.abort=null;
    for(const node of [this.capture,this.filter,this.worklet,this.silent])node?.disconnect();
    if(this.worklet)this.worklet.port.onmessage=null;
    this.capture=this.filter=this.worklet=this.silent=null;
    this.$('soundRecognitionEnabled').checked=false;
    this.$('soundRecognitionState').textContent=message;
    this.$('soundRecognitionResult').textContent='No current sound classification.';
    this.controls();
  }
  async start() {
    if(!this.canStart()||this.getInput()?.state!=='listening')return this.stop();
    const revision=++this.revision;
    this.$('soundRecognitionState').textContent='Checking local YAMNet model…';
    try {
      const status=await this.api('/api/sound-model');
      if(revision!==this.revision)return;
      if(!status.ready)throw new Error(status.message||'Local sound model is not ready.');
      const input=this.getInput(),context=input.context;
      if(!context?.audioWorklet)throw new Error('Audio worklets unavailable. Open localhost:5050 in Google Chrome.');
      let module=this.modules.get(context);
      if(!module){module=context.audioWorklet.addModule('/static/js/pcm_capture_worklet.js');this.modules.set(context,module);module.catch(()=>this.modules.delete(context));}
      await module;
      if(revision!==this.revision||!this.canStart()||input.state!=='listening')return;
      this.capture=context.createMediaStreamSource(input.stream);
      this.filter=context.createBiquadFilter();this.filter.type='lowpass';this.filter.frequency.value=7000;
      this.worklet=new AudioWorkletNode(context,'bim-pcm-capture');
      this.silent=context.createGain();this.silent.gain.value=0;
      this.capture.connect(this.filter);this.filter.connect(this.worklet);this.worklet.connect(this.silent);this.silent.connect(context.destination);
      this.active=true;this.$('soundRecognitionState').textContent='YAMNet enabled · short audio frames processed by this laptop; not saved.';
      this.worklet.port.onmessage=event=>this.classify(event.data,revision);
      this.worklet.onprocessorerror=()=>this.stop('Audio processing stopped. Restart recognition to retry.');
    } catch(error) { if(revision===this.revision)this.stop(error.message||'Sound recognition unavailable.'); }
  }
  async classify(samples,revision) {
    if(!this.active||this.flight||revision!==this.revision||!this.canStart()||this.getInput()?.state!=='listening')return;
    const input=this.getInput();
    if(input.stream.getAudioTracks().some(track=>track.readyState!=='live'||track.muted||!track.enabled))return this.stop('Microphone is not providing live audio; recognition stopped.');
    if(input.robotInput&&input.stream.getAudioTracks().some(track=>track.getSettings().deviceId!==input.inputId))return this.stop('Headset input changed; recognition stopped.');
    if(!(samples instanceof Float32Array)||samples.length!==15600)return;
    const pcm=new ArrayBuffer(62400),view=new DataView(pcm);
    samples.forEach((value,index)=>view.setFloat32(index*4,value,true));
    const abort=this.abort=new AbortController();
    const started=performance.now();
    const flight=this.flight=(async()=>{
      try {
        const result=await this.api('/api/sound-classify',{method:'POST',headers:{'Content-Type':'application/octet-stream','X-Sample-Rate':'16000'},body:pcm,signal:abort.signal});
        if(revision!==this.revision||!this.active||!this.canStart())return;
        if(performance.now()-started>=2000){this.$('soundRecognitionResult').textContent='Classification arrived too late; waiting for a fresh audio frame.';return;}
        this.$('soundRecognitionResult').textContent=`${result.event} · ${result.model_label} · model score ${(result.score*100).toFixed(1)}%. Verify by listening.`;
        clearTimeout(this.expiry);this.expiry=setTimeout(()=>{if(revision===this.revision)this.$('soundRecognitionResult').textContent='No fresh sound classification.';},3000);
      } catch(error) { if(revision===this.revision&&this.active)this.stop(error.message||'Sound recognition stopped.'); }
    })();
    try {await flight;} finally {if(this.flight===flight)this.flight=null;}
  }
};

window.BIMDuplexAudio = class {
  constructor({canStart,onBeforeStart}) {
    this.canStart=canStart;this.onBeforeStart=onBeforeStart;this.revision=0;this.streams=[];this.outputs=[];this.active=false;this.pending=false;
    this.$=id=>document.getElementById(id);
    this.ids=['duplexRobotMic','duplexOperatorMic','duplexRobotOutput','duplexOperatorOutput'];
    this.$('duplexFind').onclick=()=>this.find();this.$('duplexStart').onclick=()=>this.start();this.$('duplexStop').onclick=()=>this.stop('Two-way audio stopped.');
    for(const id of [...this.ids,'duplexMounted'])this.$(id).addEventListener('change',()=>this.stop('Audio routing changed. Review all four devices and press Start.'));
    document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='hidden')this.stop('Two-way audio stopped while the page is hidden.');});
    window.addEventListener('pagehide',()=>this.stop('Two-way audio stopped when the page closed.'));
    navigator.mediaDevices?.addEventListener('devicechange',()=>this.refresh());
    this.controls();
  }
  controls() {
    const values=this.ids.map(id=>this.$(id).value);
    const supported=!!HTMLMediaElement.prototype.setSinkId;
    this.$('duplexStart').disabled=this.active||this.pending||!supported||!this.$('duplexMounted').checked||values.some(v=>!v)||values[0]===values[1]||values[2]===values[3];
    this.$('duplexStop').disabled=!this.active&&!this.pending;
    this.$('duplexFind').disabled=this.active||this.pending;
    if(!supported)this.$('duplexState').textContent='Output selection unavailable. Use Google Chrome at localhost:5050 for this test.';
  }
  stop(message='Two-way audio off.') {
    this.revision++;this.active=false;
    for(const output of this.outputs){output.onerror=null;output.pause();output.srcObject=null;}
    for(const stream of this.streams)stream.getTracks().forEach(track=>{track.onended=track.onmute=null;track.stop();});
    this.outputs=[];this.streams=[];
    this.$('duplexState').textContent=message;this.controls();
  }
  async refresh() {
    if(!navigator.mediaDevices?.enumerateDevices)return;
    try {
      const devices=(await navigator.mediaDevices.enumerateDevices()).filter(d=>d.deviceId&&!['default','communications'].includes(d.deviceId));
      if(this.active&&this.ids.some(id=>!devices.some(d=>d.deviceId===this.$(id).value)))this.stop('A selected audio device disconnected; no replacement was selected.');
      for(const id of this.ids){
        const select=this.$(id),value=select.value,kind=id.endsWith('Mic')?'audioinput':'audiooutput';
        select.replaceChildren(new Option('Select a specific device',''));
        devices.filter(d=>d.kind===kind).forEach((d,i)=>select.add(new Option(d.label||`${kind} ${i+1}`,d.deviceId)));
        select.value=devices.some(d=>d.kind===kind&&d.deviceId===value)?value:'';
      }
      this.controls();
    } catch {this.stop('Cannot verify selected audio devices. Use Find audio devices again.');}
  }
  async find() {
    if(this.active||this.pending||!this.canStart())return;
    this.onBeforeStart();
    const revision=++this.revision;this.pending=true;this.controls();let probe;
    try {
      this.$('duplexState').textContent='Allow microphone permission to reveal device names; discovery stops the input immediately.';
      probe=await navigator.mediaDevices.getUserMedia({audio:true,video:false});
      probe.getTracks().forEach(track=>track.stop());
      if(revision!==this.revision||!this.canStart())return;
      await this.refresh();this.$('duplexState').textContent='Select robot and operator microphones and outputs. Nothing is listening or playing.';
    } catch {if(revision===this.revision)this.$('duplexState').textContent='Audio device discovery was not granted or is unavailable.';}
    finally {probe?.getTracks().forEach(track=>track.stop());this.pending=false;this.controls();}
  }
  async start() {
    this.controls();if(this.$('duplexStart').disabled||!this.canStart())return;
    this.onBeforeStart();const revision=++this.revision;this.pending=true;this.controls();
    this.$('duplexState').textContent='Opening the exact selected microphones and outputs…';
    try {
      const values=this.ids.map(id=>this.$(id).value);
      for(const [index,sink] of [[0,values[3]],[1,values[2]]]){
        const stream=await navigator.mediaDevices.getUserMedia({audio:{deviceId:{exact:values[index]},echoCancellation:true,noiseSuppression:true,autoGainControl:false},video:false});
        if(revision!==this.revision||!this.canStart()){stream.getTracks().forEach(t=>t.stop());return;}
        this.streams.push(stream);
        const tracks=stream.getAudioTracks();
        if(!tracks.length||tracks.some(t=>t.readyState!=='live'||t.getSettings().deviceId!==values[index]))throw new Error('The browser did not return the selected microphone.');
        tracks.forEach(track=>{track.onended=()=>this.stop('A microphone ended; two-way audio stopped.');track.onmute=()=>this.stop('A microphone became unavailable; two-way audio stopped.');});
        const output=new Audio();this.outputs.push(output);output.srcObject=stream;
        output.onerror=()=>this.stop('An audio output failed; both directions stopped.');
        await output.setSinkId(sink);
        if(output.sinkId!==sink)throw new Error('The browser did not confirm the selected audio output.');
        if(revision!==this.revision||!this.canStart())return;
      }
      for(const output of this.outputs){await output.play();if(revision!==this.revision||!this.canStart())return;}
      this.active=true;this.$('duplexState').textContent='Two-way audio active · robot microphone → operator output; operator microphone → robot earpiece. Test both directions at low volume.';
    } catch(error) {if(revision===this.revision)this.stop(error.message||'Could not open both audio directions. No fallback device was used.');}
    finally {
      this.pending=false;
      if(!this.active&&revision===this.revision)this.stop('Two-way audio did not start. Check exact devices and browser permission.');
      this.controls();
    }
  }
};
