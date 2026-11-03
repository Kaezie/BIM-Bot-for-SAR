'use strict';
window.BIMMovement = class {
  constructor({api, canAct, notify}) {
    this.api = api; this.canAct = canAct; this.notify = notify;
    this.$ = id => document.getElementById(id);
    this.data = null; this.flight = null; this.pending = false; this.revision = 0; this.expiry = null;
    this.names = {F:'Forward', B:'Backward', L:'Left turn', R:'Right turn', S:'Stopped'};
    this.$('movementReturn').onclick = () => this.command('return');
    this.$('movementStop').onclick = () => this.command('stop');
    this.$('movementDownload').onclick = () => this.download();
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'hidden' && this.data?.can_stop) this.command('stop');
    });
  }

  invalidate(message) {
    clearTimeout(this.expiry);
    this.$('movementState').textContent = 'Unavailable';
    this.$('movementMessage').textContent = message;
    this.$('movementReturn').disabled = true;
    this.$('movementCurrent').textContent = '—';
    this.$('movementProgress').textContent = 'Live status unavailable';
    if (this.data) this.data = {...this.data, fresh:false, lease_required:false, can_return:false};
  }

  render(data) {
    clearTimeout(this.expiry);
    this.data = data;
    const fresh = data.fresh === true && Number.isFinite(data.updated_at) && Date.now()/1000-data.updated_at >= 0 && Date.now()/1000-data.updated_at < 5;
    const moves = Array.isArray(data.segments) ? data.segments : [];
    const state = data.return_state || data.state;
    this.$('movementState').textContent = !data.configured ? 'Not configured' : !fresh ? 'Stale / unavailable' : `${data.simulated ? 'SIMULATED · ' : ''}${(state || 'unknown').replaceAll('_',' ')}`;
    this.$('movementMessage').textContent = !data.configured ? 'Connect the updated Uno through the USB serial movement bridge.' : !fresh ? 'Recorded history may be retained below; current robot motion is unknown.' : state === 'command_uncertain' ? 'Command acknowledgement was lost. Use Stop and verify the robot.' : state === 'replay_complete' ? 'Recorded reverse playback finished. Physical arrival at base is unverified.' : !data.trace_complete ? 'Trace is incomplete or cannot be replayed. At the starting point, stop and press * on the IR remote to begin a new trace.' : !data.control_configured ? 'Movement history is available. Return control is not configured.' : !data.return_ready && state === 'stopped' ? 'Movement recorded. Supervised return is disabled or controller interlocks are not ready.' : 'Controller movement history received. Review the route and surroundings before returning.';
    this.$('movementSource').textContent = data.source || '—';
    this.$('movementCount').textContent = data.segments ? String(moves.length) : '—';
    this.$('movementTime').textContent = Number.isFinite(data.total_duration_ms) ? `${(data.total_duration_ms/1000).toFixed(2)} s` : '—';
    this.$('movementCurrent').textContent = fresh ? this.names[data.current_move] || '—' : '—';
    this.$('movementProgress').textContent = fresh ? `${data.returned_steps || 0} / ${moves.length} steps played` : 'Live status unavailable';
    const list = this.$('movementList'); list.replaceChildren();
    if (!moves.length) { const row=document.createElement('li'); row.textContent='No recorded movements available.'; list.append(row); }
    moves.forEach(move => { const row=document.createElement('li'); row.textContent=`${this.names[move.direction] || 'Unknown'} · ${(move.duration_ms/1000).toFixed(2)} s`; list.append(row); });
    this.$('movementReturn').disabled = this.pending || !fresh || !data.can_return;
    this.$('movementStop').disabled = this.pending || !data.can_stop;
    this.$('movementDownload').disabled = !data.segments || !this.canAct();
    if (fresh) this.expiry = setTimeout(() => this.invalidate('Movement updates stopped. Current motion is unknown; use Stop if a return is active.'), Math.max(1,(5-(Date.now()/1000-data.updated_at))*1000));
  }

  async load() {
    if (this.flight || !this.canAct()) return this.flight;
    const revision = this.revision;
    this.flight = (async () => {
      try {
        const data = await this.api('/api/movement-data');
        if (revision !== this.revision || !this.canAct()) return;
        this.render(data);
        if (data.lease_required && data.fresh && Date.now()/1000-data.updated_at < 5 && !this.pending && document.visibilityState === 'visible') await this.command('heartbeat');
      } catch { if (revision === this.revision) this.invalidate('Could not retrieve movement status. Current motion is unknown.'); }
    })().finally(() => { this.flight = null; });
    return this.flight;
  }

  async command(action) {
    if (this.pending || !this.canAct() || !this.data) return;
    if (action === 'return' && (!this.data.can_return || document.visibilityState !== 'visible')) return;
    if (action !== 'return' && !this.data.can_stop) return;
    this.pending = true; this.revision++;
    this.$('movementReturn').disabled = true; this.$('movementStop').disabled = true;
    try {
      const data = await this.api(action === 'return' ? '/api/return_to_base' : `/api/movement/${action}`, {
        method:'POST', headers:{'Content-Type':'application/json'},
        body:JSON.stringify(action === 'return' ? {trace_id:this.data.trace_id,segment_count:this.data.segments.length,total_duration_ms:this.data.total_duration_ms} : {command_id:this.data.command_id})
      });
      if (this.canAct()) this.render(data);
      if (action !== 'heartbeat') this.notify(action === 'return' ? 'Controller acknowledged reverse playback. Keep this page visible; arrival must be checked.' : 'Controller acknowledged Stop.');
    } catch (error) {
      this.invalidate(error.message);
      this.notify(error.message);
    } finally {
      this.pending = false;
      this.$('movementStop').disabled = !this.canAct() || !this.data?.can_stop;
      // A fresh status read is required before another Return command.
    }
  }

  download() {
    if (!this.canAct() || !this.data?.segments) return;
    const blob = new Blob([JSON.stringify({exported_at:new Date().toISOString(), note:'Motor commands and durations; not measured position or verified return to base.', ...this.data}, null, 2)], {type:'application/json'});
    const url=URL.createObjectURL(blob), link=document.createElement('a');
    link.href=url; link.download=`bimbot_movement_${Date.now()}.json`; link.click();
    setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
};
