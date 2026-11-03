"""Synthetic position contracts and clocks; no location or receiver access."""
import unittest
from functools import wraps
from unittest.mock import MagicMock, patch

from flask import Flask, jsonify, request
from requests.exceptions import Timeout

from features.routes import register
from features.telemetry import Telemetry, validate


def gps(**changes):
    return dict({'frame':'wgs84', 'source':'fixture-gps', 'fix_valid':True,
                 'latitude':0.0, 'longitude':0.0, 'sample_age_ms':100,
                 'sequence':1, 'satellites':8, 'horizontal_accuracy_m':4.5}, **changes)


class PositionTests(unittest.TestCase):
    def setUp(self):
        self.http = MagicMock()
        self.telemetry = Telemetry({'position':'http://fixture/position'}, self.http)

    def poll(self, payload, now=100, duration=.2):
        self.http.get.return_value.json.return_value = payload
        with patch('features.telemetry.time.time', return_value=now), \
             patch('features.telemetry.time.monotonic', side_effect=[0, duration]):
            self.telemetry.poll('position')
            return self.telemetry.get('position')

    def test_valid_fix_preserves_real_zero_coordinates_with_explicit_metadata(self):
        result = validate('position', gps())
        self.assertTrue(result['fix_valid'])
        self.assertEqual((result['latitude'],result['longitude']), (0,0))
        self.assertEqual(result['satellites'],8)
        self.assertEqual(result['horizontal_accuracy_m'],4.5)

    def test_global_coordinates_need_explicit_fix_age_and_sequence(self):
        for field in ('fix_valid','sample_age_ms','sequence'):
            data=gps(); data.pop(field)
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate('position', data)

    def test_rejects_invalid_coordinates_quality_and_freshness(self):
        for key, values in {
            'latitude':(91,-91,True,'0',float('nan')),
            'longitude':(181,-181,None,float('inf')),
            'fix_valid':(None,0,1,'true'),
            'sample_age_ms':(-1,5000,10000,True,None,float('inf')),
            'sequence':(-1,1.5,True,None,'1'),
            'satellites':(-1,256,True,1.5),
            'horizontal_accuracy_m':(-1,True,float('nan')),
            'source':('', '   ', 1, 'x'*81),
        }.items():
            for value in values:
                with self.subTest(key=key,value=value), self.assertRaises(ValueError):
                    validate('position', gps(**{key:value}))

    def test_no_fix_discards_any_coordinates_even_if_payload_keeps_them(self):
        self.assertTrue(self.poll(gps())['fresh'])
        reading=self.poll(gps(fix_valid=False,latitude=41,longitude=51),now=101)
        self.assertTrue(reading['connected'])
        self.assertFalse(reading['fresh'])
        self.assertFalse(reading['fix_valid'])
        self.assertNotIn('latitude',reading)
        self.assertNotIn('longitude',reading)
        self.assertIn('waiting for a valid GPS fix', reading['message'])

    def test_fix_freshness_includes_source_age_and_entire_http_exchange(self):
        reading=self.poll(gps(sample_age_ms=500),duration=.25)
        self.assertAlmostEqual(reading['updated_at'],99.25)
        self.assertAlmostEqual(reading['transport_ms'],250)
        self.assertTrue(reading['fresh'])
        with patch('features.telemetry.time.time',return_value=104.25):
            self.assertFalse(self.telemetry.get('position')['fresh'])

    def test_frozen_sequence_cannot_rejuvenate_even_with_reset_reported_age(self):
        first=self.poll(gps(sample_age_ms=500),duration=.25)
        repeated=self.poll(gps(sample_age_ms=0),now=103,duration=.01)
        self.assertEqual(first['updated_at'],repeated['updated_at'])
        with patch('features.telemetry.time.time',return_value=104.25):
            self.assertFalse(self.telemetry.get('position')['fresh'])
        # A stationary GPS receiver can produce new valid samples at the same
        # coordinates. Freshness follows sequence, not distance travelled.
        next_fix=self.poll(gps(sequence=2),now=105)
        self.assertTrue(next_fix['fresh'])
        self.assertEqual(next_fix['latitude'],first['latitude'])

    def test_new_source_does_not_inherit_old_source_sequence_age(self):
        self.poll(gps(sample_age_ms=4000),duration=0)
        changed=self.poll(gps(source='another-fixture',sample_age_ms=0),now=105,duration=0)
        self.assertEqual(changed['updated_at'],105)
        self.assertTrue(changed['fresh'])

    def test_timeout_and_invalid_payload_invalidate_fix_then_recover(self):
        self.poll(gps())
        self.http.get.side_effect=Timeout('sensitive endpoint must not be published')
        self.telemetry.poll('position')
        reading=self.telemetry.get('position')
        self.assertFalse(reading['fresh'])
        self.assertEqual(reading['error_code'],'timeout')
        self.assertNotIn('sensitive',reading['message'])
        self.http.get.side_effect=None
        invalid=self.poll(gps(latitude=200),now=101)
        self.assertFalse(invalid['fresh'])
        self.assertEqual(invalid['error_code'],'invalid_payload')
        self.assertTrue(self.poll(gps(sequence=2),now=102)['fresh'])

    def test_legacy_local_coordinates_and_timed_local_samples(self):
        data={'frame':'local_meters','source':'fixture-encoders','x':1,'y':2}
        self.assertEqual(validate('position',data)['x'],1)
        self.assertNotIn('latitude',validate('position',data))
        reading=self.poll({**data,'sample_age_ms':500,'sequence':4})
        self.assertTrue(reading['fresh'])
        self.assertAlmostEqual(reading['updated_at'],99.3)
        with patch('features.telemetry.time.time',return_value=104.3):
            self.assertFalse(self.telemetry.get('position')['fresh'])

    def test_unconfigured_does_not_contact_hardware_or_supply_coordinates(self):
        telemetry=Telemetry({'position':''},self.http)
        telemetry.poll('position')
        reading=telemetry.get('position')
        self.http.get.assert_not_called()
        self.assertFalse(reading['configured'])
        self.assertFalse(reading['fresh'])
        self.assertNotIn('latitude',reading)

    def test_position_api_requires_auth_and_disables_location_caching(self):
        app=Flask(__name__)
        def auth(fn):
            @wraps(fn)
            def checked(*a,**kw):
                if request.headers.get('Authorization')!='Bearer fixture':
                    return jsonify(error='Unauthorized'),401
                return fn(*a,**kw)
            return checked
        register(app,auth,MagicMock(),self.telemetry,lambda:{},lambda:{},lambda:{})
        client=app.test_client()
        self.assertEqual(client.get('/api/position-data').status_code,401)
        self.assertEqual(client.get('/api/position-data?access_token=fixture').status_code,401)
        self.poll(gps())
        with patch('features.telemetry.time.time',return_value=100):
            response=client.get('/api/position-data',headers={'Authorization':'Bearer fixture'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.headers['Cache-Control'],'no-store')
        self.assertTrue(response.get_json()['fresh'])


if __name__=='__main__': unittest.main()
