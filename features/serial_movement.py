"""Explicitly opened Uno serial adapter. Importing this module opens no device.

Challenge/reply snapshots bound sample age to a fresh serial request, rather
than making old buffered lines appear current. The original camera is untouched.
"""
from copy import deepcopy
import hmac
import json
from pathlib import Path
import secrets
import threading
import time
from uuid import uuid4

from flask import Flask, jsonify, request
from .movement import identifier, validate_trace

STATES = dict(I='idle', C='recording', S='stopped', R='returning', P='replay_complete', X='cancelled', E='fault')
ACTIONS = {'return':('RETURN','R'), 'stop':('STOP','S'), 'heartbeat':('KEEP','K')}


class BridgeError(Exception):
    pass


class SerialMovementBridge:
    def __init__(self, serial_port, *, allow_return=False, record_directory=None, clock=time.monotonic):
        self.port, self.allow_return, self.clock = serial_port, allow_return, clock
        self.directory = Path(record_directory) if record_directory else None
        self.lock = threading.RLock()
        self.changed = threading.Condition(self.lock)
        self.command_lock = threading.Lock()
        self.write_lock = threading.Lock()
        self.epoch = uuid4().hex
        self.sequence = 0
        self.pending = None
        self.cache = {}
        self.latest = None
        self.last_sent = -100
        self.acknowledgements = {}
        self.stopped = threading.Event()
        self.error = None
        self.saved = None
        self.want_full = True

    def write(self, line):
        raw = (line+'\n').encode('ascii')
        with self.write_lock:
            written = self.port.write(raw)
        if written != len(raw):
            self.invalidate('serial_write_failed')
            raise BridgeError('Serial command could not be sent completely.')

    def invalidate(self, reason):
        with self.lock:
            self.error = reason
            self.latest = None
            self.pending = None
            self.changed.notify_all()

    def query(self, force=False):
        with self.lock:
            now = self.clock()
            if self.pending and now-self.pending['at'] < 4:
                return
            if not force and now-self.last_sent < .25:
                return
            nonce = secrets.token_hex(4)
            full = self.want_full
            self.pending = {'nonce':nonce, 'at':now, 'full':full, 'segments':{}}
            self.last_sent = now
        self.write(f'{"D" if full else "Q"} {nonce}')

    def feed(self, raw):
        if isinstance(raw, (bytes, bytearray)):
            try: raw=raw.decode('ascii')
            except UnicodeDecodeError: return
        if len(raw)>127:
            self.invalidate('serial_line_too_long'); return
        words=raw.strip().split()
        if not words: return
        if words == ['BOOT','BIMBOT_MOVE_1']:
            with self.lock:
                self.epoch=uuid4().hex; self.cache.clear(); self.sequence=0
                self.want_full=True; self.acknowledgements.clear()
                self.invalidate('controller_restarted')
            return
        if words[0]=='A':
            try:
                if len(words)!=7 or words[1] not in ('R','S','K') or words[4] not in STATES or words[5] not in ('0','1'):
                    raise ValueError()
                identifier(words[2],'command_id')
                if len(words[3])!=8 or any(c not in '0123456789abcdef' for c in words[3]):raise ValueError()
                ack={'id':words[2], 'state':STATES[words[4]], 'accepted':words[5]=='1','counter':int(words[6]),'at':self.clock()}
                if ack['counter']<0: raise ValueError()
            except ValueError: return
            with self.lock:
                self.acknowledgements[(words[1],words[2],words[3])]=ack
                if len(self.acknowledgements)>32: self.acknowledgements.pop(next(iter(self.acknowledgements)))
                self.changed.notify_all()
            return
        with self.lock:
            pending=self.pending
            if not pending or len(words)<2 or words[1]!=pending['nonce']: return
            try:
                if words[0]=='X':
                    self.pending=None; return
                if words[0]=='M':
                    if len(words)!=11 or words[3] not in STATES or words[8] not in ('0','1') or words[9] not in ('0','1'):
                        raise ValueError()
                    counter,active,count,returned,fault=(int(words[i]) for i in (2,5,6,7,10))
                    if not 0<=counter<=2**32-1 or not 0<=count<=80 or not 0<=fault<=5: raise ValueError()
                    pending['header']={'counter':counter,'state':STATES[words[3]],'current_move':words[4],
                        'active_duration_ms':active,'count':count,'returned_steps':returned,
                        'trace_complete':words[8]=='1','return_ready':words[9]=='1','fault':fault}
                elif words[0]=='C':
                    if len(words)!=3: raise ValueError()
                    pending['command_id']=None if words[2]=='-' else identifier(words[2],'command_id')
                elif words[0]=='P':
                    if len(words)!=5 or not pending['full']: raise ValueError()
                    index=int(words[2])
                    if not 0<=index<80 or index in pending['segments']: raise ValueError()
                    pending['segments'][index]={'direction':words[3],'duration_ms':int(words[4])}
                elif words[0]=='E':
                    if len(words)!=2: raise ValueError()
                    self.commit(pending)
                    self.pending=None
            except (ValueError,KeyError,TypeError):
                self.error='invalid_controller_snapshot'; self.pending=None; self.latest=None

    def commit(self, pending):
        header=pending['header']
        counter=header['counter']; count=header['count']
        if 'command_id' not in pending: raise ValueError('Missing command association')
        if pending['full']:
            if set(pending['segments'])!=set(range(count)): raise ValueError('Incomplete path dump')
            segments=[pending['segments'][i] for i in range(count)]
        else:
            segments=deepcopy(self.cache.get(counter,[]))
            if len(segments)>count: segments=[]
        entire=len(segments)==count
        self.sequence+=1
        value=validate_trace({**header, 'source':'uno_usb_serial', 'trace_id':f'{self.epoch}-{counter}',
            'sequence':self.sequence,'sample_age_ms':(self.clock()-pending['at'])*1000,
            'command_id':pending['command_id'],'segments':segments,
            'trace_complete':header['trace_complete'] and entire,
            'return_ready':header['return_ready'] and entire and self.allow_return})
        if pending['full']: self.cache[counter]=deepcopy(segments)
        self.want_full=not entire
        self.latest={'value':value,'at':pending['at']}
        self.error=None
        self.archive(value)

    def archive(self, value):
        fingerprint=(value['trace_id'],tuple((m['direction'],m['duration_ms']) for m in value['segments']),value['state'],value['trace_complete'])
        if not self.directory or fingerprint==self.saved: return
        try:
            self.directory.mkdir(parents=True,exist_ok=True)
            path=self.directory/(value['trace_id']+'.json')
            temporary=path.with_suffix('.tmp')
            temporary.write_text(json.dumps({'saved_at':time.time(),'note':'Historical motor commands, not GPS or verified arrival.',**value},indent=2)+'\n')
            temporary.replace(path)
            self.saved=fingerprint
        except OSError:
            # A storage failure cannot make old telemetry fresh or authorize motion.
            self.error='record_storage_failed'

    def snapshot(self):
        with self.lock:
            if self.error and self.error!='record_storage_failed': raise BridgeError('Controller telemetry unavailable. Check serial connection and firmware.')
            if not self.latest: raise BridgeError('Waiting for a complete controller snapshot.')
            data=deepcopy(self.latest['value'])
            data['sample_age_ms']=(self.clock()-self.latest['at'])*1000
            if data['sample_age_ms']>=5000: raise BridgeError('Controller telemetry is stale.')
            data['storage_available']=self.error!='record_storage_failed'
            return data

    def command(self, action, command_id, trace_id, timeout=2):
        if not isinstance(action,str) or action not in ACTIONS: raise BridgeError('Unsupported movement action.')
        try: identifier(command_id,'command_id'); identifier(trace_id,'trace_id')
        except ValueError as exc: raise BridgeError('Invalid command identifiers.') from exc
        if len(command_id)!=32 or any(c not in '0123456789abcdef' for c in command_id): raise BridgeError('Expected a hexadecimal command ID.')
        verb,code=ACTIONS[action]
        with self.command_lock:
            if action!='stop':
                data=self.snapshot()
                if data['trace_id']!=trace_id: raise BridgeError('Controller trace changed.')
                if action=='return' and not data['return_ready']: raise BridgeError('Supervised return is not enabled or ready.')
                if action=='heartbeat' and (data['state']!='returning' or data['command_id']!=command_id): raise BridgeError('No matching active return.')
                counter=trace_id.rsplit('-',1)[1]
            else: counter=None
            with self.lock:
                nonce=secrets.token_hex(4)
                sent=self.clock()
            self.write(f'{verb} {command_id}'+(f' {counter}' if action=='return' else '')+f' {nonce}')
            deadline=time.monotonic()+timeout
            with self.changed:
                while True:
                    ack=self.acknowledgements.get((code,command_id,nonce))
                    if ack and ack['at']>=sent:
                        expected='stopped' if action=='stop' else 'returning'
                        if not ack['accepted'] or ack['state']!=expected or (counter is not None and str(ack['counter'])!=counter):
                            raise BridgeError('Controller rejected the command or did not confirm the expected state.')
                        self.pending=None; self.last_sent=-100
                        # Path is already cached before Return, so status refresh is short.
                        self.want_full=False
                        return {'acknowledged':True,'command_id':command_id,'trace_id':trace_id,'state':expected}
                    remaining=deadline-time.monotonic()
                    if remaining<=0: raise BridgeError('Controller acknowledgement timed out; motion is uncertain.')
                    self.changed.wait(min(remaining,.1))

    def run(self):
        buffer=bytearray()
        controller_started=False
        startup_deadline=self.clock()+3
        try:
            while not self.stopped.is_set():
                chunk=self.port.read(128)
                if chunk:
                    buffer.extend(chunk)
                    while b'\n' in buffer:
                        line,_,rest=buffer.partition(b'\n');buffer=bytearray(rest)
                        if line.strip()==b'BOOT BIMBOT_MOVE_1':
                            controller_started=True
                        if controller_started:
                            self.feed(line)
                    if len(buffer)>127: raise BridgeError('Serial input line exceeded its limit.')
                # Opening Uno serial resets it. Traffic during Optiboot's
                # startup window can keep it in the bootloader indefinitely.
                # Wait silently for the expected firmware, never poll an
                # unconfirmed or differently programmed controller.
                if controller_started:
                    self.query()
                elif self.clock()>=startup_deadline:
                    self.invalidate('controller_startup_not_confirmed')
                    return
        except Exception:
            self.invalidate('serial_disconnected')
        finally:
            self.stopped.set()

    def close(self):
        # Do not send a motion command during teardown. The controller's local
        # manual timeout/return lease expires even if transport has disappeared.
        self.stopped.set()
        self.port.close()


def create_bridge_app(bridge, control_key=''):
    app=Flask(__name__)
    @app.get('/movement')
    def movement():
        try: response=jsonify(bridge.snapshot())
        except BridgeError as error: response=jsonify(error=str(error));response.status_code=503
        response.headers['Cache-Control']='no-store'
        return response

    @app.post('/command')
    def command():
        if not control_key or not hmac.compare_digest(request.headers.get('X-Robot-Key','').encode(),control_key.encode()):
            return jsonify(error='Movement control is disabled or unauthorized.'),403
        data=request.get_json(silent=True)
        if not isinstance(data,dict): return jsonify(error='Expected a JSON movement command.'),400
        try: return jsonify(bridge.command(data.get('action'),data.get('command_id'),data.get('trace_id')))
        except BridgeError as error: return jsonify(error=str(error)),502
    return app
