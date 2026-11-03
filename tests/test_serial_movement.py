"""Generated Uno serial frames only: no serial device is opened by these tests."""
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock
from features.serial_movement import SerialMovementBridge, BridgeError, create_bridge_app


class SerialMovementTests(unittest.TestCase):
    def setUp(self):
        self.port=MagicMock();self.port.write.side_effect=lambda raw:len(raw)
        self.now=100.0
        self.bridge=SerialMovementBridge(self.port,allow_return=True,clock=lambda:self.now)

    def snapshot(self, *, full=True,count=2,state='S',complete=1,ready=1,command='-',counter=1,parts=None):
        self.bridge.pending=None;self.bridge.last_sent=-100;self.bridge.want_full=full
        self.bridge.query(force=True)
        nonce=self.bridge.pending['nonce']
        self.now+=.1
        self.bridge.feed(f'M {nonce} {counter} {state} S 0 {count} 0 {complete} {ready} 0')
        self.bridge.feed(f'C {nonce} {command}')
        if full:
            for i,direction,duration in (parts if parts is not None else [(0,'F',1200),(1,'L',450)]):
                self.bridge.feed(f'P {nonce} {i} {direction} {duration}')
        self.now+=.1
        self.bridge.feed(f'E {nonce}')
        return nonce

    def test_construction_opens_nothing_and_queries_never_move_motors(self):
        self.port.write.assert_not_called()
        self.bridge.query()
        self.assertRegex(self.port.write.call_args.args[0].decode(),r'^D [a-f0-9]{8}\n$')

    def test_reset_waits_for_firmware_boot_before_polling(self):
        # Repeated serial polling can keep the real Uno in its bootloader.
        # Model an initially silent reset, including a fragmented boot banner.
        chunks = iter([b'', b'', b'BOOT BIMBOT_', b'MOVE_1\r\n', b''])
        booted = False
        writes = []

        def read(_size):
            nonlocal booted
            self.now += .1
            chunk = next(chunks, None)
            if chunk is None:
                self.bridge.stopped.set()
                return b''
            if chunk == b'MOVE_1\r\n':
                booted = True
            return chunk

        def write(raw):
            writes.append((booted, raw))
            return len(raw)

        self.port.read.side_effect = read
        self.port.write.side_effect = write
        self.bridge.run()
        self.assertTrue(writes)
        self.assertTrue(all(ready for ready, _raw in writes))
        self.assertTrue(all(raw.startswith(b'D ') for _ready, raw in writes))

    def test_missing_or_wrong_firmware_boot_never_queries(self):
        def read(_size):
            self.now += 1
            if self.now > 110:
                self.bridge.stopped.set()
            return b'T:25.00,H:50.00\r\n'

        self.port.read.side_effect = read
        self.bridge.run()
        self.port.write.assert_not_called()
        self.assertEqual(self.bridge.error, 'controller_startup_not_confirmed')

    def test_real_read_loop_decodes_buffered_serial_snapshots(self):
        # run() partitions a bytearray; exercise that path rather than feeding
        # pre-decoded strings, which hid the real USB parsing failure.
        chunks = [b'BOOT BIMBOT_MOVE_1\r\n']

        def write(raw):
            nonce = raw.decode('ascii').split()[1]
            chunks.append((f'M {nonce} 0 I S 0 0 0 0 0 0\n'
                           f'C {nonce} -\nE {nonce}\n').encode('ascii'))
            return len(raw)

        def read(_size):
            self.now += .05
            if chunks:
                return chunks.pop(0)
            self.bridge.stopped.set()
            return b''

        self.port.read.side_effect = read
        self.port.write.side_effect = write
        self.bridge.run()
        data = self.bridge.snapshot()
        self.assertEqual(data['source'], 'uno_usb_serial')
        self.assertEqual(data['state'], 'idle')
        self.assertEqual(data['current_move'], 'S')
        self.assertFalse(data['return_ready'])

    def test_full_trace_has_conservative_query_age_and_no_position(self):
        self.snapshot()
        data=self.bridge.snapshot()
        self.assertEqual(data['segments'],[{'direction':'F','duration_ms':1200},{'direction':'L','duration_ms':450}])
        self.assertAlmostEqual(data['sample_age_ms'],200)
        self.assertTrue(data['return_ready']);self.assertFalse(data['position_measured'])
        self.assertNotIn('latitude',data)
        first=data['sequence'];self.now+=1
        repeated=self.bridge.snapshot()
        self.assertEqual(repeated['sequence'],first)
        self.assertAlmostEqual(repeated['sample_age_ms'],1200)
        self.now+=4
        with self.assertRaises(BridgeError):self.bridge.snapshot()

    def test_partial_and_old_challenge_cannot_complete_a_new_snapshot(self):
        self.bridge.query();nonce=self.bridge.pending['nonce']
        self.bridge.feed('M deadbeef 1 S S 0 0 0 1 1 0')
        self.bridge.feed(f'M {nonce} 1 S S 0 0 0 1 1 0')
        self.bridge.feed(f'E {nonce}') # C/command association absent.
        with self.assertRaises(BridgeError):self.bridge.snapshot()

    def test_bad_or_missing_path_entries_never_authorize_return(self):
        for parts in ([(0,'F',1200)],[(0,'Z',1),(1,'L',450)],[(0,'F',0),(1,'L',450)],[(0,'F',1),(0,'L',1)]):
            with self.subTest(parts=parts):
                self.snapshot(parts=parts)
                with self.assertRaises(BridgeError):self.bridge.snapshot()

    def test_status_reuses_only_matching_cached_trace_and_marks_missing_steps_incomplete(self):
        self.snapshot()
        self.snapshot(full=False,command='a'*32,state='R',ready=0)
        self.assertEqual(len(self.bridge.snapshot()['segments']),2)
        self.snapshot(full=False,count=3,state='C',ready=0)
        self.assertFalse(self.bridge.snapshot()['trace_complete'])
        self.assertFalse(self.bridge.snapshot()['return_ready'])
        self.assertTrue(self.bridge.want_full)

    def test_boot_invalidates_old_trace_and_ready_state(self):
        self.snapshot();old_id=self.bridge.snapshot()['trace_id']
        self.bridge.feed('BOOT BIMBOT_MOVE_1')
        with self.assertRaises(BridgeError):self.bridge.snapshot()
        self.snapshot()
        self.assertNotEqual(self.bridge.snapshot()['trace_id'],old_id)

    def test_abort_is_not_published_as_a_fresh_sample(self):
        self.bridge.query();nonce=self.bridge.pending['nonce']
        self.bridge.feed(f'M {nonce} 1 S S 0 0 0 1 1 0')
        self.bridge.feed(f'X {nonce}')
        with self.assertRaises(BridgeError):self.bridge.snapshot()

    def command_with_ack(self,action,accepted=True,state=None):
        self.snapshot();trace_id=self.bridge.snapshot()['trace_id'];command_id='a'*32
        if action=='heartbeat':self.snapshot(full=False,state='R',command=command_id,ready=0)
        original=self.port.write.side_effect
        def write(raw):
            if raw.decode().split()[0] in ('RETURN','STOP','KEEP'):
                code={'return':'R','stop':'S','heartbeat':'K'}[action]
                nonce=raw.decode().split()[-1]
                self.bridge.feed(f'A {code} {command_id} {nonce} {state or ("S" if action=="stop" else "R")} {1 if accepted else 0} 1')
            return original(raw)
        self.port.write.side_effect=write
        return self.bridge.command(action,command_id,trace_id,timeout=.02)

    def test_matching_controller_ack_is_required_for_commands(self):
        for action in ('return','stop','heartbeat'):
            with self.subTest(action=action):
                ack=self.command_with_ack(action)
                self.assertTrue(ack['acknowledged'])
                self.assertEqual(ack['state'],'stopped' if action=='stop' else 'returning')

    def test_rejected_wrong_state_and_timeout_do_not_report_success(self):
        with self.assertRaises(BridgeError):self.command_with_ack('return',accepted=False)
        self.port.write.side_effect=lambda raw:len(raw)
        self.snapshot()
        with self.assertRaises(BridgeError):self.bridge.command('return','b'*32,self.bridge.snapshot()['trace_id'],timeout=.001)

    def test_disabled_return_and_changed_trace_write_no_motion(self):
        self.snapshot();self.bridge.allow_return=False
        # Readiness must be requalified when an operator gate changes.
        self.snapshot()
        self.port.write.reset_mock()
        with self.assertRaises(BridgeError):self.bridge.command('return','a'*32,self.bridge.snapshot()['trace_id'])
        with self.assertRaises(BridgeError):self.bridge.command('return','a'*32,'different-trace')
        self.port.write.assert_not_called()

    def test_stop_can_halt_an_unknown_stale_trace_but_needs_new_ack(self):
        command_id='c'*32
        def write(raw):
            nonce=raw.decode().split()[-1]
            self.bridge.feed(f'A S {command_id} {nonce} S 1 0')
            return len(raw)
        self.port.write.side_effect=write
        result=self.bridge.command('stop',command_id,'old-bridge-trace')
        self.assertEqual(result['state'],'stopped')

    def test_buffered_old_ack_cannot_acknowledge_a_new_command(self):
        self.snapshot();command_id='a'*32
        self.port.write.side_effect=lambda raw:(self.bridge.feed(f'A R {command_id} deadbeef R 1 1') or len(raw))
        with self.assertRaises(BridgeError):self.bridge.command('return',command_id,self.bridge.snapshot()['trace_id'],timeout=.001)

    def test_records_are_archived_but_never_restored_as_live_samples(self):
        with tempfile.TemporaryDirectory() as directory:
            self.bridge.directory=Path(directory);self.snapshot()
            files=list(Path(directory).glob('*.json'));self.assertEqual(len(files),1)
            data=json.loads(files[0].read_text());self.assertIn('Historical',data['note'])
            restored=SerialMovementBridge(self.port,record_directory=directory)
            with self.assertRaises(BridgeError):restored.snapshot()

    def test_http_commands_require_a_key_and_import_never_connects_to_serial(self):
        app=create_bridge_app(self.bridge,'fixture-control-key');client=app.test_client()
        self.assertEqual(client.get('/movement').status_code,503)
        self.assertEqual(client.post('/command',json={}).status_code,403)
        self.snapshot()
        response=client.get('/movement');self.assertEqual(response.status_code,200)
        self.assertEqual(response.headers['Cache-Control'],'no-store')
        self.assertEqual(client.post('/command',json=[],headers={'X-Robot-Key':'fixture-control-key'}).status_code,400)
        self.assertEqual(create_bridge_app(self.bridge).test_client().post('/command',json={}).status_code,403)

    def test_short_write_or_disconnect_clears_live_status(self):
        self.snapshot();self.port.write.side_effect=lambda raw:0
        with self.assertRaises(BridgeError):self.bridge.write('Q aaaaaaaa')
        with self.assertRaises(BridgeError):self.bridge.snapshot()
        self.bridge.close();self.port.close.assert_called_once()


if __name__=='__main__':unittest.main()
