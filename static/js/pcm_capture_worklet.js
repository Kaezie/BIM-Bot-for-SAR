class BIMPCMCapture extends AudioWorkletProcessor {
  constructor(){super();this.frame=new Float32Array(15600);this.index=0;this.sum=0;this.weight=0;this.ratio=sampleRate/16000;}
  process(inputs,outputs){
    for(const output of outputs)for(const channel of output)channel.fill(0);
    const input=inputs[0]?.[0];if(!input)return true;
    for(const value of input){
      let remaining=1;
      while(remaining>1e-9){
        const amount=Math.min(remaining,this.ratio-this.weight);
        this.sum+=value*amount;this.weight+=amount;remaining-=amount;
        if(this.weight>=this.ratio-1e-9){
          this.frame[this.index++]=Math.max(-1,Math.min(1,this.sum/this.ratio));this.sum=0;this.weight=0;
          if(this.index===this.frame.length){this.port.postMessage(this.frame,[this.frame.buffer]);this.frame=new Float32Array(15600);this.index=0;}
        }
      }
    }
    return true;
  }
}
registerProcessor('bim-pcm-capture',BIMPCMCapture);
