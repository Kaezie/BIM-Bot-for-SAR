"""Bounded device sessions established by a fresh, server-verified Google user.

Only an opaque random cookie is retained in the browser. The local database
stores its hash and identity, never Supabase access or refresh tokens. Resolving
a device session needs no network and does not extend its fixed expiry.
"""
from contextlib import contextmanager
from hashlib import sha256
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
from types import SimpleNamespace
from urllib.parse import urlsplit

from flask import jsonify, request


COOKIE_NAME = 'bimbot_local_session'
MAX_SESSION_SECONDS = 12 * 60 * 60
TOKEN_PATTERN = re.compile(r'[A-Za-z0-9_-]{43}\Z')


def _field(value, name, default=None):
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)


def is_google_user(user):
    """Use only fields supplied by the server's verified get_user response."""
    if user is None or _field(user, 'is_anonymous', False):
        return False
    metadata = _field(user, 'app_metadata', {}) or {}
    if isinstance(metadata, dict):
        providers = metadata.get('providers', [])
        if metadata.get('provider') == 'google' or (
                isinstance(providers, (list, tuple)) and 'google' in providers):
            return True
    identities = _field(user, 'identities', []) or []
    return isinstance(identities, (list, tuple)) and any(
        _field(identity, 'provider') == 'google' for identity in identities)


def _origin(value):
    try:
        parsed = urlsplit(value)
        if (parsed.scheme.lower() not in {'http', 'https'} or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.path not in {'', '/'} or parsed.query or parsed.fragment):
            return None
        return (parsed.scheme.lower(), parsed.hostname.lower(),
                parsed.port or (443 if parsed.scheme.lower() == 'https' else 80))
    except (TypeError, ValueError):
        return None


def same_origin_request():
    """Require browser evidence of same-origin intent for cookie mutations."""
    fetch_site = request.headers.get('Sec-Fetch-Site', '').lower()
    if fetch_site and fetch_site not in {'same-origin', 'none'}:
        return False
    origin = request.headers.get('Origin')
    if origin is not None:
        supplied, expected = _origin(origin), _origin(request.host_url)
        return supplied is not None and supplied == expected
    return fetch_site == 'same-origin'


class OfflineSessions:
    def __init__(self, data_dir, ttl_seconds=MAX_SESSION_SECONDS):
        ttl_seconds = int(ttl_seconds)
        if ttl_seconds <= 0:
            raise ValueError('Device session lifetime must be positive.')
        self.ttl_seconds = min(ttl_seconds, MAX_SESSION_SECONDS)
        self.data_dir = Path(data_dir).expanduser()
        self.data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.database_path = self.data_dir / 'sessions.sqlite3'
        descriptor = os.open(self.database_path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(descriptor)
        os.chmod(self.database_path, 0o600)
        with self._database() as db:
            db.execute('CREATE TABLE IF NOT EXISTS local_sessions ('
                       'token_hash TEXT PRIMARY KEY, owner_id TEXT NOT NULL, '
                       'email TEXT NOT NULL, created_at INTEGER NOT NULL, '
                       'expires_at INTEGER NOT NULL)')
            db.execute('CREATE INDEX IF NOT EXISTS local_sessions_expiry '
                       'ON local_sessions (expires_at)')

    @contextmanager
    def _database(self):
        db = sqlite3.connect(self.database_path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _token_hash(token):
        if not isinstance(token, str) or not TOKEN_PATTERN.fullmatch(token):
            return None
        return sha256(token.encode('ascii')).hexdigest()

    @staticmethod
    def _snapshot(user):
        return {'user': {'id': user.id, 'email': user.email},
                'expires_at': user.expires_at, 'local': True, 'access_token': None}

    def create(self, user):
        owner, email = _field(user, 'id'), _field(user, 'email')
        if (not isinstance(owner, str) or not owner.strip() or len(owner) > 256
                or not isinstance(email, str) or not email.strip() or len(email) > 320):
            raise ValueError('A verified user identity is required.')
        token = secrets.token_urlsafe(32)
        now = int(time.time())
        expires_at = now + self.ttl_seconds
        with self._database() as db:
            db.execute('DELETE FROM local_sessions WHERE expires_at <= ?', (now,))
            db.execute('INSERT INTO local_sessions VALUES (?, ?, ?, ?, ?)',
                       (self._token_hash(token), owner, email, now, expires_at))
        identity = SimpleNamespace(id=owner, email=email, expires_at=expires_at, local=True)
        return token, self._snapshot(identity)

    def resolve(self, token):
        token_hash = self._token_hash(token)
        if token_hash is None:
            return None
        now = time.time()
        with self._database() as db:
            row = db.execute('SELECT owner_id, email, expires_at FROM local_sessions '
                             'WHERE token_hash = ?', (token_hash,)).fetchone()
            if row is None:
                return None
            if row['expires_at'] <= now:
                db.execute('DELETE FROM local_sessions WHERE token_hash = ?', (token_hash,))
                return None
        return SimpleNamespace(id=row['owner_id'], email=row['email'],
                               expires_at=row['expires_at'], local=True)

    def revoke(self, token):
        token_hash = self._token_hash(token)
        if token_hash is not None:
            with self._database() as db:
                db.execute('DELETE FROM local_sessions WHERE token_hash = ?', (token_hash,))

    def current_user(self):
        return self.resolve(request.cookies.get(COOKIE_NAME))

    def register(self, app, verify_token_fresh):
        def local_session():
            if request.method == 'GET':
                user = self.current_user()
                response = jsonify({'session': self._snapshot(user) if user else None})
            elif not same_origin_request():
                response = jsonify({'error': 'Same-origin session request required.'})
                response.status_code = 403
            elif request.method == 'DELETE':
                self.revoke(request.cookies.get(COOKIE_NAME))
                response = jsonify({'session': None})
                response.delete_cookie(COOKIE_NAME, path='/', httponly=True,
                                       secure=request.is_secure, samesite='Strict')
            else:
                scheme, _, token = request.headers.get('Authorization', '').partition(' ')
                user = None
                if scheme.lower() == 'bearer' and token.strip():
                    try:
                        user = verify_token_fresh(token.strip())
                    except Exception:
                        # Provider errors may contain credentials; keep the
                        # response independent of their text or exception type.
                        user = None
                if user is None:
                    response = jsonify({'error': 'Sign in with Google online to enable this device.'})
                    response.status_code = 401
                elif not is_google_user(user):
                    response = jsonify({'error': 'A verified Google account is required.'})
                    response.status_code = 403
                else:
                    try:
                        local_token, snapshot = self.create(user)
                    except ValueError:
                        response = jsonify({'error': 'A verified Google account is required.'})
                        response.status_code = 403
                    else:
                        self.revoke(request.cookies.get(COOKIE_NAME))
                        response = jsonify({'session': snapshot})
                        response.set_cookie(COOKIE_NAME, local_token, max_age=self.ttl_seconds,
                                            httponly=True, secure=request.is_secure,
                                            samesite='Strict', path='/')
            response.headers['Cache-Control'] = 'no-store'
            response.headers['Vary'] = 'Cookie'
            return response

        app.add_url_rule('/api/local-session', 'bimbot_local_session', local_session,
                         methods=['GET', 'POST', 'DELETE'])
