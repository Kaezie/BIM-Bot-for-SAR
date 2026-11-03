"""Local-session security and persistence without Google, Supabase, or hardware."""
from contextlib import closing
from hashlib import sha256
from http.cookies import SimpleCookie
import json
from pathlib import Path
import sqlite3
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from flask import Flask, jsonify

from features.offline_auth import COOKIE_NAME, MAX_SESSION_SECONDS, OfflineSessions, is_google_user


class OfflineSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data_dir = Path(self.temp.name) / 'device'
        self.sessions = OfflineSessions(self.data_dir)
        self.user = SimpleNamespace(id='google-user-a', email='operator@example.test',
                                    app_metadata={'provider': 'google'}, identities=[])
        self.verify = MagicMock(return_value=self.user)
        self.app = Flask(__name__)
        self.sessions.register(self.app, self.verify)

        @self.app.get('/private')
        def private():
            user = self.sessions.current_user()
            if user is None:
                return jsonify({'error': 'Unauthorized'}), 401
            return jsonify({'owner_id': user.id})

        self.client = self.app.test_client()
        self.headers = {'Origin': 'http://localhost', 'Authorization': 'Bearer test-supabase-token'}

    def exchange(self, **kwargs):
        return self.client.post('/api/local-session', headers=self.headers, **kwargs)

    def test_session_survives_a_new_store_instance_without_cloud_access(self):
        token, snapshot = self.sessions.create(self.user)
        restarted = OfflineSessions(self.data_dir)
        user = restarted.resolve(token)
        self.assertEqual((user.id, user.email), (self.user.id, self.user.email))
        self.assertEqual(user.expires_at, snapshot['expires_at'])
        self.assertTrue(user.local)
        self.verify.assert_not_called()

    def test_database_stores_hash_and_identity_without_raw_tokens(self):
        response = self.exchange()
        self.assertEqual(response.status_code, 200)
        token = self.client.get_cookie(COOKIE_NAME).value
        with closing(sqlite3.connect(self.sessions.database_path)) as db:
            row = db.execute('SELECT token_hash, owner_id, email FROM local_sessions').fetchone()
            columns = [column[1] for column in db.execute('PRAGMA table_info(local_sessions)')]
        self.assertEqual(row, (sha256(token.encode()).hexdigest(), self.user.id, self.user.email))
        self.assertNotIn('access_token', columns)
        self.assertNotIn('refresh_token', columns)
        stored = self.sessions.database_path.read_bytes()
        self.assertNotIn(token.encode(), stored)
        self.assertNotIn(b'test-supabase-token', stored)
        self.assertEqual(stat.S_IMODE(self.sessions.database_path.stat().st_mode), 0o600)

    def test_expiry_is_fixed_and_resolving_cannot_extend_it(self):
        with patch('features.offline_auth.time.time', return_value=1000):
            token, snapshot = self.sessions.create(self.user)
        expires = 1000 + MAX_SESSION_SECONDS
        self.assertEqual(snapshot['expires_at'], expires)
        for instant in [1001, expires - 1]:
            with patch('features.offline_auth.time.time', return_value=instant):
                self.assertEqual(self.sessions.resolve(token).expires_at, expires)
        with patch('features.offline_auth.time.time', return_value=expires):
            self.assertIsNone(self.sessions.resolve(token))
        with closing(sqlite3.connect(self.sessions.database_path)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM local_sessions').fetchone()[0], 0)

    def test_requested_lifetime_cannot_exceed_twelve_hours(self):
        sessions = OfflineSessions(self.data_dir, ttl_seconds=999999)
        self.assertEqual(sessions.ttl_seconds, MAX_SESSION_SECONDS)
        with self.assertRaises(ValueError):
            OfflineSessions(self.data_dir, ttl_seconds=0)

    def test_revocation_persists_and_is_idempotent(self):
        token, _ = self.sessions.create(self.user)
        self.sessions.revoke(token)
        self.sessions.revoke(token)
        self.assertIsNone(OfflineSessions(self.data_dir).resolve(token))

    def test_identity_or_random_cookie_cannot_fabricate_a_session(self):
        for token in [None, '', self.user.id, json.dumps({'id': self.user.id, 'email': self.user.email}),
                      'a' * 43, 'x' * 4096, 'é' * 43]:
            with self.subTest(token_type=type(token).__name__):
                self.assertIsNone(self.sessions.resolve(token))
        self.client.set_cookie(COOKIE_NAME, 'a' * 43)
        self.assertEqual(self.client.get('/private').status_code, 401)
        self.verify.assert_not_called()

    def test_verified_google_exchange_returns_only_the_local_snapshot(self):
        response = self.exchange(json={'id': 'spoofed-owner', 'email': 'spoof@example.test'})
        self.assertEqual(response.status_code, 200)
        self.verify.assert_called_once_with('test-supabase-token')
        snapshot = response.get_json()['session']
        self.assertEqual(snapshot['user'], {'id': self.user.id, 'email': self.user.email})
        self.assertEqual(set(snapshot), {'user', 'expires_at', 'local', 'access_token'})
        self.assertTrue(snapshot['local'])
        self.assertIsNone(snapshot['access_token'])
        self.assertNotIn('test-supabase-token', response.get_data(as_text=True))

    def test_cookie_is_persistent_httponly_strict_and_host_only(self):
        response = self.exchange()
        cookie = SimpleCookie()
        cookie.load(response.headers['Set-Cookie'])
        value = cookie[COOKIE_NAME]
        self.assertTrue(value['httponly'])
        self.assertEqual(value['samesite'], 'Strict')
        self.assertEqual(value['path'], '/')
        self.assertEqual(value['domain'], '')
        self.assertEqual(int(value['max-age']), MAX_SESSION_SECONDS)
        self.assertTrue(value['expires'])
        self.assertFalse(value['secure'])
        self.assertEqual(response.headers['Cache-Control'], 'no-store')

    def test_https_cookie_is_secure(self):
        response = self.client.post('/api/local-session', base_url='https://localhost',
                                    headers={**self.headers, 'Origin': 'https://localhost'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('; Secure;', response.headers['Set-Cookie'])

    def test_session_and_protected_route_resolve_offline_without_verification(self):
        self.exchange()
        self.verify.reset_mock()
        self.verify.side_effect = RuntimeError('Internet unavailable')
        for _ in range(2):
            response = self.client.get('/api/local-session')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()['session']['user']['id'], self.user.id)
            self.assertEqual(self.client.get('/private').get_json(), {'owner_id': self.user.id})
        self.verify.assert_not_called()

    def test_reading_an_expired_browser_cookie_does_not_fall_back_to_cloud(self):
        self.exchange()
        expires = self.client.get('/api/local-session').get_json()['session']['expires_at']
        self.verify.reset_mock()
        with patch('features.offline_auth.time.time', return_value=expires + 1):
            self.assertEqual(self.client.get('/api/local-session').get_json(), {'session': None})
            self.assertEqual(self.client.get('/private').status_code, 401)
        self.verify.assert_not_called()

    def test_exchange_requires_a_bearer_even_with_a_local_cookie(self):
        self.exchange()
        self.verify.reset_mock()
        response = self.client.post('/api/local-session?access_token=pretend',
                                    headers={'Origin': 'http://localhost'},
                                    json={'access_token': 'pretend', 'provider': 'google'})
        self.assertEqual(response.status_code, 401)
        self.verify.assert_not_called()

    def test_bad_or_unreachable_provider_token_cannot_establish_device_access(self):
        for result in [None, RuntimeError('private-provider-error test-supabase-token')]:
            with self.subTest(result_type=type(result).__name__):
                self.verify.side_effect = result if isinstance(result, Exception) else None
                self.verify.return_value = None
                response = self.exchange()
                self.assertEqual(response.status_code, 401)
                self.assertNotIn('test-supabase-token', response.get_data(as_text=True))
                self.assertNotIn('private-provider-error', response.get_data(as_text=True))
                self.assertIsNone(self.client.get_cookie(COOKIE_NAME))

    def test_editable_user_metadata_cannot_claim_google_provider(self):
        self.verify.return_value = SimpleNamespace(id=self.user.id, email=self.user.email,
            app_metadata={'provider': 'email', 'providers': ['email']},
            identities=[{'provider': 'email'}], user_metadata={'provider': 'google', 'providers': ['google']})
        response = self.exchange()
        self.assertEqual(response.status_code, 403)
        self.assertIsNone(self.client.get_cookie(COOKIE_NAME))
        self.assertFalse(is_google_user(self.verify.return_value))

    def test_google_provider_may_be_verified_in_app_metadata_or_identities(self):
        for metadata, identities in [({'provider': 'google'}, []),
                                     ({'providers': ['email', 'google']}, []),
                                     ({}, [SimpleNamespace(provider='google')]),
                                     ({}, [{'provider': 'google'}])]:
            with self.subTest(metadata=metadata, identities_type=type(identities).__name__):
                self.verify.return_value = {'id': self.user.id, 'email': self.user.email,
                                            'app_metadata': metadata, 'identities': identities}
                self.assertEqual(self.exchange().status_code, 200)

    def test_anonymous_or_incomplete_users_are_rejected(self):
        for user in [{'id': self.user.id, 'email': self.user.email, 'is_anonymous': True,
                      'app_metadata': {'provider': 'google'}},
                     {'id': '', 'email': self.user.email, 'app_metadata': {'provider': 'google'}}]:
            with self.subTest(anonymous=user.get('is_anonymous', False)):
                self.verify.return_value = user
                self.assertEqual(self.exchange().status_code, 403)
                self.assertIsNone(self.client.get_cookie(COOKIE_NAME))

    def test_origin_and_fetch_site_rejections_happen_before_provider_verification(self):
        for origin_headers in [{}, {'Origin': 'http://other.test'}, {'Origin': 'null'},
                               {'Origin': 'http://localhost:5050'},
                               {'Origin': 'https://localhost'},
                               {'Origin': 'http://localhost', 'Sec-Fetch-Site': 'cross-site'},
                               {'Origin': 'http://localhost', 'Sec-Fetch-Site': 'same-site'},
                               {'Sec-Fetch-Site': 'none'}]:
            with self.subTest(headers=origin_headers):
                response = self.client.post('/api/local-session',
                    headers={**origin_headers, 'Authorization': 'Bearer test-supabase-token'})
                self.assertEqual(response.status_code, 403)
        self.verify.assert_not_called()

    def test_same_origin_fetch_metadata_can_support_clients_without_an_origin_header(self):
        response = self.client.post('/api/local-session', headers={
            'Sec-Fetch-Site': 'same-origin', 'Authorization': 'Bearer test-supabase-token'})
        self.assertEqual(response.status_code, 200)

    def test_logout_is_local_revokes_session_and_rejects_cross_origin_actions(self):
        self.exchange()
        token = self.client.get_cookie(COOKIE_NAME).value
        self.verify.reset_mock()
        rejected = self.client.delete('/api/local-session', headers={'Origin': 'http://attacker.test'})
        self.assertEqual(rejected.status_code, 403)
        self.assertIsNotNone(self.sessions.resolve(token))
        response = self.client.delete('/api/local-session', headers={'Origin': 'http://localhost'})
        self.assertEqual(response.get_json(), {'session': None})
        self.assertIsNone(self.client.get_cookie(COOKIE_NAME))
        self.assertIsNone(OfflineSessions(self.data_dir).resolve(token))
        self.verify.assert_not_called()

    def test_online_exchange_rotates_an_existing_local_cookie(self):
        self.exchange()
        previous = self.client.get_cookie(COOKIE_NAME).value
        self.exchange()
        replacement = self.client.get_cookie(COOKIE_NAME).value
        self.assertNotEqual(previous, replacement)
        self.assertIsNone(self.sessions.resolve(previous))
        self.assertIsNotNone(self.sessions.resolve(replacement))


if __name__ == '__main__':
    unittest.main()
